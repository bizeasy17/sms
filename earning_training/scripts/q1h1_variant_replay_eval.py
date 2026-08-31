from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BACKTEST_WINDOW = {"Q1": (5, 12), "H1": (9, 4)}


@dataclass(frozen=True)
class PolicyConfig:
    top_pct: float = 0.08
    min_score: float = 0.0
    max_positions: int = 30
    max_stock_weight: float = 0.05
    max_industry_weight: float = 0.20
    commission: float = 0.0003
    slippage: float = 0.0005
    drawdown_soft_limit: float = -0.12
    drawdown_hard_limit: float = -0.22
    max_allowed_drawdown: float = -0.30
    reduced_exposure: float = 0.50
    cooldown_periods: int = 5
    walk_forward_folds: int = 4

    def validate(self) -> None:
        if not 0 < self.top_pct <= 1:
            raise ValueError("top_pct must be in (0, 1]")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        if self.max_positions < 1:
            raise ValueError("max_positions must be positive")
        if not 0 < self.max_stock_weight <= 1 or not 0 < self.max_industry_weight <= 1:
            raise ValueError("position weight limits must be in (0, 1]")
        if self.commission < 0 or self.slippage < 0:
            raise ValueError("trading costs cannot be negative")
        if not -1 < self.drawdown_hard_limit < self.drawdown_soft_limit < 0:
            raise ValueError("drawdown limits must satisfy -1 < hard < soft < 0")
        if not -1 < self.max_allowed_drawdown <= self.drawdown_hard_limit:
            raise ValueError("max_allowed_drawdown must be no greater than drawdown_hard_limit")
        if not 0 <= self.reduced_exposure <= 1 or self.cooldown_periods < 0:
            raise ValueError("invalid drawdown exposure controls")
        if self.walk_forward_folds < 1:
            raise ValueError("walk_forward_folds must be positive")


