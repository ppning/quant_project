from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import io
from pathlib import Path

import akshare as ak
import pandas as pd


REALTIME_COLUMNS = [
    "symbol",
    "spot_turnover_rate",
    "spot_volume_ratio",
    "float_market_cap_yi",
    "total_market_cap_yi",
    "spot_pct_change",
]

BOARD_COLUMNS = ["symbol", "industry_name", "industry_heat", "concept_name", "concept_heat"]
TAIL_COLUMNS = ["symbol", "tail_amount_ratio", "tail_return", "tail_close_to_high"]


def normalize_symbol(symbol: object) -> str:
    return str(symbol).strip().zfill(6)


def _read_cache(path: Path, dtype: dict[str, str] | None = None) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=dtype or {"symbol": str})
    if "symbol" in frame.columns:
        frame["symbol"] = frame["symbol"].map(normalize_symbol)
    return frame


def load_realtime_snapshot(cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    cache_path = cache_dir / "realtime_snapshot.csv"
    if cache_path.exists() and not refresh:
        return _read_cache(cache_path)

    try:
        raw = ak.stock_zh_a_spot_em()
        rename = {
            "代码": "symbol",
            "换手率": "spot_turnover_rate",
            "量比": "spot_volume_ratio",
            "流通市值": "float_market_cap",
            "总市值": "total_market_cap",
            "涨跌幅": "spot_pct_change",
        }
        selected = [column for column in rename if column in raw.columns]
        frame = raw.rename(columns=rename)[[rename[column] for column in selected]].copy()
        frame["symbol"] = frame["symbol"].map(normalize_symbol)
        for column in ["spot_turnover_rate", "spot_volume_ratio", "float_market_cap", "total_market_cap", "spot_pct_change"]:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["float_market_cap_yi"] = frame.get("float_market_cap", pd.NA) / 100_000_000
        frame["total_market_cap_yi"] = frame.get("total_market_cap", pd.NA) / 100_000_000
        for column in REALTIME_COLUMNS:
            if column not in frame.columns:
                frame[column] = pd.NA
        frame = frame[REALTIME_COLUMNS]
        frame.to_csv(cache_path, index=False, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        print(f"Realtime warning: failed to load spot snapshot: {exc}")
        if cache_path.exists():
            return _read_cache(cache_path)
        return pd.DataFrame(columns=REALTIME_COLUMNS)


def _board_member_frame(board_type: str, board_name: str, heat: float) -> pd.DataFrame:
    if board_type == "industry":
        raw = ak.stock_board_industry_cons_em(symbol=board_name)
    else:
        raw = ak.stock_board_concept_cons_em(symbol=board_name)
    if "代码" not in raw.columns:
        return pd.DataFrame(columns=["symbol", f"{board_type}_name", f"{board_type}_heat"])
    frame = pd.DataFrame(
        {
            "symbol": raw["代码"].map(normalize_symbol),
            f"{board_type}_name": board_name,
            f"{board_type}_heat": heat,
        }
    )
    return frame.drop_duplicates(subset=["symbol"])


def _load_hot_board_members(
    cache_dir: Path,
    board_type: str,
    refresh: bool,
    top_n: int,
) -> pd.DataFrame:
    cache_path = cache_dir / f"hot_{board_type}_members.csv"
    if cache_path.exists() and not refresh:
        return _read_cache(cache_path)

    try:
        name_func = ak.stock_board_industry_name_em if board_type == "industry" else ak.stock_board_concept_name_em
        raw = name_func()
        name_column = "板块名称" if "板块名称" in raw.columns else "名称"
        heat_column = "涨跌幅"
        raw[heat_column] = pd.to_numeric(raw[heat_column], errors="coerce")
        hot_boards = raw.dropna(subset=[heat_column]).sort_values(heat_column, ascending=False).head(top_n)
        frames = []
        for row in hot_boards.itertuples(index=False):
            board_name = getattr(row, name_column)
            heat = float(getattr(row, heat_column))
            try:
                frames.append(_board_member_frame(board_type, board_name, heat))
            except Exception as exc:
                print(f"Realtime warning: failed to load {board_type} board {board_name}: {exc}")
        if not frames:
            return pd.DataFrame(columns=["symbol", f"{board_type}_name", f"{board_type}_heat"])
        members = pd.concat(frames, ignore_index=True)
        members = members.sort_values(f"{board_type}_heat", ascending=False).drop_duplicates(subset=["symbol"])
        members.to_csv(cache_path, index=False, encoding="utf-8-sig")
        return members
    except Exception as exc:
        print(f"Realtime warning: failed to load {board_type} heat: {exc}")
        if cache_path.exists():
            return _read_cache(cache_path)
        return pd.DataFrame(columns=["symbol", f"{board_type}_name", f"{board_type}_heat"])


def load_board_heat(cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    industry = _load_hot_board_members(cache_dir, "industry", refresh, top_n=20)
    concept = _load_hot_board_members(cache_dir, "concept", refresh, top_n=30)
    merged = pd.merge(industry, concept, on="symbol", how="outer")
    for column in BOARD_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA
    return merged[BOARD_COLUMNS]


def _normalize_minute_frame(raw: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "时间": "time",
        "日期": "time",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    selected = [column for column in rename if column in raw.columns]
    frame = raw.rename(columns=rename)[[rename[column] for column in selected]].copy()
    frame["time"] = pd.to_datetime(frame["time"])
    for column in ["open", "close", "high", "low", "volume", "amount"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "amount" not in frame.columns and "volume" in frame.columns:
        frame["amount"] = frame["volume"]
    return frame.dropna(subset=["time", "close"]).sort_values("time")


def fetch_tail_signal(symbol: str, trade_date: pd.Timestamp, cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    tail_dir = cache_dir / "tail"
    tail_dir.mkdir(parents=True, exist_ok=True)
    date_text = trade_date.strftime("%Y-%m-%d")
    cache_path = tail_dir / f"{symbol}_{date_text}.csv"
    if cache_path.exists() and not refresh:
        return _read_cache(cache_path)

    try:
        start = f"{date_text} 09:30:00"
        end = f"{date_text} 15:00:00"
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            raw = ak.stock_zh_a_hist_min_em(symbol=symbol, start_date=start, end_date=end, period="5", adjust="")
        minute = _normalize_minute_frame(raw)
        if minute.empty:
            raise ValueError("empty minute data")
        tail = minute[minute["time"].dt.time >= datetime.strptime("14:30:00", "%H:%M:%S").time()]
        base = minute[minute["time"].dt.time <= datetime.strptime("14:30:00", "%H:%M:%S").time()]
        amount_sum = minute["amount"].sum()
        tail_amount_ratio = tail["amount"].sum() / amount_sum if amount_sum else pd.NA
        base_close = base["close"].iloc[-1] if not base.empty else minute["close"].iloc[0]
        last_close = minute["close"].iloc[-1]
        tail_high = tail["high"].max() if not tail.empty and "high" in tail.columns else minute["high"].max()
        frame = pd.DataFrame(
            {
                "symbol": [symbol],
                "tail_amount_ratio": [tail_amount_ratio],
                "tail_return": [last_close / base_close - 1 if base_close else pd.NA],
                "tail_close_to_high": [last_close / tail_high - 1 if tail_high else pd.NA],
            }
        )
        frame.to_csv(cache_path, index=False, encoding="utf-8-sig")
        return frame
    except Exception as exc:
        print(f"Realtime warning: failed to load tail signal {symbol}: {exc}")
        return pd.DataFrame(columns=TAIL_COLUMNS)


def load_tail_signals(
    symbols: list[str],
    trade_date: pd.Timestamp,
    cache_dir: Path,
    refresh: bool = False,
    workers: int = 4,
) -> pd.DataFrame:
    frames = []
    if workers <= 1:
        frames = [fetch_tail_signal(symbol, trade_date, cache_dir, refresh) for symbol in symbols]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_tail_signal, symbol, trade_date, cache_dir, refresh) for symbol in symbols]
            frames = [future.result() for future in as_completed(futures)]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=TAIL_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def enrich_realtime_features(
    scored: pd.DataFrame,
    cache_dir: Path,
    refresh: bool = False,
    tail_limit: int = 50,
    workers: int = 4,
) -> pd.DataFrame:
    if scored.empty:
        return scored

    output = scored.copy()
    latest_date = pd.to_datetime(output["date"].max())
    latest_mask = output["date"] == latest_date
    latest = output[latest_mask].copy()

    spot = load_realtime_snapshot(cache_dir, refresh)
    board = load_board_heat(cache_dir, refresh)
    latest = latest.merge(spot, on="symbol", how="left").merge(board, on="symbol", how="left")

    tail_symbols = latest.sort_values("first_board_score", ascending=False)["symbol"].head(tail_limit).tolist()
    tail = load_tail_signals(tail_symbols, latest_date, cache_dir, refresh, workers=workers)
    latest = latest.merge(tail, on="symbol", how="left")

    realtime_columns = [column for column in REALTIME_COLUMNS + BOARD_COLUMNS + TAIL_COLUMNS if column != "symbol"]
    for column in realtime_columns:
        if column not in output.columns:
            output[column] = pd.NA
        if column in latest.columns:
            output.loc[latest_mask, column] = latest[column].to_numpy()
    return output
