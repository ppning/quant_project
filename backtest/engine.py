from __future__ import annotations

import math

import pandas as pd


def run_equal_weight_backtest(selections: pd.DataFrame) -> pd.DataFrame:
    if selections.empty:
        return pd.DataFrame(columns=["date", "period_return", "equity"])

    returns = (
        selections.dropna(subset=["forward_return_1d"])
        .groupby("date")["forward_return_1d"]
        .mean()
        .rename("period_return")
        .reset_index()
        .sort_values("date")
    )
    returns["equity"] = (1 + returns["period_return"]).cumprod()
    return returns


def summarize_performance(equity_curve: pd.DataFrame) -> dict[str, float]:
    if equity_curve.empty:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "annual_volatility": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
        }

    daily = equity_curve["period_return"].fillna(0.0)
    total_return = equity_curve["equity"].iloc[-1] - 1
    periods = max(len(equity_curve), 1)
    annual_return = (1 + total_return) ** (252 / periods) - 1
    annual_volatility = daily.std(ddof=0) * math.sqrt(252)
    sharpe = annual_return / annual_volatility if annual_volatility else 0.0
    drawdown = equity_curve["equity"] / equity_curve["equity"].cummax() - 1

    return {
        "total_return": float(total_return),
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_volatility),
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
    }
