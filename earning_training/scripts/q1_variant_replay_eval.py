from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs" / "local_valuation_checks" / "q1_r3_cls_abc_replay_20260429"

VARIANT_CONFIG = {
    "A": {
        "model_version": "dev_20260429_q1_exp_r3_cls_a",
        "config_path": BASE_DIR / "configs" / "default.q1_opt_exp_r3_cls_a.yaml",
    },
    "B": {
        "model_version": "dev_20260429_q1_exp_r3_cls_b",
        "config_path": BASE_DIR / "configs" / "default.q1_opt_exp_r3_cls_b.yaml",
    },
    "C": {
        "model_version": "dev_20260429_q1_exp_r3_cls_c",
        "config_path": BASE_DIR / "configs" / "default.q1_opt_exp_r3_cls_c.yaml",
    },
}


def load_dataset_from_config(config_path: Path, report_type: str = "Q1") -> pd.DataFrame:
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


def split_train_test(df: pd.DataFrame, cfg: dict[str, Any], reg_target_col: str, cls_target_col: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    train_cfg = cfg.get("train") or {}
    model_df = df.copy()

    if train_cfg.get("train_end_date"):
        cutoff = pd.Timestamp(train_cfg.get("train_end_date"))
    else:
        cutoff = model_df["trade_date"].quantile(0.8)

    train = model_df[model_df["trade_date"] <= cutoff]
    test = model_df[model_df["trade_date"] > cutoff]

    if len(train) == 0 and len(model_df) > 1:
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


def assign_decile(score: pd.Series) -> pd.Series:
    pct = score.rank(method="first", pct=True, ascending=False)
    decile = np.floor(pct * 10.0).astype(int) + 1
    decile = np.clip(decile, 1, 10)
    return pd.Series(decile, index=score.index)


def compute_metrics(eval_df: pd.DataFrame) -> dict[str, Any]:
    def _top_part(g: pd.DataFrame) -> pd.DataFrame:
        k = max(1, int(math.ceil(len(g) * 0.1)))
        return g.nlargest(k, "score")

    top = eval_df.groupby("trade_date", group_keys=False).apply(_top_part)

    daily_ret = top.groupby("trade_date")["target_valuation_return"].mean().sort_index()
    equity = (1.0 + daily_ret.fillna(0.0)).cumprod()
    rolling_peak = equity.cummax()
    drawdown = (equity / rolling_peak) - 1.0

    annual = top.groupby("trade_year")["target_valuation_return"].mean().sort_index()

    with_decile = eval_df.copy()
    with_decile["decile"] = with_decile.groupby("trade_date", group_keys=False)["score"].apply(assign_decile)
    decile_curve = (
        with_decile.groupby("decile")["target_valuation_return"]
        .agg(["mean", "count"])
        .rename(columns={"mean": "avg_return", "count": "sample_count"})
        .reset_index()
        .sort_values("decile")
    )

    out = {
        "top_decile_avg_return": float(top["target_valuation_return"].mean()),
        "top_decile_hit_rate": float((top["target_valuation_return"] > 0).mean()),
        "max_drawdown": float(drawdown.min()),
        "annual_top_decile_mean": float(annual.mean()) if len(annual) else None,
        "annual_top_decile_std": float(annual.std(ddof=0)) if len(annual) else None,
        "top_sample_rows": int(len(top)),
        "test_rows_eval": int(len(eval_df)),
        "daily_points": int(len(daily_ret)),
        "decile_curve": decile_curve.to_dict(orient="records"),
        "annual_top_decile": [
            {"year": int(y), "avg_return": float(v)} for y, v in annual.items()
        ],
    }
    return out


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    shared_cfg = yaml.safe_load(VARIANT_CONFIG["A"]["config_path"].read_text(encoding="utf-8")) or {}
    base_df = load_dataset_from_config(VARIANT_CONFIG["A"]["config_path"], report_type="Q1")
    base_df["trade_date"] = pd.to_datetime(base_df["trade_date"], errors="coerce")

    all_results: dict[str, Any] = {}
    decile_rows: list[dict[str, Any]] = []

    for variant, meta in VARIANT_CONFIG.items():
        version_dir = BASE_DIR / "outputs" / "model_versions" / meta["model_version"]
        model_path = version_dir / "models_Q1.joblib"
        metrics_path = version_dir / "metrics_Q1.json"

        bundle = joblib.load(model_path)
        train_cfg = (yaml.safe_load(meta["config_path"].read_text(encoding="utf-8")) or {}).get("train") or {}

        reg_target_col = str(bundle.get("metrics", {}).get("reg_target_col", "target_fy_value_yoy"))
        cls_target_col = str(bundle.get("metrics", {}).get("cls_target_col", "target_fy_up"))
        feature_cols = list(bundle.get("feature_cols", []))

        train, test, cutoff = split_train_test(base_df, shared_cfg, reg_target_col, cls_target_col)
        x_test = impute_like_training(
            train=train,
            test=test,
            feature_cols=feature_cols,
            cutoff=cutoff,
            lookback_years=int(train_cfg.get("stock_median_lookback_years", 3)),
        )

        clf = bundle["classifier"]
        score = pd.Series(clf.predict_proba(x_test)[:, 1], index=x_test.index, name="score")

        eval_df = test.loc[score.index, ["trade_date", "target_valuation_return"]].copy()
        eval_df["score"] = score
        eval_df = eval_df.dropna(subset=["trade_date", "target_valuation_return", "score"])
        eval_df["trade_year"] = eval_df["trade_date"].dt.year

        result = compute_metrics(eval_df)
        result["run_id"] = (json.loads(metrics_path.read_text(encoding="utf-8")) or {}).get("run_id")
        all_results[variant] = result

        for item in result["decile_curve"]:
            decile_rows.append({"variant": variant, **item})

    summary_path = OUTPUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.DataFrame(decile_rows).to_csv(OUTPUT_DIR / "decile_curve.csv", index=False, encoding="utf-8-sig")

    table = []
    for variant in ["A", "B", "C"]:
        r = all_results[variant]
        table.append(
            {
                "variant": variant,
                "run_id": r.get("run_id"),
                "top_decile_avg_return": r.get("top_decile_avg_return"),
                "top_decile_hit_rate": r.get("top_decile_hit_rate"),
                "max_drawdown": r.get("max_drawdown"),
                "annual_top_decile_std": r.get("annual_top_decile_std"),
                "top_sample_rows": r.get("top_sample_rows"),
                "daily_points": r.get("daily_points"),
            }
        )

    pd.DataFrame(table).to_csv(OUTPUT_DIR / "summary_table.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(table, ensure_ascii=False, indent=2))
    print(f"written: {summary_path}")


if __name__ == "__main__":
    main()
