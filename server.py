from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import re


ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "reports" / "index.html"
STOCK_DIAGNOSIS_SCRIPT = ROOT / "my-skills" / "stock-diagnosis" / "scripts" / "get_data.py"
TRADINGAGENT_SCRIPT = ROOT / "scripts" / "run_tradingagent.py"
TRADINGAGENT_ROOT = Path("/Users/ningpeipei/Downloads/tradingagent-main")
STATE_LOCK = threading.Lock()
STATE: dict[str, object] = {
    "running": False,
    "progress": 0,
    "message": "idle",
    "error": "",
}


def _set_state(**values: object) -> None:
    with STATE_LOCK:
        STATE.update(values)


def _state_snapshot() -> dict[str, object]:
    with STATE_LOCK:
        return dict(STATE)


def _progress_worker() -> None:
    while True:
        time.sleep(1)
        state = _state_snapshot()
        if not state["running"]:
            return
        progress = int(state["progress"])
        if progress < 85:
            _set_state(progress=min(progress + 2, 85))
        elif progress < 95:
            _set_state(progress=progress + 1)


def _update_worker() -> None:
    _set_state(running=True, progress=1, message="starting", error="")
    threading.Thread(target=_progress_worker, daemon=True).start()
    try:
        command = [sys.executable, "main.py", "--config", "utils/sample_config.toml", "--refresh"]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or "update failed").strip()
            _set_state(running=False, progress=0, message="failed", error=error[-600:])
            return
        _set_state(running=False, progress=100, message="done", error="")
    except Exception as exc:
        _set_state(running=False, progress=0, message="failed", error=str(exc))


def _start_update() -> bool:
    state = _state_snapshot()
    if state["running"]:
        return False
    threading.Thread(target=_update_worker, daemon=True).start()
    return True


def _home_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>量化研究工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #146c94;
      --accent-strong: #0f4c75;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.55;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 36px 20px 56px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 30px;
      line-height: 1.2;
    }
    .subtitle {
      margin: 0 0 24px;
      color: var(--muted);
      max-width: 720px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }
    .card {
      display: grid;
      min-height: 190px;
      align-content: space-between;
      gap: 18px;
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: inherit;
      text-decoration: none;
      transition: border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
    }
    .card:hover {
      border-color: rgba(20, 108, 148, 0.5);
      box-shadow: 0 12px 28px rgba(15, 76, 117, 0.08);
      transform: translateY(-2px);
    }
    .card h2 {
      margin: 0 0 8px;
      font-size: 20px;
    }
    .card p {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }
    .action {
      color: var(--accent);
      font-weight: 800;
      font-size: 14px;
    }
    @media (max-width: 700px) {
      main { padding: 24px 12px 40px; }
      h1 { font-size: 26px; }
    }
  </style>
</head>
<body>
  <main>
    <h1>量化研究工作台</h1>
    <p class="subtitle">选择一个工作台开始分析。策略筛选用于股票池和首板候选，单股分析用于判断某一只股票当前是否适合买入。</p>
    <section class="grid" aria-label="工作台入口">
      <a class="card" href="/strategy.html">
        <div>
          <h2>策略筛选工作台</h2>
          <p>刷新股票池，按首板策略筛选试仓、观察和剔除样本，并查看历史信号回看。</p>
        </div>
        <span class="action">进入工作台</span>
      </a>
      <a class="card" href="/stock.html">
        <div>
          <h2>单股买入分析工作台</h2>
          <p>输入股票名称或代码，调用 stock-diagnosis skill，输出是否适合买入及诊断依据。</p>
        </div>
        <span class="action">进入工作台</span>
      </a>
      <a class="card" href="/tradingagent.html">
        <div>
          <h2>TradingAgent 分析工作台</h2>
          <p>接入 tradingagent-main 多 Agent 研究引擎，生成 BUY/HOLD/SELL 决策和完整报告。</p>
        </div>
        <span class="action">进入工作台</span>
      </a>
    </section>
  </main>
