"""
OpenClaw mx_personal_kb_search skill runtime.

This module is intentionally self-contained:
- No hard-coded user identity.
- Runtime defaults are defined in-code.
"""

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

EM_API_KEY = os.environ.get("EM_API_KEY", "em_I2kh47c0Acf4hA2ITXeTwYDMwaJTaADH").strip()
DEFAULT_OUTPUT_DIR = Path.cwd() / "miaoxiang" / "kb_search"
TIMEOUT_SECONDS = 60
KB_SEARCH_URL = (
    "https://ai-saas.eastmoney.com/proxy/"
    "app-robo-advisor-api/assistant/private-domain-search"
)


def _extract_error_message(body: str) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    try:
        data = json.loads(body)
    except Exception:
        return body[:200]
    if isinstance(data, dict):
        for key in ("msg", "message", "error", "stack"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return body[:200]


def _format_timestamp(value: Any) -> Optional[str]:
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, str):
        text = value.strip()
        # API may already return formatted strings (e.g. "2025-05-15 16:10:59").
        if not text:
            return None
        if not text.lstrip("-").isdigit():
            return text
        value = text
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts > 10 ** 12:
        ts = ts / 1000.0
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%d %H:%M")


def _humanize_size(value: Any) -> Optional[str]:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return "{0:.0f} {1}".format(size, units[idx])
    return "{0:.1f} {1}".format(size, units[idx])


def _strip_description_prefix(text: Any) -> str:
    """
    Strip the templated "描述：<title>\\n内容：<body>" prefix from chunk text.

    The KB pipeline stores each chunk as a two-line preamble plus body. The
    description repeats the title, so we drop the preamble for cleaner output.
    """
    if not isinstance(text, str):
        return ""
    body = text.lstrip()
    if not body.startswith("描述："):
        return text.strip()
    _, sep, rest = body.partition("\n内容：")
    if sep:
        return rest.strip()
    # No "内容：" separator -> at least drop the leading description line.
    _, nl, rest = body.partition("\n")
    if nl:
        return rest.strip()
    return text.strip()


