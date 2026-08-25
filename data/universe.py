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


def _read_cached_universe(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": str})
    frame["symbol"] = frame["symbol"].map(normalize_symbol)
    return frame


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("--", "", regex=False),
        errors="coerce",
    )


def _board_name_column(frame: pd.DataFrame) -> str | None:
    for column in ["名称", "板块名称", "行业", "概念名称"]:
        if column in frame.columns:
            return column
    return None


def _board_score_column(frame: pd.DataFrame) -> str | None:
    preferred = ["今日主力净流入-净额", "主力净流入-净额", "净额", "资金净流入", "涨跌幅"]
    for column in preferred:
        if column in frame.columns:
            return column
    candidates = [column for column in frame.columns if "净" in column or "流入" in column or "涨跌幅" in column]
    return candidates[0] if candidates else None


def _load_fund_flow_boards(board_type: str, cache_dir: Path, refresh: bool, top_n: int) -> pd.DataFrame:
    cache_path = cache_dir / f"active_{board_type}_boards.csv"
    if cache_path.exists() and not refresh:
        return pd.read_csv(cache_path)

    sector_type = "行业资金流" if board_type == "industry" else "概念资金流"
    try:
        raw = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type=sector_type)
    except Exception as exc:
        print(f"Universe warning: failed to load {sector_type}: {exc}")
        try:
            name_func = ak.stock_board_industry_name_em if board_type == "industry" else ak.stock_board_concept_name_em
            raw = name_func()
        except Exception as fallback_exc:
            print(f"Universe warning: failed to load {board_type} board heat: {fallback_exc}")
            return pd.DataFrame(columns=["board_name", "board_type", "board_score"])

    name_column = _board_name_column(raw)
    score_column = _board_score_column(raw)
    if not name_column:
        return pd.DataFrame(columns=["board_name", "board_type", "board_score"])

    frame = pd.DataFrame(
        {
            "board_name": raw[name_column].astype(str),
            "board_type": board_type,
            "board_score": _to_numeric(raw[score_column]) if score_column else 0,
        }
    )
    frame = frame.dropna(subset=["board_name"]).drop_duplicates(subset=["board_name"])
    frame = frame.sort_values("board_score", ascending=False).head(top_n)
    frame.to_csv(cache_path, index=False, encoding="utf-8-sig")
    return frame


def _board_members(board_type: str, board_name: str, board_score: float) -> pd.DataFrame:
    raw = (
        ak.stock_board_industry_cons_em(symbol=board_name)
        if board_type == "industry"
        else ak.stock_board_concept_cons_em(symbol=board_name)
    )
    if "代码" not in raw.columns:
        return pd.DataFrame(columns=["symbol", "active_board_name", "active_board_type", "active_board_score"])
    return pd.DataFrame(
        {
            "symbol": raw["代码"].map(normalize_symbol),
            "active_board_name": board_name,
            "active_board_type": board_type,
            "active_board_score": board_score,
        }
    )


def _load_active_board_members(cache_dir: Path, refresh: bool, board_top_n: int) -> pd.DataFrame:
    cache_path = cache_dir / "active_board_members_v2.csv"
    if cache_path.exists() and not refresh:
        return _read_cached_universe(cache_path)

    boards = pd.concat(
        [
            _load_fund_flow_boards("industry", cache_dir, refresh, board_top_n),
            _load_fund_flow_boards("concept", cache_dir, refresh, board_top_n),
        ],
        ignore_index=True,
    )
    frames = []
    for row in boards.itertuples(index=False):
        try:
            frames.append(_board_members(row.board_type, row.board_name, row.board_score))
        except Exception as exc:
            print(f"Universe warning: failed to load board {row.board_name}: {exc}")

    if not frames:
        fallback_frames = []
        fallback_specs = [
            (cache_dir / "hot_industry_members.csv", "industry_name", "industry_heat", "industry"),
            (cache_dir / "hot_concept_members.csv", "concept_name", "concept_heat", "concept"),
        ]
        for path, name_column, score_column, board_type in fallback_specs:
            if not path.exists():
                continue
            fallback = _read_cached_universe(path)
            if name_column not in fallback.columns:
                continue
            fallback_frames.append(
                pd.DataFrame(
                    {
                        "symbol": fallback["symbol"],
                        "active_board_name": fallback[name_column],
                        "active_board_type": board_type,
                        "active_board_score": _to_numeric(fallback[score_column]) if score_column in fallback.columns else 0,
                    }
                )
            )
        if not fallback_frames:
            return pd.DataFrame(columns=["symbol", "active_board_name", "active_board_type", "active_board_score"])
        members = pd.concat(fallback_frames, ignore_index=True)
        members = members.sort_values("active_board_score", ascending=False).drop_duplicates(subset=["symbol"])
        members.to_csv(cache_path, index=False, encoding="utf-8-sig")
        return members

    members = pd.concat(frames, ignore_index=True)
    members = members.sort_values("active_board_score", ascending=False).drop_duplicates(subset=["symbol"])
    members.to_csv(cache_path, index=False, encoding="utf-8-sig")
    return members


