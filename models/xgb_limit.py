from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, roc_auc_score
from xgboost import XGBClassifier


FEATURE_COLUMNS = [
    "pct_change",
    "return_1d",
    "momentum_20",
    "momentum_60",
    "ma_gap_20",
    "ma20_distance",
    "volatility_20",
    "drawdown_60",
    "volume_ratio_5",
    "volume_ratio_20",
    "turnover_rate",
    "float_market_cap_est_yi",
    "limit_up_count_20d",
    "low_position_60",
    "low_position_252",
    "distance_high_252",
    "distance_platform_high_20",
    "intraday_strength",
    "close_to_high",
    "limit_up_distance",
    "high_to_limit_distance",
    "ma5_slope",
    "rsi_6",
    "first_board_score",
    "close_above_ma20",
    "ma_alignment",
    "near_platform_breakout",
    "near_limit_touch",
    "broken_limit_touch",
    "market_up_ratio",
    "market_avg_pct_change",
    "market_median_pct_change",
    "market_limit_up_count",
    "market_near_limit_count",
    "market_broken_limit_count",
    "market_broken_limit_rate",
    "market_first_limit_up_count",
    "market_limit_up_ratio",
    "market_first_limit_up_ratio",
    "market_sentiment_score",
    "amount",
]


@dataclass(frozen=True)
class XGBLimitUpResult:
    scored: pd.DataFrame
    validation_predictions: pd.DataFrame
    metrics: dict[str, float]
    feature_importance: pd.DataFrame


def _build_training_frame(scored: pd.DataFrame, min_history_days: int) -> pd.DataFrame:
    frame = scored.copy()
    frame["history_days"] = frame.groupby("symbol").cumcount() + 1
    frame = frame[frame["history_days"] >= min_history_days]
    frame = frame.dropna(subset=["next_limit_up"])

    first_board_universe = (
        (frame["pct_change"] < frame["limit_up_threshold"])
        & (frame["limit_up_count_20d"].fillna(0) == 0)
        & frame["low_position_60"].notna()
    )
    return frame[first_board_universe].copy()


def _feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    features = frame[FEATURE_COLUMNS].copy()
    for column in features.columns:
        if features[column].dtype == bool:
            features[column] = features[column].astype(int)
        features[column] = pd.to_numeric(features[column], errors="coerce")
    return features


def _empty_result(scored: pd.DataFrame, reason: str) -> XGBLimitUpResult:
    output = scored.copy()
    output["xgb_limit_up_prob"] = 0.0
    return XGBLimitUpResult(
        scored=output,
        validation_predictions=pd.DataFrame(),
        metrics={
            "XGBoost状态": reason,
            "训练样本数": 0.0,
            "验证样本数": 0.0,
            "验证涨停数": 0.0,
            "验证TopN样本数": 0.0,
            "验证TopN涨停数": 0.0,
            "验证TopN命中率": 0.0,
            "验证TopN平均次日收益": 0.0,
            "验证TopN Lift": 0.0,
            "验证AUC": 0.0,
            "验证Precision": 0.0,
            "验证Recall": 0.0,
        },
        feature_importance=pd.DataFrame(columns=["feature", "importance"]),
    )


def _fit_model(x_train: pd.DataFrame, y_train: pd.Series) -> XGBClassifier:
    negative_count = max(int((y_train == 0).sum()), 1)
    positive_count = max(int((y_train == 1).sum()), 1)
    scale_pos_weight = negative_count / positive_count

    model = XGBClassifier(
        n_estimators=80,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.85,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        n_jobs=2,
    )
    model.fit(x_train, y_train)
    return model


