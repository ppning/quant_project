from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from html import escape
import json
from pathlib import Path

import pandas as pd

from data.loader import load_universe_history
from data.enrichment import enrich_realtime_features
from data.universe import resolve_universe
from factors.calculator import add_factors
from strategy.first_board import (
    add_realtime_score,
    add_first_board_score,
    historical_first_board_picks,
    latest_first_board_candidates,
    latest_trade_tier_candidates,
    summarize_first_board_performance,
    summarize_tier_performance,
)
from utils.config import load_config


def place_name_after_symbol(frame: pd.DataFrame) -> pd.DataFrame:
    if "symbol" not in frame.columns or "name" not in frame.columns:
        return frame
    columns = [column for column in frame.columns if column != "name"]
    symbol_index = columns.index("symbol")
    columns.insert(symbol_index + 1, "name")
    return frame[columns]


def format_report_frame(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    date_columns = [column for column in display.columns if column == "date" or column.endswith("_date")]
    for column in date_columns:
        display[column] = pd.to_datetime(display[column]).dt.strftime("%Y-%m-%d")

    rename_columns = {
        "date": "日期",
        "symbol": "代码",
        "name": "名称",
        "close": "收盘价",
        "pct_change": "当日涨幅%",
        "trade_tier": "分档",
        "buy_signal_score": "买入确认分",
        "buy_core_checks": "核心条件数",
        "buy_risk_veto": "风险否决",
        "realtime_score": "实时增强分",
        "first_board_score": "首板分",
        "first_board_candidate": "严格候选",
        "first_board_watchlist": "观察池",
        "next_pct_change": "次日涨幅%",
        "next_limit_up": "次日涨停",
        "turnover_rate": "换手率%",
        "spot_turnover_rate": "实时换手率%",
        "spot_volume_ratio": "实时量比",
        "float_market_cap_yi": "流通市值(亿)",
        "float_market_cap_est_yi": "估算流通市值(亿)",
        "effective_float_market_cap_yi": "有效流通市值(亿)",
        "industry_name": "热点行业",
        "industry_heat": "行业涨幅%",
        "concept_name": "热点概念",
        "concept_heat": "概念涨幅%",
        "market_sentiment_score": "市场情绪分",
        "market_up_ratio": "市场上涨占比",
        "market_limit_up_count": "市场涨停数",
        "market_first_limit_up_count": "市场首板数",
        "market_broken_limit_rate": "市场炸板率",
        "tail_amount_ratio": "尾盘成交占比",
        "tail_return": "14:30后涨幅",
        "tail_close_to_high": "尾盘收盘距高点",
        "effective_float_market_cap_yi": "有效流通市值(亿)",
        "volume_ratio_5_display": "量能/5日均量",
        "volume_ratio_20_display": "量能/20日均量",
        "limit_up_count_20d": "近20日涨停数",
        "ma_alignment": "均线排列",
        "ma20_distance": "偏离20日线",
        "rsi_6": "RSI(6)",
        "low_position_252": "一年低位分位",
        "distance_high_252": "距一年高点",
        "distance_platform_high_20": "距20日平台上轨",
        "near_platform_breakout": "接近平台突破",
        "near_limit_touch": "盘中接近涨停",
        "healthy_near_limit_touch": "健康近板",
        "broken_limit_touch": "盘中炸板/近板失败",
        "failed_near_limit_touch": "失败近板",
        "huge_volume_release": "巨量兑现",
        "high_position_risk": "高位透支",
        "limit_up_distance": "收盘距涨停价",
        "low_position_60": "60日低位分位",
        "close_to_high": "收盘距日高",
        "intraday_strength": "日内强势度",
        "close_above_ma20": "站上20日线",
        "ma5_slope": "5日线斜率",
        "rank": "排名",
        "feature": "特征",
        "importance": "重要性",
    }
    display = display.rename(columns={key: value for key, value in rename_columns.items() if key in display.columns})

    bool_columns = [
        "次日涨停",
        "风险否决",
        "严格候选",
        "观察池",
        "站上20日线",
        "均线排列",
        "接近平台突破",
        "盘中接近涨停",
        "健康近板",
        "盘中炸板/近板失败",
        "失败近板",
        "巨量兑现",
        "高位透支",
    ]
    for column in bool_columns:
        if column in display.columns:
            display[column] = display[column].map({True: "是", False: "否"}).fillna("")

    numeric_columns = display.select_dtypes(include="number").columns
    for column in numeric_columns:
        display[column] = display[column].map(lambda value: "" if pd.isna(value) else round(float(value), 4))
    display = display.where(pd.notna(display), "")
    return display


def table_html(
    title: str,
    frame: pd.DataFrame,
    max_rows: int | None = None,
    result_kind: str = "strategy-one",
) -> str:
    display = frame.copy()
    if max_rows is not None and len(display) > max_rows:
        display = display.tail(max_rows)
        note = f"<p class=\"note\">仅展示最近 {max_rows} 行，共 {len(frame)} 行。</p>"
    else:
        note = ""

    if display.empty:
        table = "<p class=\"empty\">暂无数据</p>"
    else:
        table = format_report_frame(display).to_html(index=False, escape=True, classes="report-table", border=0)
    return (
        f"<section class=\"result-section\" data-result-kind=\"{escape(result_kind)}\">"
        f"<div class=\"section-heading\"><h2>{escape(title)}</h2><span>{len(frame)} 条</span></div>"
        f"{note}<div class=\"table-wrap\">{table}</div></section>"
    )


def metric_value_html(value: object) -> str:
    if isinstance(value, str):
        return escape(value)
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return escape(str(value))


def write_html_report(
    output_path: Path,
    latest_candidates: pd.DataFrame,
    trial_candidates: pd.DataFrame,
    watch_candidates: pd.DataFrame,
    reject_candidates: pd.DataFrame,
    historical_picks: pd.DataFrame,
    metrics: dict[str, object],
) -> None:
    metric_cards = "\n".join(
        f"<div class=\"metric\"><span>{escape(str(name))}</span><strong>{metric_value_html(value)}</strong></div>"
        for name, value in metrics.items()
    )
    strategy_summary = {
        "试仓": len(trial_candidates),
        "观察": len(watch_candidates),
        "最新候选": len(latest_candidates),
        "剔除样本": len(reject_candidates),
    }
    strategy_summary_html = "\n".join(
        f"<div class=\"summary-item\"><span>{escape(name)}</span><strong>{count}</strong></div>"
        for name, count in strategy_summary.items()
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>首板涨停预测报告</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #146c94;
      --accent-strong: #0f4c75;
      --success: #1f8a70;
      --warning: #b7791f;
    }}
    *,
    *::before,
    *::after {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.5;
    }}
    main {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      font-weight: 700;
    }}
    .subtitle {{
      margin: 0 0 22px;
      color: var(--muted);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(820px, 1fr);
      gap: 20px;
      align-items: stretch;
      min-height: calc(100vh - 130px);
      overflow-x: auto;
    }}
    .strategy-sidebar {{
      position: sticky;
      top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      align-self: start;
      font-size: 13px;
    }}
    .sidebar-title {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
    }}
    .sidebar-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .update-pool-button {{
      flex: 0 0 auto;
      min-height: 30px;
      border: 1px solid rgba(20, 108, 148, 0.35);
      border-radius: 6px;
      background: #eef8fb;
      color: var(--accent-strong);
      padding: 0 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    .update-pool-button:disabled {{
      background: #e2e8f0;
      color: #64748b;
      border-color: #cbd5e1;
      cursor: wait;
    }}
    .sidebar-meta {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .strategy-list {{
      display: grid;
      gap: 10px;
      margin: 16px 0;
    }}
    .strategy-option {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
      color: var(--text);
      font: inherit;
      text-align: left;
    }}
    .strategy-option.active {{
      border-color: rgba(20, 108, 148, 0.55);
      background: #eef8fb;
      box-shadow: inset 3px 0 0 var(--accent);
    }}
    .strategy-option.disabled {{
      opacity: 0.58;
    }}
    .strategy-option strong {{
      display: block;
      margin-bottom: 4px;
      font-size: 14px;
    }}
    .strategy-option span {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}
    .strategy-option small {{
      display: inline-block;
      margin-top: 8px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }}
    .filter-button {{
      width: 100%;
      min-height: 36px;
      margin-top: 10px;
      display: block;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      padding: 0 18px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }}
    .filter-button:hover {{
      background: var(--accent-strong);
    }}
    .filter-button:disabled {{
      background: #cbd5e1;
      color: #475569;
      cursor: not-allowed;
    }}
    .sidebar-note {{
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 12px;
    }}
    .result-panel {{
      min-width: 820px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      font-size: 13px;
    }}
    .panel-header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }}
    .panel-title {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
    }}
    .panel-subtitle {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .base-date {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
      min-width: 150px;
      text-align: right;
    }}
    .base-date span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
    }}
    .base-date strong {{
      display: block;
      margin-top: 4px;
      font-size: 16px;
    }}
    .result-status {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .summary-grid {{
      display: none;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    body.results-ready .summary-grid {{
      display: grid;
    }}
    .summary-item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
    }}
    .summary-item span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
    }}
    .summary-item strong {{
      display: block;
      margin-top: 4px;
      font-size: 20px;
    }}
    .result-placeholder {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--muted);
      padding: 26px 18px;
      text-align: center;
    }}
    body.results-ready .result-placeholder {{
      display: none;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 26px;
    }}
    .metric {{
      background: #fbfcfe;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 22px;
    }}
    .result-section {{
      display: none;
      margin-top: 22px;
    }}
    body.results-ready .result-section {{
      display: block;
    }}
    .section-heading {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }}
    h2 {{
      margin: 0;
      font-size: 18px;
    }}
    .section-heading span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .table-wrap {{
      overflow: auto;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .report-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      white-space: nowrap;
    }}
    .report-table th,
    .report-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: right;
    }}
    .report-table th {{
      position: sticky;
      top: 0;
      background: #edf2f7;
      color: #344054;
      font-weight: 600;
    }}
    .report-table th:first-child,
    .report-table td:first-child,
    .report-table th:nth-child(2),
    .report-table td:nth-child(2),
    .report-table th:nth-child(3),
    .report-table td:nth-child(3) {{
      text-align: left;
    }}
    .note,
    .empty {{
      color: var(--muted);
      margin: 0 0 8px;
      font-size: 13px;
    }}
    @media (max-width: 700px) {{
      main {{
        padding: 20px 12px 36px;
      }}
      .layout {{
        grid-template-columns: 280px minmax(760px, 1fr);
        min-height: calc(100vh - 110px);
      }}
      .strategy-sidebar {{
        position: sticky;
        left: 0;
        z-index: 2;
      }}
      .result-panel {{
        min-width: 760px;
      }}
      .panel-header {{
        display: flex;
      }}
      .base-date {{
        margin-top: 0;
        text-align: right;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>策略筛选工作台</h1>
    <p class="subtitle">沪深300 + 中证500活跃板块股票池，按策略筛选并展示候选结果。</p>
    <div class="layout">
      <aside class="strategy-sidebar" aria-label="筛选策略列表">
        <div class="sidebar-header">
          <p class="sidebar-title">筛选策略</p>
          <button class="update-pool-button" id="updatePoolButton" type="button">更新股票池</button>
        </div>
        <p class="sidebar-meta">先选择策略，再点击筛选按钮。</p>
        <div class="strategy-list">
          <div class="strategy-option active" data-strategy="strategy-one" data-label="策略一">
            <strong>策略一</strong>
            <span>低位启动首板，结合放量、趋势、热点和尾盘确认。</span>
            <small>当前可用</small>
            <button class="filter-button" type="button" data-filter-strategy="strategy-one" data-label="策略一">按策略一筛选</button>
          </div>
          <div class="strategy-option disabled" data-strategy="strategy-two" data-label="策略二">
            <strong>策略二</strong>
            <span>预留策略位，可接入机器学习涨停概率。</span>
            <small>待接入</small>
            <button class="filter-button" type="button" disabled>待接入</button>
          </div>
          <div class="strategy-option disabled" data-strategy="strategy-three" data-label="策略三">
            <strong>策略三</strong>
            <span>预留策略位，可接入板块轮动强度筛选。</span>
            <small>待接入</small>
            <button class="filter-button" type="button" disabled>待接入</button>
          </div>
          <div class="strategy-option disabled" data-strategy="strategy-four" data-label="策略四">
            <strong>策略四</strong>
            <span>预留策略位，可接入尾盘资金异动筛选。</span>
            <small>待接入</small>
            <button class="filter-button" type="button" disabled>待接入</button>
          </div>
          <div class="strategy-option disabled" data-strategy="strategy-five" data-label="策略五">
            <strong>策略五</strong>
            <span>预留策略位，可接入自定义组合条件。</span>
            <small>待接入</small>
            <button class="filter-button" type="button" disabled>待接入</button>
          </div>
        </div>
        <p class="sidebar-note">当前只有策略一会返回结果，其余策略作为后续扩展入口。</p>
      </aside>
      <section class="result-panel" aria-label="筛选结果">
        <div class="panel-header">
          <div>
            <p class="panel-title">筛选结果</p>
            <p class="panel-subtitle">右侧展示当前策略的指标、候选分层和历史回看。</p>
          </div>
          <div class="base-date">
            <span>报告基准日</span>
            <strong>{escape(str(metrics.get("预测基准日", "")))}</strong>
          </div>
        </div>
        <div class="metrics">{metric_cards}</div>
        <div class="result-status">
          <span id="resultStatus">请选择左侧策略并点击筛选按钮。</span>
        </div>
        <div class="summary-grid" aria-label="筛选汇总">
          {strategy_summary_html}
        </div>
        <div class="result-placeholder">点击左侧“按策略一筛选”后展示候选池、分层结果和历史回看。</div>
        {table_html("试仓候选", trial_candidates)}
        {table_html("观察候选", watch_candidates)}
        {table_html("放弃/剔除样本", reject_candidates)}
        {table_html("最新首板候选", latest_candidates)}
        {table_html("历史首板信号回看", historical_picks, max_rows=300)}
      </section>
    </div>
  </main>
  <script>
    const resultStatus = document.getElementById("resultStatus");
    const updatePoolButton = document.getElementById("updatePoolButton");
    const strategyOptions = Array.from(document.querySelectorAll(".strategy-option"));
    const filterButtons = Array.from(document.querySelectorAll("[data-filter-strategy]"));

    filterButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        const activeStrategyLabel = button.dataset.label || "策略一";
        const activeStrategy = button.dataset.filterStrategy;
        strategyOptions.forEach((item) => item.classList.remove("active"));
        document.querySelector(`[data-strategy="${{activeStrategy}}"]`).classList.add("active");
        document.body.classList.add("results-ready");
        resultStatus.textContent = `已按${{activeStrategyLabel}}完成筛选，结果如下。`;
        document.querySelector(".summary-grid").scrollIntoView({{ behavior: "smooth", block: "start" }});
      }});
    }});

    async function readUpdateStatus() {{
      const response = await fetch("/api/update-status", {{ cache: "no-store" }});
      if (!response.ok) {{
        throw new Error("status failed");
      }}
      return response.json();
    }}

    function renderUpdateButton(status) {{
      if (status.running) {{
        updatePoolButton.disabled = true;
        updatePoolButton.textContent = `更新中 ${{status.progress}}%`;
        return;
      }}
      updatePoolButton.disabled = false;
      updatePoolButton.textContent = status.progress === 100 ? "更新完成" : "更新股票池";
    }}

    async function pollUpdateStatus() {{
      const status = await readUpdateStatus();
      renderUpdateButton(status);
      if (status.running) {{
        window.setTimeout(pollUpdateStatus, 1500);
        return;
      }}
      if (status.progress === 100) {{
        window.setTimeout(() => window.location.reload(), 800);
      }} else if (status.error) {{
        updatePoolButton.textContent = "更新失败";
        resultStatus.textContent = status.error;
      }}
    }}

    updatePoolButton.addEventListener("click", async () => {{
      if (window.location.protocol === "file:") {{
        resultStatus.textContent = "更新股票池需要通过本地服务打开页面，不能直接在 file:// 下运行。";
        return;
      }}
      updatePoolButton.disabled = true;
      updatePoolButton.textContent = "更新中 0%";
      resultStatus.textContent = "正在拉取新一天股票池并重新筛选。";
      try {{
        const response = await fetch("/api/update-stock-pool", {{ method: "POST" }});
        if (!response.ok) {{
          throw new Error("start failed");
        }}
        pollUpdateStatus();
      }} catch (error) {{
        updatePoolButton.disabled = false;
        updatePoolButton.textContent = "更新失败";
        resultStatus.textContent = "更新服务不可用，请确认已通过本地服务打开页面。";
      }}
    }});
  </script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an A-share first-board limit-up prediction pipeline.")
    parser.add_argument("--config", default="utils/sample_config.toml", help="Path to the TOML config file.")
    parser.add_argument("--refresh", action="store_true", help="Refresh AkShare data instead of using CSV cache.")
    parser.add_argument("--max-symbols", type=int, default=None, help="Override universe.max_symbols for quick tests.")
    parser.add_argument(
        "--trade-date",
        default=None,
        help="Use this T date as the prediction base date, e.g. 20260603, 2026-06-03, or 2026.06.03.",
    )
    return parser


