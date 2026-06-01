from __future__ import annotations

import json
import math
from itertools import product
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs" / "local_valuation_checks" / "h1_r1_ab_replay_20260503"

VARIANT_CONFIG = {
    "BASE": {
        "model_version": "dev_20260404_mix_q1h1_base_q3fy_v2",
        "config_path": BASE_DIR / "configs" / "default.yaml",
    },
    "R1": {
        "model_version": "dev_20260503_h1_opt_exp_r1_cls_a",
        "config_path": BASE_DIR / "configs" / "default.h1_opt_exp_r1_cls_a.yaml",
    },
}

RISK_FILTER_MIN_SAMPLES = 80
RISK_FILTER_TOP_PCT = 0.20
RISK_CONFIDENCE_MIN = 0.55
GLOBAL_CASH_STOP_DD = -0.10

GRID_TOP_PCT = [0.10, 0.07, 0.05, 0.03]
GRID_CONFIDENCE_MIN = [0.00, 0.50, 0.55, 0.60, 0.65]
GRID_W_PROB = [1.0, 0.7, 0.5, 0.3]
GRID_W_RET = [0.0, 0.3, 0.5, 0.7, 1.0]
GRID_USE_RISK_FILTER = [False, True]
ANNUALIZATION_DAYS = 252


def load_dataset_from_metrics(metrics_path: Path, report_type: str = "H1") -> pd.DataFrame | None:
    if not metrics_path.exists():
        return None

    payload = json.loads(metrics_path.read_text(encoding="utf-8")) or {}
    dataset_path_text = str(payload.get("dataset_path") or "").strip()
    if not dataset_path_text:
        return None

    dataset_path = Path(dataset_path_text)
    if not dataset_path.exists():
        return None

    split_file = dataset_path.parent / "datasets_by_report_type" / f"{dataset_path.stem}_{report_type}.parquet"
    if split_file.exists():
        return pd.read_parquet(split_file)

    frame = pd.read_parquet(dataset_path)
    if "report_type" not in frame.columns:
        return frame
    rt = frame["report_type"].fillna("UNKNOWN").astype(str).str.upper()
    return frame[rt == report_type].copy()


def load_dataset_from_config(config_path: Path, report_type: str = "H1") -> pd.DataFrame:
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

    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found from config: {dataset_path}")

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

    if len(train) == 0 and len(model_df) > 1:
        cutoff = model_df["trade_date"].quantile(0.8)
        train = model_df[model_df["trade_date"] <= cutoff]
        test = model_df[model_df["trade_date"] > cutoff]

    fy_split_enabled = bool(train_cfg.get("fy_split_by_fiscal_year", True))
    fy_targets = {"target_fy_up", "target_fy_value", "target_fy_value_yoy"}
    if (
        fy_split_enabled
        and "fiscal_year" in model_df.columns
        and (reg_target_col in fy_targets or cls_target_col in fy_targets)
    ):
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


def assign_decile(score: pd.Series) -> pd.Series:
    pct = score.rank(method="first", pct=True, ascending=False)
    decile = np.floor(pct * 10.0).astype(int) + 1
    decile = np.clip(decile, 1, 10)
    return pd.Series(decile, index=score.index)


def _resolve_high_risk_industries(train_df: pd.DataFrame) -> set[str]:
    if "industry_name" not in train_df.columns or "target_valuation_return" not in train_df.columns:
        return set()

    industry_stats = (
        train_df.groupby("industry_name")["target_valuation_return"]
        .agg(["count", "std"])
        .rename(columns={"count": "samples", "std": "ret_std"})
        .reset_index()
    )
    industry_stats = industry_stats[industry_stats["samples"] >= RISK_FILTER_MIN_SAMPLES]
    industry_stats = industry_stats.dropna(subset=["ret_std"])
    if industry_stats.empty:
        return set()

    cutoff = industry_stats["ret_std"].quantile(max(0.0, min(1.0, 1.0 - RISK_FILTER_TOP_PCT)))
    return set(industry_stats.loc[industry_stats["ret_std"] >= cutoff, "industry_name"].astype(str))


def _apply_risk_constraints(eval_df: pd.DataFrame, high_risk_industries: set[str]) -> pd.DataFrame:
    constrained = eval_df.copy()
    if high_risk_industries and "industry_name" in constrained.columns:
        constrained = constrained[~constrained["industry_name"].astype(str).isin(high_risk_industries)]
    constrained = constrained[constrained["score"] >= RISK_CONFIDENCE_MIN]
    return constrained


def _build_top_daily_returns(eval_df: pd.DataFrame, score_col: str = "score", top_pct: float = 0.10) -> tuple[pd.DataFrame, pd.Series]:
    def _top_part(g: pd.DataFrame) -> pd.DataFrame:
        k = max(1, int(math.ceil(len(g) * float(top_pct))))
        return g.nlargest(k, score_col)

    top = eval_df.groupby("trade_date", group_keys=False).apply(_top_part)
    daily_ret = top.groupby("trade_date")["target_valuation_return"].mean().sort_index()
    return top, daily_ret


