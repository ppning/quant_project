from __future__ import annotations

import argparse
from datetime import datetime
from html import escape
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
    summarize_first_board_performance,
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


def table_html(title: str, frame: pd.DataFrame, max_rows: int | None = None) -> str:
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
    return f"<section><h2>{escape(title)}</h2>{note}<div class=\"table-wrap\">{table}</div></section>"


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
    historical_picks: pd.DataFrame,
    metrics: dict[str, object],
) -> None:
    metric_cards = "\n".join(
        f"<div class=\"metric\"><span>{escape(str(name))}</span><strong>{metric_value_html(value)}</strong></div>"
        for name, value in metrics.items()
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
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.5;
    }}
    main {{
      max-width: 1200px;
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
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 26px;
    }}
    .metric {{
      background: var(--panel);
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
    section {{
      margin-top: 22px;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 18px;
    }}
    .table-wrap {{
      overflow: auto;
      background: var(--panel);
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
  </style>
</head>
<body>
  <main>
    <h1>首板涨停预测报告</h1>
    <p class="subtitle">低位启动首板模型：T 日收盘后筛选，观察 T+1 是否首次涨停。当前版本只生成 HTML 报告。</p>
    <div class="metrics">{metric_cards}</div>
    {table_html("最新首板候选", latest_candidates)}
    {table_html("历史首板信号回看", historical_picks, max_rows=300)}
  </main>
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


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    end_date = normalize_trade_date(args.trade_date) or config.data.end_date
    config.output.report_dir.mkdir(parents=True, exist_ok=True)
    symbols, names = resolve_universe(
        manual_symbols=config.universe.symbols,
        manual_names=config.universe.names,
        index_symbols=config.universe.index_symbols,
        cache_dir=config.data.cache_dir,
        max_symbols=args.max_symbols if args.max_symbols is not None else config.universe.max_symbols,
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
    historical_picks = historical_first_board_picks(
        scored,
        config.strategy.top_n,
        config.strategy.min_history_days,
    )
    latest_candidates = place_name_after_symbol(latest_candidates)
    historical_picks = place_name_after_symbol(historical_picks)
    metrics = summarize_first_board_performance(historical_picks)
    prediction_date = ""
    if not latest_candidates.empty and "date" in latest_candidates.columns:
        prediction_date = pd.to_datetime(latest_candidates["date"].max()).strftime("%Y-%m-%d")
    if prediction_date:
        metrics = {"预测基准日": prediction_date, "预测目标": "T+1 涨停"} | metrics
    write_html_report(
        config.output.report_dir / "index.html",
        latest_candidates,
        historical_picks,
        metrics,
    )

    print(f"Universe symbols: {len(symbols)}")
    print(f"Loaded rows: {len(history)}")
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
