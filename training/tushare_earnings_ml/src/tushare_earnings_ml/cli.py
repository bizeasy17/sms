from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd

from .config import load_config
from .data_sources import load_financial_cache, load_market_frames
from .feature_builder import build_features
from .targets import build_targets
from .trainer import save_artifacts, train_models


def _prepare_dataset(config_path: str) -> pd.DataFrame:
    cfg = load_config(config_path)

    trading, fundamental = load_market_frames(
        db_url=cfg.data["db_url"],
        trading_table=cfg.data.get("trading_table", "stockdata_stocktradinghistory"),
        fundamental_table=cfg.data.get("fundamental_table", "stockdata_stockfundamentalhistory"),
        start_date=cfg.data.get("start_date"),
        end_date=cfg.data.get("end_date"),
        freq=cfg.data.get("freq", "D"),
        scope_prefixes=cfg.data.get("scope_prefixes") or None,
    )

    financial_cache = {}
    if bool(cfg.feature.get("use_financial_cache", True)):
        financial_cache = load_financial_cache(cfg.data.get("financial_cache_dir", ""))

    dataset = build_features(
        trading=trading,
        fundamental=fundamental,
        financial_cache=financial_cache,
        lookback_days=int(cfg.feature.get("lookback_days", 20)),
        min_history_rows=int(cfg.feature.get("min_history_rows", 120)),
    )
    dataset = build_targets(dataset, horizon_days=int(cfg.label.get("horizon_days", 20)))

    out_dir = Path(cfg.output["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = out_dir / cfg.output.get("dataset_file", "dataset.parquet")
    dataset.to_parquet(dataset_path, index=False)
    print(f"dataset saved: {dataset_path} rows={len(dataset)}")
    return dataset


def cmd_prepare_dataset(args):
    _prepare_dataset(args.config)


def cmd_train(args):
    cfg = load_config(args.config)
    out_dir = Path(cfg.output["dir"])
    dataset_path = out_dir / cfg.output.get("dataset_file", "dataset.parquet")

    if dataset_path.exists() and not args.rebuild:
        dataset = pd.read_parquet(dataset_path)
    else:
        dataset = _prepare_dataset(args.config)

    bundle = train_models(
        df=dataset,
        train_end_date=cfg.train.get("train_end_date"),
        random_state=int(cfg.train.get("random_state", 42)),
    )
    save_artifacts(
        bundle,
        output_dir=out_dir,
        model_file=cfg.output.get("model_file", "models.joblib"),
        metrics_file=cfg.output.get("metrics_file", "metrics.json"),
    )
    print(f"train done: metrics={bundle.get('metrics')}")


def cmd_predict(args):
    cfg = load_config(args.config)
    out_dir = Path(cfg.output["dir"])
    model_path = out_dir / cfg.output.get("model_file", "models.joblib")
    dataset_path = out_dir / cfg.output.get("dataset_file", "dataset.parquet")

    if not model_path.exists():
        raise FileNotFoundError(f"model not found: {model_path}")
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")

    bundle = joblib.load(model_path)
    data = pd.read_parquet(dataset_path)
    data = data.sort_values(["ts_code", "trade_date"])

    code = str(args.ts_code).strip()
    subset = data[data["ts_code"] == code]
    if subset.empty:
        raise ValueError(f"No rows for ts_code={code}")

    row = subset.tail(1).copy()
    x = row[bundle["feature_cols"]].fillna(0)

    reg_pred = None
    if bundle.get("regressor") is not None:
        reg_pred = float(bundle["regressor"].predict(x)[0])
    cls_prob = float(bundle["classifier"].predict_proba(x)[0][1])

    print({
        "ts_code": code,
        "trade_date": str(row["trade_date"].iloc[0]),
        "pred_earnings_growth": reg_pred,
        "pred_valuation_up_prob": cls_prob,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tushare earnings forecast project CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare-dataset")
    p_prepare.add_argument("--config", required=True)
    p_prepare.set_defaults(func=cmd_prepare_dataset)

    p_train = sub.add_parser("train")
    p_train.add_argument("--config", required=True)
    p_train.add_argument("--rebuild", action="store_true", default=False)
    p_train.set_defaults(func=cmd_train)

    p_predict = sub.add_parser("predict")
    p_predict.add_argument("--config", required=True)
    p_predict.add_argument("--ts-code", required=True)
    p_predict.set_defaults(func=cmd_predict)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
