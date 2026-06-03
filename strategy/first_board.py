from __future__ import annotations

import pandas as pd


DISPLAY_COLUMNS = [
    "date",
    "symbol",
    "name",
    "close",
    "pct_change",
    "realtime_score",
    "first_board_score",
    "first_board_candidate",
    "first_board_watchlist",
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
    "effective_float_market_cap_yi",
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
    "healthy_near_limit_touch",
    "broken_limit_touch",
    "failed_near_limit_touch",
    "huge_volume_release",
    "high_position_risk",
    "limit_up_distance",
    "low_position_60",
    "close_to_high",
    "intraday_strength",
    "close_above_ma20",
    "ma5_slope",
]


def _score_between(series: pd.Series, lower: float, upper: float, points: float) -> pd.Series:
    return series.between(lower, upper, inclusive="both").astype(float) * points


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame.get(column, pd.Series(pd.NA, index=frame.index)), errors="coerce")


def _bool_column(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.get(column, pd.Series(False, index=frame.index)).fillna(False).astype(bool)


def _turnover_ready_by_cap(turnover: pd.Series, market_cap: pd.Series) -> pd.Series:
    turnover = pd.to_numeric(turnover, errors="coerce")
    market_cap = pd.to_numeric(market_cap, errors="coerce")
    cap_missing = market_cap.isna()
    cap_lt_30 = market_cap.lt(30)
    cap_30_100 = market_cap.between(30, 100, inclusive="both")
    cap_100_300 = market_cap.gt(100) & market_cap.le(300)
    cap_gt_300 = market_cap.gt(300)

    return (
        (cap_missing & turnover.between(3, 8, inclusive="both"))
        | (cap_lt_30 & turnover.between(5, 12, inclusive="both"))
        | (cap_30_100 & turnover.between(3, 10, inclusive="both"))
        | (cap_100_300 & turnover.between(2, 7, inclusive="both"))
        | (cap_gt_300 & turnover.between(1, 5, inclusive="both"))
    )


def add_first_board_score(factored: pd.DataFrame) -> pd.DataFrame:
    scored = factored.copy()
    scored["first_board_score"] = 0.0
    scored["volume_ratio_5_display"] = scored["volume_ratio_5"] + 1
    scored["volume_ratio_20_display"] = scored["volume_ratio_20"] + 1

    not_already_limit_up = scored["pct_change"] < scored["limit_up_threshold"]
    red_or_flat = scored["pct_change"].between(0, scored["limit_up_threshold"] - 1, inclusive="both")
    price_momentum = scored["pct_change"].between(2, scored["limit_up_threshold"] - 1, inclusive="both")
    volume_control = scored["volume_ratio_5_display"].between(1.3, 3.0, inclusive="both")
    volume_ideal = scored["volume_ratio_5_display"].between(1.5, 3.0, inclusive="both")
    volume_active = scored["volume_ratio_20_display"].between(1.2, 3.5, inclusive="both")
    turnover_available = scored["turnover_rate"].notna()
    market_cap_est = _numeric_column(scored, "float_market_cap_est_yi")
    turnover_ready = _turnover_ready_by_cap(scored["turnover_rate"], market_cap_est)
    turnover_neutral = ~turnover_available
    trend_ready = scored["ma_alignment"].fillna(False)
    rsi_ready = scored["rsi_6"].between(55, 70, inclusive="both")
    rsi_not_overheat = scored["rsi_6"].fillna(0) < 85
    no_recent_limit = scored["limit_up_count_20d"].fillna(0) == 0
    low_start = scored["low_position_252"].between(0.05, 0.65, inclusive="both")
    platform_ready = scored["near_platform_breakout"].fillna(False)
    strong_close = scored["intraday_strength"] >= 0.7
    ma5_up = scored["ma5_slope"] > 0
    close_to_high = _numeric_column(scored, "close_to_high")
    market_sentiment = scored.get("market_sentiment_score", pd.Series(0, index=scored.index)).fillna(0)
    market_up_ratio = scored.get("market_up_ratio", pd.Series(pd.NA, index=scored.index))
    market_broken_rate = scored.get("market_broken_limit_rate", pd.Series(0, index=scored.index)).fillna(0)
    market_not_fragile = market_up_ratio.fillna(0.5).ge(0.35) & market_broken_rate.le(0.7)
    watchlist_market_ok = market_up_ratio.fillna(0.5).ge(0.3)
    near_limit = _bool_column(scored, "near_limit_touch")
    healthy_near_limit = _bool_column(scored, "healthy_near_limit_touch")
    broken_limit = _bool_column(scored, "broken_limit_touch")
    failed_near_limit = _bool_column(scored, "failed_near_limit_touch")
    huge_volume_release = _bool_column(scored, "huge_volume_release")
    high_position_risk = _bool_column(scored, "high_position_risk")
    close_hold = close_to_high >= -0.02

    scored["first_board_score"] += red_or_flat.astype(float) * 10
    scored["first_board_score"] += price_momentum.astype(float) * 10
    scored["first_board_score"] += volume_ideal.astype(float) * 20
    scored["first_board_score"] += volume_active.astype(float) * 10
    scored["first_board_score"] += (turnover_ready | turnover_neutral).astype(float) * 15
    scored["first_board_score"] += trend_ready.astype(float) * 20
    scored["first_board_score"] += rsi_ready.astype(float) * 15
    scored["first_board_score"] += rsi_not_overheat.astype(float) * 5
    scored["first_board_score"] += no_recent_limit.astype(float) * 15
    scored["first_board_score"] += low_start.astype(float) * 10
    scored["first_board_score"] += platform_ready.astype(float) * 15
    scored["first_board_score"] += strong_close.astype(float) * 10
    scored["first_board_score"] += ma5_up.astype(float) * 5
    scored["first_board_score"] += close_hold.astype(float) * 5
    scored["first_board_score"] += market_sentiment.clip(lower=-15, upper=35)
    scored["first_board_score"] += near_limit.astype(float) * 5
    scored["first_board_score"] += healthy_near_limit.astype(float) * 10
    scored["first_board_score"] -= broken_limit.astype(float) * 10
    scored["first_board_score"] -= failed_near_limit.astype(float) * 15
    scored["first_board_score"] -= huge_volume_release.astype(float) * 15
    scored["first_board_score"] -= high_position_risk.astype(float) * 10

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
        & ~failed_near_limit
        & ~huge_volume_release
        & ~high_position_risk
    )
    scored["first_board_watchlist"] = (
        not_already_limit_up
        & red_or_flat
        & (volume_control | volume_active | strong_close | platform_ready | healthy_near_limit)
        & watchlist_market_ok
        & ~failed_near_limit
        & ~huge_volume_release
    )
    return scored


