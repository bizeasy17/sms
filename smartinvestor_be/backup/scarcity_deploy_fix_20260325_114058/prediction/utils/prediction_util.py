import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from django.conf import settings
import joblib
import pandas as pd
from datastore.models import (
    StockCostHistory,
    StockTradingHistory,
    StockFundamentalHistory,
)

from prediction.utils.ta_util import calculate_all_features
from prediction.models import StockPrediction
from prediction.models import StockCombinedFeature
from prediction.services.sw_history_quantiles import SwHistoryQuantileService
from prediction.services.validation_loader import ValuationConfig
from prediction.utils.feature_util import read_features_from_yaml

fields_ohlc = ["open_qfq", "high_qfq", "low_qfq", "close_qfq"]

fields_trading = [
    "change",
    "pct_change",
    "vol",
    "macd_dif",
    "macd_dea",
    "macd",
    "rsi_6",
    "rsi_12",
    "rsi_24",
    "kdj_k",
    "kdj_d",
    "kdj_j",
]

fields_fundamental = [
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pb",
    "ps",
    "ps_ttm",
    "total_share",
    "float_share",
    "free_share",
    "total_mv",
    "circ_mv",
]

fields_cost = [
    "cost_pct5",
    "cost_pct15",
    "cost_pct50",
    "cost_pct85",
    "cost_pct95",
    "weight_avg",
    "winner_rate",
    "his_high",
    "his_low",
]

fields_calculated = [
    "atr",
    "pct_vol_chg",
    "pct_o2c",
    "lower_shadow",
    "upper_shadow",
    "mab_10",
    "mab_25",
    "volatility_ratio",
    "shadow_ratio",
    "mab_60",
    "mab_120",
    "mab_200",
    "free_share_ratio",
]

fields_calculated_M = [
    "atr",
    "pct_vol_chg",
    "pct_o2c",
    "lower_shadow",
    "upper_shadow",
    "mab_10",
    "mab_25",
    "volatility_ratio",
    "shadow_ratio",
    "mab_60",
]

features_DW = ["mab_60", "mab_120", "mab_200"]

features = [
    "trade_date",
    "change",
    "pct_chg",
    "vol",
    "atr",
    "pct_vol_chg",
    "pct_o2c",
    "lower_shadow",
    "upper_shadow",
    "dif",
    "dea",
    "bar",
    "rsi_6",
    "rsi_12",
    "rsi_24",
    "k",
    "d",
    "j",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pb",
    "ps",
    "ps_ttm",
    "total_share",
    "float_share",
    "free_share",
    "total_mv",
    "circ_mv",
    "free_share_ratio",
    "mab_10",
    "mab_25",
    "volatility_ratio",
    "shadow_ratio",
]

PEG_MIN_GROWTH_PCT = 5.0
PEG_MAX_GROWTH_PCT = 80.0
PEG_MIN_TARGET_PE = 5.0
PEG_MAX_TARGET_PE = 45.0


def predict_stock_trend(
    ts_code,
    corp,
    given_date,
    freq="D",
    model=None,
    model_name="XGB",
    volatility="STDOPT",
    version="1.1",
    project_root=None,
):
    """Predict stock trend using the specified model."""
    # 选择只包含在给定列表中的列
    # new_data_filtered = new_data[columns_to_keep if version in ["0.1"] else high_importance_features]

    # 获取最后一次预测的日期
    last_prediction = (
        StockPrediction.objects.filter(
            ts_code=ts_code,
            applied_model=model_name,
            volatility=volatility,
            freq=freq,
            model_version=version,
        )
        .order_by("-trade_date")
        .first()
    )

    if given_date is None:
        today = date.today()
        if freq == "D":
            next_date = (
                last_prediction.trade_date + timedelta(days=1)
                if last_prediction
                else today
            )
            while next_date.weekday() > 4:
                next_date += timedelta(days=1)

            given_date = next_date
        elif freq == "W":
            base_date = last_prediction.trade_date if last_prediction else today
            days_to_friday = (4 - base_date.weekday() + 7) % 7 or 7
            given_date = base_date + timedelta(days=days_to_friday)
        elif freq == "M":
            base_date = last_prediction.trade_date if last_prediction else today
            year, month = base_date.year, base_date.month
            month = month + 1 if month < 12 else 1
            year = year if month > 1 else year + 1
            first_next_month = date(year, month, 1)
            given_date = first_next_month + timedelta(days=32)
            given_date = date(given_date.year, given_date.month, 1) - timedelta(days=1)

        # Check if TradingHistory exists for next_date, else get latest available trade_date
        if not StockTradingHistory.objects.filter(
            ts_code=ts_code, freq=freq, trade_date=given_date
        ).exists():
            latest_record = (
                StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
                .order_by("-trade_date")
                .first()
            )
            if latest_record:
                given_date = latest_record.trade_date
    feature_df = get_feature_data2(
        ts_code=ts_code,
        given_date=given_date,
        feature_list=None,
        freq=freq,
        project_root=project_root,
        model_name=model_name,
        version=version,
    )

    # 使用模型进行预测
    if feature_df is None or feature_df.empty:
        raise ValueError(f"No feature data available for {ts_code} on {given_date}")

    trade_dates = feature_df.pop("trade_date")
    feature_df = feature_df.apply(pd.to_numeric, errors="coerce")
    preds = model.predict(feature_df)
    proba = model.predict_proba(feature_df) if hasattr(model, "predict_proba") else None
    predictions = []
    for idx, pred in enumerate(preds):
        if pred in [1, 2]:
            label = {1: "B", 2: "T"}[pred]
            confidence = max(proba[idx]) if proba is not None else None
            predictions.append(
                {
                    "trade_date": trade_dates.iloc[idx],
                    "top_or_bottom": label,
                    "confidence": (
                        round(confidence, 2) if confidence is not None else None
                    ),
                }
            )

    save_prediction_result(
        ts_code=ts_code,
        corp=corp,
        # given_date=given_date,
        freq=freq,
        model_name=model_name,
        volatility=volatility,
        predictions=predictions,
        version=version,
    )
    return predictions


def save_prediction_result(
    ts_code,
    corp,
    freq="D",
    model_name="XGB",
    volatility="STDOPT",
    version="1.1",
    predictions=None,
):
    """
    Saves the prediction results into the StockPrediction table.

    Args:
        ts_code (str): Stock code.
        given_date (str): Date for which prediction is made.
        predictions (array-like): Prediction results.
        freq (str): Frequency, default 'D'.
    """
    records = []
    for record in predictions:
        record["freq"] = freq
        record["volatility"] = volatility
        record["applied_model"] = model_name
        record["model_version"] = version
        if "row" in record:
            del record["row"]
        records.append(record)

    for idx, pred in enumerate(records):
        StockPrediction.objects.create(
            ts_code=ts_code,
            freq=freq,
            trade_date=pred["trade_date"],
            corporation=corp,
            **{k: v for k, v in pred.items() if k != "trade_date" and k != "freq"},
        )


def get_model_by_name(
    model_name,
    volatility="STDOPT",
    freq="D",
    version="1.0",
    file_suffix="model",
    ts_code_prefix=None,
):
    """
    Constructs the file path for a model based on the given parameters.
    """
    # if model == "RF":
    models = {}
    if ts_code_prefix:
        models[ts_code_prefix] = load_model(
            f"{settings.STATIC_ROOT}/models/{version}/{model_name}_{volatility}_{freq}_{ts_code_prefix}.{file_suffix}"
        )

    for ts_code_prefix in ["60", "0", "3", "688"]:
        model_path = f"{settings.STATIC_ROOT}/models/{version}/{model_name}_{volatility}_{freq}_{ts_code_prefix}.{file_suffix}"
        if os.path.exists(model_path):
            models[ts_code_prefix] = load_model(model_path)
    return models


def load_model(model_path):
    """
    Loads a model from the specified file path.

    Args:
        model_path (str): Path to the model file.

    Returns:
        The loaded model object.
    """
    return joblib.load(model_path)


def get_ts_code_prefix(ts_code):
    if ts_code.startswith("60"):
        return "60"
    elif ts_code.startswith("0"):
        return "0"
    elif ts_code.startswith("3"):
        return "3"
    elif ts_code.startswith("688"):
        return "688"
    else:
        return ""