def load_dataset(config_path: Path, report_type: str) -> pd.DataFrame:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    out_cfg = cfg.get("output") or {}

    out_dir = Path(out_cfg.get("dir", "outputs"))
    if not out_dir.is_absolute():
        out_dir = config_path.parent.parent / out_dir

    dataset_version = str(out_cfg.get("dataset_version") or "").strip()
    if bool(out_cfg.get("use_dataset_versioning", False)) and dataset_version:
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

    fy_targets = {"target_fy_up", "target_fy_value", "target_fy_value_yoy"}
    if bool(train_cfg.get("fy_split_by_fiscal_year", True)) and "fiscal_year" in model_df.columns and (
        reg_target_col in fy_targets or cls_target_col in fy_targets
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


def filter_backtest_window(
    eval_df: pd.DataFrame,
    start_month: int,
    end_month: int,
) -> pd.DataFrame:
    if not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
        raise ValueError("backtest window months must be in [1, 12]")
    month = eval_df["trade_date"].dt.month
    if start_month <= end_month:
        in_window = month.between(start_month, end_month)
    else:
        in_window = (month >= start_month) | (month <= end_month)
    return eval_df[in_window].copy()


def _target_weights(group: pd.DataFrame, policy: PolicyConfig) -> tuple[pd.DataFrame, dict[str, float]]:
    ranked = group.sort_values("score", ascending=False).drop_duplicates("ts_code")
    target_count = min(policy.max_positions, max(1, int(np.ceil(len(ranked) * policy.top_pct))))
    selected = ranked[ranked["score"] >= policy.min_score].head(target_count).copy()
    if selected.empty:
        return selected, {}

    selected["weight"] = min(1.0 / len(selected), policy.max_stock_weight)
    industry_weight = selected.groupby("industry_name")["weight"].transform("sum")
    scale = (policy.max_industry_weight / industry_weight).clip(upper=1.0)
    selected["weight"] *= scale
    return selected, dict(zip(selected["ts_code"], selected["weight"], strict=True))


def _turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    symbols = set(previous) | set(current)
    stock_turnover = sum(abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols)
    previous_cash = 1.0 - sum(previous.values())
    current_cash = 1.0 - sum(current.values())
    return 0.5 * (stock_turnover + abs(current_cash - previous_cash))


def _period_metrics(periods: pd.DataFrame) -> dict[str, Any]:
    if periods.empty:
        return {
            "total_return": 0.0,
            "avg_return": 0.0,
            "hit_rate": 0.0,
            "max_drawdown": 0.0,
            "daily_points": 0,
        }
    equity = (1.0 + periods["net_return"]).cumprod()
    running_peak = equity.cummax().clip(lower=1.0)
    drawdown = equity / running_peak - 1.0
    return {
        "total_return": float(equity.iloc[-1] - 1.0),
        "avg_return": float(periods["net_return"].mean()),
        "hit_rate": float((periods["net_return"] > 0).mean()),
        "max_drawdown": float(drawdown.min()),
        "daily_points": int(len(periods)),
    }


def _walk_forward_metrics(periods: pd.DataFrame, folds: int) -> dict[str, Any]:
    windows = []
    for fold_number, indices in enumerate(np.array_split(np.arange(len(periods)), min(folds, len(periods))), 1):
        if len(indices) == 0:
            continue
        window = periods.iloc[indices]
        metrics = _period_metrics(window)
        metrics.update(
            {
                "fold": fold_number,
                "start_date": window["trade_date"].iloc[0].date().isoformat(),
                "end_date": window["trade_date"].iloc[-1].date().isoformat(),
            }
        )
        windows.append(metrics)

    returns = [window["total_return"] for window in windows]
    return {
        "mode": "fixed_model_rolling_time_windows",
        "positive_fold_ratio": float(np.mean(np.asarray(returns) > 0)) if returns else 0.0,
        "worst_fold_return": float(min(returns)) if returns else 0.0,
        "folds": windows,
    }


def compute_policy_metrics(eval_df: pd.DataFrame, policy: PolicyConfig) -> dict[str, Any]:
    policy.validate()
    previous_weights: dict[str, float] = {}
    equity = peak = 1.0
    cooldown_remaining = 0
    picked_rows = 0
    records = []

    for trade_date, group in eval_df.groupby("trade_date", sort=True):
        drawdown_before = equity / peak - 1.0
        if cooldown_remaining > 0:
            exposure = 0.0
            cooldown_remaining -= 1
            if cooldown_remaining == 0:
                peak = equity
        elif drawdown_before <= policy.drawdown_hard_limit:
            exposure = 0.0
            cooldown_remaining = max(0, policy.cooldown_periods - 1)
        elif drawdown_before <= policy.drawdown_soft_limit:
            exposure = policy.reduced_exposure
        else:
            exposure = 1.0

        selected, raw_weights = _target_weights(group, policy)
        weights = (
            {symbol: weight * exposure for symbol, weight in raw_weights.items()}
            if exposure > 0
            else {}
        )
        turnover = _turnover(previous_weights, weights)
        cost = turnover * (policy.commission + policy.slippage)
        returns = dict(zip(selected["ts_code"], selected["target_valuation_return"], strict=True))
        gross_return = sum(weight * float(returns[symbol]) for symbol, weight in weights.items())
        net_return = max(-1.0, gross_return - cost)
        equity *= 1.0 + net_return
        peak = max(peak, equity)
        picked_rows += len(weights)
        records.append(
            {
                "trade_date": trade_date,
                "gross_return": gross_return,
                "net_return": net_return,
                "turnover": turnover,
                "cost": cost,
                "exposure": sum(weights.values()),
                "positions": len(weights),
            }
        )
        previous_weights = weights

    periods = pd.DataFrame(records)
    metrics = _period_metrics(periods)
    metrics.update(
        {
            "avg_gross_return": float(periods["gross_return"].mean()) if len(periods) else 0.0,
            "annual_std": float(periods.groupby(periods["trade_date"].dt.year)["net_return"].mean().std(ddof=0))
            if len(periods)
            else None,
            "avg_turnover": float(periods["turnover"].mean()) if len(periods) else 0.0,
            "total_cost": float(periods["cost"].sum()) if len(periods) else 0.0,
            "avg_exposure": float(periods["exposure"].mean()) if len(periods) else 0.0,
            "picked_rows": int(picked_rows),
            "walk_forward": _walk_forward_metrics(periods, policy.walk_forward_folds),
        }
    )
    return metrics


def eval_model(
    report_type: str,
    model_version: str,
    config_path: Path,
    policy: PolicyConfig,
    backtest_start_month: int,
    backtest_end_month: int,
) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    df = load_dataset(config_path, report_type=report_type)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")

    version_dir = BASE_DIR / "outputs" / "model_versions" / model_version
    bundle = joblib.load(version_dir / f"models_{report_type}.joblib")

    feature_cols = list(bundle.get("feature_cols", []))
    metrics_meta = bundle.get("metrics", {}) or {}
    reg_target_col = str(metrics_meta.get("reg_target_col", "target_fy_value_yoy"))
    cls_target_col = str(metrics_meta.get("cls_target_col", "target_fy_up"))

    train, test, cutoff = split_train_test(df, cfg, reg_target_col, cls_target_col)
    lookback = int((cfg.get("train") or {}).get("stock_median_lookback_years", 3))
    x_test = impute_like_training(train, test, feature_cols, cutoff, lookback)

    score = pd.Series(bundle["classifier"].predict_proba(x_test)[:, 1], index=x_test.index, name="score")
    eval_df = test.loc[
        score.index,
        ["trade_date", "ts_code", "industry_name", "target_valuation_return"],
    ].copy()
    eval_df["ts_code"] = eval_df["ts_code"].fillna("").astype(str)
    eval_df["industry_name"] = eval_df["industry_name"].fillna("UNKNOWN").astype(str)
    eval_df["score"] = score
    eval_df = eval_df.dropna(subset=["trade_date", "target_valuation_return", "score"])
    unfiltered_dates = int(eval_df["trade_date"].nunique())
    eval_df = filter_backtest_window(eval_df, backtest_start_month, backtest_end_month)
    if eval_df.empty:
        raise ValueError(
            f"no {report_type} rows remain after applying backtest window "
            f"{backtest_start_month}-{backtest_end_month}"
        )

    return {
        "report_type": report_type,
        "model_version": model_version,
        "run_id": metrics_meta.get("run_id"),
        "cls_acc": metrics_meta.get("cls_acc"),
        "cls_auc": metrics_meta.get("cls_auc"),
        "reg_mae": metrics_meta.get("reg_mae"),
        "cls_decision_threshold": metrics_meta.get("cls_decision_threshold"),
        "cls_gray_zone_abs_min": metrics_meta.get("cls_gray_zone_abs_min"),
        "backtest_window": {
            "start_month": backtest_start_month,
            "end_month": backtest_end_month,
            "start_date": eval_df["trade_date"].min().date().isoformat(),
            "end_date": eval_df["trade_date"].max().date().isoformat(),
            "unfiltered_dates": unfiltered_dates,
            "filtered_dates": int(eval_df["trade_date"].nunique()),
        },
        "policy": compute_policy_metrics(eval_df, policy),
    }


def parse_variant(value: str) -> tuple[str, str, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("variant must be name=model_version=config_path")
    name, model_version, config_path = parts
    return name, model_version, BASE_DIR / config_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Q1/H1 model variants with a fixed top-percentile policy.")
    parser.add_argument("--report-type", required=True, choices=["Q1", "H1", "Q3", "FY"])
    parser.add_argument("--top-pct", type=float, default=0.08)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--max-positions", type=int, default=30)
    parser.add_argument("--max-stock-weight", type=float, default=0.05)
    parser.add_argument("--max-industry-weight", type=float, default=0.20)
    parser.add_argument("--commission", type=float, default=0.0003)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--drawdown-soft-limit", type=float, default=-0.12)
    parser.add_argument("--drawdown-hard-limit", type=float, default=-0.22)
    parser.add_argument("--max-allowed-drawdown", type=float, default=-0.30)
    parser.add_argument("--reduced-exposure", type=float, default=0.50)
    parser.add_argument("--cooldown-periods", type=int, default=5)
    parser.add_argument("--walk-forward-folds", type=int, default=4)
    parser.add_argument("--backtest-start-month", type=int)
    parser.add_argument("--backtest-end-month", type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--variant", action="append", type=parse_variant, required=True)
    args = parser.parse_args()

    policy = PolicyConfig(
        top_pct=args.top_pct,
        min_score=args.min_score,
        max_positions=args.max_positions,
        max_stock_weight=args.max_stock_weight,
        max_industry_weight=args.max_industry_weight,
        commission=args.commission,
        slippage=args.slippage,
        drawdown_soft_limit=args.drawdown_soft_limit,
        drawdown_hard_limit=args.drawdown_hard_limit,
        max_allowed_drawdown=args.max_allowed_drawdown,
        reduced_exposure=args.reduced_exposure,
        cooldown_periods=args.cooldown_periods,
        walk_forward_folds=args.walk_forward_folds,
    )
    policy.validate()
    default_start_month, default_end_month = DEFAULT_BACKTEST_WINDOW.get(args.report_type, (1, 12))
    backtest_start_month = args.backtest_start_month or default_start_month
    backtest_end_month = args.backtest_end_month or default_end_month

    results = {}
    for name, model_version, config_path in args.variant:
        results[name] = eval_model(
            args.report_type,
            model_version,
            config_path,
            policy,
            backtest_start_month,
            backtest_end_month,
        )

    names = list(results)
    baseline_name = names[0]
    baseline = results[baseline_name]
    deltas = {}
    for name in names[1:]:
        item = results[name]
        deltas[f"{name}_minus_{baseline_name}"] = {
            "cls_acc": float(item["cls_acc"] - baseline["cls_acc"]),
            "cls_auc": float(item["cls_auc"] - baseline["cls_auc"]),
            "reg_mae": float(item["reg_mae"] - baseline["reg_mae"]),
            "policy_avg_return": float(item["policy"]["avg_return"] - baseline["policy"]["avg_return"]),
            "policy_hit_rate": float(item["policy"]["hit_rate"] - baseline["policy"]["hit_rate"]),
            "policy_max_drawdown": float(item["policy"]["max_drawdown"] - baseline["policy"]["max_drawdown"]),
        }

    report = {
        "report_type": args.report_type,
        "backtest_start_month": backtest_start_month,
        "backtest_end_month": backtest_end_month,
        "policy": asdict(policy),
        "baseline_variant": baseline_name,
        "variants": results,
        "deltas": deltas,
    }

    out_path = BASE_DIR / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"written: {out_path}")


if __name__ == "__main__":
    main()