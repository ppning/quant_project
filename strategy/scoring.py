from __future__ import annotations

import numpy as np
import pandas as pd


def cross_sectional_zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if np.isnan(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def add_scores(factor_frame: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    missing = [factor for factor in weights if factor not in factor_frame.columns]
    if missing:
        raise ValueError(f"missing factors: {missing}")

    scored = factor_frame.copy()
    scored["score"] = 0.0

    for factor, weight in weights.items():
        zscore_name = f"{factor}_z"
        scored[zscore_name] = scored.groupby("date")[factor].transform(cross_sectional_zscore)
        scored["score"] += scored[zscore_name].fillna(0.0) * weight

    return scored


def latest_selection(scored: pd.DataFrame, top_n: int, min_history_days: int) -> pd.DataFrame:
    eligible = scored.dropna(subset=["score"]).copy()
    eligible["history_days"] = eligible.groupby("symbol").cumcount() + 1
    eligible = eligible[eligible["history_days"] >= min_history_days]

    if eligible.empty:
        return eligible

    latest_date = eligible["date"].max()
    columns = ["date", "symbol"]
    if "name" in eligible.columns:
        columns.append("name")
    columns.extend(["close", "score"])
    factor_columns = [column for column in scored.columns if column.endswith("_z")]
    return (
        eligible[eligible["date"] == latest_date]
        .sort_values("score", ascending=False)
        .head(top_n)[columns + factor_columns]
    )


def make_rebalance_selection(scored: pd.DataFrame, rebalance: str, top_n: int, min_history_days: int) -> pd.DataFrame:
    eligible = scored.dropna(subset=["score"]).copy()
    eligible["history_days"] = eligible.groupby("symbol").cumcount() + 1
    eligible = eligible[eligible["history_days"] >= min_history_days]
    if eligible.empty:
        return eligible

    trading_days = pd.Series(sorted(eligible["date"].unique()))
    rebalance_days = (
        pd.DataFrame({"date": trading_days})
        .set_index("date")
        .resample(rebalance)
        .last()
        .dropna()
        .index
    )

    selected = eligible[eligible["date"].isin(rebalance_days)].copy()
    selected["rank"] = selected.groupby("date")["score"].rank(ascending=False, method="first")
    return selected[selected["rank"] <= top_n].sort_values(["date", "rank"])