def get_feature_data2(
    ts_code,
    given_date,
    feature_list=None,
    freq="D",
    model_name="XGB",
    version="1.1",
    project_root=None,
):
    """
    Retrieves data from StockTradingHistory and StockFundamentalHistory for the given stock and feature list.

    Args:
        ts_code (str): Stock code to query.
        start_date (str): Start date (YYYY-MM-DD).
        end_date (str): End date (YYYY-MM-DD).
        feature_list (list, optional): List of feature names to retrieve. If None, uses default based on freq.
        freq (str): Frequency, 'D' for daily, 'W' for weekly, 'M' for monthly.
        model_name (str): Model name, default "XGB".
        version (str): Version, default "1.1".
        project_root (str): Project root directory.

    Returns:
        pd.DataFrame: DataFrame with columns matching feature_list.
    """
    if version == "1.1":
        return get_feature_data(
            ts_code,
            given_date,
            feature_list,
            freq,
        )
    else:
        ts_code_prefix = get_ts_code_prefix(ts_code)
        feature_type = f"{model_name}_{freq}_{ts_code_prefix}"
        feature_file_path = os.path.join(
            project_root, f"prediction/config/features/{version}/features.yaml"
        )

        if feature_list is None:
            # fields yaml定义了trading，fundamental，cost三种特征的字段
            feature_list = read_features_from_yaml(
                feature_file_path, feature_type=feature_type
            )
        qs = StockCombinedFeature.objects.filter(
            ts_code=ts_code, freq=freq, trade_date__gte=given_date
        ).values("trade_date", *(feature_list or []))
        df = pd.DataFrame(list(qs))
        return df


def get_feature_data(
    ts_code,
    given_date,
    feature_list=None,
    freq="D",
):
    """
    Retrieves data from StockTradingHistory and StockFundamentalHistory for the given stock and feature list.

    Args:
        ts_code (str): Stock code to query.
        start_date (str): Start date (YYYY-MM-DD).
        end_date (str): End date (YYYY-MM-DD).
        feature_list (list, optional): List of feature names to retrieve. If None, uses default based on freq.
        freq (str): Frequency, 'D' for daily, 'W' for weekly, 'M' for monthly.

    Returns:
        pd.DataFrame: DataFrame with columns matching feature_list.
    """

    # Select feature list based on freq
    calc_fields = []
    if freq in ["D", "W"]:
        calc_fields = fields_calculated
    elif freq == "M":
        calc_fields = fields_calculated_M

    if feature_list is not None:
        selected_features = feature_list
    else:
        selected_features = features if freq == "M" else features + features_DW

    # Validate input
    if not any([given_date]):
        raise ValueError("At least one of given_date must be provided.")

    # Build query params
    def get_qs(model, freq, fields):
        # Check if a record with the given date exists
        if not model.objects.filter(
            ts_code=ts_code, freq=freq, trade_date=given_date
        ).exists():
            raise ValueError(f"No data available for {ts_code} on {given_date}")

        if given_date:
            qs = (
                model.objects.filter(
                    ts_code=ts_code, freq=freq, trade_date__lte=given_date
                )
                .order_by("-trade_date")
                .values("trade_date", *fields)[:200]
            )
            today_str = date.today().strftime("%Y-%m-%d")
            if str(given_date) < today_str:
                extra_qs = (
                    model.objects.filter(
                        ts_code=ts_code,
                        freq=freq,
                        trade_date__gt=given_date,
                        trade_date__lte=today_str,
                    )
                    .order_by("-trade_date")
                    .values("trade_date", *fields)
                )
                qs = list(qs) + list(extra_qs)
            else:
                qs = list(qs)
            df = pd.DataFrame(qs)
            if not df.empty:
                df = df.sort_values(by="trade_date", ascending=False)
            return df
        return None

    trading_df = get_qs(StockTradingHistory, freq, fields=fields_trading + fields_ohlc)
    fundamental_df = get_qs(StockFundamentalHistory, freq, fields=fields_fundamental)
    # cost_df = get_qs(StockCostHistory, freq, fields=fields_cost)

    if (
        trading_df is None
        or trading_df.empty
        or fundamental_df is None
        or fundamental_df.empty
        # or cost_df is None
        # or cost_df.empty
    ):
        raise ValueError(f"No data available for {ts_code} on {given_date}")

    trading_df.rename(
        columns={
            "open_qfq": "open",
            "high_qfq": "high",
            "low_qfq": "low",
            "close_qfq": "close",
            "pct_change": "pct_chg",
            "macd_dif": "dif",
            "macd_dea": "dea",
            "macd": "bar",
            "kdj_k": "k",
            "kdj_d": "d",
            "kdj_j": "j",
        },
        inplace=True,
    )

    # Merge on date, prioritizing trading data, then fill with fundamental data
    # Merge trading and fundamental data on 'trade_date'
    result_df = trading_df.set_index("trade_date")
    if not fundamental_df.empty:
        fundamental_df = fundamental_df.set_index("trade_date")
        result_df = result_df.combine_first(fundamental_df)

    # Calculate additional features if needed
    if calc_fields:
        result_df = calculate_all_features(result_df)

    # Select and order columns
    result_df = result_df.reindex(columns=selected_features)

    # Reset index to make 'trade_date' a column
    result_df = result_df.reset_index()

    # Filter rows based on provided dates
    result_df["trade_date"] = result_df["trade_date"].astype(str)
    if given_date:
        result_df = result_df[result_df["trade_date"] >= str(given_date)]

    # else: keep all

    # Drop 'index' column if present, but keep 'trade_date'
    result_df = result_df.drop(columns=["index"], errors="ignore")
    return result_df


def get_tushare_pro(token=None):
    """Return a tushare pro client.

    If ``ts.set_token()`` has already been called during Django settings
    initialization, callers can use ``ts.pro_api()`` directly here.
    """

    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("tushare is not installed.") from exc

    if token:
        ts.set_token(token)
    return ts.pro_api()


def _safe_float(value, default=None):
    if value is None or value == "":
        return default
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pick_value(row, candidates, default=None):
    for key in candidates:
        if key in row:
            value = _safe_float(row.get(key), None)
            if value is not None:
                return value
    return default


def _latest_record(df, sort_cols=None):
    if df is None or df.empty:
        return {}
    if sort_cols:
        valid_cols = [col for col in sort_cols if col in df.columns]
        if valid_cols:
            df = df.sort_values(valid_cols, ascending=False)
    return df.iloc[0].to_dict()


def _normalize_date_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    # Be tolerant of mixed sources like 20250228.0 / 2025-02-28 / Timestamp strings.
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return text.replace("-", "").strip()


def _parse_date_yyyymmdd(value):
    text = _normalize_date_text(value)
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _is_more_recent_period(candidate_row, base_row):
    candidate_end = _normalize_date_text((candidate_row or {}).get("end_date"))
    base_end = _normalize_date_text((base_row or {}).get("end_date"))
    if candidate_end and base_end and candidate_end != base_end:
        return candidate_end > base_end

    candidate_ann = _normalize_date_text((candidate_row or {}).get("ann_date"))
    base_ann = _normalize_date_text((base_row or {}).get("ann_date"))
    if candidate_ann and base_ann and candidate_ann != base_ann:
        return candidate_ann > base_ann
    return False


def _blend_preferred(primary, fallback, alpha=0.7):
    if primary is None and fallback is None:
        return None
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    return alpha * primary + (1.0 - alpha) * fallback


def _is_express_vip_eligible(
    express_row,
    fina_row,
    income_row,
    trade_date,
    strict_match=True,
    max_age_days=180,
):
    if not express_row:
        return False, "missing_express_row"
    if not strict_match:
        return True, "strict_disabled"

    trade_dt = _parse_date_yyyymmdd(trade_date)
    ann_dt = _parse_date_yyyymmdd((express_row or {}).get("ann_date"))
    if ann_dt is None:
        return False, "ann_date_missing"
    if trade_dt is not None and ann_dt > trade_dt:
        return False, "ann_date_after_trade_date"

    base_end_candidates = [
        _parse_date_yyyymmdd((fina_row or {}).get("end_date")),
        _parse_date_yyyymmdd((income_row or {}).get("end_date")),
    ]
    base_end_candidates = [item for item in base_end_candidates if item is not None]
    base_end_dt = max(base_end_candidates) if base_end_candidates else None
    express_end_dt = _parse_date_yyyymmdd((express_row or {}).get("end_date"))
    is_period_upgrade = False
    if base_end_dt is not None:
        if express_end_dt is None:
            return False, "express_end_date_missing"
        if express_end_dt < base_end_dt:
            return False, "express_end_before_base_end"
        if express_end_dt > base_end_dt:
            is_period_upgrade = True

    if trade_dt is not None and max_age_days is not None and not is_period_upgrade:
        try:
            age_limit = int(max_age_days)
        except (TypeError, ValueError):
            age_limit = 180
        if age_limit >= 0 and (trade_dt - ann_dt).days > age_limit:
            return False, "ann_date_stale"

    if is_period_upgrade:
        return True, "eligible_period_upgrade"

    return True, "eligible"


