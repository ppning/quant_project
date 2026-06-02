from __future__ import annotations

from pathlib import Path

import akshare as ak
import pandas as pd


def normalize_symbol(symbol: object) -> str:
    return str(symbol).strip().zfill(6)


def fetch_index_constituents(index_symbol: str) -> pd.DataFrame:
    raw = ak.index_stock_cons_csindex(symbol=index_symbol)
    required = ["成分券代码", "成分券名称"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError(f"{index_symbol} missing constituent columns: {missing}")

    frame = raw.rename(columns={"成分券代码": "symbol", "成分券名称": "name"}).copy()
    frame["symbol"] = frame["symbol"].map(normalize_symbol)
    frame["name"] = frame["name"].astype(str)
    frame["source_index"] = index_symbol
    return frame[["symbol", "name", "source_index"]].drop_duplicates(subset=["symbol"])


def load_index_constituents(index_symbol: str, cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"universe_{index_symbol}.csv"
    if cache_path.exists() and not refresh:
        frame = pd.read_csv(cache_path, dtype={"symbol": str, "source_index": str})
        frame["symbol"] = frame["symbol"].map(normalize_symbol)
        return frame

    frame = fetch_index_constituents(index_symbol)
    frame.to_csv(cache_path, index=False, encoding="utf-8-sig")
    return frame


def resolve_universe(
    manual_symbols: list[str],
    manual_names: dict[str, str],
    index_symbols: list[str],
    cache_dir: Path,
    max_symbols: int = 0,
    refresh: bool = False,
) -> tuple[list[str], dict[str, str]]:
    frames = []
    errors = []

    for index_symbol in index_symbols:
        try:
            frames.append(load_index_constituents(index_symbol, cache_dir, refresh))
        except Exception as exc:
            errors.append(f"{index_symbol}: {exc}")

    index_universe = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["symbol", "name"])
    manual_frame = pd.DataFrame(
        {
            "symbol": [normalize_symbol(symbol) for symbol in manual_symbols],
            "name": [manual_names.get(normalize_symbol(symbol), "") for symbol in manual_symbols],
        }
    )
    universe = pd.concat([index_universe[["symbol", "name"]], manual_frame], ignore_index=True)
    universe["symbol"] = universe["symbol"].map(normalize_symbol)
    universe = universe.drop_duplicates(subset=["symbol"]).sort_values("symbol")

    if max_symbols > 0:
        universe = universe.head(max_symbols)

    names = {row.symbol: row.name for row in universe.itertuples(index=False) if row.name}
    if errors:
        print("Universe warnings:")
        for error in errors:
            print(f"  - {error}")
    if universe.empty:
        raise RuntimeError("resolved universe is empty")
    return universe["symbol"].tolist(), names
