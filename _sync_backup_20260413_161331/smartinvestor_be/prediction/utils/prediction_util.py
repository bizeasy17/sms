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


def _filter_financial_frame_asof(df, trade_date=None):
    if df is None or df.empty or trade_date is None:
        return df

    cutoff = _normalize_date_text(trade_date)
    if len(cutoff) != 8 or not cutoff.isdigit():
        return df

    ann_col = None
    for candidate in ["ann_date", "f_ann_date"]:
        if candidate in df.columns:
            ann_col = candidate
            break
    if ann_col is None:
        return df

    ann_series = df[ann_col].map(_normalize_date_text)
    visible_mask = ann_series.eq("") | ann_series.le(cutoff)
    filtered = df[visible_mask].copy()
    return filtered if not filtered.empty else df


def _filter_financial_frames_asof(frames, trade_date=None):
    if not isinstance(frames, dict) or trade_date is None:
        return frames

    filtered = dict(frames)
    for key in ["fina_indicator", "income", "balancesheet", "cashflow", "dividend", "express_vip"]:
        filtered[key] = _filter_financial_frame_asof(filtered.get(key), trade_date=trade_date)
    return filtered


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


def _record_for_end_date(df, end_date, sort_cols=None):
    if df is None or df.empty or not end_date or "end_date" not in df.columns:
        return {}

    target = _normalize_date_text(end_date)
    if not target:
        return {}

    matched = df[df["end_date"].map(_normalize_date_text).eq(target)].copy()
    if matched.empty:
        return {}

    return _latest_record(matched, sort_cols or ["end_date", "ann_date", "f_ann_date"])


def _previous_year_end_date(report_end):
    text = _normalize_date_text(report_end)
    if len(text) != 8 or not text.isdigit():
        return None
    return f"{int(text[:4]) - 1:04d}1231"


def _same_period_last_year_end_date(report_end):
    text = _normalize_date_text(report_end)
    if len(text) != 8 or not text.isdigit():
        return None
    return f"{int(text[:4]) - 1:04d}{text[4:]}"


def _simple_annualization_factor(report_end):
    text = _normalize_date_text(report_end)
    if len(text) != 8 or not text.isdigit() or text.endswith("1231"):
        return 1.0
    try:
        month = int(text[4:6])
    except ValueError:
        month = 12
    month = max(1, min(month, 12))
    return 12.0 / month


def _resolve_ttm_flow_value(current_value, report_end, previous_annual_value=None, previous_same_period_value=None):
    if current_value is None:
        return None, None, "missing_current"

    text = _normalize_date_text(report_end)
    if len(text) != 8 or not text.isdigit() or text.endswith("1231"):
        return current_value, 1.0, "full_year"

    if previous_annual_value is not None and previous_same_period_value is not None:
        return current_value + previous_annual_value - previous_same_period_value, None, "ttm"

    factor = _simple_annualization_factor(text)
    return current_value * factor, factor, "simple_annualized"


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


def _apply_express_vip_adjustments(snapshot, express_row, fina_row=None, income_row=None, frames=None):
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
    income_df = (frames or {}).get("income") if isinstance(frames, dict) else None
    prev_annual_income_row = _record_for_end_date(
        income_df,
        _previous_year_end_date(period_end),
        ["end_date", "ann_date", "f_ann_date"],
    )
    prev_same_income_row = _record_for_end_date(
        income_df,
        _same_period_last_year_end_date(period_end),
        ["end_date", "ann_date", "f_ann_date"],
    )
    express_netprofit, express_netprofit_factor, express_netprofit_method = _resolve_ttm_flow_value(
        express_netprofit,
        period_end,
        previous_annual_value=_pick_value(
            prev_annual_income_row,
            ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"],
        ),
        previous_same_period_value=_pick_value(
            prev_same_income_row,
            ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"],
        ),
    )
    express_revenue, express_revenue_factor, express_revenue_method = _resolve_ttm_flow_value(
        express_revenue,
        period_end,
        previous_annual_value=_pick_value(
            prev_annual_income_row,
            ["revenue", "total_revenue", "oper_rev"],
        ),
        previous_same_period_value=_pick_value(
            prev_same_income_row,
            ["revenue", "total_revenue", "oper_rev"],
        ),
    )
    primary_annualization_method = express_netprofit_method or express_revenue_method or snapshot.get("annualization_method")
    primary_annualization_factor = express_netprofit_factor if express_netprofit is not None else express_revenue_factor

    if express_netprofit is not None:
        adjusted["netprofit"] = _blend_preferred(express_netprofit, adjusted.get("netprofit"), alpha=0.7)
    if express_revenue is not None:
        adjusted["revenue"] = _blend_preferred(express_revenue, adjusted.get("revenue"), alpha=0.7)

    adjusted["express_end_date"] = _normalize_date_text(express_row.get("end_date")) or None
    adjusted["express_ann_date"] = _normalize_date_text(express_row.get("ann_date")) or None
    adjusted["annualization_method"] = primary_annualization_method
    adjusted["annualization_factor"] = primary_annualization_factor
    adjusted["profit_data_source"] = "express_vip"
    if not _is_more_recent_period(express_row, fina_row or income_row):
        # Same-period quick report still improves timeliness but mark as blended to indicate caution.
        adjusted["profit_data_source"] = "express_vip_blended"

    return adjusted



from prediction.utils import valuation_util as _valuation_util


get_stock_valuation_snapshot = _valuation_util.get_stock_valuation_snapshot
estimate_market_value = _valuation_util.estimate_market_value
estimate_by_pe = _valuation_util.estimate_by_pe
estimate_by_ps = _valuation_util.estimate_by_ps
estimate_by_pb = _valuation_util.estimate_by_pb
estimate_by_sw_history = _valuation_util.estimate_by_sw_history
estimate_by_peg = _valuation_util.estimate_by_peg
estimate_by_ev_ebitda = _valuation_util.estimate_by_ev_ebitda
estimate_by_fcff_dcf = _valuation_util.estimate_by_fcff_dcf
estimate_by_ddm = _valuation_util.estimate_by_ddm
estimate_all_supported_methods = _valuation_util.estimate_all_supported_methods
summarize_valuation_range = _valuation_util.summarize_valuation_range
format_valuation_range_output = _valuation_util.format_valuation_range_output
run_valuation_scenarios = _valuation_util.run_valuation_scenarios
run_sensitivity_analysis = _valuation_util.run_sensitivity_analysis
test_valuation = _valuation_util.test_valuation
test_valuation_light = _valuation_util.test_valuation_light
demo_valuation_for_pingan = _valuation_util.demo_valuation_for_pingan