def _resolve_express_growth_pct(express_row):
    direct_growth = _pick_value(
        express_row,
        ["yoy_dedu_np", "yoy_np", "yoy_sales", "tr_yoy", "or_yoy", "netprofit_yoy"],
    )
    if direct_growth is not None and abs(direct_growth) <= 1000:
        return direct_growth

    yoy_net_profit = _pick_value(express_row, ["yoy_net_profit"])
    # Some tushare express_vip responses provide yoy_net_profit as absolute delta, not percentage.
    if yoy_net_profit is not None and abs(yoy_net_profit) > 1000:
        current_netprofit = _pick_value(
            express_row,
            ["n_income_attr_p", "n_income", "net_profit", "profit_dedt", "deduct_np"],
        )
        if current_netprofit is not None:
            previous_netprofit = current_netprofit - yoy_net_profit
            if previous_netprofit and previous_netprofit > 0:
                derived_growth_pct = (yoy_net_profit / previous_netprofit) * 100.0
                return max(-500.0, min(derived_growth_pct, 1000.0))

    if yoy_net_profit is not None and abs(yoy_net_profit) <= 1000:
        return yoy_net_profit
    return None


def _apply_express_vip_adjustments(snapshot, express_row, fina_row=None, income_row=None):
    if not express_row:
        return snapshot

    adjusted = dict(snapshot)
    adjusted["base_peg_growth_yoy_pct"] = snapshot.get("peg_growth_yoy_pct")
    adjusted["base_netprofit"] = snapshot.get("netprofit")
    adjusted["base_revenue"] = snapshot.get("revenue")
    adjusted["express_blend_alpha"] = 0.7
    express_yoy = _resolve_express_growth_pct(express_row)
    if express_yoy is not None:
        adjusted["peg_growth_yoy_pct"] = express_yoy

    express_netprofit = _pick_value(
        express_row,
        ["n_income_attr_p", "n_income", "net_profit", "profit_dedt", "deduct_np"],
    )
    express_revenue = _pick_value(
        express_row,
        ["revenue", "total_revenue", "oper_rev"],
    )

    period_end = _normalize_date_text(express_row.get("end_date"))
    # For interim reports, annualize conservatively to avoid over-amplifying a strong quarter.
    if period_end and len(period_end) == 8 and not period_end.endswith("1231"):
        try:
            month = int(period_end[4:6])
        except ValueError:
            month = 12
        month = max(1, min(month, 12))
        annual_factor = min(12.0 / month, 1.8)
        if express_netprofit is not None:
            express_netprofit = express_netprofit * annual_factor
        if express_revenue is not None:
            express_revenue = express_revenue * annual_factor

    if express_netprofit is not None:
        adjusted["netprofit"] = _blend_preferred(express_netprofit, adjusted.get("netprofit"), alpha=0.7)
    if express_revenue is not None:
        adjusted["revenue"] = _blend_preferred(express_revenue, adjusted.get("revenue"), alpha=0.7)

    adjusted["express_end_date"] = _normalize_date_text(express_row.get("end_date")) or None
    adjusted["express_ann_date"] = _normalize_date_text(express_row.get("ann_date")) or None
    adjusted["profit_data_source"] = "express_vip"
    if not _is_more_recent_period(express_row, fina_row or income_row):
        # Same-period quick report still improves timeliness but mark as blended to indicate caution.
        adjusted["profit_data_source"] = "express_vip_blended"

    return adjusted


def _equity_value_to_price(equity_value, total_share):
    if equity_value in (None, 0) or total_share in (None, 0):
        return None
    return equity_value / total_share


def _with_price_info(result, snapshot):
    result["total_share"] = snapshot.get("total_share")
    result["implied_price"] = _equity_value_to_price(
        result.get("equity_value"),
        snapshot.get("total_share"),
    )
    return result


def _resolve_peg_inputs(target_peg, growth_pct):
    applied_target_peg = 1.0 if target_peg is None else float(target_peg)
    if not math.isfinite(applied_target_peg) or applied_target_peg <= 0:
        raise ValueError("PEG valuation requires a positive target PEG.")
    if growth_pct is None:
        raise ValueError("PEG valuation requires profit growth rate.")

    raw_growth_pct = float(growth_pct)
    if not math.isfinite(raw_growth_pct):
        raise ValueError("PEG valuation requires finite profit growth rate.")
    if raw_growth_pct <= 0:
        raise ValueError("PEG valuation skipped: non-positive profit growth rate.")

    effective_growth_pct = min(max(raw_growth_pct, PEG_MIN_GROWTH_PCT), PEG_MAX_GROWTH_PCT)
    raw_target_pe = applied_target_peg * effective_growth_pct
    effective_target_pe = min(max(raw_target_pe, PEG_MIN_TARGET_PE), PEG_MAX_TARGET_PE)

    quality_flags = []
    if not math.isclose(effective_growth_pct, raw_growth_pct, rel_tol=0.0, abs_tol=1e-9):
        quality_flags.append("growth_clamped")
    if not math.isclose(effective_target_pe, raw_target_pe, rel_tol=0.0, abs_tol=1e-9):
        quality_flags.append("target_pe_clamped")

    return {
        "target_peg": applied_target_peg,
        "raw_growth_rate_pct": raw_growth_pct,
        "growth_rate_pct": effective_growth_pct,
        "raw_target_pe": raw_target_pe,
        "derived_target_pe": effective_target_pe,
        "peg_quality_flag": "+".join(quality_flags) if quality_flags else "normal",
    }


def summarize_valuation_range(valuation_results, total_share=None):
    """根据估值结果汇总估值区间和对应价格区间。"""

    if isinstance(valuation_results, pd.DataFrame):
        df = valuation_results.copy()
    else:
        df = pd.DataFrame(valuation_results)

    if df.empty or "equity_value" not in df.columns:
        return {
            "equity_value_min": None,
            "equity_value_max": None,
            "price_min": None,
            "price_max": None,
        }

    equity_values = pd.to_numeric(df["equity_value"], errors="coerce").dropna()
    if equity_values.empty:
        return {
            "equity_value_min": None,
            "equity_value_max": None,
            "price_min": None,
            "price_max": None,
        }

    effective_total_share = total_share
    if effective_total_share is None and "total_share" in df.columns:
        total_share_series = pd.to_numeric(df["total_share"], errors="coerce").dropna()
        if not total_share_series.empty:
            effective_total_share = total_share_series.iloc[0]

    equity_value_min = equity_values.min()
    equity_value_max = equity_values.max()
    return {
        "equity_value_min": equity_value_min,
        "equity_value_max": equity_value_max,
        "equity_value_mid": equity_values.median(),
        "price_min": _equity_value_to_price(equity_value_min, effective_total_share),
        "price_max": _equity_value_to_price(equity_value_max, effective_total_share),
        "price_mid": _equity_value_to_price(equity_values.median(), effective_total_share),
        "total_share": effective_total_share,
    }


def format_valuation_range_output(
    valuation_results,
    total_share=None,
    current_price=None,
    equity_unit=100000000,
    equity_unit_label="亿元",
    price_decimals=2,
):
    """格式化估值区间与价格区间，适合接口直接返回。"""

    summary = summarize_valuation_range(valuation_results, total_share=total_share)

    def _fmt_number(value, decimals=2):
        if value is None:
            return None
        return round(value, decimals)

    def _fmt_equity(value):
        if value is None:
            return None
        return round(value / equity_unit, 2)

    equity_min = summary.get("equity_value_min")
    equity_max = summary.get("equity_value_max")
    equity_mid = summary.get("equity_value_mid")
    price_min = summary.get("price_min")
    price_max = summary.get("price_max")
    price_mid = summary.get("price_mid")

    price_upside_min = None
    price_upside_max = None
    price_upside_mid = None
    if current_price not in (None, 0):
        if price_min is not None:
            price_upside_min = (price_min / current_price) - 1
        if price_max is not None:
            price_upside_max = (price_max / current_price) - 1
        if price_mid is not None:
            price_upside_mid = (price_mid / current_price) - 1

    return {
        "equity_value_range": {
            "min": equity_min,
            "max": equity_max,
            "mid": equity_mid,
            "min_display": (
                f"{_fmt_equity(equity_min)}{equity_unit_label}"
                if equity_min is not None
                else None
            ),
            "max_display": (
                f"{_fmt_equity(equity_max)}{equity_unit_label}"
                if equity_max is not None
                else None
            ),
            "mid_display": (
                f"{_fmt_equity(equity_mid)}{equity_unit_label}"
                if equity_mid is not None
                else None
            ),
            "range_display": (
                f"[{_fmt_equity(equity_min)}, {_fmt_equity(equity_max)}]{equity_unit_label}"
                if equity_min is not None and equity_max is not None
                else None
            ),
        },
        "price_range": {
            "min": price_min,
            "max": price_max,
            "mid": price_mid,
            "min_display": (
                f"{_fmt_number(price_min, price_decimals)}元"
                if price_min is not None
                else None
            ),
            "max_display": (
                f"{_fmt_number(price_max, price_decimals)}元"
                if price_max is not None
                else None
            ),
            "mid_display": (
                f"{_fmt_number(price_mid, price_decimals)}元"
                if price_mid is not None
                else None
            ),
            "range_display": (
                f"[{_fmt_number(price_min, price_decimals)}, {_fmt_number(price_max, price_decimals)}]元"
                if price_min is not None and price_max is not None
                else None
            ),
        },
        "upside_range": {
            "min": price_upside_min,
            "max": price_upside_max,
            "mid": price_upside_mid,
            "min_display": (
                f"{round(price_upside_min * 100, 2)}%"
                if price_upside_min is not None
                else None
            ),
            "max_display": (
                f"{round(price_upside_max * 100, 2)}%"
                if price_upside_max is not None
                else None
            ),
            "mid_display": (
                f"{round(price_upside_mid * 100, 2)}%"
                if price_upside_mid is not None
                else None
            ),
        },
        "total_share": summary.get("total_share"),
        "current_price": current_price,
    }