def _walk_forward_predictions(trainable: pd.DataFrame, top_n: int) -> pd.DataFrame:
    unique_dates = sorted(trainable["date"].dropna().unique())
    if len(unique_dates) < 20:
        return pd.DataFrame()

    start_index = max(int(len(unique_dates) * 0.55), 1)
    validation_dates = unique_dates[start_index:]
    if not validation_dates:
        return pd.DataFrame()

    fold_count = min(3, max(1, len(validation_dates) // 60))
    fold_edges = np.array_split(validation_dates, fold_count)
    predictions = []

    for fold_dates in fold_edges:
        fold_dates = list(fold_dates)
        if not fold_dates:
            continue
        fold_start = fold_dates[0]
        train = trainable[trainable["date"] < fold_start].copy()
        valid = trainable[trainable["date"].isin(fold_dates)].copy()
        if train.empty or valid.empty or train["next_limit_up"].sum() == 0:
            continue

        x_train = _feature_matrix(train)
        y_train = train["next_limit_up"].astype(int)
        model = _fit_model(x_train, y_train)

        valid["xgb_limit_up_prob"] = model.predict_proba(_feature_matrix(valid))[:, 1]
        valid["xgb_pred_label"] = valid["xgb_limit_up_prob"] >= 0.5
        valid["rank"] = valid.groupby("date")["xgb_limit_up_prob"].rank(ascending=False, method="first")
        predictions.append(valid)

    if not predictions:
        return pd.DataFrame()
    return pd.concat(predictions, ignore_index=True).sort_values(["date", "rank"])


def train_predict_xgb_limit_up(scored: pd.DataFrame, top_n: int, min_history_days: int) -> XGBLimitUpResult:
    trainable = _build_training_frame(scored, min_history_days)
    if len(trainable) < 80:
        return _empty_result(scored, "样本不足")

    positive_count = int(trainable["next_limit_up"].sum())
    if positive_count < 2:
        return _empty_result(scored, "涨停正样本不足")

    valid = _walk_forward_predictions(trainable, top_n)
    if valid.empty:
        return _empty_result(scored, "滚动验证样本不足")

    x_train = _feature_matrix(trainable)
    y_train = trainable["next_limit_up"].astype(int)
    model = _fit_model(x_train, y_train)

    output = scored.copy()
    output["xgb_limit_up_prob"] = model.predict_proba(_feature_matrix(output))[:, 1]

    validation_picks = valid[valid["rank"] <= top_n].sort_values(["date", "rank"])

    y_valid = valid["next_limit_up"].astype(int)
    y_pred = valid["xgb_pred_label"].astype(int)
    auc = roc_auc_score(y_valid, valid["xgb_limit_up_prob"]) if y_valid.nunique() > 1 else 0.0
    hit_count = float(validation_picks["next_limit_up"].fillna(False).sum())
    base_rate = float(y_valid.mean()) if len(y_valid) else 0.0
    topn_hit_rate = hit_count / len(validation_picks) if len(validation_picks) else 0.0
    metrics = {
        "XGBoost状态": "已训练",
        "训练样本数": float(len(trainable)),
        "验证样本数": float(len(valid)),
        "验证涨停数": float(y_valid.sum()),
        "验证TopN样本数": float(len(validation_picks)),
        "验证TopN涨停数": hit_count,
        "验证TopN命中率": topn_hit_rate,
        "验证TopN平均次日收益": float(validation_picks["next_pct_change"].mean() / 100) if len(validation_picks) else 0.0,
        "验证TopN Lift": topn_hit_rate / base_rate if base_rate else 0.0,
        "验证AUC": float(auc),
        "验证Precision": float(precision_score(y_valid, y_pred, zero_division=0)),
        "验证Recall": float(recall_score(y_valid, y_pred, zero_division=0)),
    }

    feature_importance = (
        pd.DataFrame({"feature": FEATURE_COLUMNS, "importance": model.feature_importances_})
        .sort_values("importance", ascending=False)
        .head(12)
    )
    return XGBLimitUpResult(
        scored=output,
        validation_predictions=validation_picks,
        metrics=metrics,
        feature_importance=feature_importance,
    )
