from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error, roc_auc_score


def _split_time(df: pd.DataFrame, train_end_date: str | None):
    if not train_end_date:
        cutoff = df["trade_date"].quantile(0.8)
    else:
        cutoff = pd.Timestamp(train_end_date)
    train = df[df["trade_date"] <= cutoff].copy()
    test = df[df["trade_date"] > cutoff].copy()
    return train, test


def train_models(df: pd.DataFrame, train_end_date: str | None = None, random_state: int = 42):
    feature_exclude = {
        "ts_code",
        "trade_date",
        "target_valuation_return",
        "target_valuation_up",
        "target_earnings_growth",
    }
    feature_cols = [c for c in df.columns if c not in feature_exclude]

    model_df = df.copy()
    model_df[feature_cols] = model_df[feature_cols].replace([np.inf, -np.inf], np.nan)
    model_df[feature_cols] = model_df[feature_cols].fillna(model_df[feature_cols].median(numeric_only=True))

    train, test = _split_time(model_df, train_end_date)

    x_train = train[feature_cols]
    x_test = test[feature_cols]

    reg_mask_train = train["target_earnings_growth"].notna()
    reg_mask_test = test["target_earnings_growth"].notna()

    reg = HistGradientBoostingRegressor(random_state=random_state)
    clf = HistGradientBoostingClassifier(random_state=random_state)

    if reg_mask_train.sum() > 50:
        reg.fit(x_train.loc[reg_mask_train], train.loc[reg_mask_train, "target_earnings_growth"])
        reg_pred = reg.predict(x_test.loc[reg_mask_test]) if reg_mask_test.sum() > 0 else np.array([])
        reg_mae = float(mean_absolute_error(test.loc[reg_mask_test, "target_earnings_growth"], reg_pred)) if reg_mask_test.sum() > 0 else None
    else:
        reg = None
        reg_mae = None

    cls_mask_train = train["target_valuation_up"].notna()
    cls_mask_test = test["target_valuation_up"].notna()
    clf.fit(x_train.loc[cls_mask_train], train.loc[cls_mask_train, "target_valuation_up"])
    cls_pred = clf.predict(x_test.loc[cls_mask_test]) if cls_mask_test.sum() > 0 else np.array([])
    cls_prob = clf.predict_proba(x_test.loc[cls_mask_test])[:, 1] if cls_mask_test.sum() > 0 else np.array([])

    cls_acc = float(accuracy_score(test.loc[cls_mask_test, "target_valuation_up"], cls_pred)) if cls_mask_test.sum() > 0 else None
    cls_auc = float(roc_auc_score(test.loc[cls_mask_test, "target_valuation_up"], cls_prob)) if cls_mask_test.sum() > 0 else None

    return {
        "regressor": reg,
        "classifier": clf,
        "feature_cols": feature_cols,
        "metrics": {
            "reg_mae": reg_mae,
            "cls_acc": cls_acc,
            "cls_auc": cls_auc,
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
        },
    }


def save_artifacts(bundle: dict, output_dir: str | Path, model_file: str, metrics_file: str):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(bundle, output_dir / model_file)
    (output_dir / metrics_file).write_text(
        json.dumps(bundle.get("metrics", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