def _fetch_tushare_frames(ts_code, trade_date=None, pro=None):
    """Fetch commonly used tushare data frames for valuation."""

    pro = pro or get_tushare_pro()
    trade_date_str = None
    if trade_date:
        trade_date_str = str(trade_date).replace("-", "")

    daily_basic = pro.daily_basic(ts_code=ts_code, trade_date=trade_date_str)
    if daily_basic is None or daily_basic.empty:
        daily_basic = pro.daily_basic(ts_code=ts_code, limit=1)

    fina_indicator = pro.fina_indicator(ts_code=ts_code, limit=8)
    income = pro.income(ts_code=ts_code, limit=8)
    balancesheet = pro.balancesheet(ts_code=ts_code, limit=8)
    cashflow = pro.cashflow(ts_code=ts_code, limit=8)
    dividend = pro.dividend(ts_code=ts_code)
    try:
        express_vip = pro.express_vip(ts_code=ts_code, limit=4)
    except Exception:
        express_vip = None

    return {
        "daily_basic": daily_basic,
        "fina_indicator": fina_indicator,
        "income": income,
        "balancesheet": balancesheet,
        "cashflow": cashflow,
        "dividend": dividend,
        "express_vip": express_vip,
    }

def _calc_ebitda_and_ebit(financials):
        """
        Calculate EBITDA and EBIT from available financial indicators.
        Args:
            financials (dict): Contains rows from fina_indicator, income, balancesheet, cashflow.
        Returns:
            tuple: (ebitda, ebit)
        """
        fina_row = _latest_record(financials.get("fina_indicator"), ["end_date", "ann_date"])
        income_row = _latest_record(financials.get("income"), ["end_date", "ann_date"])
        balance_row = _latest_record(financials.get("balancesheet"), ["end_date", "ann_date"])
        cashflow_row = _latest_record(financials.get("cashflow"), ["end_date", "ann_date"])

        # Try EBITDA calculation
        ebitda = _pick_value(fina_row, ["ebitda", "ebitda2"])
        if ebitda in (None, 0):
            # EBITDA = Operating Income + Depreciation + Amortization
            operating_income = _pick_value(income_row, ["operate_profit", "op_income"])
            depreciation = _pick_value(fina_row, ["depr"], 0.0)
            amortization = _pick_value(fina_row, ["amortization"], 0.0)
            if depreciation == 0.0:
                depreciation = _pick_value(income_row, ["depr"], 0.0)
            if amortization == 0.0:
                amortization = _pick_value(income_row, ["amortization"], 0.0)
            if depreciation == 0.0:
                depreciation = _pick_value(cashflow_row, ["depr_fa_coga_dpba"], 0.0)
            if amortization == 0.0:
                amortization = _pick_value(cashflow_row, ["amort_intang_assets"], 0.0)
            if operating_income is not None:
                ebitda = operating_income + depreciation + amortization

        # Try EBIT calculation
        ebit = _pick_value(fina_row, ["ebit", "ebit2"])
        if ebit in (None, 0):
            # EBIT = Operating Income
            ebit = _pick_value(income_row, ["operate_profit", "op_income"])
            if ebit is None:
                # EBIT = EBITDA - Depreciation - Amortization
                if ebitda is not None:
                    depreciation = _pick_value(fina_row, ["depr"], 0.0)
                    amortization = _pick_value(fina_row, ["amortization"], 0.0)
                    if depreciation == 0.0:
                        depreciation = _pick_value(income_row, ["depr"], 0.0)
                    if amortization == 0.0:
                        amortization = _pick_value(income_row, ["amortization"], 0.0)
                    if depreciation == 0.0:
                        depreciation = _pick_value(cashflow_row, ["depr_fa_coga_dpba"], 0.0)
                    if amortization == 0.0:
                        amortization = _pick_value(cashflow_row, ["amort_intang_assets"], 0.0)
                    ebit = ebitda - depreciation - amortization

        return ebitda, ebit