</body>
</html>
"""


def _stock_workbench_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>单股买入分析工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #146c94;
      --accent-strong: #0f4c75;
      --good: #13795b;
      --warn: #a16207;
      --bad: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.55;
    }
    main {
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 52px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }
    h1 {
      margin: 0 0 4px;
      font-size: 28px;
      line-height: 1.2;
    }
    .subtitle {
      margin: 0;
      color: var(--muted);
    }
    a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 700;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    .input-row {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 12px;
      align-items: end;
    }
    label {
      display: grid;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }
    input {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 12px;
      color: var(--text);
      font: inherit;
      background: #fff;
    }
    button {
      min-height: 42px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      padding: 0 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    button:disabled {
      background: #cbd5e1;
      color: #475569;
      cursor: wait;
    }
    .hint {
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .result {
      display: none;
      margin-top: 18px;
      gap: 18px;
      grid-template-columns: 320px minmax(0, 1fr);
      align-items: start;
    }
    .result.ready {
      display: grid;
    }
    .verdict {
      border-left: 4px solid var(--warn);
    }
    .verdict.good { border-left-color: var(--good); }
    .verdict.bad { border-left-color: var(--bad); }
    .verdict h2,
    .report h2 {
      margin: 0 0 10px;
      font-size: 18px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 0 10px;
      background: #fff8e5;
      color: var(--warn);
      font-weight: 800;
      font-size: 13px;
    }
    .verdict.good .badge {
      background: #e7f6ef;
      color: var(--good);
    }
    .verdict.bad .badge {
      background: #fde9e7;
      color: var(--bad);
    }
    .reason {
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 14px;
    }
    .report-body {
      max-height: 68vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfcfe;
      white-space: pre-wrap;
      font-size: 14px;
    }
    .error {
      display: none;
      margin-top: 14px;
      color: var(--bad);
      font-weight: 700;
    }
    .error.visible { display: block; }
    @media (max-width: 820px) {
      main { padding: 20px 12px 40px; }
      .topbar { align-items: flex-start; flex-direction: column; }
      .input-row { grid-template-columns: 1fr; }
      .result.ready { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <div class="topbar">
      <div>
        <h1>单股买入分析工作台</h1>
        <p class="subtitle">输入一只沪深京 A 股，输出当前是否适合买入及诊断依据。</p>
      </div>
      <a href="/">返回首页</a>
    </div>
    <section class="panel">
      <div class="input-row">
        <label>
          股票名称或代码
          <input id="stockInput" value="江淮汽车" placeholder="例如：江淮汽车、600418、东方财富">
        </label>
        <button id="analyzeButton" type="button">分析是否适合买入</button>
      </div>
      <p class="hint">结果来自 stock-diagnosis skill。结论仅供研究参考，不构成投资建议。</p>
      <p class="error" id="errorText"></p>
    </section>
    <section class="result" id="result">
      <aside class="panel verdict" id="verdictCard">
        <h2>买入结论</h2>
        <span class="badge" id="verdictBadge">等待分析</span>
        <p class="reason" id="verdictReason"></p>
      </aside>
      <article class="panel report">
        <h2>诊断报告</h2>
        <div class="report-body" id="reportBody"></div>
      </article>
    </section>
  </main>
  <script>
    const input = document.getElementById("stockInput");
    const button = document.getElementById("analyzeButton");
    const errorText = document.getElementById("errorText");
    const result = document.getElementById("result");
    const verdictCard = document.getElementById("verdictCard");
    const verdictBadge = document.getElementById("verdictBadge");
    const verdictReason = document.getElementById("verdictReason");
    const reportBody = document.getElementById("reportBody");

    function render(payload) {
      verdictCard.classList.remove("good", "bad");
      if (payload.verdict_level === "buy") {
        verdictCard.classList.add("good");
      } else if (payload.verdict_level === "avoid") {
        verdictCard.classList.add("bad");
      }
      verdictBadge.textContent = payload.verdict || "需要人工判断";
      verdictReason.textContent = payload.reason || "请结合完整诊断报告和个人风险承受能力判断。";
      reportBody.textContent = payload.content || "";
      result.classList.add("ready");
    }

    async function analyze() {
      const stock = input.value.trim();
      if (!stock) {
        errorText.textContent = "请输入股票名称或代码。";
        errorText.classList.add("visible");
        return;
      }
      button.disabled = true;
      button.textContent = "分析中...";
      errorText.classList.remove("visible");
      try {
        const response = await fetch("/api/analyze-stock", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stock }),
        });
        const payload = await response.json();
        if (!response.ok || payload.error) {
          throw new Error(payload.error || "分析失败");
        }
        render(payload);
      } catch (error) {
        errorText.textContent = error.message || "分析服务暂时不可用。";
        errorText.classList.add("visible");
      } finally {
        button.disabled = false;
        button.textContent = "分析是否适合买入";
      }
    }

    button.addEventListener("click", analyze);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        analyze();
      }
    });
  </script>
</body>
</html>
"""