def _apply_global_cash_stop(daily_ret: pd.Series, stop_drawdown: float = GLOBAL_CASH_STOP_DD) -> tuple[pd.Series, dict[str, Any]]:
    if daily_ret.empty:
        return daily_ret.copy(), {
            "stop_triggered": False,
            "stop_trigger_date": None,
            "post_stop_cash_days": 0,
        }

    adjusted = daily_ret.copy()
    equity = (1.0 + adjusted.fillna(0.0)).cumprod()
    rolling_peak = equity.cummax()
    drawdown = (equity / rolling_peak) - 1.0

    trigger_date = None
    for trade_date, dd in drawdown.items():
        if float(dd) <= float(stop_drawdown):
            trigger_date = trade_date
            break

    if trigger_date is None:
        return adjusted, {
            "stop_triggered": False,
            "stop_trigger_date": None,
            "post_stop_cash_days": 0,
        }

    later_mask = adjusted.index > trigger_date
    adjusted.loc[later_mask] = 0.0
    return adjusted, {
        "stop_triggered": True,
        "stop_trigger_date": str(pd.Timestamp(trigger_date).date()),
        "post_stop_cash_days": int(later_mask.sum()),
    }


def compute_metrics(
    eval_df: pd.DataFrame,
    score_col: str = "score",
    top_pct: float = 0.10,
    global_cash_stop_dd: float | None = None,
) -> dict[str, Any]:
    top, daily_ret = _build_top_daily_returns(eval_df, score_col=score_col, top_pct=top_pct)

    stop_meta = {
        "stop_triggered": False,
        "stop_trigger_date": None,
        "post_stop_cash_days": 0,
    }
    if global_cash_stop_dd is not None:
        daily_ret, stop_meta = _apply_global_cash_stop(daily_ret, stop_drawdown=global_cash_stop_dd)

    equity = (1.0 + daily_ret.fillna(0.0)).cumprod()
    rolling_peak = equity.cummax()
    drawdown = (equity / rolling_peak) - 1.0
    total_return = float(equity.iloc[-1] - 1.0) if len(equity) else None

    annualized_return = None
    if len(equity):
        final_equity = float(equity.iloc[-1])
        if final_equity > 0:
            annualized_return = float(final_equity ** (ANNUALIZATION_DAYS / len(equity)) - 1.0)

    annual = top.groupby("trade_year")["target_valuation_return"].mean().sort_index()

    with_decile = eval_df.copy()
    with_decile["decile"] = with_decile.groupby("trade_date", group_keys=False)[score_col].apply(assign_decile)
    decile_curve = (
        with_decile.groupby("decile")["target_valuation_return"]
        .agg(["mean", "count"])
        .rename(columns={"mean": "avg_return", "count": "sample_count"})
        .reset_index()
        .sort_values("decile")
    )

    return {
        "top_decile_avg_return": float(daily_ret.mean()) if len(daily_ret) else None,
        "top_decile_hit_rate": float((top["target_valuation_return"] > 0).mean()),
        "max_drawdown": float(drawdown.min()),
        "cumulative_top_decile_return": total_return,
        "annualized_top_decile_return": annualized_return,
        "annual_top_decile_mean": float(annual.mean()) if len(annual) else None,
        "annual_top_decile_std": float(annual.std(ddof=0)) if len(annual) else None,
        "top_sample_rows": int(len(top)),
        "test_rows_eval": int(len(eval_df)),
        "daily_points": int(len(daily_ret)),
        "decile_curve": decile_curve.to_dict(orient="records"),
        "annual_top_decile": [
            {"year": int(y), "avg_return": float(v)} for y, v in annual.items()
        ],
        "global_cash_stop": stop_meta,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_metrics_path = BASE_DIR / "outputs" / "model_versions" / VARIANT_CONFIG["BASE"]["model_version"] / "metrics_H1.json"
    r1_metrics_path = BASE_DIR / "outputs" / "model_versions" / VARIANT_CONFIG["R1"]["model_version"] / "metrics_H1.json"

    base_df = load_dataset_from_metrics(base_metrics_path, report_type="H1")
    if base_df is None:
        base_df = load_dataset_from_metrics(r1_metrics_path, report_type="H1")

    shared_cfg = yaml.safe_load(VARIANT_CONFIG["BASE"]["config_path"].read_text(encoding="utf-8")) or {}
    if base_df is None:
        try:
            base_df = load_dataset_from_config(VARIANT_CONFIG["BASE"]["config_path"], report_type="H1")
        except FileNotFoundError:
            base_df = load_dataset_from_config(VARIANT_CONFIG["R1"]["config_path"], report_type="H1")

    base_df["trade_date"] = pd.to_datetime(base_df["trade_date"], errors="coerce")

    all_results: dict[str, Any] = {}
    decile_rows: list[dict[str, Any]] = []
    high_risk_industries: set[str] = set()
    r1_eval_df: pd.DataFrame | None = None

    for variant, meta in VARIANT_CONFIG.items():
        version_dir = BASE_DIR / "outputs" / "model_versions" / meta["model_version"]
        model_path = version_dir / "models_H1.joblib"
        metrics_path = version_dir / "metrics_H1.json"

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
        reg = bundle["regressor"]
        score = pd.Series(clf.predict_proba(x_test)[:, 1], index=x_test.index, name="score")
        pred_return = pd.Series(reg.predict(x_test), index=x_test.index, name="pred_return")

        eval_df = test.loc[score.index, ["trade_date", "target_valuation_return"]].copy()
        if "industry_name" in test.columns:
            eval_df["industry_name"] = test.loc[score.index, "industry_name"]
        eval_df["prob_up"] = score
        eval_df["pred_return"] = pred_return
        eval_df["score"] = score
        eval_df = eval_df.dropna(subset=["trade_date", "target_valuation_return", "score"])
        eval_df["trade_year"] = eval_df["trade_date"].dt.year

        if variant == "R1":
            high_risk_industries = _resolve_high_risk_industries(train)
            r1_eval_df = eval_df.copy()

        result = compute_metrics(eval_df)
        result_global_cash_stop = compute_metrics(eval_df, global_cash_stop_dd=GLOBAL_CASH_STOP_DD)
        result["run_id"] = (json.loads(metrics_path.read_text(encoding="utf-8")) or {}).get("run_id")
        all_results[variant] = result
        all_results[f"{variant}_GLOBAL_STOP"] = {
            **result_global_cash_stop,
            "run_id": result.get("run_id"),
            "global_cash_stop_dd": GLOBAL_CASH_STOP_DD,
        }

        for item in result["decile_curve"]:
            decile_rows.append({"variant": variant, **item})

        if variant == "R1":
            constrained_eval_df = _apply_risk_constraints(eval_df, high_risk_industries)
            if len(constrained_eval_df) > 0:
                constrained_eval_df = constrained_eval_df.copy()
                constrained_eval_df["trade_year"] = constrained_eval_df["trade_date"].dt.year
                constrained_result = compute_metrics(constrained_eval_df)
                constrained_result["run_id"] = result.get("run_id")
                constrained_result["risk_filter"] = {
                    "high_risk_industry_count": len(high_risk_industries),
                    "confidence_min": RISK_CONFIDENCE_MIN,
                    "min_industry_samples": RISK_FILTER_MIN_SAMPLES,
                    "risk_top_pct": RISK_FILTER_TOP_PCT,
                    "rows_after_filter": int(len(constrained_eval_df)),
                }
                all_results["R1_RISK"] = constrained_result
                all_results["R1_RISK_GLOBAL_STOP"] = {
                    **compute_metrics(constrained_eval_df, global_cash_stop_dd=GLOBAL_CASH_STOP_DD),
                    "run_id": result.get("run_id"),
                    "global_cash_stop_dd": GLOBAL_CASH_STOP_DD,
                    "risk_filter": constrained_result["risk_filter"],
                }
                for item in constrained_result["decile_curve"]:
                    decile_rows.append({"variant": "R1_RISK", **item})

    # High-return oriented parameter search on R1.
    grid_rows: list[dict[str, Any]] = []
    if r1_eval_df is not None and len(r1_eval_df) > 0:
        for top_pct, conf_min, w_prob, w_ret, use_risk in product(
            GRID_TOP_PCT,
            GRID_CONFIDENCE_MIN,
            GRID_W_PROB,
            GRID_W_RET,
            GRID_USE_RISK_FILTER,
        ):
            if abs((w_prob + w_ret)) < 1e-12:
                continue

            trial = r1_eval_df.copy()

            if use_risk:
                trial = _apply_risk_constraints(trial, high_risk_industries)
            if conf_min > 0:
                trial = trial[trial["prob_up"] >= conf_min]

            if len(trial) < 300:
                continue

            ret_pos = trial["pred_return"].clip(lower=0.0)
            ret_rank = ret_pos.rank(method="average", pct=True)
            trial["score_param"] = (w_prob * trial["prob_up"]) + (w_ret * ret_rank)
            trial = trial.dropna(subset=["score_param", "target_valuation_return", "trade_date"])
            if trial.empty:
                continue

            trial["trade_year"] = pd.to_datetime(trial["trade_date"], errors="coerce").dt.year
            trial = trial.dropna(subset=["trade_year"])
            if trial.empty:
                continue

            metrics = compute_metrics(trial, score_col="score_param", top_pct=float(top_pct))
            metrics_global_stop = compute_metrics(
                trial,
                score_col="score_param",
                top_pct=float(top_pct),
                global_cash_stop_dd=GLOBAL_CASH_STOP_DD,
            )
            grid_rows.append(
                {
                    "top_pct": float(top_pct),
                    "confidence_min": float(conf_min),
                    "w_prob": float(w_prob),
                    "w_ret": float(w_ret),
                    "use_risk_filter": bool(use_risk),
                    "rows_after_filter": int(len(trial)),
                    "top_decile_avg_return": metrics.get("top_decile_avg_return"),
                    "top_decile_hit_rate": metrics.get("top_decile_hit_rate"),
                    "max_drawdown": metrics.get("max_drawdown"),
                    "annualized_top_decile_return": metrics.get("annualized_top_decile_return"),
                    "annual_top_decile_std": metrics.get("annual_top_decile_std"),
                    "global_stop_top_decile_avg_return": metrics_global_stop.get("top_decile_avg_return"),
                    "global_stop_annualized_top_decile_return": metrics_global_stop.get("annualized_top_decile_return"),
                    "global_stop_max_drawdown": metrics_global_stop.get("max_drawdown"),
                    "global_stop_annual_top_decile_std": metrics_global_stop.get("annual_top_decile_std"),
                    "global_stop_triggered": (metrics_global_stop.get("global_cash_stop") or {}).get("stop_triggered"),
                    "global_stop_trigger_date": (metrics_global_stop.get("global_cash_stop") or {}).get("stop_trigger_date"),
                    "top_sample_rows": metrics.get("top_sample_rows"),
                    "daily_points": metrics.get("daily_points"),
                }
            )

    summary_path = OUTPUT_DIR / "summary.json"

    if grid_rows:
        grid_df = pd.DataFrame(grid_rows)
        grid_df = grid_df.sort_values(
            by=["top_decile_avg_return", "top_decile_hit_rate"],
            ascending=[False, False],
        ).reset_index(drop=True)
        grid_global_stop_df = grid_df.sort_values(
            by=["global_stop_top_decile_avg_return", "top_decile_hit_rate"],
            ascending=[False, False],
        ).reset_index(drop=True)
        grid_top10 = grid_df.head(10)
        grid_global_stop_top10 = grid_global_stop_df.head(10)
        grid_df.to_csv(OUTPUT_DIR / "param_search_all.csv", index=False, encoding="utf-8-sig")
        grid_top10.to_csv(OUTPUT_DIR / "param_search_top10.csv", index=False, encoding="utf-8-sig")
        grid_global_stop_top10.to_csv(
            OUTPUT_DIR / "param_search_global_stop_top10.csv",
            index=False,
            encoding="utf-8-sig",
        )
        all_results["R1_PARAM_SEARCH"] = {
            "grid_size": int(len(grid_df)),
            "top10": grid_top10.to_dict(orient="records"),
            "global_stop_top10": grid_global_stop_top10.to_dict(orient="records"),
            "global_cash_stop_dd": GLOBAL_CASH_STOP_DD,
        }

    summary_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.DataFrame(decile_rows).to_csv(OUTPUT_DIR / "decile_curve.csv", index=False, encoding="utf-8-sig")

    table = []
    for variant in [
        "BASE",
        "BASE_GLOBAL_STOP",
        "R1",
        "R1_GLOBAL_STOP",
        "R1_RISK",
        "R1_RISK_GLOBAL_STOP",
    ]:
        if variant not in all_results:
            continue
        r = all_results[variant]
        table.append(
            {
                "variant": variant,
                "run_id": r.get("run_id"),
                "top_decile_avg_return": r.get("top_decile_avg_return"),
                "top_decile_hit_rate": r.get("top_decile_hit_rate"),
                "max_drawdown": r.get("max_drawdown"),
                "annualized_top_decile_return": r.get("annualized_top_decile_return"),
                "annual_top_decile_std": r.get("annual_top_decile_std"),
                "top_sample_rows": r.get("top_sample_rows"),
                "daily_points": r.get("daily_points"),
            }
        )

    pd.DataFrame(table).to_csv(OUTPUT_DIR / "summary_table.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(table, ensure_ascii=False, indent=2))
    if grid_rows:
        print("top1_search=", all_results["R1_PARAM_SEARCH"]["top10"][0])
        print("top1_global_stop_search=", all_results["R1_PARAM_SEARCH"]["global_stop_top10"][0])
        print(f"written: {OUTPUT_DIR / 'param_search_top10.csv'}")
        print(f"written: {OUTPUT_DIR / 'param_search_global_stop_top10.csv'}")
    print(f"written: {summary_path}")


if __name__ == "__main__":
    main()