def normalize_trade_date(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip().replace("-", "").replace(".", "").replace("/", "")
    try:
        return datetime.strptime(text, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise SystemExit(f"Invalid --trade-date: {value}. Expected YYYYMMDD or YYYY-MM-DD.") from exc


def combined_history_cache_path(config: object, end_date: str, max_symbols: int) -> Path | None:
    if not end_date:
        return None
    key_payload = {
        "adjust": config.data.adjust,
        "end_date": end_date,
        "index_symbols": config.universe.index_symbols,
        "manual_symbols": config.universe.symbols,
        "max_symbols": max_symbols,
        "mode": config.universe.mode,
        "board_top_n": config.universe.board_top_n,
        "universe_selector_version": 2,
        "provider": config.data.provider,
        "start_date": config.data.start_date,
    }
    key = hashlib.sha1(json.dumps(key_payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    processed_dir = config.data.cache_dir.parent / "processed"
    return processed_dir / f"history_{end_date}_{key}.csv"


def load_combined_history_cache(path: Path) -> pd.DataFrame:
    history = pd.read_csv(path, parse_dates=["date"], dtype={"symbol": str})
    history["symbol"] = history["symbol"].str.zfill(6)
    return history


def save_combined_history_cache(path: Path, history: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(path, index=False)


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    end_date = normalize_trade_date(args.trade_date) or config.data.end_date
    max_symbols = args.max_symbols if args.max_symbols is not None else config.universe.max_symbols
    history_cache_path = combined_history_cache_path(config, end_date, max_symbols)
    config.output.report_dir.mkdir(parents=True, exist_ok=True)

    loaded_combined_cache = bool(history_cache_path and history_cache_path.exists() and not args.refresh)
    if loaded_combined_cache:
        history = load_combined_history_cache(history_cache_path)
        symbols = history["symbol"].drop_duplicates().tolist()
        names = (
            history.drop_duplicates(subset=["symbol"])
            .set_index("symbol")["name"]
            .dropna()
            .astype(str)
            .to_dict()
        )
    else:
        symbols, names = resolve_universe(
            manual_symbols=config.universe.symbols,
            manual_names=config.universe.names,
            index_symbols=config.universe.index_symbols,
            cache_dir=config.data.cache_dir,
            max_symbols=max_symbols,
            mode=config.universe.mode,
            board_top_n=config.universe.board_top_n,
            refresh=args.refresh,
        )
        history = load_universe_history(
            symbols=symbols,
            start_date=config.data.start_date,
            end_date=end_date,
            adjust=config.data.adjust,
            cache_dir=config.data.cache_dir,
            symbol_names=names,
            provider=config.data.provider,
            workers=config.data.workers,
            refresh=args.refresh,
        )
        if history_cache_path is not None:
            save_combined_history_cache(history_cache_path, history)

    factored = add_factors(history)
    scored = add_first_board_score(factored)
    scored = enrich_realtime_features(
        scored,
        cache_dir=config.data.cache_dir,
        refresh=args.refresh,
        tail_limit=50,
        workers=min(config.data.workers, 6),
    )
    scored = add_realtime_score(scored)
    latest_candidates = latest_first_board_candidates(
        scored,
        config.strategy.top_n,
        config.strategy.min_history_days,
    )
    trial_candidates = latest_trade_tier_candidates(
        scored,
        "试仓",
        config.strategy.top_n,
        config.strategy.min_history_days,
    )
    watch_candidates = latest_trade_tier_candidates(
        scored,
        "观察",
        config.strategy.top_n,
        config.strategy.min_history_days,
    )
    reject_candidates = latest_trade_tier_candidates(
        scored,
        "放弃",
        config.strategy.top_n,
        config.strategy.min_history_days,
    )
    historical_picks = historical_first_board_picks(
        scored,
        config.strategy.top_n,
        config.strategy.min_history_days,
    )
    latest_candidates = place_name_after_symbol(latest_candidates)
    trial_candidates = place_name_after_symbol(trial_candidates)
    watch_candidates = place_name_after_symbol(watch_candidates)
    reject_candidates = place_name_after_symbol(reject_candidates)
    historical_picks = place_name_after_symbol(historical_picks)
    metrics = {
        **summarize_first_board_performance(historical_picks),
        **summarize_tier_performance(scored, "试仓", config.strategy.top_n, config.strategy.min_history_days),
        **summarize_tier_performance(scored, "观察", config.strategy.top_n, config.strategy.min_history_days),
    }
    prediction_date = ""
    if not latest_candidates.empty and "date" in latest_candidates.columns:
        prediction_date = pd.to_datetime(latest_candidates["date"].max()).strftime("%Y-%m-%d")
    if prediction_date:
        metrics = {"预测基准日": prediction_date, "预测目标": "T+1 涨停"} | metrics
    write_html_report(
        config.output.report_dir / "index.html",
        latest_candidates,
        trial_candidates,
        watch_candidates,
        reject_candidates,
        historical_picks,
        metrics,
    )

    print(f"Universe symbols: {len(symbols)}")
    print(f"Loaded rows: {len(history)}")
    if loaded_combined_cache:
        print(f"Loaded combined history cache: {history_cache_path}")
    elif history_cache_path is not None:
        print(f"Saved combined history cache: {history_cache_path}")
    if end_date:
        print(f"Prediction base date requested: {end_date}")
    if prediction_date:
        print(f"Prediction base date used: {prediction_date}")
    print(f"Latest first-board candidates: {len(latest_candidates)}")
    print(f"Historical first-board picks: {len(historical_picks)}")
    print(f"Reports: {config.output.report_dir}")
    print(f"HTML report: {config.output.report_dir / 'index.html'}")


if __name__ == "__main__":
    main()