def _load_spot_activity(cache_dir: Path, refresh: bool) -> pd.DataFrame:
    cache_path = cache_dir / "active_spot_snapshot.csv"
    if cache_path.exists() and not refresh:
        return _read_cached_universe(cache_path)

    try:
        raw = ak.stock_zh_a_spot_em()
    except Exception as exc:
        print(f"Universe warning: failed to load active spot snapshot: {exc}")
        return pd.DataFrame(columns=["symbol", "active_score"])

    rename = {
        "代码": "symbol",
        "名称": "spot_name",
        "涨跌幅": "spot_pct_change",
        "换手率": "spot_turnover_rate",
        "量比": "spot_volume_ratio",
        "成交额": "spot_amount",
    }
    selected = [column for column in rename if column in raw.columns]
    frame = raw.rename(columns=rename)[[rename[column] for column in selected]].copy()
    frame["symbol"] = frame["symbol"].map(normalize_symbol)
    for column in ["spot_pct_change", "spot_turnover_rate", "spot_volume_ratio", "spot_amount"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        else:
            frame[column] = pd.NA

    frame["active_score"] = 0.0
    frame["active_score"] += frame["spot_pct_change"].fillna(0).clip(lower=-5, upper=10)
    frame["active_score"] += frame["spot_turnover_rate"].fillna(0).clip(upper=15) * 1.5
    frame["active_score"] += frame["spot_volume_ratio"].fillna(0).clip(upper=5) * 5
    frame["active_score"] += frame["spot_amount"].rank(pct=True).fillna(0) * 10
    frame.to_csv(cache_path, index=False, encoding="utf-8-sig")
    return frame


def resolve_active_board_universe(
    manual_symbols: list[str],
    manual_names: dict[str, str],
    index_symbols: list[str],
    cache_dir: Path,
    max_symbols: int,
    board_top_n: int,
    refresh: bool = False,
) -> tuple[list[str], dict[str, str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"active_universe_v2_{'_'.join(index_symbols)}_{max_symbols}_{board_top_n}.csv"
    if cache_path.exists() and not refresh:
        universe = _read_cached_universe(cache_path)
        names = {row.symbol: row.name for row in universe.itertuples(index=False) if getattr(row, "name", "")}
        return universe["symbol"].tolist(), names

    frames = []
    errors = []
    for index_symbol in index_symbols:
        try:
            frames.append(load_index_constituents(index_symbol, cache_dir, refresh))
        except Exception as exc:
            errors.append(f"{index_symbol}: {exc}")

    base = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["symbol", "name"])
    manual_frame = pd.DataFrame(
        {
            "symbol": [normalize_symbol(symbol) for symbol in manual_symbols],
            "name": [manual_names.get(normalize_symbol(symbol), "") for symbol in manual_symbols],
        }
    )
    base = pd.concat([base[["symbol", "name"]], manual_frame], ignore_index=True)
    base["symbol"] = base["symbol"].map(normalize_symbol)
    base = base.drop_duplicates(subset=["symbol"]).sort_values("symbol")
    if base.empty:
        raise RuntimeError("resolved base universe is empty")

    board_members = _load_active_board_members(cache_dir, refresh, board_top_n)
    spot = _load_spot_activity(cache_dir, refresh)
    active = base.merge(board_members, on="symbol", how="left").merge(spot, on="symbol", how="left")
    active["active_board_score"] = pd.to_numeric(active.get("active_board_score", 0), errors="coerce").fillna(0)
    active["active_score"] = pd.to_numeric(active.get("active_score", 0), errors="coerce").fillna(0)
    active["universe_active_score"] = active["active_board_score"].rank(pct=True).fillna(0) * 50 + active["active_score"]

    board_filtered = active[active["active_board_name"].notna()].copy()
    ranked = board_filtered if not board_filtered.empty else active
    limit = max_symbols if max_symbols > 0 else 100
    universe = ranked.sort_values("universe_active_score", ascending=False).head(limit)
    universe = universe[["symbol", "name", "universe_active_score", "active_board_name", "active_board_type"]]
    universe.to_csv(cache_path, index=False, encoding="utf-8-sig")

    if errors:
        print("Universe warnings:")
        for error in errors:
            print(f"  - {error}")
    names = {row.symbol: row.name for row in universe.itertuples(index=False) if row.name}
    return universe["symbol"].tolist(), names


def resolve_universe(
    manual_symbols: list[str],
    manual_names: dict[str, str],
    index_symbols: list[str],
    cache_dir: Path,
    max_symbols: int = 0,
    mode: str = "index",
    board_top_n: int = 10,
    refresh: bool = False,
) -> tuple[list[str], dict[str, str]]:
    if mode == "active_boards":
        return resolve_active_board_universe(
            manual_symbols=manual_symbols,
            manual_names=manual_names,
            index_symbols=index_symbols,
            cache_dir=cache_dir,
            max_symbols=max_symbols,
            board_top_n=board_top_n,
            refresh=refresh,
        )

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