def _format_chunks_as_markdown(chunks: List[Any]) -> str:
    """Render knowledge-base hits as a readable Markdown summary."""
    seen_keys: set = set()
    unique: List[Dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        key = chunk.get("primaryKey") or "{0}|{1}".format(
            chunk.get("fileMd5") or "", chunk.get("chunkSeq")
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(chunk)

    if not unique:
        return ""

    lines: List[str] = [
        "# 私域知识库检索结果",
        "",
        "共检索到 {0} 条相关内容。".format(len(unique)),
        "",
    ]

    for idx, chunk in enumerate(unique, start=1):
        title = chunk.get("title") or chunk.get("fileName") or "片段 {0}".format(idx)
        chunk_seq = chunk.get("chunkSeq")
        if chunk_seq not in (None, ""):
            lines.append("## {0}. {1} · 片段 #{2}".format(idx, title, chunk_seq))
        else:
            lines.append("## {0}. {1}".format(idx, title))
        lines.append("")

        time_value = (
            chunk.get("timestamp")
            or chunk.get("esUpdateTime")
            or chunk.get("createTime")
        )
        meta_pairs = [
            ("来源文件", chunk.get("fileName")),
            ("类型", chunk.get("type")),
            ("工作表", chunk.get("sheetName")),
            ("文件大小", _humanize_size(chunk.get("fileSize"))),
            ("时间", _format_timestamp(time_value)),
            ("预览链接", chunk.get("previewUrl")),
        ]
        for label, value in meta_pairs:
            if value in (None, "", []):
                continue
            lines.append("- {0}：{1}".format(label, value))

        body = _strip_description_prefix(chunk.get("text"))
        if body:
            lines.append("")
            lines.append("**原文片段：**")
            lines.append("")
            quoted = body.replace("\r\n", "\n").replace("\n", "\n> ")
            lines.append("> {0}".format(quoted))

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


_SUCCESS_MESSAGES = {"成功", "success", "ok"}

# Synthetic user-facing notice for "no hits" responses. The upstream API
# sometimes returns `{code:200, message:"成功", data:[]}` with no business
# message attached, even though the SKILL.md output contract promises an
# explicit "未检索到" wording. We materialise it here so the downstream Agent
# always gets an actionable signal instead of an empty string.
_NO_HITS_NOTICE = "未在您的知识库中检索到与该问题相关的内容，请换种说法再试"


def _pick_status_message(raw: Dict[str, Any]) -> str:
    """
    Pick a user-facing status message from the API response when chunks are
    absent. Returns "" if only success markers are present.
    """
    for key in ("message", "msg"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            if stripped.lower() not in _SUCCESS_MESSAGES and stripped not in _SUCCESS_MESSAGES:
                return stripped
    return ""


def _extract_content(raw: Any) -> str:
    """
    Extract readable content from API response.
    Supports:
    - Plain text status/error messages (e.g. "您暂无知识库权限...")
    - List of chunk dicts -> rendered as Markdown sections
    - Wrapped dict shapes: {code, message, data: <list|str|dict>}
    - Empty `data` with a meaningful `message` -> surfaces the message
    - Fallback: prettified JSON for unknown structures
    """
    if raw is None:
        return ""

    if isinstance(raw, str):
        return raw.strip()

    if isinstance(raw, list):
        formatted = _format_chunks_as_markdown(raw)
        if formatted:
            return formatted
        return ""

    if isinstance(raw, dict):
        code = raw.get("code")
        if code is not None and code not in (0, 200, "0", "200"):
            message = _pick_status_message(raw)
            if message:
                return message

        data = raw.get("data")

        if isinstance(data, str) and data.strip():
            return data.strip()

        if isinstance(data, list):
            formatted = _format_chunks_as_markdown(data)
            if formatted:
                return formatted
            # Empty / unusable list -> fall back to status message, or the
            # synthetic "no hits" notice when the API stayed silent (which
            # is what the live endpoint does when nothing matches).
            message = _pick_status_message(raw)
            if message:
                return message
            return _NO_HITS_NOTICE

        if isinstance(data, dict):
            display = data.get("displayData")
            if isinstance(display, str) and display.strip():
                return display.strip()
            if isinstance(display, list):
                formatted = _format_chunks_as_markdown(display)
                if formatted:
                    return formatted
            for key in ("chunks", "items", "results", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    formatted = _format_chunks_as_markdown(value)
                    if formatted:
                        return formatted
            for key in ("content", "answer", "summary", "message", "msg"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        for key in ("displayData", "content", "answer", "summary"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                formatted = _format_chunks_as_markdown(value)
                if formatted:
                    return formatted

        # Final fallback: surface a non-success status message if present.
        message = _pick_status_message(raw)
        if message:
            return message

        return ""

    return ""


def _http_call_kb_search(query: str) -> Any:
    payload = {"query": query}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url=KB_SEARCH_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "em_api_key": EM_API_KEY,
        },
    )

    try:
        with urllib_request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib_error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        message = _extract_error_message(err_body) or "http status {0}".format(exc.code)
        raise RuntimeError("KB search API request failed: {0}".format(message))
    except urllib_error.URLError as exc:
        raise RuntimeError("KB search API request failed: {0}".format(exc.reason))

    raw_body = (raw_body or "").strip()
    if not raw_body:
        raise RuntimeError("KB search API returned an empty response.")

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        # Some status responses may come back as plain text.
        return raw_body


def _has_valid_content(raw: Any) -> bool:
    """
    Determine whether the response contains a *saveable* knowledge-base body
    (i.e. an actual chunk list / report), not just a status message.

    We deliberately do NOT persist permission / empty-library / no-hit notices
    to disk — those should stay transient and be relayed to the user directly.
    """
    if raw is None:
        return False

    if isinstance(raw, str):
        return False

    if isinstance(raw, list):
        return any(isinstance(item, dict) for item in raw)

    if isinstance(raw, dict):
        code = raw.get("code")
        if code is not None and code not in (0, 200, "0", "200"):
            return False

        status = raw.get("status")
        if isinstance(status, int) and status < 0:
            return False

        data = raw.get("data")
        if isinstance(data, list):
            return any(isinstance(item, dict) for item in data)
        if isinstance(data, dict):
            display = data.get("displayData")
            if isinstance(display, list):
                return any(isinstance(item, dict) for item in display)
            for key in ("chunks", "items", "results", "list"):
                value = data.get(key)
                if isinstance(value, list) and any(isinstance(item, dict) for item in value):
                    return True
            if isinstance(display, str) and display.strip():
                # Some endpoints embed a full markdown report in displayData.
                return True
            return False

        for key in ("displayData",):
            value = raw.get(key)
            if isinstance(value, list) and any(isinstance(item, dict) for item in value):
                return True
            if isinstance(value, str) and value.strip():
                return True
        return False

    return False


async def search_personal_kb(
    query: str,
    output_dir: Optional[Path] = None,
    save_to_file: bool = True,
) -> Dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {
            "query": "",
            "content": "",
            "output_path": None,
            "raw": None,
            "error": "query is empty",
        }

    out_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    result: Dict[str, Any] = {
        "query": query,
        "content": "",
        "output_path": None,
        "raw": None,
    }

    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _http_call_kb_search, query)
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["raw"] = raw
    result["content"] = _extract_content(raw)

    if save_to_file and result["content"] and _has_valid_content(raw):
        unique_suffix = uuid.uuid4().hex[:8]
        output_path = out_dir / "kb_search_{0}.md".format(unique_suffix)
        output_path.write_text(result["content"], encoding="utf-8")
        result["output_path"] = str(output_path)

    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search the personal knowledge base via natural language query."
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Natural language query (resolve any pronouns/coreferences before passing in).",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save the result to a local file.",
    )
    return parser


def run_cli() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    query = (args.query or "").strip()
    if not query:
        import sys

        query = (sys.stdin.read() or "").strip()

    if not query:
        parser.print_help()
        raise SystemExit(1)

    async def _main() -> None:
        result = await search_personal_kb(query=query, save_to_file=not args.no_save)
        if "error" in result:
            print("Error: {0}".format(result["error"]))
            raise SystemExit(2)
        if result.get("output_path"):
            print("Saved: {0}".format(result["output_path"]))
        print(result.get("content", ""))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_main())
    finally:
        loop.close()


if __name__ == "__main__":
    run_cli()