def add_realtime_score(scored: pd.DataFrame) -> pd.DataFrame:
    output = scored.copy()
    output["realtime_score"] = output["first_board_score"].fillna(0)

    market_cap = output.get("float_market_cap_yi", pd.Series(pd.NA, index=output.index))
    market_cap = market_cap.fillna(output.get("float_market_cap_est_yi", pd.Series(pd.NA, index=output.index)))
    output["effective_float_market_cap_yi"] = market_cap
    market_cap_available = market_cap.notna()
    market_cap_core = market_cap.between(30, 100, inclusive="both")
    market_cap_secondary = market_cap.gt(100) & market_cap.le(300)
    market_cap_ready = market_cap_core | market_cap_secondary
    turnover_source = output.get("spot_turnover_rate", output.get("turnover_rate", pd.Series(pd.NA, index=output.index)))
    turnover_ready = _turnover_ready_by_cap(turnover_source, market_cap)
    industry_hot = output.get("industry_heat", pd.Series(pd.NA, index=output.index)).fillna(0) >= 1.5
    concept_hot = output.get("concept_heat", pd.Series(pd.NA, index=output.index)).fillna(0) >= 1.5
    tail_amount = _numeric_column(output, "tail_amount_ratio")
    tail_return = _numeric_column(output, "tail_return")
    tail_close_to_high = _numeric_column(output, "tail_close_to_high")
    tail_amount_ready = tail_amount >= 0.25
    tail_return_ready = tail_return > 0
    tail_close_hold = tail_close_to_high >= -0.01
    tail_push = tail_amount_ready & tail_return_ready & tail_close_hold
    tail_fade = (tail_amount >= 0.2) & ((tail_return < -0.005) | (tail_close_to_high < -0.03))

    output["realtime_score"] += market_cap_core.astype(float) * 25
    output["realtime_score"] += market_cap_secondary.astype(float) * 10
    output["realtime_score"] -= (market_cap_available & ~market_cap_ready).astype(float) * 20
    output["realtime_score"] += turnover_ready.astype(float) * 10
    output["realtime_score"] += industry_hot.astype(float) * 10
    output["realtime_score"] += concept_hot.astype(float) * 10
    output["realtime_score"] += tail_amount_ready.astype(float) * 10
    output["realtime_score"] += tail_return_ready.astype(float) * 10
    output["realtime_score"] += tail_close_hold.astype(float) * 5
    output["realtime_score"] += tail_push.astype(float) * 10
    output["realtime_score"] -= tail_fade.astype(float) * 15

    output["realtime_candidate"] = output["first_board_candidate"] & ~tail_fade.fillna(False)
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
    if hard_candidates.empty:
        if "first_board_watchlist" in latest.columns:
            watchlist = latest[latest["first_board_watchlist"]]
            ranked = watchlist if not watchlist.empty else latest
        else:
            ranked = latest
    else:
        ranked = hard_candidates
    columns = [column for column in DISPLAY_COLUMNS if column in ranked.columns]
    sort_column = "realtime_score" if "realtime_score" in ranked.columns else "first_board_score"
    return ranked.sort_values(sort_column, ascending=False).head(top_n)[columns]


def historical_first_board_picks(scored: pd.DataFrame, top_n: int, min_history_days: int) -> pd.DataFrame:
    eligible = scored.dropna(subset=["next_pct_change"]).copy()
    eligible["history_days"] = eligible.groupby("symbol").cumcount() + 1
    eligible = eligible[eligible["history_days"] >= min_history_days]
    eligible = eligible[eligible["first_board_candidate"]]
    if eligible.empty:
        return eligible

    sort_column = "first_board_score"
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