def get_stock_valuation_snapshot(
    ts_code,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """Return a normalized valuation snapshot from tushare.

    Returns a dict with the most relevant current metrics used by the valuation
    functions below. Amount fields are normalized to ``元`` where possible.
    """

    pro = pro or get_tushare_pro(token=token)
    frames = _fetch_tushare_frames(ts_code=ts_code, trade_date=trade_date, pro=pro)

    daily_basic_row = _latest_record(frames["daily_basic"], ["trade_date"])
    fina_row = _latest_record(frames["fina_indicator"], ["end_date", "ann_date"])
    income_row = _latest_record(frames["income"], ["end_date", "ann_date"])
    balance_row = _latest_record(frames["balancesheet"], ["end_date", "ann_date"])
    cashflow_row = _latest_record(frames["cashflow"], ["end_date", "ann_date"])
    express_row = _latest_record(frames.get("express_vip"), ["end_date", "ann_date"])
    dividend_df = frames["dividend"]

    total_mv_wan = _pick_value(daily_basic_row, ["total_mv"])
    circ_mv_wan = _pick_value(daily_basic_row, ["circ_mv"])
    total_mv = total_mv_wan * 10000 if total_mv_wan is not None else None
    circ_mv = circ_mv_wan * 10000 if circ_mv_wan is not None else None

    total_share_wan = _pick_value(daily_basic_row, ["total_share"])
    total_share = total_share_wan * 10000 if total_share_wan is not None else None

    pe_ttm = _pick_value(daily_basic_row, ["pe_ttm", "pe"])
    ps_ttm = _pick_value(daily_basic_row, ["ps_ttm", "ps"])
    pb = _pick_value(daily_basic_row, ["pb"])
    close_price = _pick_value(daily_basic_row, ["close"])

    yoy_profit = _pick_value(
        fina_row,
        ["netprofit_yoy", "dt_netprofit_yoy", "tr_yoy", "or_yoy"],
    )
    ebitda = _pick_value(
        fina_row,
        ["ebitda", "ebitda2"],
    )

    ebit = _pick_value(fina_row, ["ebit", "ebit2", "operate_profit"])
    
    if ebitda in (None, 0) or ebit in (None, 0):
        ebitda, ebit = _calc_ebitda_and_ebit(frames)
    
    netprofit = _pick_value(
        income_row,
        ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"],
    )
    revenue = _pick_value(
        income_row,
        ["revenue", "total_revenue", "oper_rev"],
    )

    cash = _pick_value(
        balance_row,
        ["money_cap", "money_funds", "c_cash_equ_end_period"],
        default=0.0,
    )
    debt = sum(
        filter(
            None,
            [
                _pick_value(balance_row, ["st_borr"], 0.0),
                _pick_value(balance_row, ["lt_borr"], 0.0),
                _pick_value(balance_row, ["bond_payable"], 0.0),
                _pick_value(balance_row, ["non_cur_liab_due_1y"], 0.0),
            ],
        )
    )
    equity_book_value = _pick_value(
        balance_row,
        ["total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int", "total_assets"],
    )

    ocf = _pick_value(
        cashflow_row,
        ["n_cashflow_act", "n_cashflow_oper_act"],
    )
    capex = _pick_value(
        cashflow_row,
        ["c_pay_acq_const_fiolta", "c_pay_acq_const_fiolta_oth"],
        default=0.0,
    )
    fcff = None
    if ocf is not None:
        fcff = ocf - abs(capex)

    annual_dividend = None
    if dividend_df is not None and not dividend_df.empty:
        latest_dividend = _latest_record(dividend_df, ["end_date", "ann_date"])
        cash_div_per_10 = _pick_value(latest_dividend, ["cash_div_tax", "stk_div"])
        if cash_div_per_10 is not None and total_share is not None:
            annual_dividend = cash_div_per_10 / 10 * total_share

    if netprofit is None and total_mv is not None and pe_ttm not in (None, 0):
        netprofit = total_mv / pe_ttm
    if revenue is None and total_mv is not None and ps_ttm not in (None, 0):
        revenue = total_mv / ps_ttm
    if equity_book_value is None and total_mv is not None and pb not in (None, 0):
        equity_book_value = total_mv / pb

    enterprise_value = None
    if total_mv is not None:
        enterprise_value = total_mv + debt - cash

    effective_trade_date = daily_basic_row.get("trade_date") or trade_date

    snapshot = {
        "ts_code": ts_code,
        "trade_date": effective_trade_date,
        "end_date": fina_row.get("end_date") or income_row.get("end_date"),
        "close_price": close_price,
        "total_share": total_share,
        "market_cap": total_mv,
        "circulating_market_cap": circ_mv,
        "pe_ttm": pe_ttm,
        "ps_ttm": ps_ttm,
        "pb": pb,
        "peg_growth_yoy_pct": yoy_profit,
        "netprofit": netprofit,
        "revenue": revenue,
        "equity_book_value": equity_book_value,
        "ebitda": ebitda,
        "ebit": ebit,
        "cash": cash,
        "debt": debt,
        "enterprise_value": enterprise_value,
        "fcff": fcff,
        "annual_dividend": annual_dividend,
        "profit_data_source": "fina_indicator_income",
        "base_peg_growth_yoy_pct": yoy_profit,
        "base_netprofit": netprofit,
        "base_revenue": revenue,
        "express_blend_alpha": None,
        "express_end_date": None,
        "express_ann_date": None,
        "express_apply_reason": "no_express_row",
        "express_block_reason": None,
        "strict_express_match": bool(strict_express_match),
        "express_max_age_days": express_max_age_days,
        "raw_frames": frames,
    }

    if express_row:
        eligible, reason = _is_express_vip_eligible(
            express_row=express_row,
            fina_row=fina_row,
            income_row=income_row,
            trade_date=effective_trade_date,
            strict_match=strict_express_match,
            max_age_days=express_max_age_days,
        )
        snapshot["express_end_date"] = _normalize_date_text(express_row.get("end_date")) or None
        snapshot["express_ann_date"] = _normalize_date_text(express_row.get("ann_date")) or None
        snapshot["express_apply_reason"] = reason
        if eligible:
            snapshot = _apply_express_vip_adjustments(
                snapshot=snapshot,
                express_row=express_row,
                fina_row=fina_row,
                income_row=income_row,
            )
            snapshot["express_apply_reason"] = reason
            snapshot["express_block_reason"] = None
        else:
            snapshot["express_block_reason"] = reason
    return snapshot


def estimate_market_value(
    ts_code,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """市价法：直接返回当前总市值。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code=ts_code,
        trade_date=trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    result = {
        "method": "market_cap",
        "ts_code": ts_code,
        "equity_value": snapshot["market_cap"],
        "market_cap": snapshot["market_cap"],
        "close_price": snapshot["close_price"],
        "trade_date": snapshot["trade_date"],
    }
    return _with_price_info(result, snapshot)


def estimate_by_pe(
    ts_code,
    peer_pe=None,
    target_pe=None,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """PE估值：股权价值 = 净利润 × 目标PE。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    applied_pe = target_pe if target_pe is not None else peer_pe
    if applied_pe is None:
        applied_pe = snapshot["pe_ttm"]
    if snapshot["netprofit"] is None or applied_pe in (None, 0):
        raise ValueError("PE valuation requires netprofit and target PE.")

    equity_value = snapshot["netprofit"] * applied_pe
    result = {
        "method": "pe",
        "ts_code": ts_code,
        "equity_value": equity_value,
        "netprofit": snapshot["netprofit"],
        "applied_multiple": applied_pe,
        "current_multiple": snapshot["pe_ttm"],
    }
    return _with_price_info(result, snapshot)


def estimate_by_ps(
    ts_code,
    peer_ps=None,
    target_ps=None,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """PS估值：股权价值 = 营收 × 目标PS。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    applied_ps = target_ps if target_ps is not None else peer_ps
    if applied_ps is None:
        applied_ps = snapshot["ps_ttm"]
    if snapshot["revenue"] is None or applied_ps in (None, 0):
        raise ValueError("PS valuation requires revenue and target PS.")

    equity_value = snapshot["revenue"] * applied_ps
    result = {
        "method": "ps",
        "ts_code": ts_code,
        "equity_value": equity_value,
        "revenue": snapshot["revenue"],
        "applied_multiple": applied_ps,
        "current_multiple": snapshot["ps_ttm"],
    }
    return _with_price_info(result, snapshot)


def estimate_by_pb(
    ts_code,
    peer_pb=None,
    target_pb=None,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """PB估值：股权价值 = 净资产 × 目标PB。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    applied_pb = target_pb if target_pb is not None else peer_pb
    if applied_pb is None:
        applied_pb = snapshot["pb"]
    if snapshot["equity_book_value"] is None or applied_pb in (None, 0):
        raise ValueError("PB valuation requires equity_book_value and target PB.")

    equity_value = snapshot["equity_book_value"] * applied_pb
    result = {
        "method": "pb",
        "ts_code": ts_code,
        "equity_value": equity_value,
        "equity_book_value": snapshot["equity_book_value"],
        "applied_multiple": applied_pb,
        "current_multiple": snapshot["pb"],
    }
    return _with_price_info(result, snapshot)


SW_HISTORY_DEFAULT_YEARS = (3, 5, 10)
SW_HISTORY_DEFAULT_QUANTILE = 0.5
SW_HISTORY_DEFAULT_MIN_SAMPLES = 120


def _normalize_sw_history_years(history_years):
    if history_years in (None, ""):
        return SW_HISTORY_DEFAULT_YEARS

    if isinstance(history_years, str):
        items = [item.strip() for item in history_years.split(",") if item.strip()]
    elif isinstance(history_years, (list, tuple, set)):
        items = list(history_years)
    else:
        items = [history_years]

    normalized = []
    for item in items:
        try:
            years = int(item)
        except (TypeError, ValueError):
            continue
        if years > 0:
            normalized.append(years)

    return tuple(sorted(set(normalized))) or SW_HISTORY_DEFAULT_YEARS


def _resolve_sw_history_trade_date(trade_date, snapshot_trade_date):
    candidate = trade_date or snapshot_trade_date
    if candidate is None:
        raise ValueError("SW historical valuation requires a valid trade date.")

    if isinstance(candidate, datetime):
        return candidate.strftime("%Y%m%d")
    if isinstance(candidate, date):
        return candidate.strftime("%Y%m%d")

    text = str(candidate).replace("-", "").strip()
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid trade_date for SW historical valuation: {candidate}")
    return text


def _resolve_sw_history_context(
    ts_code,
    trade_date,
    market="CN",
    token=None,
    pro=None,
    history_years=None,
    history_quantile=SW_HISTORY_DEFAULT_QUANTILE,
    history_min_samples=SW_HISTORY_DEFAULT_MIN_SAMPLES,
):
    effective_pro = pro or get_tushare_pro(token=token)
    base_dir = Path(settings.BASE_DIR) / "static"
    cfg = ValuationConfig(base_dir, market=market)
    sw_info = cfg.get_sw_params_by_tscode(ts_code)
    industry_code = sw_info.get("industry_code")
    if not industry_code:
        raise ValueError(f"未找到 {ts_code} 的申万行业编码，无法计算行业历史估值。")

    history_service = SwHistoryQuantileService(
        pro=effective_pro,
        window_years=_normalize_sw_history_years(history_years),
        quantile=(
            SW_HISTORY_DEFAULT_QUANTILE if history_quantile is None else float(history_quantile)
        ),
        min_samples=(
            SW_HISTORY_DEFAULT_MIN_SAMPLES
            if history_min_samples is None
            else int(history_min_samples)
        ),
    )
    history_payload = history_service.build_history_payload(industry_code, trade_date)
    return {
        "sw_info": sw_info,
        "history_payload": history_payload,
    }


def _median_value(values):
    normalized = []
    for value in values:
        if value is None:
            continue
        try:
            value_float = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value_float):
            normalized.append(value_float)
    if not normalized:
        return None
    normalized.sort()
    mid = len(normalized) // 2
    if len(normalized) % 2 == 1:
        return normalized[mid]
    return (normalized[mid - 1] + normalized[mid]) / 2


def _build_sw_history_variant(history_windows, history_quantile, history_min_samples):
    years = []
    for item in history_windows or []:
        text = str(item or "").strip().lower()
        if text.endswith("y"):
            text = text[:-1]
        if text.isdigit():
            years.append(int(text))
    years = sorted(set(years))
    years_text = "-".join(str(y) for y in years) if years else "na"

    quantile_value = SW_HISTORY_DEFAULT_QUANTILE if history_quantile is None else float(history_quantile)
    quantile_text = f"q{int(round(quantile_value * 100))}"
    min_samples_value = (
        SW_HISTORY_DEFAULT_MIN_SAMPLES if history_min_samples is None else int(history_min_samples)
    )
    return f"hist_y{years_text}_{quantile_text}_m{min_samples_value}"[:128]


def _build_sw_history_component_rows(snapshot, sw_history_result):
    if not isinstance(sw_history_result, dict):
        return []

    component_implied_prices = sw_history_result.get("component_implied_prices") or {}
    component_target_multiples = sw_history_result.get("component_target_multiples") or {}
    industry_code = sw_history_result.get("industry_code")
    industry_name = sw_history_result.get("industry_name")
    history_windows = sw_history_result.get("history_windows") or []
    history_quantile = sw_history_result.get("history_quantile")
    history_min_samples = sw_history_result.get("history_min_samples")
    variant = _build_sw_history_variant(history_windows, history_quantile, history_min_samples)

    base_payload = {
        "ts_code": sw_history_result.get("ts_code"),
        "valuation_variant": variant,
        "compare_group": "sw_history_anchor",
        "industry_level": "L3" if industry_code else None,
        "industry_code": industry_code,
        "industry_name": industry_name,
        "target_source": "sw_history_anchor_component",
        "history_windows": history_windows,
        "history_quantile": history_quantile,
        "history_min_samples": history_min_samples,
    }

    rows = []
    for method in ["pe", "pb", "ps"]:
        implied_price = component_implied_prices.get(method)
        target_multiple = component_target_multiples.get(method)
        if implied_price is None or target_multiple in (None, 0):
            continue

        total_share = snapshot.get("total_share")
        equity_value = None
        if total_share not in (None, 0):
            equity_value = float(implied_price) * float(total_share)

        current_multiple = None
        if method == "pe":
            current_multiple = snapshot.get("pe_ttm")
        elif method == "pb":
            current_multiple = snapshot.get("pb")
        elif method == "ps":
            current_multiple = snapshot.get("ps_ttm")

        rows.append(
            {
                "method": method,
                "equity_value": equity_value,
                "implied_price": float(implied_price),
                "applied_multiple": float(target_multiple),
                "current_multiple": current_multiple,
                **base_payload,
            }
        )

    return rows


def estimate_by_sw_history(
    ts_code,
    trade_date=None,
    token=None,
    pro=None,
    market="CN",
    history_years=None,
    history_quantile=SW_HISTORY_DEFAULT_QUANTILE,
    history_min_samples=SW_HISTORY_DEFAULT_MIN_SAMPLES,
    strict_express_match=True,
    express_max_age_days=180,
):
    """申万行业历史估值：用行业历史分位锚点生成目标倍数，再聚合为单一估值结果。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    effective_trade_date = _resolve_sw_history_trade_date(trade_date, snapshot.get("trade_date"))
    context = _resolve_sw_history_context(
        ts_code=ts_code,
        trade_date=effective_trade_date,
        market=market,
        token=token,
        pro=pro,
        history_years=history_years,
        history_quantile=history_quantile,
        history_min_samples=history_min_samples,
    )

    sw_info = context.get("sw_info") or {}
    history_payload = context.get("history_payload") or {}
    anchors = history_payload.get("anchors") or {}

    component_rows = []

    pe_anchor = anchors.get("pe")
    if snapshot.get("netprofit") is not None and pe_anchor not in (None, 0):
        pe_equity_value = snapshot.get("netprofit") * pe_anchor
        component_rows.append(
            {
                "method": "pe",
                "target_multiple": float(pe_anchor),
                "equity_value": pe_equity_value,
                "implied_price": _equity_value_to_price(pe_equity_value, snapshot.get("total_share")),
            }
        )

    pb_anchor = anchors.get("pb")
    if snapshot.get("equity_book_value") is not None and pb_anchor not in (None, 0):
        pb_equity_value = snapshot.get("equity_book_value") * pb_anchor
        component_rows.append(
            {
                "method": "pb",
                "target_multiple": float(pb_anchor),
                "equity_value": pb_equity_value,
                "implied_price": _equity_value_to_price(pb_equity_value, snapshot.get("total_share")),
            }
        )

    ps_anchor = anchors.get("ps")
    if snapshot.get("revenue") is not None and ps_anchor not in (None, 0):
        ps_equity_value = snapshot.get("revenue") * ps_anchor
        component_rows.append(
            {
                "method": "ps",
                "target_multiple": float(ps_anchor),
                "equity_value": ps_equity_value,
                "implied_price": _equity_value_to_price(ps_equity_value, snapshot.get("total_share")),
            }
        )

    component_prices = [row.get("implied_price") for row in component_rows]
    composite_price = _median_value(component_prices)
    if composite_price is None:
        raise ValueError("SW historical valuation requires at least one valid PE/PB/PS historical anchor.")

    total_share = snapshot.get("total_share")
    composite_equity_value = (
        composite_price * total_share if total_share not in (None, 0) else _median_value([row.get("equity_value") for row in component_rows])
    )

    return {
        "method": "sw_history",
        "ts_code": ts_code,
        "equity_value": composite_equity_value,
        "total_share": total_share,
        "implied_price": composite_price,
        "industry_code": sw_info.get("industry_code"),
        "industry_name": sw_info.get("industry_name"),
        "history_windows": history_payload.get("windows"),
        "history_quantile": history_payload.get("quantile"),
        "history_min_samples": history_payload.get("min_samples"),
        "valuation_variant": _build_sw_history_variant(
            history_payload.get("windows"),
            history_payload.get("quantile"),
            history_payload.get("min_samples"),
        ),
        "compare_group": "sw_history_anchor",
        "industry_level": "L3" if sw_info.get("industry_code") else None,
        "history_targets": anchors,
        "history_target_pe": pe_anchor,
        "history_target_pb": pb_anchor,
        "history_target_ps": ps_anchor,
        "component_methods": [row.get("method") for row in component_rows],
        "component_count": len(component_rows),
        "component_implied_prices": {
            row.get("method"): round(float(row.get("implied_price")), 4)
            for row in component_rows
            if row.get("implied_price") is not None
        },
        "component_target_multiples": {
            row.get("method"): row.get("target_multiple") for row in component_rows
        },
        "target_source": "sw_history_anchor_median",
    }


def estimate_by_peg(
    ts_code,
    target_peg=1.0,
    growth_rate_pct=None,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """PEG估值：目标PE = 目标PEG × 利润增速(%)。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    growth_pct = (
        growth_rate_pct
        if growth_rate_pct is not None
        else snapshot["peg_growth_yoy_pct"]
    )
    peg_inputs = _resolve_peg_inputs(target_peg=target_peg, growth_pct=growth_pct)

    result = estimate_by_pe(
        ts_code=ts_code,
        target_pe=peg_inputs["derived_target_pe"],
        trade_date=trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    result.update(
        {
            "method": "peg",
            **peg_inputs,
        }
    )
    return result


def estimate_by_ev_ebitda(
    ts_code,
    target_ev_ebitda,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """EV/EBITDA估值：股权价值 = EBITDA × EV/EBITDA - 债务 + 现金。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    if snapshot["ebitda"] in (None, 0):
        raise ValueError("EV/EBITDA valuation requires EBITDA.")

    enterprise_value = snapshot["ebitda"] * target_ev_ebitda
    equity_value = enterprise_value - snapshot["debt"] + snapshot["cash"]
    result = {
        "method": "ev_ebitda",
        "ts_code": ts_code,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "ebitda": snapshot["ebitda"],
        "target_ev_ebitda": target_ev_ebitda,
        "cash": snapshot["cash"],
        "debt": snapshot["debt"],
    }
    return _with_price_info(result, snapshot)


def estimate_by_fcff_dcf(
    ts_code,
    forecast_fcff=None,
    base_fcff=None,
    growth_rates=None,
    discount_rate=0.1,
    terminal_growth_rate=0.03,
    net_debt=None,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """FCFF-DCF估值。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    if forecast_fcff is None:
        starting_fcff = base_fcff if base_fcff is not None else snapshot["fcff"]
        if starting_fcff is None:
            raise ValueError("FCFF-DCF requires forecast_fcff or base_fcff/fcff.")
        growth_rates = growth_rates or [0.08, 0.06, 0.05, 0.04, 0.03]
        forecast_fcff = []
        current_fcff = starting_fcff
        for growth in growth_rates:
            current_fcff = current_fcff * (1 + growth)
            forecast_fcff.append(current_fcff)

    if discount_rate <= terminal_growth_rate:
        raise ValueError("discount_rate must be greater than terminal_growth_rate.")

    present_values = []
    for idx, fcff in enumerate(forecast_fcff, start=1):
        present_values.append(fcff / ((1 + discount_rate) ** idx))

    terminal_fcff = forecast_fcff[-1] * (1 + terminal_growth_rate)
    terminal_value = terminal_fcff / (discount_rate - terminal_growth_rate)
    terminal_pv = terminal_value / ((1 + discount_rate) ** len(forecast_fcff))

    enterprise_value = sum(present_values) + terminal_pv
    effective_net_debt = (
        net_debt
        if net_debt is not None
        else (snapshot["debt"] - snapshot["cash"])
    )
    equity_value = enterprise_value - effective_net_debt

    result = {
        "method": "fcff_dcf",
        "ts_code": ts_code,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "forecast_fcff": forecast_fcff,
        "discount_rate": discount_rate,
        "terminal_growth_rate": terminal_growth_rate,
        "terminal_value": terminal_value,
        "net_debt": effective_net_debt,
    }
    return _with_price_info(result, snapshot)


def estimate_by_ddm(
    ts_code,
    annual_dividend=None,
    discount_rate=0.1,
    dividend_growth_rate=0.03,
    stage_dividends=None,
    terminal_growth_rate=None,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """股利折现模型（支持 Gordon 或两阶段 DDM）。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    terminal_growth_rate = (
        dividend_growth_rate
        if terminal_growth_rate is None
        else terminal_growth_rate
    )

    if stage_dividends:
        present_values = [
            dividend / ((1 + discount_rate) ** idx)
            for idx, dividend in enumerate(stage_dividends, start=1)
        ]
        if discount_rate <= terminal_growth_rate:
            raise ValueError("discount_rate must be greater than terminal_growth_rate.")
        final_dividend = stage_dividends[-1] * (1 + terminal_growth_rate)
        terminal_value = final_dividend / (discount_rate - terminal_growth_rate)
        equity_value = sum(present_values) + terminal_value / (
            (1 + discount_rate) ** len(stage_dividends)
        )
        result = {
            "method": "ddm",
            "ts_code": ts_code,
            "equity_value": equity_value,
            "stage_dividends": stage_dividends,
            "discount_rate": discount_rate,
            "terminal_growth_rate": terminal_growth_rate,
        }
        return _with_price_info(result, snapshot)

    dividend_total = (
        annual_dividend if annual_dividend is not None else snapshot["annual_dividend"]
    )
    if dividend_total is None:
        raise ValueError("DDM requires annual_dividend or dividend data from tushare.")
    if discount_rate <= dividend_growth_rate:
        raise ValueError("discount_rate must be greater than dividend_growth_rate.")

    equity_value = dividend_total * (1 + dividend_growth_rate) / (
        discount_rate - dividend_growth_rate
    )
    result = {
        "method": "ddm",
        "ts_code": ts_code,
        "equity_value": equity_value,
        "annual_dividend": dividend_total,
        "discount_rate": discount_rate,
        "dividend_growth_rate": dividend_growth_rate,
    }
    return _with_price_info(result, snapshot)


def run_valuation_scenarios(model_func, scenarios, base_kwargs=None):
    """情景分析：按不同参数组合批量运行估值函数。"""

    base_kwargs = base_kwargs or {}
    results = []
    for scenario_name, scenario_kwargs in scenarios.items():
        merged_kwargs = {**base_kwargs, **scenario_kwargs}
        valuation = model_func(**merged_kwargs)
        valuation["scenario"] = scenario_name
        results.append(valuation)
    df = pd.DataFrame(results)
    summary = summarize_valuation_range(df)
    for key, value in summary.items():
        df[key] = value
    return df


def run_sensitivity_analysis(model_func, base_kwargs, variable_grid):
    """敏感性分析：逐个参数扰动后输出估值结果。"""

    records = []
    for variable_name, values in variable_grid.items():
        for value in values:
            kwargs = dict(base_kwargs)
            kwargs[variable_name] = value
            valuation = model_func(**kwargs)
            records.append(
                {
                    "variable": variable_name,
                    "value": value,
                    "method": valuation.get("method"),
                    "equity_value": valuation.get("equity_value"),
                    "enterprise_value": valuation.get("enterprise_value"),
                    "implied_price": valuation.get("implied_price"),
                    "total_share": valuation.get("total_share"),
                }
            )
    df = pd.DataFrame(records)
    summary = summarize_valuation_range(df)
    for key, value in summary.items():
        df[key] = value
    return df


def estimate_all_supported_methods(
    ts_code,
    trade_date=None,
    token=None,
    pro=None,
    pe_target=None,
    ps_target=None,
    pb_target=None,
    peg_target=1.0,
    ev_ebitda_target=None,
    dcf_kwargs=None,
    ddm_kwargs=None,
    sw_history_kwargs=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """统一汇总多种估值方法结果。"""

    snapshot = get_stock_valuation_snapshot(
        ts_code,
        trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    results = [
        estimate_market_value(
            ts_code,
            trade_date,
            token=token,
            pro=pro,
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
        )
    ]

    effective_target_pe = pe_target if pe_target is not None else snapshot.get("pe_ttm")
    if snapshot.get("netprofit") is not None and effective_target_pe not in (None, 0):
        results.append(
            estimate_by_pe(
                ts_code,
                target_pe=effective_target_pe,
                trade_date=trade_date,
                token=token,
                pro=pro,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
            )
        )
    if snapshot.get("revenue") is not None:
        results.append(
            estimate_by_ps(
                ts_code,
                target_ps=ps_target or snapshot.get("ps_ttm"),
                trade_date=trade_date,
                token=token,
                pro=pro,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
            )
        )
    if snapshot.get("equity_book_value") is not None:
        results.append(
            estimate_by_pb(
                ts_code,
                target_pb=pb_target or snapshot.get("pb"),
                trade_date=trade_date,
                token=token,
                pro=pro,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
            )
        )
    try:
        sw_history_result = estimate_by_sw_history(
            ts_code,
            trade_date=trade_date,
            token=token,
            pro=pro,
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
            **(sw_history_kwargs or {}),
        )
        results.append(sw_history_result)
        results.extend(_build_sw_history_component_rows(snapshot, sw_history_result))
    except ValueError:
        pass
    if snapshot.get("peg_growth_yoy_pct") not in (None, 0):
        try:
            results.append(
                estimate_by_peg(
                    ts_code,
                    target_peg=peg_target,
                    trade_date=trade_date,
                    token=token,
                    pro=pro,
                    strict_express_match=strict_express_match,
                    express_max_age_days=express_max_age_days,
                )
            )
        except ValueError as exc:
            results.append(
                {
                    "method": "peg",
                    "ts_code": ts_code,
                    "equity_value": None,
                    "implied_price": None,
                    "total_share": snapshot.get("total_share"),
                    "target_peg": peg_target,
                    "raw_growth_rate_pct": snapshot.get("peg_growth_yoy_pct"),
                    "growth_rate_pct": None,
                    "raw_target_pe": None,
                    "derived_target_pe": None,
                    "peg_quality_flag": "non_positive_growth_skipped",
                    "peg_skip_reason": str(exc),
                }
            )
    if ev_ebitda_target is not None and snapshot.get("ebitda") not in (None, 0):
        results.append(
            estimate_by_ev_ebitda(
                ts_code,
                target_ev_ebitda=ev_ebitda_target,
                trade_date=trade_date,
                token=token,
                pro=pro,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
            )
        )

    dcf_kwargs = dcf_kwargs or {}
    try:
        results.append(
            estimate_by_fcff_dcf(
                ts_code,
                trade_date=trade_date,
                token=token,
                pro=pro,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
                **dcf_kwargs,
            )
        )
    except ValueError:
        pass

    ddm_kwargs = ddm_kwargs or {}
    try:
        results.append(
            estimate_by_ddm(
                ts_code,
                trade_date=trade_date,
                token=token,
                pro=pro,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
                **ddm_kwargs,
            )
        )
    except ValueError:
        pass

    df = pd.DataFrame(results)
    if "equity_value" in df.columns:
        df["equity_value_亿元"] = df["equity_value"] / 100000000
    if "enterprise_value" in df.columns:
        df["enterprise_value_亿元"] = df["enterprise_value"] / 100000000
    summary = summarize_valuation_range(df, total_share=snapshot.get("total_share"))
    for key, value in summary.items():
        df[key] = value
    return df


def test_valuation(
    ts_code,
    trade_date=None,
    current_price=None,
    pro=None,
    pe_target=None,
    ps_target=None,
    pb_target=None,
    peg_target=1.0,
    ev_ebitda_target=None,
    dcf_kwargs=None,
    ddm_kwargs=None,
    sw_history_kwargs=None,
    scenario_model="fcff_dcf",
    scenario_overrides=None,
    sensitivity_grid=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    """示例封装：统一输出股票估值明细、估值区间、价格区间、情景分析和敏感性分析。

    Returns:
        dict: {
            "snapshot": ...,
            "valuations": DataFrame,
            "formatted_range": dict,
            "scenario_analysis": DataFrame | None,
            "sensitivity_analysis": DataFrame | None,
        }
    """

    snapshot = get_stock_valuation_snapshot(
        ts_code=ts_code,
        trade_date=trade_date,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    resolved_current_price = (
        current_price if current_price is not None else snapshot.get("close_price")
    )

    dcf_kwargs = dcf_kwargs or {}
    ddm_kwargs = ddm_kwargs or {}

    valuations = estimate_all_supported_methods(
        ts_code=ts_code,
        trade_date=trade_date,
        pro=pro,
        pe_target=pe_target,
        ps_target=ps_target,
        pb_target=pb_target,
        peg_target=peg_target,
        ev_ebitda_target=ev_ebitda_target,
        dcf_kwargs=dcf_kwargs,
        ddm_kwargs=ddm_kwargs,
        sw_history_kwargs=sw_history_kwargs,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )

    formatted_range = format_valuation_range_output(
        valuations,
        total_share=snapshot.get("total_share"),
        current_price=resolved_current_price,
    )

    scenario_analysis = None
    scenario_model_map = {
        "fcff_dcf": estimate_by_fcff_dcf,
        "ddm": estimate_by_ddm,
        "pe": estimate_by_pe,
        "ps": estimate_by_ps,
        "pb": estimate_by_pb,
        "ev_ebitda": estimate_by_ev_ebitda,
    }
    scenario_func = scenario_model_map.get(scenario_model)

    base_kwargs_map = {
        "fcff_dcf": {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "pro": pro,
            "strict_express_match": strict_express_match,
            "express_max_age_days": express_max_age_days,
            **dcf_kwargs,
        },
        "ddm": {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "pro": pro,
            "strict_express_match": strict_express_match,
            "express_max_age_days": express_max_age_days,
            **ddm_kwargs,
        },
        "pe": {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "pro": pro,
            "strict_express_match": strict_express_match,
            "express_max_age_days": express_max_age_days,
            "target_pe": pe_target or snapshot.get("pe_ttm"),
        },
        "ps": {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "pro": pro,
            "strict_express_match": strict_express_match,
            "express_max_age_days": express_max_age_days,
            "target_ps": ps_target or snapshot.get("ps_ttm"),
        },
        "pb": {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "pro": pro,
            "strict_express_match": strict_express_match,
            "express_max_age_days": express_max_age_days,
            "target_pb": pb_target or snapshot.get("pb"),
        },
        "ev_ebitda": {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "pro": pro,
            "strict_express_match": strict_express_match,
            "express_max_age_days": express_max_age_days,
            "target_ev_ebitda": ev_ebitda_target,
        },
    }

    if scenario_func is not None:
        default_scenarios = {
            "bear": {},
            "base": {},
            "bull": {},
        }
        if scenario_model == "fcff_dcf":
            default_scenarios = {
                "bear": {
                    "discount_rate": dcf_kwargs.get("discount_rate", 0.11),
                    "terminal_growth_rate": dcf_kwargs.get("terminal_growth_rate", 0.02),
                    "growth_rates": dcf_kwargs.get("growth_rates", [0.05, 0.04, 0.03, 0.03, 0.02]),
                },
                "base": {
                    "discount_rate": dcf_kwargs.get("discount_rate", 0.1),
                    "terminal_growth_rate": dcf_kwargs.get("terminal_growth_rate", 0.03),
                    "growth_rates": dcf_kwargs.get("growth_rates", [0.08, 0.06, 0.05, 0.04, 0.03]),
                },
                "bull": {
                    "discount_rate": dcf_kwargs.get("discount_rate", 0.09),
                    "terminal_growth_rate": dcf_kwargs.get("terminal_growth_rate", 0.04),
                    "growth_rates": dcf_kwargs.get("growth_rates", [0.12, 0.10, 0.08, 0.06, 0.05]),
                },
            }
        elif scenario_model == "ddm":
            default_scenarios = {
                "bear": {
                    "discount_rate": ddm_kwargs.get("discount_rate", 0.11),
                    "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.01),
                },
                "base": {
                    "discount_rate": ddm_kwargs.get("discount_rate", 0.1),
                    "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.03),
                },
                "bull": {
                    "discount_rate": ddm_kwargs.get("discount_rate", 0.09),
                    "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.05),
                },
            }
        elif scenario_model == "pe":
            base_pe = pe_target or snapshot.get("pe_ttm")
            if base_pe is not None:
                default_scenarios = {
                    "bear": {"target_pe": base_pe * 0.85},
                    "base": {"target_pe": base_pe},
                    "bull": {"target_pe": base_pe * 1.15},
                }
        elif scenario_model == "ps":
            base_ps = ps_target or snapshot.get("ps_ttm")
            if base_ps is not None:
                default_scenarios = {
                    "bear": {"target_ps": base_ps * 0.85},
                    "base": {"target_ps": base_ps},
                    "bull": {"target_ps": base_ps * 1.15},
                }
        elif scenario_model == "pb":
            base_pb = pb_target or snapshot.get("pb")
            if base_pb is not None:
                default_scenarios = {
                    "bear": {"target_pb": base_pb * 0.85},
                    "base": {"target_pb": base_pb},
                    "bull": {"target_pb": base_pb * 1.15},
                }
        elif scenario_model == "ev_ebitda" and ev_ebitda_target is not None:
            default_scenarios = {
                "bear": {"target_ev_ebitda": ev_ebitda_target * 0.85},
                "base": {"target_ev_ebitda": ev_ebitda_target},
                "bull": {"target_ev_ebitda": ev_ebitda_target * 1.15},
            }

        scenarios = scenario_overrides or default_scenarios
        try:
            scenario_analysis = run_valuation_scenarios(
                scenario_func,
                scenarios=scenarios,
                base_kwargs=base_kwargs_map.get(scenario_model, {}),
            )
        except ValueError:
            scenario_analysis = None

    sensitivity_analysis = None
    if sensitivity_grid:
        try:
            sensitivity_analysis = run_sensitivity_analysis(
                scenario_func or estimate_by_fcff_dcf,
                base_kwargs=base_kwargs_map.get(
                    scenario_model,
                    {
                        "ts_code": ts_code,
                        "trade_date": trade_date,
                        "pro": pro,
                        **dcf_kwargs,
                    },
                ),
                variable_grid=sensitivity_grid,
            )
        except ValueError:
            sensitivity_analysis = None

    return {
        "snapshot": snapshot,
        "valuations": valuations,
        "formatted_range": formatted_range,
        "scenario_analysis": scenario_analysis,
        "sensitivity_analysis": sensitivity_analysis,
    }


def demo_valuation_for_pingan(trade_date=None, pro=None):
    """最小示例：以平安银行 000001.SZ 演示完整估值流程。"""

    return test_valuation(
        ts_code="000001.SZ",
        trade_date=trade_date,
        pro=pro,
        pe_target=6.5,
        ps_target=1.2,
        pb_target=0.7,
        peg_target=0.9,
        ev_ebitda_target=5.5,
        dcf_kwargs={
            "discount_rate": 0.10,
            "terminal_growth_rate": 0.03,
            "growth_rates": [0.08, 0.06, 0.05, 0.04, 0.03],
        },
        ddm_kwargs={
            "discount_rate": 0.10,
            "dividend_growth_rate": 0.03,
        },
        scenario_model="fcff_dcf",
        sensitivity_grid={
            "discount_rate": [0.09, 0.10, 0.11],
            "terminal_growth_rate": [0.02, 0.03, 0.04],
        },
    )


