from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml


BASE_DIR = Path(__file__).resolve().parents[1]
OUT_FILE = BASE_DIR / "outputs" / "local_valuation_checks" / "q1_p1_f3_scan06_vs_f3_20260723.json"

BASELINE_MODEL_VERSION = "uat_20260719_q1_p1_f3_grayzone_threshold"
BASELINE_CONFIG_PATH = BASE_DIR / "configs" / "default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold.yaml"

NEW_MODEL_VERSION = "uat_20260723_q1_p1_f3_grayzone_threshold_scan06"
NEW_CONFIG_PATH = BASE_DIR / "configs" / "default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan06.yaml"

POLICY_TOP_PCT = 0.08


def load_dataset(config_path: Path, report_type: str = "Q1") -> pd.DataFrame:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    out_cfg = cfg.get("output") or {}

    out_dir = Path(out_cfg.get("dir", "outputs"))
    if not out_dir.is_absolute():
        out_dir = config_path.parent.parent / out_dir

    use_versioning = bool(out_cfg.get("use_dataset_versioning", False))
    dataset_version = str(out_cfg.get("dataset_version") or "").strip()
    if use_versioning and dataset_version:
        ds_root = out_dir / str(out_cfg.get("dataset_versions_dir", "datasets")) / dataset_version
    else:
        ds_root = out_dir

    dataset_file = str(out_cfg.get("dataset_file", "dataset.parquet"))
    split_dir = ds_root / str(out_cfg.get("split_dataset_dir", "datasets_by_report_type"))
    split_file = split_dir / f"{Path(dataset_file).stem}_{report_type}.parquet"
    dataset_path = ds_root / dataset_file

    if split_file.exists():
        return pd.read_parquet(split_file)

    frame = pd.read_parquet(dataset_path)
    rt = frame["report_type"].fillna("UNKNOWN").astype(str).str.upper()
    return frame[rt == report_type].copy()


def split_train_test(
    df: pd.DataFrame,
    cfg: dict[str, Any],
    reg_target_col: str,
    cls_target_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
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


def impute_like_training(
    train: pd.DataFrame,
    test: pd.DataFrame,
    feature_cols: list[str],
    cutoff: pd.Timestamp,
    lookback_years: int,
) -> pd.DataFrame:
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


def compute_policy_metrics(eval_df: pd.DataFrame, top_pct: float) -> dict[str, Any]:
    rows = []
    for _, g in eval_df.groupby("trade_date"):
        g2 = g.sort_values("score", ascending=False)
        k = max(1, int(np.ceil(len(g2) * top_pct)))
        rows.append(g2.head(k))

    top = pd.concat(rows, axis=0)
    daily_ret = top.groupby("trade_date")["target_valuation_return"].mean().sort_index()
    equity = (1.0 + daily_ret.fillna(0.0)).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0
    annual = top.groupby(top["trade_date"].dt.year)["target_valuation_return"].mean()

    return {
        "top_pct": top_pct,
        "avg_return": float(top["target_valuation_return"].mean()),
        "hit_rate": float((top["target_valuation_return"] > 0).mean()),
        "max_drawdown": float(drawdown.min()),
        "annual_std": float(annual.std(ddof=0)) if len(annual) else None,
        "picked_rows": int(len(top)),
        "daily_points": int(len(daily_ret)),
    }


def eval_model(model_version: str, config_path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    df = load_dataset(config_path, report_type="Q1")
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")

    version_dir = BASE_DIR / "outputs" / "model_versions" / model_version
    bundle = joblib.load(version_dir / "models_Q1.joblib")

    feature_cols = list(bundle.get("feature_cols", []))
    metrics_meta = bundle.get("metrics", {}) or {}
    reg_target_col = str(metrics_meta.get("reg_target_col", "target_fy_value_yoy"))
    cls_target_col = str(metrics_meta.get("cls_target_col", "target_fy_up"))

    train, test, cutoff = split_train_test(df, cfg, reg_target_col, cls_target_col)
    lookback = int((cfg.get("train") or {}).get("stock_median_lookback_years", 3))
    x_test = impute_like_training(train, test, feature_cols, cutoff, lookback)

    score = pd.Series(bundle["classifier"].predict_proba(x_test)[:, 1], index=x_test.index, name="score")

    eval_df = test.loc[score.index, ["trade_date", "target_valuation_return"]].copy()
    eval_df["score"] = score
    eval_df = eval_df.dropna(subset=["trade_date", "target_valuation_return", "score"])

    policy = compute_policy_metrics(eval_df, top_pct=POLICY_TOP_PCT)

    return {
        "model_version": model_version,
        "run_id": metrics_meta.get("run_id"),
        "cls_acc": metrics_meta.get("cls_acc"),
        "cls_auc": metrics_meta.get("cls_auc"),
        "reg_mae": metrics_meta.get("reg_mae"),
        "cls_decision_threshold": metrics_meta.get("cls_decision_threshold"),
        "cls_gray_zone_abs_min": metrics_meta.get("cls_gray_zone_abs_min"),
        "policy": policy,
    }


def main() -> None:
    baseline = eval_model(BASELINE_MODEL_VERSION, BASELINE_CONFIG_PATH)
    new = eval_model(NEW_MODEL_VERSION, NEW_CONFIG_PATH)

    delta = {
        "cls_acc": float(new["cls_acc"] - baseline["cls_acc"]),
        "cls_auc": float(new["cls_auc"] - baseline["cls_auc"]),
        "reg_mae": float(new["reg_mae"] - baseline["reg_mae"]),
        "policy_avg_return": float(new["policy"]["avg_return"] - baseline["policy"]["avg_return"]),
        "policy_hit_rate": float(new["policy"]["hit_rate"] - baseline["policy"]["hit_rate"]),
        "policy_max_drawdown": float(new["policy"]["max_drawdown"] - baseline["policy"]["max_drawdown"]),
    }

    report = {
        "policy": {
            "top_pct": POLICY_TOP_PCT,
            "min_score": "none",
            "max_per_industry": "none",
        },
        "baseline": baseline,
        "new": new,
        "delta_new_minus_baseline": delta,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"written: {OUT_FILE}")


if __name__ == "__main__":
    main()