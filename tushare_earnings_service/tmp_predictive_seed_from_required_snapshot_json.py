import argparse
import json
import os
from pathlib import Path

import django
import joblib
import numpy as np
import pandas as pd

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tushare_earnings_service.settings")
django.setup()

from earnings_forecast.services import EarningsForecastPipeline  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build predictive history seed json from required feature snapshots JSON."
    )
    parser.add_argument(
        "--input-json",
        required=True,
        help="Input required feature snapshots json file.",
    )
    parser.add_argument(
        "--output-json",
        required=True,
        help="Output predictive history seed json path.",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Optional pipeline config path. Defaults to configs/default.yaml.",
    )
    parser.add_argument(
        "--serving-slot",
        default="production",
        help="Serving slot for model selection. Default production.",
    )
    return parser.parse_args()


def normalize_end_date(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = text[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def to_period(financial_end_date, report_type):
    token = normalize_end_date(financial_end_date)
    if not token:
        return ""
    year = token[:4]
    rt = str(report_type or "").strip().upper()
    return f"{year}{rt}" if rt else ""


def to_float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def valid_fill_value(value):
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        return False
    return True


def get_report_type_code(report_type):
    mapping = {"Q1": 1.0, "H1": 2.0, "Q3": 3.0, "FY": 4.0}
    return mapping.get(str(report_type or "").strip().upper())


def build_feature_row(item):
    report_type = str(item.get("report_type") or "").strip().upper()
    feature_snapshot = item.get("feature_snapshot") or {}
    market_snapshot = item.get("market_snapshot") or {}

    row = {}
    row.update(feature_snapshot)
    row.update(market_snapshot)
    row["report_type"] = report_type
    if row.get("report_type_code") in (None, ""):
        row["report_type_code"] = get_report_type_code(report_type)
    return row


def main():
    args = parse_args()
    input_json = Path(args.input_json)
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    rows = json.loads(input_json.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("input json must be a list")

    config_path = args.config.strip() if args.config else "configs/default.yaml"
    pipeline = EarningsForecastPipeline(config_path=config_path)

    model_cache = {}

    out_rows = []
    matched = 0
    skipped_not_ready = 0
    skipped_no_model = 0
    skipped_no_target = 0
    errors = 0

    for item in rows:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("ready_for_predict")):
            skipped_not_ready += 1
            continue

        ts_code = str(item.get("ts_code") or "").strip().upper()
        report_type = str(item.get("report_type") or "").strip().upper()
        required_end = normalize_end_date(item.get("financial_end_date"))
        if not ts_code or not report_type or not required_end:
            continue

        try:
            model_path = pipeline._resolve_predict_model_path(
                latest_report_type=report_type,
                model_version=None,
                serving_slot=args.serving_slot,
            )
            if not model_path.exists():
                skipped_no_model += 1
                continue

            bundle_key = str(model_path.resolve())
            bundle = model_cache.get(bundle_key)
            if bundle is None:
                bundle = joblib.load(model_path)
                model_cache[bundle_key] = bundle

            effective_model_version = pipeline._infer_model_version_from_path(model_path)
            dataset_path = pipeline._resolve_predict_dataset_path(
                model_version=effective_model_version,
                serving_slot=args.serving_slot,
            )

            feature_cols = list(bundle.get("feature_cols") or [])
            raw_row = build_feature_row(item)
            x = pd.DataFrame([raw_row]).reindex(columns=feature_cols)
            x = x.replace([np.inf, -np.inf], np.nan)
            for col in feature_cols:
                x[col] = pd.to_numeric(x[col], errors="coerce")

            industry_name = str(raw_row.get("industry_name") or "UNKNOWN")
            global_median, industry_median_df = pipeline._load_predict_impute_stats(
                model_version=effective_model_version,
                feature_cols=feature_cols,
                dataset_path=dataset_path,
            )
            if not industry_median_df.empty and industry_name in industry_median_df.index:
                ind_med = industry_median_df.loc[industry_name]
            else:
                ind_med = pd.Series(dtype=float)

            for col in feature_cols:
                ind_val = ind_med.get(col)
                if valid_fill_value(ind_val):
                    x[col] = x[col].fillna(ind_val)
                g_val = global_median.get(col)
                if valid_fill_value(g_val):
                    x[col] = x[col].fillna(g_val)
                if bool(x[col].isna().any()):
                    x[col] = x[col].fillna(0.0)

            classifier = bundle["classifier"]
            regressor = bundle.get("regressor")

            industry_models = bundle.get("industry_models") or {}
            if isinstance(industry_models, dict) and industry_name in industry_models:
                im = industry_models.get(industry_name) or {}
                if im.get("classifier") is not None:
                    classifier = im["classifier"]
                if im.get("regressor") is not None:
                    regressor = im["regressor"]

            earnings_pred = None
            if regressor is not None:
                earnings_pred = float(regressor.predict(x)[0])
            valuation_up_prob = float(classifier.predict_proba(x)[0][1])
            valuation_mapping = pipeline._valuation_mapping(
                valuation_up_prob=valuation_up_prob,
                earnings_growth=earnings_pred,
            )

            score = float(valuation_mapping.get("score") or 0.0)
            if score >= 65:
                risk_level = "LOW"
            elif score >= 50:
                risk_level = "MEDIUM"
            else:
                risk_level = "HIGH"

            current_price = to_float_or_none((item.get("market_snapshot") or {}).get("close"))
            current_market_cap = to_float_or_none((item.get("market_snapshot") or {}).get("total_mv"))
            industry_rank = to_float_or_none(raw_row.get("pe_ind_rank"))
            realized_volatility = to_float_or_none(raw_row.get("vol_lb_std"))
            anchor_trade = str(item.get("anchor_trade") or (item.get("market_snapshot") or {}).get("trade_date") or "")
            asof_trade_date = pd.to_datetime(anchor_trade, errors="coerce")
            if pd.isna(asof_trade_date):
                asof_trade_date = pd.Timestamp.today()
            market_regime_meta = pipeline._detect_market_regime(asof_trade_date=asof_trade_date)
            market_regime = str(market_regime_meta.get("regime") or "BALANCE").upper()

            quant_target = pipeline._build_quantitative_target(
                score=score,
                current_price=current_price,
                current_market_cap=current_market_cap,
                valuation_up_prob=valuation_up_prob,
                earnings_growth=earnings_pred,
                industry_rank=industry_rank,
                risk_level=risk_level,
                realized_volatility=realized_volatility,
                market_regime=market_regime,
            )
            target_price = to_float_or_none(quant_target.get("target_price"))
            target_price_low = to_float_or_none(quant_target.get("target_price_low"))
            target_price_high = to_float_or_none(quant_target.get("target_price_high"))
            if target_price is None:
                skipped_no_target += 1
                continue
        except Exception:
            errors += 1
            continue

        market = item.get("market_snapshot") or {}
        anchor_trade = str(item.get("anchor_trade") or market.get("trade_date") or "").strip()
        close_value = to_float_or_none(market.get("close"))

        out_rows.append(
            {
                "ts_code": ts_code,
                "stock_name": item.get("stock_name"),
                "period": to_period(required_end, report_type),
                "report_type": report_type,
                "report_end": required_end,
                "anchor_trade": anchor_trade,
                "close": close_value,
                "predictive_target": target_price,
                "predictive_target_low": target_price_low,
                "predictive_target_high": target_price_high,
                "model_version": effective_model_version,
                "feature_data_source": "json_feature_snapshot",
            }
        )
        matched += 1

    out_rows = sorted(
        out_rows,
        key=lambda x: (x.get("ts_code") or "", x.get("report_end") or "", x.get("report_type") or ""),
    )
    output_json.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"input_json={input_json}")
    print(f"output_json={output_json}")
    print(f"rows_input={len(rows)}")
    print(f"rows_output={len(out_rows)}")
    print(f"matched={matched}")
    print(f"skipped_not_ready={skipped_not_ready}")
    print(f"skipped_no_model={skipped_no_model}")
    print(f"skipped_no_target={skipped_no_target}")
    print(f"errors={errors}")


if __name__ == "__main__":
    main()