def _tradingagent_workbench_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TradingAgent 分析工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #146c94;
      --accent-strong: #0f4c75;
      --buy: #13795b;
      --hold: #a16207;
      --sell: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.55;
    }
    main { max-width: 1180px; margin: 0 auto; padding: 28px 20px 52px; }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }
    h1 { margin: 0 0 4px; font-size: 28px; line-height: 1.2; }
    .subtitle { margin: 0; color: var(--muted); }
    a { color: var(--accent); text-decoration: none; font-weight: 700; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    .input-row {
      display: grid;
      grid-template-columns: minmax(150px, 1fr) minmax(150px, 1fr) auto;
      gap: 12px;
      align-items: end;
    }
    label {
      display: grid;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }
    input {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 12px;
      color: var(--text);
      font: inherit;
      background: #fff;
    }
    button {
      min-height: 42px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      padding: 0 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    button:disabled { background: #cbd5e1; color: #475569; cursor: wait; }
    .hint { margin: 10px 0 0; color: var(--muted); font-size: 13px; }
    .error { display: none; margin-top: 14px; color: var(--sell); font-weight: 700; white-space: pre-wrap; }
    .error.visible { display: block; }
    .result {
      display: none;
      margin-top: 18px;
      gap: 18px;
      grid-template-columns: 320px minmax(0, 1fr);
      align-items: start;
    }
    .result.ready { display: grid; }
    .decision { border-left: 4px solid var(--hold); }
    .decision.buy { border-left-color: var(--buy); }
    .decision.sell { border-left-color: var(--sell); }
    .decision h2,
    .report h2 { margin: 0 0 10px; font-size: 18px; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      border-radius: 999px;
      padding: 0 12px;
      background: #fff8e5;
      color: var(--hold);
      font-weight: 900;
      letter-spacing: 0;
    }
    .decision.buy .badge { background: #e7f6ef; color: var(--buy); }
    .decision.sell .badge { background: #fde9e7; color: var(--sell); }
    .reason,
    .meta { margin: 12px 0 0; color: var(--muted); font-size: 14px; white-space: pre-wrap; }
    .report-body {
      max-height: 68vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfcfe;
      white-space: pre-wrap;
      font-size: 14px;
    }
    @media (max-width: 820px) {
      main { padding: 20px 12px 40px; }
      .topbar { align-items: flex-start; flex-direction: column; }
      .input-row { grid-template-columns: 1fr; }
      .result.ready { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <div class="topbar">
      <div>
        <h1>TradingAgent 分析工作台</h1>
        <p class="subtitle">输入标的和交易日，运行多 Agent 研究流程，输出 BUY / HOLD / SELL 决策。</p>
      </div>
      <a href="/">返回首页</a>
    </div>
    <section class="panel">
      <div class="input-row">
        <label>
          股票代码
          <input id="symbolInput" value="600418" placeholder="例如：600418、300750.SZ、01810.HK">
        </label>
        <label>
          交易日
          <input id="dateInput" value="2026-06-22" placeholder="例如：2026-06-22">
        </label>
        <button id="runButton" type="button">运行 TradingAgent</button>
      </div>
      <p class="hint">默认使用 quick mode，并持久化完整 Markdown / PDF 报告。运行可能需要数分钟。</p>
      <p class="error" id="errorText"></p>
    </section>
    <section class="result" id="result">
      <aside class="panel decision" id="decisionCard">
        <h2>最终决策</h2>
        <span class="badge" id="actionBadge">等待分析</span>
        <p class="reason" id="rationaleText"></p>
        <p class="meta" id="metaText"></p>
      </aside>
      <article class="panel report">
        <h2>完整报告预览</h2>
        <div class="report-body" id="reportBody"></div>
      </article>
    </section>
  </main>
  <script>
    const symbolInput = document.getElementById("symbolInput");
    const dateInput = document.getElementById("dateInput");
    const runButton = document.getElementById("runButton");
    const errorText = document.getElementById("errorText");
    const result = document.getElementById("result");
    const decisionCard = document.getElementById("decisionCard");
    const actionBadge = document.getElementById("actionBadge");
    const rationaleText = document.getElementById("rationaleText");
    const metaText = document.getElementById("metaText");
    const reportBody = document.getElementById("reportBody");

    function render(payload) {
      const action = payload.action || "HOLD";
      decisionCard.classList.remove("buy", "sell");
      if (action === "BUY") decisionCard.classList.add("buy");
      if (action === "SELL") decisionCard.classList.add("sell");
      actionBadge.textContent = action;
      rationaleText.textContent = payload.rationale || "TradingAgent 未返回理由。";
      metaText.textContent = [
        payload.report_file ? `Markdown: ${payload.report_file}` : "",
        payload.report_pdf_file ? `PDF: ${payload.report_pdf_file}` : "",
        payload.report_dir ? `目录: ${payload.report_dir}` : "",
      ].filter(Boolean).join("\\n");
      reportBody.textContent = payload.report_preview || "暂无报告预览。";
      result.classList.add("ready");
    }

    async function runTradingAgent() {
      const symbol = symbolInput.value.trim();
      const tradeDate = dateInput.value.trim();
      if (!symbol || !tradeDate) {
        errorText.textContent = "请输入股票代码和交易日。";
        errorText.classList.add("visible");
        return;
      }
      runButton.disabled = true;
      runButton.textContent = "运行中...";
      errorText.classList.remove("visible");
      try {
        const response = await fetch("/api/run-tradingagent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol, trade_date: tradeDate }),
        });
        const payload = await response.json();
        if (!response.ok || payload.error) {
          throw new Error(payload.error || "TradingAgent 运行失败");
        }
        render(payload);
      } catch (error) {
        errorText.textContent = error.message || "TradingAgent 服务暂时不可用。";
        errorText.classList.add("visible");
      } finally {
        runButton.disabled = false;
        runButton.textContent = "运行 TradingAgent";
      }
    }

    runButton.addEventListener("click", runTradingAgent);
  </script>
</body>
</html>
"""


def _classify_buy_decision(content: str) -> dict[str, str]:
    text = content or ""
    negative_terms = [
        "不建议买入",
        "不适合买入",
        "暂不适合买入",
        "不宜追高",
        "避免追高",
        "谨慎买入",
        "观望",
        "减仓",
        "风险较大",
        "短期承压",
    ]
    positive_terms = [
        "适合买入",
        "建议买入",
        "可以买入",
        "逢低布局",
        "逢低关注",
        "存在机会",
        "具备配置价值",
        "超跌反弹机会",
    ]
    if any(term in text for term in negative_terms):
        return {
            "verdict_level": "avoid",
            "verdict": "暂不建议直接买入",
            "reason": "报告中出现观望、谨慎、承压或追高风险信号，当前更适合作为观察标的。",
        }
    if any(term in text for term in positive_terms):
        return {
            "verdict_level": "buy",
            "verdict": "可关注买入机会",
            "reason": "报告中出现买入、逢低布局或机会类表述，但仍需结合仓位和风险控制。",
        }
    return {
        "verdict_level": "watch",
        "verdict": "需要观察，不给出直接买入信号",
        "reason": "诊断报告没有形成足够明确的买入信号，建议继续关注关键价位、资金面和基本面变化。",
    }


def _analyze_stock(stock: str) -> dict[str, object]:
    stock = (stock or "").strip()
    if not stock:
        return {"error": "请输入股票名称或代码。"}
    if not STOCK_DIAGNOSIS_SCRIPT.exists():
        return {"error": "stock-diagnosis skill 脚本不存在。"}

    query = f"{stock} 当前是否适合买入？请给出明确结论和主要依据"
    completed = subprocess.run(
        [sys.executable, str(STOCK_DIAGNOSIS_SCRIPT), "--query", query, "--no-save"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0:
        message = output or error or "股票分析失败，请稍后重试。"
        if message.startswith("Error: "):
            message = message.removeprefix("Error: ").strip()
        return {"error": message[-1000:]}
    decision = _classify_buy_decision(output)
    return {
        "stock": stock,
        "query": query,
        "content": output,
        **decision,
    }


def _run_tradingagent(symbol: str, trade_date: str) -> dict[str, object]:
    symbol = (symbol or "").strip()
    trade_date = (trade_date or "").strip()
    if not symbol:
        return {"error": "请输入股票代码。"}
    if not trade_date:
        return {"error": "请输入交易日。"}
    if not TRADINGAGENT_ROOT.exists():
        return {"error": "tradingagent-main 项目目录不存在。"}
    if not TRADINGAGENT_SCRIPT.exists():
        return {"error": "TradingAgent 桥接脚本不存在。"}

    cached = _load_cached_tradingagent_report(symbol, trade_date)
    if cached:
        return cached

    completed = subprocess.run(
        [
            sys.executable,
            str(TRADINGAGENT_SCRIPT),
            "--symbol",
            symbol,
            "--trade-date",
            trade_date,
        ],
        cwd=TRADINGAGENT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=900,
    )
    marker = "__TRADINGAGENT_RESULT__"
    payload_line = ""
    for line in reversed((completed.stdout or "").splitlines()):
        if line.startswith(marker):
            payload_line = line[len(marker) :]
            break
    if not payload_line:
        message = (completed.stderr or completed.stdout or "TradingAgent 未返回结果。").strip()
        return {"error": message[-2000:]}
    try:
        payload = json.loads(payload_line)
    except json.JSONDecodeError:
        return {"error": "TradingAgent 返回结果无法解析。"}
    if completed.returncode != 0 and not payload.get("error"):
        payload["error"] = (completed.stderr or "TradingAgent 运行失败。").strip()[-2000:]
    if payload.get("ok") is False:
        payload["error"] = str(payload.get("error") or "TradingAgent 运行失败。")
    return payload


def _normalize_tradingagent_symbol(symbol: str) -> str:
    text = (symbol or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def _normalize_tradingagent_date(trade_date: str) -> str:
    return (trade_date or "").strip().replace("-", "").replace("/", "").replace(".", "")


def _read_tradingagent_file(path: Path, limit: int = 50000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _classify_tradingagent_action(text: str) -> str:
    match = re.search(r"评级\**\s*[:：]\s*([A-Za-z]+)", text or "")
    if match:
        value = match.group(1).upper()
        if value in {"BUY", "HOLD", "SELL"}:
            return value
    upper = (text or "").upper()
    for action in ("SELL", "BUY", "HOLD"):
        if action in upper:
            return action
    return "HOLD"


def _extract_tradingagent_rationale(text: str) -> str:
    if not text:
        return ""
    marker = "2. **执行摘要**:"
    if marker in text:
        part = text.split(marker, 1)[1]
        next_marker = "\n3."
        if next_marker in part:
            part = part.split(next_marker, 1)[0]
        return part.strip()
    return text[:1200].strip()


def _load_cached_tradingagent_report(symbol: str, trade_date: str) -> dict[str, object] | None:
    normalized_symbol = _normalize_tradingagent_symbol(symbol)
    normalized_date = _normalize_tradingagent_date(trade_date)
    if not normalized_symbol or not normalized_date:
        return None
    reports_dir = TRADINGAGENT_ROOT / "reports"
    if not reports_dir.exists():
        return None
    matches = sorted(
        reports_dir.glob(f"{normalized_symbol}_{normalized_date}_*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        return None
    report_dir = matches[0]
    decision_file = report_dir / "4_portfolio" / "final_trade_decision_report.md"
    report_file = report_dir / "complete_report.md"
    report_pdf_file = report_dir / "complete_report.pdf"
    decision_text = _read_tradingagent_file(decision_file, limit=12000)
    preview = _read_tradingagent_file(report_file, limit=50000)
    action = _classify_tradingagent_action(decision_text)
    return {
        "ok": True,
        "cached": True,
        "symbol": symbol,
        "trade_date": trade_date,
        "action": action,
        "rationale": _extract_tradingagent_rationale(decision_text),
        "confidence": None,
        "report_file": str(report_file) if report_file.exists() else "",
        "report_pdf_file": str(report_pdf_file) if report_pdf_file.exists() else "",
        "report_dir": str(report_dir),
        "report_preview": preview or decision_text,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def do_GET(self) -> None:
        if self.path == "/":
            data = _home_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path in {"/strategy.html", "/reports/index.html"}:
            self._send_file(REPORT_PATH, "text/html; charset=utf-8")
            return
        if self.path == "/stock.html":
            data = _stock_workbench_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/tradingagent.html":
            data = _tradingagent_workbench_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/api/update-status":
            self._send_json(_state_snapshot())
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/update-stock-pool":
            started = _start_update()
            status = 202 if started else 200
            self._send_json(_state_snapshot(), status=status)
            return
        if self.path == "/api/analyze-stock":
            payload = self._read_json_body()
            result = _analyze_stock(str(payload.get("stock", "")))
            self._send_json(result, status=400 if result.get("error") else 200)
            return
        if self.path == "/api/run-tradingagent":
            payload = self._read_json_body()
            result = _run_tradingagent(
                str(payload.get("symbol", "")),
                str(payload.get("trade_date", "")),
            )
            self._send_json(result, status=400 if result.get("error") else 200)
            return
        self.send_error(404)


def main() -> None:
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Report server: http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
