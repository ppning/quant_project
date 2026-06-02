from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import io
from pathlib import Path

import akshare as ak
import pandas as pd

EASTMONEY_COLUMNS = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "涨跌幅": "pct_change",
}

EASTMONEY_OPTIONAL_COLUMNS = {
    "换手率": "turnover_rate",
}

NORMALIZED_COLUMNS = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_change",
    "turnover_rate",
]


def ensure_history_schema(frame: pd.DataFrame) -> pd.DataFrame:
    for column in NORMALIZED_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[NORMALIZED_COLUMNS]


def normalize_eastmoney_ohlcv(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    missing = [column for column in EASTMONEY_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"{symbol} missing AkShare columns: {missing}")

    rename_columns = {**EASTMONEY_COLUMNS, **EASTMONEY_OPTIONAL_COLUMNS}
    selected_columns = [column for column in rename_columns if column in raw.columns]
    frame = raw.rename(columns=rename_columns)[[rename_columns[column] for column in selected_columns]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = symbol

    numeric_columns = ["open", "close", "high", "low", "volume", "amount", "pct_change", "turnover_rate"]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    return ensure_history_schema(frame)


def normalize_tencent_ohlcv(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = ["date", "open", "close", "high", "low", "amount"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError(f"{symbol} missing Tencent columns: {missing}")

    frame = raw[required].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = symbol

    numeric_columns = ["open", "close", "high", "low", "amount"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    # Tencent's AkShare wrapper exposes amount only; use it as the liquidity proxy for volume factors.
    frame["volume"] = frame["amount"]
    frame["pct_change"] = frame["close"].pct_change() * 100
    frame["turnover_rate"] = pd.NA
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    return ensure_history_schema(frame)


def with_market_prefix(symbol: str) -> str:
    return f"sh{symbol}" if symbol.startswith(("5", "6", "9")) else f"sz{symbol}"


def fetch_from_eastmoney(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    actual_end_date = end_date or datetime.now().strftime("%Y%m%d")
    raw = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=actual_end_date,
        adjust=adjust,
    )
    return normalize_eastmoney_ohlcv(raw, symbol)


def fetch_from_tencent(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    actual_end_date = end_date or datetime.now().strftime("%Y%m%d")
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        raw = ak.stock_zh_a_hist_tx(
            symbol=with_market_prefix(symbol),
            start_date=start_date,
            end_date=actual_end_date,
            adjust=adjust,
            timeout=15,
        )
    return normalize_tencent_ohlcv(raw, symbol)


def fetch_symbol_history(symbol: str, start_date: str, end_date: str, adjust: str, provider: str) -> pd.DataFrame:
    normalized_provider = provider.lower()
    if normalized_provider == "eastmoney":
        return fetch_from_eastmoney(symbol, start_date, end_date, adjust)
    if normalized_provider == "tencent":
        return fetch_from_tencent(symbol, start_date, end_date, adjust)
    if normalized_provider != "auto":
        raise ValueError(f"unsupported data provider: {provider}")

    try:
        return fetch_from_eastmoney(symbol, start_date, end_date, adjust)
    except Exception as eastmoney_error:
        try:
            frame = fetch_from_tencent(symbol, start_date, end_date, adjust)
            print(f"Data fallback: {symbol} eastmoney failed, loaded from tencent.")
            return frame
        except Exception as tencent_error:
            raise RuntimeError(
                f"eastmoney failed: {eastmoney_error}; tencent failed: {tencent_error}"
            ) from tencent_error


def load_symbol_history(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
    cache_dir: Path,
    provider: str,
    refresh: bool = False,
) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_name = f"{symbol}_{start_date}_{end_date or 'latest'}_{adjust or 'none'}_{provider}.csv"
    cache_path = cache_dir / cache_name
    legacy_cache_path = cache_dir / f"{symbol}_{start_date}_{end_date or 'latest'}_{adjust or 'none'}.csv"

    if cache_path.exists() and not refresh:
        frame = pd.read_csv(cache_path, parse_dates=["date"], dtype={"symbol": str})
        frame["symbol"] = frame["symbol"].str.zfill(6)
        return ensure_history_schema(frame)
    if legacy_cache_path.exists() and not refresh:
        frame = pd.read_csv(legacy_cache_path, parse_dates=["date"], dtype={"symbol": str})
        frame["symbol"] = frame["symbol"].str.zfill(6)
        return ensure_history_schema(frame)

    frame = fetch_symbol_history(symbol, start_date, end_date, adjust, provider)
    frame.to_csv(cache_path, index=False)
    return frame


def load_universe_history(
    symbols: list[str],
    start_date: str,
    end_date: str,
    adjust: str,
    cache_dir: Path,
    symbol_names: dict[str, str] | None = None,
    provider: str = "auto",
    workers: int = 1,
    refresh: bool = False,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    errors: list[str] = []

    def load_one(symbol: str) -> tuple[str, pd.DataFrame | None, Exception | None]:
        try:
            return symbol, load_symbol_history(symbol, start_date, end_date, adjust, cache_dir, provider, refresh), None
        except Exception as exc:
            return symbol, None, exc

    if workers <= 1:
        results = [load_one(symbol) for symbol in symbols]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(load_one, symbol) for symbol in symbols]
            results = [future.result() for future in as_completed(futures)]

    for symbol, frame, error in results:
        if frame is not None:
            frames.append(frame)
        else:
            errors.append(f"{symbol}: {error}")

    if not frames:
        detail = "; ".join(errors) if errors else "no symbols configured"
        raise RuntimeError(f"failed to load any stock history: {detail}")

    if errors:
        print("Data warnings:")
        for error in errors:
            print(f"  - {error}")

    history = pd.concat(frames, ignore_index=True)
    history["symbol"] = history["symbol"].astype(str).str.zfill(6)
    history = history.sort_values(["date", "symbol"])
    names = symbol_names or {}
    history["name"] = history["symbol"].map(names).fillna("")
    return history
