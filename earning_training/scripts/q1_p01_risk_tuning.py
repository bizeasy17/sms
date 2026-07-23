from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BASE_DIR / "outputs" / "local_valuation_checks" / "q1_p01_risk_tuning_20260719"

MODEL_VERSION = "uat_20260718_q1_ocf_fix_fy2"
CONFIG_PATH = BASE_DIR / "configs" / "default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2.yaml"
DATASET_PATH = BASE_DIR / "outputs" / "datasets" / "15y_20260402_uat_r1" / "datasets_by_report_type_full" / "dataset_Q1_full.parquet"


def split_train_test(df: pd.DataFrame, cfg: dict[str, Any], reg_target_col: str, cls_target_col: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    train_cfg = cfg.get("train") or {}
    model_df = df.copy()

    if train_cfg.get("train_end_date"):
        cutoff = pd.Timestamp(train_cfg.get("train_end_date"))
    else:
        cutoff = model_df["trade_date"].quantile(0.8)

    train = model_df[model_df["trade_date"] <= cutoff]
    test = model_df[model_df["trade_date"] > cutoff]

    fy_split_enabled = bool(train_cfg.get("fy_split_by_fiscal_year", True))
    fy_targets = {"target_fy_up", "target_fy_value", "target_fy_value_yoy"}
    if fy_split_enabled and "fiscal_year" in model_df.columns and (reg_target_col in fy_targets or cls_target_col in fy_targets):
        fy_series = pd.to_numeric(model_df["fiscal_year"], errors="coerce")
        years = sorted(int(y) for y in fy_series.dropna().unique())
        fy_test_years = max(1, int(train_cfg.get("fy_test_years", 1)))
        if len(years) > fy_test_years:
            test_years = set(years[-fy_test_years:])
            train = model_df[~fy_series.isin(test_years)]
            test = model_df[fy_series.isin(test_years)]

    if "is_fy_row" in train.columns and bool((cfg.get("label") or {}).get("exclude_fy_rows_for_training", True)):
        train = train[~train["is_fy_row"].fillna(False)]
        test = test[~test["is_fy_row"].fillna(False)]

    return train.copy(), test.copy(), pd.Timestamp(cutoff)


def impute_like_training(train: pd.DataFrame, test: pd.DataFrame, feature_cols: list[str], cutoff: pd.Timestamp, lookback_years: int) -> pd.DataFrame:
    train_recent = train[train["trade_date"] >= (cutoff - pd.DateOffset(years=lookback_years))]
    train_global_median = train[feature_cols].median(numeric_only=True)
    train_industry_median = train.groupby("industry_name")[feature_cols].median(numeric_only=True)
    train_tscode_median = train_recent.groupby("ts_code")[feature_cols].median(numeric_only=True)

    x = test[["ts_code", "industry_name"] + feature_cols].copy()
    x[feature_cols] = x[feature_cols].replace([np.inf, -np.inf], np.nan)
    for col in feature_cols:
        x[col] = pd.to_numeric(x[col], errors="coerce")

    x["__row_id"] = x.index
    ts_med = train_tscode_median.add_suffix("__ts").reset_index()
    ind_med = train_industry_median.add_suffix("__ind").reset_index()
    x = x.merge(ts_med, on="ts_code", how="left")
    x = x.merge(ind_med, on="industry_name", how="left")

    for col in feature_cols:
        x[col] = x[col].fillna(x.get(f"{col}__ts"))
        x[col] = x[col].fillna(x.get(f"{col}__ind"))
        x[col] = x[col].fillna(train_global_median.get(col))

    x = x.set_index("__row_id", drop=True)
    return x[feature_cols]


def compute_policy_metrics(eval_df: pd.DataFrame, top_pct: float, min_score: float, max_per_industry: int | None) -> dict[str, Any]:
    rows = []
    for _, g in eval_df.groupby("trade_date"):
        g2 = g[g["score"] >= min_score].copy()
        if g2.empty:
            continue

        g2 = g2.sort_values("score", ascending=False)
        if max_per_industry is not None and max_per_industry > 0:
            g2 = g2.groupby("industry_name", group_keys=False).head(max_per_industry)
            g2 = g2.sort_values("score", ascending=False)

        k = max(1, int(np.ceil(len(g2) * top_pct)))
        rows.append(g2.head(k))

    if not rows:
        return {
            "top_pct": top_pct,
            "min_score": min_score,
            "max_per_industry": max_per_industry,
            "avg_return": None,
            "hit_rate": None,
            "max_drawdown": None,
            "annual_std": None,
            "picked_rows": 0,
            "daily_points": 0,
        }

    top = pd.concat(rows, axis=0)
    daily_ret = top.groupby("trade_date")["target_valuation_return"].mean().sort_index()
    equity = (1.0 + daily_ret.fillna(0.0)).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0
    annual = top.groupby(top["trade_date"].dt.year)["target_valuation_return"].mean()

    return {
        "top_pct": top_pct,
        "min_score": min_score,
        "max_per_industry": max_per_industry,
        "avg_return": float(top["target_valuation_return"].mean()),
        "hit_rate": float((top["target_valuation_return"] > 0).mean()),
        "max_drawdown": float(drawdown.min()),
        "annual_std": float(annual.std(ddof=0)) if len(annual) else None,
        "picked_rows": int(len(top)),
        "daily_points": int(len(daily_ret)),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    df = pd.read_parquet(DATASET_PATH)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")

    version_dir = BASE_DIR / "outputs" / "model_versions" / MODEL_VERSION
    bundle = joblib.load(version_dir / "models_Q1.joblib")
    feature_cols = list(bundle.get("feature_cols", []))
    metrics_meta = bundle.get("metrics", {}) or {}
    reg_target_col = str(metrics_meta.get("reg_target_col", "target_fy_value_yoy"))
    cls_target_col = str(metrics_meta.get("cls_target_col", "target_fy_up"))

    train, test, cutoff = split_train_test(df, cfg, reg_target_col, cls_target_col)
    lookback = int((cfg.get("train") or {}).get("stock_median_lookback_years", 3))
    x_test = impute_like_training(train, test, feature_cols, cutoff, lookback)

    score = pd.Series(bundle["classifier"].predict_proba(x_test)[:, 1], index=x_test.index, name="score")

    eval_df = test.loc[score.index, ["trade_date", "industry_name", "target_valuation_return"]].copy()
    eval_df["score"] = score
    eval_df = eval_df.dropna(subset=["trade_date", "industry_name", "target_valuation_return", "score"])

    score_q = eval_df["score"].quantile([0.0, 0.5, 0.6, 0.7, 0.8, 0.9]).to_dict()

    top_pcts = [0.05, 0.08, 0.10]
    min_scores = [
        float(score_q[0.0]),
        float(score_q[0.5]),
        float(score_q[0.6]),
        float(score_q[0.7]),
        float(score_q[0.8]),
        float(score_q[0.9]),
    ]
    max_per_inds = [None, 8, 5, 3]

    rows = []
    for top_pct in top_pcts:
        for min_score in min_scores:
            for max_per_ind in max_per_inds:
                rows.append(compute_policy_metrics(eval_df, top_pct, min_score, max_per_ind))

    out_df = pd.DataFrame(rows)
    valid = out_df.dropna(subset=["avg_return", "hit_rate", "max_drawdown"]).copy()
    valid["dd_abs"] = valid["max_drawdown"].abs()
    valid["risk_adjusted"] = valid["avg_return"] / valid["dd_abs"].replace(0.0, np.nan)
    valid = valid.sort_values(["risk_adjusted", "avg_return"], ascending=[False, False])

    baseline = compute_policy_metrics(eval_df, top_pct=0.10, min_score=float(score_q[0.0]), max_per_industry=None)

    report = {
        "model_version": MODEL_VERSION,
        "cls_target_col": cls_target_col,
        "baseline_policy": baseline,
        "best_by_risk_adjusted": valid.head(1).to_dict(orient="records"),
        "top10_candidates": valid.head(10).to_dict(orient="records"),
    }

    (OUT_DIR / "policy_scan.csv").write_text(out_df.to_csv(index=False), encoding="utf-8")
    (OUT_DIR / "policy_ranked_top10.csv").write_text(valid.head(10).to_csv(index=False), encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"written: {OUT_DIR}")


if __name__ == "__main__":
    main()
