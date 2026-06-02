from __future__ import annotations

import pandas as pd


DISPLAY_COLUMNS = [
    "date",
    "symbol",
    "name",
    "close",
    "pct_change",
    "xgb_limit_up_prob",
    "realtime_score",
    "first_board_score",
    "next_pct_change",
    "next_limit_up",
    "turnover_rate",
    "spot_turnover_rate",
    "spot_volume_ratio",
    "float_market_cap_yi",
    "float_market_cap_est_yi",
    "industry_name",
    "industry_heat",
    "concept_name",
    "concept_heat",
    "market_sentiment_score",
    "market_up_ratio",
    "market_limit_up_count",
    "market_first_limit_up_count",
    "market_broken_limit_rate",
    "tail_amount_ratio",
    "tail_return",
    "tail_close_to_high",
    "volume_ratio_5_display",
    "volume_ratio_20_display",
    "limit_up_count_20d",
    "ma_alignment",
    "ma20_distance",
    "rsi_6",
    "low_position_252",
    "distance_high_252",
    "distance_platform_high_20",
    "near_platform_breakout",
    "near_limit_touch",
    "broken_limit_touch",
    "limit_up_distance",
    "low_position_60",
    "intraday_strength",
    "close_above_ma20",
    "ma5_slope",
]


def _score_between(series: pd.Series, lower: float, upper: float, points: float) -> pd.Series:
    return series.between(lower, upper, inclusive="both").astype(float) * points


def add_first_board_score(factored: pd.DataFrame) -> pd.DataFrame:
    scored = factored.copy()
    scored["first_board_score"] = 0.0
    scored["volume_ratio_5_display"] = scored["volume_ratio_5"] + 1
    scored["volume_ratio_20_display"] = scored["volume_ratio_20"] + 1

    not_already_limit_up = scored["pct_change"] < scored["limit_up_threshold"]
    red_or_flat = scored["pct_change"].between(0, scored["limit_up_threshold"] - 1, inclusive="both")
    volume_control = scored["volume_ratio_5_display"].between(1.2, 2.5, inclusive="both")
    volume_active = scored["volume_ratio_20_display"].between(1.1, 2.8, inclusive="both")
    turnover_available = scored["turnover_rate"].notna()
    turnover_ready = scored["turnover_rate"].between(3, 8, inclusive="both")
    turnover_neutral = ~turnover_available
    trend_ready = scored["ma_alignment"].fillna(False)
    rsi_ready = scored["rsi_6"].between(55, 70, inclusive="both")
    rsi_not_overheat = scored["rsi_6"].fillna(0) < 85
    no_recent_limit = scored["limit_up_count_20d"].fillna(0) == 0
    low_start = scored["low_position_252"].between(0.05, 0.65, inclusive="both")
    platform_ready = scored["near_platform_breakout"].fillna(False)
    strong_close = scored["intraday_strength"] >= 0.7
    ma5_up = scored["ma5_slope"] > 0
    market_sentiment = scored.get("market_sentiment_score", pd.Series(0, index=scored.index)).fillna(0)
    market_up_ratio = scored.get("market_up_ratio", pd.Series(pd.NA, index=scored.index))
    market_broken_rate = scored.get("market_broken_limit_rate", pd.Series(0, index=scored.index)).fillna(0)
    market_not_fragile = market_up_ratio.fillna(0.5).ge(0.35) & market_broken_rate.le(0.7)
    near_limit = scored.get("near_limit_touch", pd.Series(False, index=scored.index)).fillna(False)
    broken_limit = scored.get("broken_limit_touch", pd.Series(False, index=scored.index)).fillna(False)

    scored["first_board_score"] += red_or_flat.astype(float) * 10
    scored["first_board_score"] += volume_control.astype(float) * 20
    scored["first_board_score"] += volume_active.astype(float) * 10
    scored["first_board_score"] += (turnover_ready | turnover_neutral).astype(float) * 10
    scored["first_board_score"] += trend_ready.astype(float) * 20
    scored["first_board_score"] += rsi_ready.astype(float) * 15
    scored["first_board_score"] += rsi_not_overheat.astype(float) * 5
    scored["first_board_score"] += no_recent_limit.astype(float) * 15
    scored["first_board_score"] += low_start.astype(float) * 10
    scored["first_board_score"] += platform_ready.astype(float) * 15
    scored["first_board_score"] += strong_close.astype(float) * 10
    scored["first_board_score"] += ma5_up.astype(float) * 5
    scored["first_board_score"] += market_sentiment.clip(lower=-15, upper=35)
    scored["first_board_score"] += near_limit.astype(float) * 5
    scored["first_board_score"] -= broken_limit.astype(float) * 10

    scored["first_board_candidate"] = (
        not_already_limit_up
        & red_or_flat
        & volume_control
        & trend_ready
        & rsi_ready
        & no_recent_limit
        & (turnover_ready | turnover_neutral)
        & (low_start | platform_ready)
        & market_not_fragile
    )
    return scored


