from __future__ import annotations

import pandas as pd


def _limit_up_threshold(symbol: str, name: str = "") -> float:
    if "ST" in name.upper():
        return 4.8
    if symbol.startswith(("300", "301", "688")):
        return 19.5
    return 9.8


def _add_symbol_factors(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("date").copy()
    symbol = str(group["symbol"].iloc[0]).zfill(6)
    name = str(group["name"].iloc[0]) if "name" in group.columns else ""
    close = group["close"]
    prev_close = close.shift(1)
    daily_return = close.pct_change()
    price_range = (group["high"] - group["low"]).replace(0, pd.NA)
    limit_threshold = _limit_up_threshold(symbol, name)
    limit_price = prev_close * (1 + limit_threshold / 100)

    group["return_1d"] = daily_return
    group["forward_return_1d"] = close.shift(-1) / close - 1
    group["next_pct_change"] = group["pct_change"].shift(-1)
    group["limit_up_threshold"] = limit_threshold
    group["is_limit_up"] = group["pct_change"] >= limit_threshold
    group["next_limit_up"] = group["next_pct_change"] >= limit_threshold
    group["limit_up_price"] = limit_price
    group["limit_up_distance"] = close / limit_price - 1
    group["high_to_limit_distance"] = group["high"] / limit_price - 1
    group["near_limit_touch"] = group["high_to_limit_distance"] >= -0.005
    group["broken_limit_touch"] = group["near_limit_touch"] & ~group["is_limit_up"]
    group["limit_up_count_20d"] = group["is_limit_up"].shift(1).rolling(20).sum()
    group["momentum_20"] = close / close.shift(20) - 1
    group["momentum_60"] = close / close.shift(60) - 1
    group["ma5"] = close.rolling(5).mean()
    group["ma10"] = close.rolling(10).mean()
    group["ma20"] = close.rolling(20).mean()
    group["ma20_distance"] = close / group["ma20"] - 1
    group["ma_gap_20"] = close / close.rolling(20).mean() - 1
    group["volatility_20"] = daily_return.rolling(20).std()
    group["drawdown_60"] = close / close.rolling(60).max() - 1
    group["volume_ma5_prev"] = group["volume"].rolling(5).mean().shift(1)
    group["volume_ratio_5"] = group["volume"] / group["volume_ma5_prev"] - 1
    group["volume_ratio_20"] = group["volume"] / group["volume"].rolling(20).mean() - 1
    group["close_above_ma20"] = close > group["ma20"]
    group["ma_alignment"] = (close > group["ma5"]) & (group["ma5"] > group["ma10"]) & (close / group["ma20"] < 1.05)
    group["ma5_slope"] = group["ma5"] / group["ma5"].shift(3) - 1
    gain = daily_return.clip(lower=0)
    loss = -daily_return.clip(upper=0)
    avg_gain_6 = gain.rolling(6).mean()
    avg_loss_6 = loss.rolling(6).mean()
    rs_6 = avg_gain_6 / avg_loss_6.replace(0, pd.NA)
    group["rsi_6"] = 100 - (100 / (1 + rs_6))
    group["intraday_strength"] = (close - group["low"]) / price_range
    group["close_to_high"] = close / group["high"] - 1
    rolling_low_60 = close.rolling(60).min()
    rolling_high_60 = close.rolling(60).max()
    group["low_position_60"] = (close - rolling_low_60) / (rolling_high_60 - rolling_low_60).replace(0, pd.NA)
    rolling_low_252 = close.rolling(252).min()
    rolling_high_252 = close.rolling(252).max()
    group["low_position_252"] = (close - rolling_low_252) / (rolling_high_252 - rolling_low_252).replace(0, pd.NA)
    group["distance_high_252"] = close / rolling_high_252 - 1
    group["platform_high_20_prev"] = group["high"].rolling(20).max().shift(1)
    group["distance_platform_high_20"] = close / group["platform_high_20_prev"] - 1
    group["near_platform_breakout"] = group["distance_platform_high_20"].between(-0.03, 0.05, inclusive="both")
    if "turnover_rate" in group.columns:
        group["turnover_rate"] = pd.to_numeric(group["turnover_rate"], errors="coerce")
    else:
        group["turnover_rate"] = pd.NA
    group["float_market_cap_est_yi"] = (
        pd.to_numeric(group["amount"], errors="coerce") / (group["turnover_rate"] / 100) / 100_000_000
    )
    return group


def _add_market_sentiment(factored: pd.DataFrame) -> pd.DataFrame:
    market = (
        factored.groupby("date", sort=True)
        .agg(
            market_symbol_count=("symbol", "nunique"),
            market_up_count=("pct_change", lambda values: (values > 0).sum()),
            market_avg_pct_change=("pct_change", "mean"),
            market_median_pct_change=("pct_change", "median"),
            market_limit_up_count=("is_limit_up", "sum"),
            market_near_limit_count=("near_limit_touch", "sum"),
            market_broken_limit_count=("broken_limit_touch", "sum"),
        )
        .reset_index()
    )

    first_limit_up = (
        factored["is_limit_up"].fillna(False)
        & (factored["limit_up_count_20d"].fillna(0) == 0)
    )
    first_counts = factored.assign(_first_limit_up=first_limit_up).groupby("date")["_first_limit_up"].sum()
    market["market_first_limit_up_count"] = market["date"].map(first_counts).fillna(0)

    market["market_up_ratio"] = market["market_up_count"] / market["market_symbol_count"].replace(0, pd.NA)
    market["market_broken_limit_rate"] = (
        market["market_broken_limit_count"] / market["market_near_limit_count"].replace(0, pd.NA)
    ).fillna(0)
    market["market_limit_up_ratio"] = market["market_limit_up_count"] / market["market_symbol_count"].replace(0, pd.NA)
    market["market_first_limit_up_ratio"] = (
        market["market_first_limit_up_count"] / market["market_symbol_count"].replace(0, pd.NA)
    )
    market["market_sentiment_score"] = 0.0
    market["market_sentiment_score"] += (market["market_up_ratio"] >= 0.55).astype(float) * 10
    market["market_sentiment_score"] += (market["market_avg_pct_change"] >= 0.5).astype(float) * 10
    market["market_sentiment_score"] += (market["market_limit_up_count"] >= 8).astype(float) * 15
    market["market_sentiment_score"] += (market["market_first_limit_up_count"] >= 4).astype(float) * 10
    market["market_sentiment_score"] -= (market["market_broken_limit_rate"] >= 0.55).astype(float) * 15

    return factored.merge(market, on="date", how="left")


def add_factors(history: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for symbol, group in history.groupby("symbol", sort=False):
        frame = _add_symbol_factors(group)
        frame["symbol"] = symbol
        frames.append(frame)
    factored = pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"])
    return _add_market_sentiment(factored)
