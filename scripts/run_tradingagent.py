from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


TRADINGAGENT_ROOT = Path("/Users/ningpeipei/Downloads/tradingagent-main")


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(TRADINGAGENT_ROOT / ".env")


def _read_text(path: str | None, limit: int = 50000) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.exists():
        return ""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def run(symbol: str, trade_date: str, quick_mode: bool) -> dict[str, object]:
    sys.path.insert(0, str(TRADINGAGENT_ROOT))
    _load_dotenv()

    from tradingagents.agent_core.types import AgentRunRequest
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.platform import TradingPlatform

    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = 1 if quick_mode else config.get("max_debate_rounds", 2)
    config["max_risk_discuss_rounds"] = 1 if quick_mode else config.get("max_risk_discuss_rounds", 1)

    platform = TradingPlatform(config=config)
    platform.register_trading_agents_agent(debug=False)
    result = platform.run_agent(
        "tradingagents",
        AgentRunRequest(
            symbol=symbol,
            trade_date=trade_date,
            context={
                "quick_mode": quick_mode,
                "persist_report": True,
            },
        ),
    )

    decision = result.decision
    outputs = result.outputs or {}
    report_file = outputs.get("report_file") or ""
    return {
        "ok": True,
        "symbol": symbol,
        "trade_date": trade_date,
        "action": decision.action.value if decision else "",
        "rationale": decision.rationale if decision else "",
        "confidence": decision.confidence if decision else None,
        "report_file": report_file,
        "report_pdf_file": outputs.get("report_pdf_file") or "",
        "report_dir": outputs.get("report_dir") or "",
        "report_preview": _read_text(str(report_file), limit=50000),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TradingAgent through its platform API.")
    parser.add_argument("--symbol", required=True, help="Stock symbol, e.g. 600418 or 600418.SH.")
    parser.add_argument("--trade-date", required=True, help="Trade date, e.g. 2026-06-22.")
    parser.add_argument("--full", action="store_true", help="Disable quick mode.")
    args = parser.parse_args()

    try:
        payload = run(
            symbol=args.symbol.strip(),
            trade_date=args.trade_date.strip(),
            quick_mode=not args.full,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }
    print("__TRADINGAGENT_RESULT__" + json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