def add_realtime_score(scored: pd.DataFrame) -> pd.DataFrame:
    output = scored.copy()
    model_score = output.get("xgb_limit_up_prob", 0) * 100
    output["realtime_score"] = output["first_board_score"].fillna(0) + model_score

    market_cap = output.get("float_market_cap_yi", pd.Series(pd.NA, index=output.index))
    market_cap = market_cap.fillna(output.get("float_market_cap_est_yi", pd.Series(pd.NA, index=output.index)))
    output["effective_float_market_cap_yi"] = market_cap
    market_cap_available = market_cap.notna()
    market_cap_ready = market_cap.between(
        30,
        100,
        inclusive="both",
    )
    turnover_source = output.get("spot_turnover_rate", output.get("turnover_rate", pd.Series(pd.NA, index=output.index)))
    turnover_ready = turnover_source.between(3, 8, inclusive="both")
    industry_hot = output.get("industry_heat", pd.Series(pd.NA, index=output.index)).fillna(0) >= 1.5
    concept_hot = output.get("concept_heat", pd.Series(pd.NA, index=output.index)).fillna(0) >= 1.5
    tail_amount_ready = output.get("tail_amount_ratio", pd.Series(pd.NA, index=output.index)).fillna(0) >= 0.25
    tail_return_ready = output.get("tail_return", pd.Series(pd.NA, index=output.index)).fillna(0) > 0

    output["realtime_score"] += market_cap_ready.astype(float) * 25
    output["realtime_score"] -= (market_cap_available & ~market_cap_ready).astype(float) * 20
    output["realtime_score"] += turnover_ready.astype(float) * 10
    output["realtime_score"] += industry_hot.astype(float) * 10
    output["realtime_score"] += concept_hot.astype(float) * 10
    output["realtime_score"] += tail_amount_ready.astype(float) * 15
    output["realtime_score"] += tail_return_ready.astype(float) * 10

    output["realtime_candidate"] = output["first_board_candidate"] & (~market_cap_available | market_cap_ready)
    return output


def latest_first_board_candidates(scored: pd.DataFrame, top_n: int, min_history_days: int) -> pd.DataFrame:
    eligible = scored.copy()
    eligible["history_days"] = eligible.groupby("symbol").cumcount() + 1
    eligible = eligible[eligible["history_days"] >= min_history_days]
    if eligible.empty:
        return eligible

    latest_date = eligible["date"].max()
    latest = eligible[eligible["date"] == latest_date].copy()
    candidate_column = "realtime_candidate" if "realtime_candidate" in latest.columns else "first_board_candidate"
    hard_candidates = latest[latest[candidate_column]]
    ranked = hard_candidates if not hard_candidates.empty else latest
    columns = [column for column in DISPLAY_COLUMNS if column in ranked.columns]
    sort_column = "realtime_score" if "realtime_score" in ranked.columns else "xgb_limit_up_prob" if "xgb_limit_up_prob" in ranked.columns else "first_board_score"
    return ranked.sort_values(sort_column, ascending=False).head(top_n)[columns]


def historical_first_board_picks(scored: pd.DataFrame, top_n: int, min_history_days: int) -> pd.DataFrame:
    eligible = scored.dropna(subset=["next_pct_change"]).copy()
    eligible["history_days"] = eligible.groupby("symbol").cumcount() + 1
    eligible = eligible[eligible["history_days"] >= min_history_days]
    eligible = eligible[eligible["first_board_candidate"]]
    if eligible.empty:
        return eligible

    sort_column = "xgb_limit_up_prob" if "xgb_limit_up_prob" in eligible.columns else "first_board_score"
    eligible["rank"] = eligible.groupby("date")[sort_column].rank(ascending=False, method="first")
    picks = eligible[eligible["rank"] <= top_n].sort_values(["date", "rank"])
    columns = [column for column in DISPLAY_COLUMNS + ["rank"] if column in picks.columns]
    return picks[columns]


def summarize_first_board_performance(picks: pd.DataFrame) -> dict[str, float]:
    if picks.empty:
        return {
            "历史信号数": 0.0,
            "次日涨停数": 0.0,
            "命中率": 0.0,
            "平均次日收益": 0.0,
            "平均首板分": 0.0,
        }

    hit_count = float(picks["next_limit_up"].fillna(False).sum())
    return {
        "历史信号数": float(len(picks)),
        "次日涨停数": hit_count,
        "命中率": hit_count / len(picks),
        "平均次日收益": float(picks["next_pct_change"].mean() / 100),
        "平均首板分": float(picks["first_board_score"].mean()),
    }
