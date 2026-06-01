import math

import pandas as pd
from django.conf import settings
from valuation.services.analysis_tools import (
    format_valuation_range_output as _format_valuation_range_output_impl,
    run_sensitivity_analysis as _run_sensitivity_analysis_impl,
    run_valuation_scenarios as _run_valuation_scenarios_impl,
    summarize_valuation_range as _summarize_valuation_range_impl,
)
from valuation.services.snapshot_provider import (
    fetch_local_financial_frames as _fetch_local_financial_frames_impl,
    fetch_tushare_frames as _fetch_tushare_frames_impl,
    filter_financial_frame_asof as _filter_financial_frame_asof_impl,
    filter_financial_frames_asof as _filter_financial_frames_asof_impl,
    get_tushare_pro as _get_tushare_pro_impl,
    latest_record as _latest_record_impl,
    normalize_date_text as _normalize_date_text_impl,
    parse_date_yyyymmdd as _parse_date_yyyymmdd_impl,
    pick_value as _pick_value_impl,
    query_local_financial_df as _query_local_financial_df_impl,
    record_for_end_date as _record_for_end_date_impl,
    safe_float as _safe_float_impl,
)
from valuation.services.sw_scarcity_tools import (
    SW_HISTORY_DEFAULT_MIN_SAMPLES,
    SW_HISTORY_DEFAULT_QUANTILE,
    build_scarcity_overlay_row as _build_scarcity_overlay_row_impl,
    build_sw_history_component_rows as _build_sw_history_component_rows_impl,
    build_sw_history_variant as _build_sw_history_variant_impl,
    median_value as _median_value_impl,
    normalize_sw_history_years as _normalize_sw_history_years_impl,
    resolve_scarcity_inputs as _resolve_scarcity_inputs_impl,
    resolve_sw_history_context as _resolve_sw_history_context_impl,
    resolve_sw_history_trade_date as _resolve_sw_history_trade_date_impl,
    select_scarcity_base_row as _select_scarcity_base_row_impl,
)


PEG_MIN_GROWTH_PCT = 5.0
PEG_MAX_GROWTH_PCT = 80.0
PEG_MIN_TARGET_PE = 5.0
PEG_MAX_TARGET_PE = 45.0


def get_tushare_pro(token=None):
    return _get_tushare_pro_impl(token=token)


def _safe_float(value, default=None):
    return _safe_float_impl(value, default=default)


def _pick_value(row, candidates, default=None):
    return _pick_value_impl(row, candidates, default=default, safe_float_func=_safe_float)


def _latest_record(df, sort_cols=None):
    return _latest_record_impl(df, sort_cols=sort_cols)


def _filter_financial_frame_asof(df, trade_date=None):
    return _filter_financial_frame_asof_impl(
        df,
        trade_date=trade_date,
        normalize_date_text_func=_normalize_date_text,
    )


def _filter_financial_frames_asof(frames, trade_date=None):
    return _filter_financial_frames_asof_impl(
        frames,
        trade_date=trade_date,
        filter_financial_frame_asof_func=_filter_financial_frame_asof,
    )


def _frame_row_count(frame):
    if frame is None:
        return 0
    try:
        return int(len(frame.index))
    except Exception:
        return 0


def _summarize_frame_counts(frames):
    names = ["daily_basic", "fina_indicator", "income", "balancesheet", "cashflow", "dividend", "express_vip"]
    return {name: _frame_row_count((frames or {}).get(name)) for name in names}


def _normalize_date_text(value):
    return _normalize_date_text_impl(value)


def _parse_date_yyyymmdd(value):
    return _parse_date_yyyymmdd_impl(value)


def _record_for_end_date(df, end_date, sort_cols=None):
    return _record_for_end_date_impl(
        df,
        end_date,
        sort_cols=sort_cols,
        normalize_date_text_func=_normalize_date_text,
        latest_record_func=_latest_record,
    )


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


def _resolve_report_type_from_end_date(report_end):
    text = _normalize_date_text(report_end)
    if len(text) != 8:
        return None
    suffix = text[4:]
    if suffix == "0331":
        return "Q1"
    if suffix == "0630":
        return "H1"
    if suffix == "0930":
        return "Q3"
    if suffix == "1231":
        return "ANNUAL"
    return "OTHER"


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


def _is_express_vip_eligible(express_row, fina_row, income_row, trade_date, strict_match=True, max_age_days=180):
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

    base_end_candidates = [_parse_date_yyyymmdd((fina_row or {}).get("end_date")), _parse_date_yyyymmdd((income_row or {}).get("end_date"))]
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
    direct_growth = _pick_value(express_row, ["yoy_dedu_np", "yoy_np", "yoy_sales", "tr_yoy", "or_yoy", "netprofit_yoy"])
    if direct_growth is not None and abs(direct_growth) <= 1000:
        return direct_growth

    yoy_net_profit = _pick_value(express_row, ["yoy_net_profit"])
    if yoy_net_profit is not None and abs(yoy_net_profit) > 1000:
        current_netprofit = _pick_value(express_row, ["n_income_attr_p", "n_income", "net_profit", "profit_dedt", "deduct_np"])
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

    express_netprofit = _pick_value(express_row, ["n_income_attr_p", "n_income", "net_profit", "profit_dedt", "deduct_np"])
    express_revenue = _pick_value(express_row, ["revenue", "total_revenue", "oper_rev"])

    period_end = _normalize_date_text(express_row.get("end_date"))
    income_df = (frames or {}).get("income") if isinstance(frames, dict) else None
    prev_annual_income_row = _record_for_end_date(income_df, _previous_year_end_date(period_end), ["end_date", "ann_date", "f_ann_date"])
    prev_same_income_row = _record_for_end_date(income_df, _same_period_last_year_end_date(period_end), ["end_date", "ann_date", "f_ann_date"])
    express_netprofit, express_netprofit_factor, express_netprofit_method = _resolve_ttm_flow_value(
        express_netprofit,
        period_end,
        previous_annual_value=_pick_value(prev_annual_income_row, ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"]),
        previous_same_period_value=_pick_value(prev_same_income_row, ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"]),
    )
    express_revenue, express_revenue_factor, express_revenue_method = _resolve_ttm_flow_value(
        express_revenue,
        period_end,
        previous_annual_value=_pick_value(prev_annual_income_row, ["revenue", "total_revenue", "oper_rev"]),
        previous_same_period_value=_pick_value(prev_same_income_row, ["revenue", "total_revenue", "oper_rev"]),
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
        adjusted["profit_data_source"] = "express_vip_blended"

    return adjusted


def _fetch_tushare_frames(ts_code, trade_date=None, pro=None):
    return _fetch_tushare_frames_impl(
        ts_code,
        trade_date=trade_date,
        pro=pro,
        get_tushare_pro_func=get_tushare_pro,
    )


def _query_local_financial_df(sql, params, db_alias=None):
    return _query_local_financial_df_impl(sql, params, db_alias=db_alias)


def _fetch_local_financial_frames(ts_code, trade_date=None, forced_report_end_date=None):
    return _fetch_local_financial_frames_impl(
        ts_code,
        trade_date=trade_date,
        forced_report_end_date=forced_report_end_date,
        parse_date_yyyymmdd_func=_parse_date_yyyymmdd,
        safe_float_func=_safe_float,
        query_local_financial_df_func=_query_local_financial_df,
    )


def _calc_ebitda_and_ebit_from_rows(fina_row=None, income_row=None, cashflow_row=None):
    ebitda = _pick_value(fina_row or {}, ["ebitda", "ebitda2"])
    if ebitda in (None, 0):
        operating_income = _pick_value(income_row or {}, ["operate_profit", "op_income"])
        depreciation = _pick_value(fina_row or {}, ["depr"], 0.0)
        amortization = _pick_value(fina_row or {}, ["amortization"], 0.0)
        if depreciation == 0.0:
            depreciation = _pick_value(income_row or {}, ["depr"], 0.0)
        if amortization == 0.0:
            amortization = _pick_value(income_row or {}, ["amortization"], 0.0)
        if depreciation == 0.0:
            depreciation = _pick_value(cashflow_row or {}, ["depr_fa_coga_dpba"], 0.0)
        if amortization == 0.0:
            amortization = _pick_value(cashflow_row or {}, ["amort_intang_assets"], 0.0)
        if operating_income is not None:
            ebitda = operating_income + depreciation + amortization

    ebit = _pick_value(fina_row or {}, ["ebit", "ebit2"])
    if ebit in (None, 0):
        ebit = _pick_value(income_row or {}, ["operate_profit", "op_income"])
        if ebit is None and ebitda is not None:
            depreciation = _pick_value(fina_row or {}, ["depr"], 0.0)
            amortization = _pick_value(fina_row or {}, ["amortization"], 0.0)
            if depreciation == 0.0:
                depreciation = _pick_value(income_row or {}, ["depr"], 0.0)
            if amortization == 0.0:
                amortization = _pick_value(income_row or {}, ["amortization"], 0.0)
            if depreciation == 0.0:
                depreciation = _pick_value(cashflow_row or {}, ["depr_fa_coga_dpba"], 0.0)
            if amortization == 0.0:
                amortization = _pick_value(cashflow_row or {}, ["amort_intang_assets"], 0.0)
            ebit = ebitda - depreciation - amortization

    return ebitda, ebit


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
    return _summarize_valuation_range_impl(valuation_results, total_share=total_share)


def format_valuation_range_output(
    valuation_results,
    total_share=None,
    current_price=None,
    equity_unit=100000000,
    equity_unit_label="亿元",
    price_decimals=2,
):
    return _format_valuation_range_output_impl(
        valuation_results,
        total_share=total_share,
        current_price=current_price,
        equity_unit=equity_unit,
        equity_unit_label=equity_unit_label,
        price_decimals=price_decimals,
    )


def get_stock_valuation_snapshot(
    ts_code,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
    forced_report_end_date=None,
    allow_express_adjustment=True,
):
    frames = None
    local_fetch_error = None
    used_tushare_fallback = False
    touched_tushare_endpoints = []

    if bool(getattr(settings, "VALUATION_USE_LOCAL_FINANCIAL_DB", True)):
        try:
            frames = _fetch_local_financial_frames(
                ts_code=ts_code,
                trade_date=trade_date,
                forced_report_end_date=forced_report_end_date,
            )
        except Exception as exc:
            local_fetch_error = str(exc)
            frames = None

    if frames is None:
        if bool(getattr(settings, "VALUATION_LOCAL_FINANCIAL_ONLY", False)):
            reason = f"local financial db unavailable and fallback is disabled: {local_fetch_error}" if local_fetch_error else "local financial db unavailable and fallback is disabled"
            raise RuntimeError(reason)
        pro = pro or get_tushare_pro(token=token)
        frames = _fetch_tushare_frames(ts_code=ts_code, trade_date=trade_date, pro=pro)
        used_tushare_fallback = True
        touched_tushare_endpoints = list((frames or {}).get("__tushare_endpoints__") or [])

    frames = _filter_financial_frames_asof(frames, trade_date=trade_date)
    frame_counts = _summarize_frame_counts(frames)
    local_missing_frames = [
        name
        for name, count in frame_counts.items()
        if count == 0
    ]

    forced_report_end_date_text = _normalize_date_text(forced_report_end_date)
    daily_basic_row = _latest_record(frames["daily_basic"], ["trade_date"])
    if forced_report_end_date_text:
        fina_row = _record_for_end_date(frames["fina_indicator"], forced_report_end_date_text, ["end_date", "ann_date", "f_ann_date"])
        income_row = _record_for_end_date(frames["income"], forced_report_end_date_text, ["end_date", "ann_date", "f_ann_date"])
        balance_row = _record_for_end_date(frames["balancesheet"], forced_report_end_date_text, ["end_date", "ann_date", "f_ann_date"])
        cashflow_row = _record_for_end_date(frames["cashflow"], forced_report_end_date_text, ["end_date", "ann_date", "f_ann_date"])
        express_row = _record_for_end_date(frames.get("express_vip"), forced_report_end_date_text, ["end_date", "ann_date", "f_ann_date"])
    else:
        fina_row = _latest_record(frames["fina_indicator"], ["end_date", "ann_date", "f_ann_date"])
        income_row = _latest_record(frames["income"], ["end_date", "ann_date", "f_ann_date"])
        balance_row = _latest_record(frames["balancesheet"], ["end_date", "ann_date", "f_ann_date"])
        cashflow_row = _latest_record(frames["cashflow"], ["end_date", "ann_date", "f_ann_date"])
        express_row = _latest_record(frames.get("express_vip"), ["end_date", "ann_date", "f_ann_date"])
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
    report_end = _normalize_date_text((fina_row or {}).get("end_date") or (income_row or {}).get("end_date"))
    prev_annual_end = _previous_year_end_date(report_end)
    prev_same_end = _same_period_last_year_end_date(report_end)
    prev_annual_income_row = _record_for_end_date(frames["income"], prev_annual_end, ["end_date", "ann_date", "f_ann_date"])
    prev_same_income_row = _record_for_end_date(frames["income"], prev_same_end, ["end_date", "ann_date", "f_ann_date"])
    prev_annual_fina_row = _record_for_end_date(frames["fina_indicator"], prev_annual_end, ["end_date", "ann_date", "f_ann_date"])
    prev_same_fina_row = _record_for_end_date(frames["fina_indicator"], prev_same_end, ["end_date", "ann_date", "f_ann_date"])
    prev_annual_cashflow_row = _record_for_end_date(frames["cashflow"], prev_annual_end, ["end_date", "ann_date", "f_ann_date"])
    prev_same_cashflow_row = _record_for_end_date(frames["cashflow"], prev_same_end, ["end_date", "ann_date", "f_ann_date"])

    raw_netprofit = _pick_value(
        income_row,
        ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"],
    )
    raw_revenue = _pick_value(
        income_row,
        ["revenue", "total_revenue", "oper_rev"],
    )
    netprofit, netprofit_factor, netprofit_method = _resolve_ttm_flow_value(
        raw_netprofit,
        report_end,
        previous_annual_value=_pick_value(prev_annual_income_row, ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"]),
        previous_same_period_value=_pick_value(prev_same_income_row, ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"]),
    )
    revenue, revenue_factor, revenue_method = _resolve_ttm_flow_value(
        raw_revenue,
        report_end,
        previous_annual_value=_pick_value(prev_annual_income_row, ["revenue", "total_revenue", "oper_rev"]),
        previous_same_period_value=_pick_value(prev_same_income_row, ["revenue", "total_revenue", "oper_rev"]),
    )

    ebitda, ebit = _calc_ebitda_and_ebit_from_rows(
        fina_row=fina_row,
        income_row=income_row,
        cashflow_row=cashflow_row,
    )
    prev_annual_ebitda, prev_annual_ebit = _calc_ebitda_and_ebit_from_rows(
        fina_row=prev_annual_fina_row,
        income_row=prev_annual_income_row,
        cashflow_row=prev_annual_cashflow_row,
    )
    prev_same_ebitda, prev_same_ebit = _calc_ebitda_and_ebit_from_rows(
        fina_row=prev_same_fina_row,
        income_row=prev_same_income_row,
        cashflow_row=prev_same_cashflow_row,
    )
    ebitda, ebitda_factor, ebitda_method = _resolve_ttm_flow_value(
        ebitda,
        report_end,
        previous_annual_value=prev_annual_ebitda,
        previous_same_period_value=prev_same_ebitda,
    )
    ebit, ebit_factor, ebit_method = _resolve_ttm_flow_value(
        ebit,
        report_end,
        previous_annual_value=prev_annual_ebit,
        previous_same_period_value=prev_same_ebit,
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

    ocf = _pick_value(cashflow_row, ["n_cashflow_act", "n_cashflow_oper_act"])
    capex = _pick_value(
        cashflow_row,
        ["c_pay_acq_const_fiolta", "c_pay_acq_const_fiolta_oth"],
        default=0.0,
    )
    fcff = None
    if ocf is not None:
        raw_fcff = ocf - abs(capex)
        prev_annual_ocf = _pick_value(prev_annual_cashflow_row, ["n_cashflow_act", "n_cashflow_oper_act"])
        prev_annual_capex = _pick_value(
            prev_annual_cashflow_row,
            ["c_pay_acq_const_fiolta", "c_pay_acq_const_fiolta_oth"],
            default=0.0,
        )
        prev_same_ocf = _pick_value(prev_same_cashflow_row, ["n_cashflow_act", "n_cashflow_oper_act"])
        prev_same_capex = _pick_value(
            prev_same_cashflow_row,
            ["c_pay_acq_const_fiolta", "c_pay_acq_const_fiolta_oth"],
            default=0.0,
        )
        prev_annual_fcff = None if prev_annual_ocf is None else prev_annual_ocf - abs(prev_annual_capex)
        prev_same_fcff = None if prev_same_ocf is None else prev_same_ocf - abs(prev_same_capex)
        fcff, fcff_factor, fcff_method = _resolve_ttm_flow_value(
            raw_fcff,
            report_end,
            previous_annual_value=prev_annual_fcff,
            previous_same_period_value=prev_same_fcff,
        )
    else:
        fcff_factor = None
        fcff_method = "missing_current"

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

    primary_annualization_method = netprofit_method if raw_netprofit is not None else revenue_method
    primary_annualization_factor = netprofit_factor if raw_netprofit is not None else revenue_factor
    if primary_annualization_method is None:
        primary_annualization_method = ebitda_method or ebit_method or fcff_method
        primary_annualization_factor = ebitda_factor or ebit_factor or fcff_factor

    enterprise_value = None
    if total_mv is not None:
        enterprise_value = total_mv + debt - cash

    effective_trade_date = daily_basic_row.get("trade_date") or trade_date
    effective_report_end_date = _normalize_date_text((fina_row or {}).get("end_date") or (income_row or {}).get("end_date")) or None
    effective_report_ann_date = _normalize_date_text((fina_row or {}).get("ann_date") or (income_row or {}).get("ann_date")) or None
    if effective_report_ann_date and effective_report_end_date and effective_report_ann_date < effective_report_end_date:
        effective_report_ann_date = None

    snapshot = {
        "ts_code": ts_code,
        "trade_date": effective_trade_date,
        "end_date": effective_report_end_date,
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
        "profit_report_end_date": effective_report_end_date,
        "profit_report_ann_date": effective_report_ann_date,
        "profit_report_type": _resolve_report_type_from_end_date(effective_report_end_date),
        "express_apply_reason": "no_express_row",
        "express_block_reason": None,
        "strict_express_match": bool(strict_express_match),
        "express_max_age_days": express_max_age_days,
        "allow_express_adjustment": bool(allow_express_adjustment),
        "annualization_method": primary_annualization_method,
        "annualization_factor": primary_annualization_factor,
        "data_fetch_trace": {
            "fetch_source": "tushare" if used_tushare_fallback else "local",
            "local_fetch_error": local_fetch_error,
            "used_tushare_fallback": used_tushare_fallback,
            "tushare_endpoints": touched_tushare_endpoints,
            "frame_counts": frame_counts,
            "local_missing_frames": local_missing_frames,
        },
        "raw_frames": frames,
        "forced_report_end_date": forced_report_end_date_text or None,
    }

    if express_row and allow_express_adjustment:
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
                frames=frames,
            )
            snapshot["express_apply_reason"] = reason
            snapshot["express_block_reason"] = None
        else:
            snapshot["express_block_reason"] = reason
    elif express_row:
        snapshot["express_apply_reason"] = "disabled_by_request"
        snapshot["express_block_reason"] = "disabled_by_request"
    return snapshot


def _resolve_snapshot_for_valuation(
    ts_code,
    trade_date=None,
    token=None,
    pro=None,
    strict_express_match=True,
    express_max_age_days=180,
    forced_report_end_date=None,
    allow_express_adjustment=True,
    snapshot=None,
):
    if snapshot is not None:
        return snapshot
    return get_stock_valuation_snapshot(
        ts_code=ts_code,
        trade_date=trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
        forced_report_end_date=forced_report_end_date,
        allow_express_adjustment=allow_express_adjustment,
    )


def estimate_market_value(ts_code, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(
        ts_code=ts_code,
        trade_date=trade_date,
        token=token,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
        snapshot=snapshot,
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


def estimate_by_pe(ts_code, peer_pe=None, target_pe=None, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    applied_pe = target_pe if target_pe is not None else peer_pe
    if applied_pe is None:
        applied_pe = snapshot["pe_ttm"]
    if snapshot["netprofit"] is None or applied_pe in (None, 0):
        raise ValueError("PE valuation requires netprofit and target PE.")
    equity_value = snapshot["netprofit"] * applied_pe
    return _with_price_info({"method": "pe", "ts_code": ts_code, "equity_value": equity_value, "netprofit": snapshot["netprofit"], "applied_multiple": applied_pe, "current_multiple": snapshot["pe_ttm"]}, snapshot)


def estimate_by_ps(ts_code, peer_ps=None, target_ps=None, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    applied_ps = target_ps if target_ps is not None else peer_ps
    if applied_ps is None:
        applied_ps = snapshot["ps_ttm"]
    if snapshot["revenue"] is None or applied_ps in (None, 0):
        raise ValueError("PS valuation requires revenue and target PS.")
    equity_value = snapshot["revenue"] * applied_ps
    return _with_price_info({"method": "ps", "ts_code": ts_code, "equity_value": equity_value, "revenue": snapshot["revenue"], "applied_multiple": applied_ps, "current_multiple": snapshot["ps_ttm"]}, snapshot)


def estimate_by_pb(ts_code, peer_pb=None, target_pb=None, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    applied_pb = target_pb if target_pb is not None else peer_pb
    if applied_pb is None:
        applied_pb = snapshot["pb"]
    if snapshot["equity_book_value"] is None or applied_pb in (None, 0):
        raise ValueError("PB valuation requires equity_book_value and target PB.")
    equity_value = snapshot["equity_book_value"] * applied_pb
    return _with_price_info({"method": "pb", "ts_code": ts_code, "equity_value": equity_value, "equity_book_value": snapshot["equity_book_value"], "applied_multiple": applied_pb, "current_multiple": snapshot["pb"]}, snapshot)


def _build_sw_history_variant(history_windows, history_quantile, history_min_samples):
    return _build_sw_history_variant_impl(history_windows, history_quantile, history_min_samples)


def _build_sw_history_component_rows(snapshot, sw_history_result):
    return _build_sw_history_component_rows_impl(snapshot, sw_history_result)


def _normalize_sw_history_years(history_years):
    return _normalize_sw_history_years_impl(history_years)


def _resolve_sw_history_trade_date(trade_date, snapshot_trade_date):
    return _resolve_sw_history_trade_date_impl(trade_date, snapshot_trade_date)


def _resolve_sw_history_context(ts_code, trade_date, market="CN", token=None, pro=None, history_years=None, history_quantile=SW_HISTORY_DEFAULT_QUANTILE, history_min_samples=SW_HISTORY_DEFAULT_MIN_SAMPLES):
    return _resolve_sw_history_context_impl(
        ts_code=ts_code,
        trade_date=trade_date,
        market=market,
        token=token,
        pro=pro,
        history_years=history_years,
        history_quantile=history_quantile,
        history_min_samples=history_min_samples,
        safe_float=_safe_float,
        get_tushare_pro=get_tushare_pro,
    )


def _median_value(values):
    return _median_value_impl(values)


def _resolve_scarcity_inputs(snapshot, valuations_df, scarcity_kwargs=None):
    return _resolve_scarcity_inputs_impl(
        snapshot=snapshot,
        valuations_df=valuations_df,
        scarcity_kwargs=scarcity_kwargs,
        safe_float=_safe_float,
        parse_date_yyyymmdd=_parse_date_yyyymmdd,
    )


def _select_scarcity_base_row(valuations_df):
    return _select_scarcity_base_row_impl(valuations_df, safe_float=_safe_float)


def _build_scarcity_overlay_row(snapshot, valuations_df, scarcity_kwargs=None):
    return _build_scarcity_overlay_row_impl(
        snapshot=snapshot,
        valuations_df=valuations_df,
        scarcity_kwargs=scarcity_kwargs,
        safe_float=_safe_float,
        parse_date_yyyymmdd=_parse_date_yyyymmdd,
    )


def estimate_by_sw_history(ts_code, trade_date=None, token=None, pro=None, market="CN", history_years=None, history_quantile=SW_HISTORY_DEFAULT_QUANTILE, history_min_samples=SW_HISTORY_DEFAULT_MIN_SAMPLES, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    effective_trade_date = _resolve_sw_history_trade_date(trade_date, snapshot.get("trade_date"))
    context = _resolve_sw_history_context(ts_code=ts_code, trade_date=effective_trade_date, market=market, token=token, pro=pro, history_years=history_years, history_quantile=history_quantile, history_min_samples=history_min_samples)
    sw_info = context.get("sw_info") or {}
    history_payload = context.get("history_payload") or {}
    anchors = history_payload.get("anchors") or {}
    component_rows = []
    pe_anchor = anchors.get("pe")
    if snapshot.get("netprofit") is not None and pe_anchor not in (None, 0):
        pe_equity_value = snapshot.get("netprofit") * pe_anchor
        component_rows.append({"method": "pe", "target_multiple": float(pe_anchor), "equity_value": pe_equity_value, "implied_price": _equity_value_to_price(pe_equity_value, snapshot.get("total_share"))})
    pb_anchor = anchors.get("pb")
    if snapshot.get("equity_book_value") is not None and pb_anchor not in (None, 0):
        pb_equity_value = snapshot.get("equity_book_value") * pb_anchor
        component_rows.append({"method": "pb", "target_multiple": float(pb_anchor), "equity_value": pb_equity_value, "implied_price": _equity_value_to_price(pb_equity_value, snapshot.get("total_share"))})
    ps_anchor = anchors.get("ps")
    if snapshot.get("revenue") is not None and ps_anchor not in (None, 0):
        ps_equity_value = snapshot.get("revenue") * ps_anchor
        component_rows.append({"method": "ps", "target_multiple": float(ps_anchor), "equity_value": ps_equity_value, "implied_price": _equity_value_to_price(ps_equity_value, snapshot.get("total_share"))})
    component_prices = [row.get("implied_price") for row in component_rows]
    composite_price = _median_value(component_prices)
    if composite_price is None:
        raise ValueError("SW historical valuation requires at least one valid PE/PB/PS historical anchor.")
    total_share = snapshot.get("total_share")
    composite_equity_value = composite_price * total_share if total_share not in (None, 0) else _median_value([row.get("equity_value") for row in component_rows])
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
        "valuation_variant": _build_sw_history_variant(history_payload.get("windows"), history_payload.get("quantile"), history_payload.get("min_samples")),
        "compare_group": "sw_history_anchor",
        "industry_level": "L3" if sw_info.get("industry_code") else None,
        "history_targets": anchors,
        "history_target_pe": pe_anchor,
        "history_target_pb": pb_anchor,
        "history_target_ps": ps_anchor,
        "component_methods": [row.get("method") for row in component_rows],
        "component_count": len(component_rows),
        "component_implied_prices": {row.get("method"): round(float(row.get("implied_price")), 4) for row in component_rows if row.get("implied_price") is not None},
        "component_target_multiples": {row.get("method"): row.get("target_multiple") for row in component_rows},
        "target_source": "sw_history_anchor_median",
    }


def estimate_by_peg(ts_code, target_peg=1.0, growth_rate_pct=None, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    growth_pct = growth_rate_pct if growth_rate_pct is not None else snapshot["peg_growth_yoy_pct"]
    peg_inputs = _resolve_peg_inputs(target_peg=target_peg, growth_pct=growth_pct)
    result = estimate_by_pe(ts_code=ts_code, target_pe=peg_inputs["derived_target_pe"], trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    result.update({"method": "peg", **peg_inputs})
    return result


def estimate_by_ev_ebitda(ts_code, target_ev_ebitda, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    if snapshot["ebitda"] in (None, 0):
        raise ValueError("EV/EBITDA valuation requires EBITDA.")
    enterprise_value = snapshot["ebitda"] * target_ev_ebitda
    equity_value = enterprise_value - snapshot["debt"] + snapshot["cash"]
    return _with_price_info({"method": "ev_ebitda", "ts_code": ts_code, "enterprise_value": enterprise_value, "equity_value": equity_value, "ebitda": snapshot["ebitda"], "target_ev_ebitda": target_ev_ebitda, "cash": snapshot["cash"], "debt": snapshot["debt"]}, snapshot)


def estimate_by_fcff_dcf(ts_code, forecast_fcff=None, base_fcff=None, growth_rates=None, discount_rate=0.1, terminal_growth_rate=0.03, net_debt=None, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
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
    effective_net_debt = net_debt if net_debt is not None else (snapshot["debt"] - snapshot["cash"])
    equity_value = enterprise_value - effective_net_debt
    return _with_price_info({"method": "fcff_dcf", "ts_code": ts_code, "enterprise_value": enterprise_value, "equity_value": equity_value, "forecast_fcff": forecast_fcff, "discount_rate": discount_rate, "terminal_growth_rate": terminal_growth_rate, "terminal_value": terminal_value, "net_debt": effective_net_debt}, snapshot)


def estimate_by_ddm(ts_code, annual_dividend=None, discount_rate=0.1, dividend_growth_rate=0.03, stage_dividends=None, terminal_growth_rate=None, trade_date=None, token=None, pro=None, strict_express_match=True, express_max_age_days=180, snapshot=None):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    terminal_growth_rate = dividend_growth_rate if terminal_growth_rate is None else terminal_growth_rate
    if stage_dividends:
        present_values = [dividend / ((1 + discount_rate) ** idx) for idx, dividend in enumerate(stage_dividends, start=1)]
        if discount_rate <= terminal_growth_rate:
            raise ValueError("discount_rate must be greater than terminal_growth_rate.")
        final_dividend = stage_dividends[-1] * (1 + terminal_growth_rate)
        terminal_value = final_dividend / (discount_rate - terminal_growth_rate)
        equity_value = sum(present_values) + terminal_value / ((1 + discount_rate) ** len(stage_dividends))
        return _with_price_info({"method": "ddm", "ts_code": ts_code, "equity_value": equity_value, "stage_dividends": stage_dividends, "discount_rate": discount_rate, "terminal_growth_rate": terminal_growth_rate}, snapshot)
    dividend_total = annual_dividend if annual_dividend is not None else snapshot["annual_dividend"]
    if dividend_total is None:
        raise ValueError("DDM requires annual_dividend or dividend data from tushare.")
    if discount_rate <= dividend_growth_rate:
        raise ValueError("discount_rate must be greater than dividend_growth_rate.")
    equity_value = dividend_total * (1 + dividend_growth_rate) / (discount_rate - dividend_growth_rate)
    return _with_price_info({"method": "ddm", "ts_code": ts_code, "equity_value": equity_value, "annual_dividend": dividend_total, "discount_rate": discount_rate, "dividend_growth_rate": dividend_growth_rate}, snapshot)


def run_valuation_scenarios(model_func, scenarios, base_kwargs=None):
    return _run_valuation_scenarios_impl(model_func, scenarios, base_kwargs=base_kwargs)


def run_sensitivity_analysis(model_func, base_kwargs, variable_grid):
    return _run_sensitivity_analysis_impl(model_func, base_kwargs, variable_grid)


def _resolve_effective_multiple_target(explicit_target, snapshot_multiple, history_targets, method_key, prefer_history_targets=False):
    if explicit_target is not None:
        return explicit_target
    if prefer_history_targets:
        anchor = _safe_float((history_targets or {}).get(method_key))
        if anchor not in (None, 0):
            return anchor
    return snapshot_multiple


def estimate_all_supported_methods(ts_code, trade_date=None, token=None, pro=None, pe_target=None, ps_target=None, pb_target=None, peg_target=1.0, ev_ebitda_target=None, dcf_kwargs=None, ddm_kwargs=None, sw_history_kwargs=None, scarcity_kwargs=None, strict_express_match=True, express_max_age_days=180, snapshot=None, prefer_sw_history_targets=False):
    snapshot = _resolve_snapshot_for_valuation(ts_code=ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    results = [estimate_market_value(ts_code, trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)]
    sw_history_result = None
    sw_history_targets = {}
    try:
        sw_history_result = estimate_by_sw_history(ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot, **(sw_history_kwargs or {}))
        if prefer_sw_history_targets:
            sw_history_targets = dict(sw_history_result.get("history_targets") or {})
    except ValueError:
        sw_history_result = None

    effective_target_pe = _resolve_effective_multiple_target(
        pe_target,
        snapshot.get("pe_ttm"),
        sw_history_targets,
        "pe",
        prefer_history_targets=prefer_sw_history_targets,
    )
    if snapshot.get("netprofit") is not None and effective_target_pe not in (None, 0):
        results.append(estimate_by_pe(ts_code, target_pe=effective_target_pe, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot))
    effective_target_ps = _resolve_effective_multiple_target(
        ps_target,
        snapshot.get("ps_ttm"),
        sw_history_targets,
        "ps",
        prefer_history_targets=prefer_sw_history_targets,
    )
    if snapshot.get("revenue") is not None and effective_target_ps not in (None, 0):
        results.append(estimate_by_ps(ts_code, target_ps=effective_target_ps, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot))
    effective_target_pb = _resolve_effective_multiple_target(
        pb_target,
        snapshot.get("pb"),
        sw_history_targets,
        "pb",
        prefer_history_targets=prefer_sw_history_targets,
    )
    if snapshot.get("equity_book_value") is not None and effective_target_pb not in (None, 0):
        results.append(estimate_by_pb(ts_code, target_pb=effective_target_pb, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot))
    if sw_history_result is not None:
        results.append(sw_history_result)
        results.extend(_build_sw_history_component_rows(snapshot, sw_history_result))
    if snapshot.get("peg_growth_yoy_pct") not in (None, 0):
        try:
            results.append(estimate_by_peg(ts_code, target_peg=peg_target, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot))
        except ValueError as exc:
            results.append({"method": "peg", "ts_code": ts_code, "equity_value": None, "implied_price": None, "total_share": snapshot.get("total_share"), "target_peg": peg_target, "raw_growth_rate_pct": snapshot.get("peg_growth_yoy_pct"), "growth_rate_pct": None, "raw_target_pe": None, "derived_target_pe": None, "peg_quality_flag": "non_positive_growth_skipped", "peg_skip_reason": str(exc)})
    if ev_ebitda_target is not None and snapshot.get("ebitda") not in (None, 0):
        results.append(estimate_by_ev_ebitda(ts_code, target_ev_ebitda=ev_ebitda_target, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot))
    dcf_kwargs = dcf_kwargs or {}
    try:
        results.append(estimate_by_fcff_dcf(ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot, **dcf_kwargs))
    except ValueError:
        pass
    ddm_kwargs = ddm_kwargs or {}
    try:
        results.append(estimate_by_ddm(ts_code, trade_date=trade_date, token=token, pro=pro, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot, **ddm_kwargs))
    except ValueError:
        pass
    scarcity_overlay = _build_scarcity_overlay_row(snapshot=snapshot, valuations_df=pd.DataFrame(results), scarcity_kwargs=scarcity_kwargs)
    if scarcity_overlay is not None:
        results.append(scarcity_overlay)
    df = pd.DataFrame(results)
    if "equity_value" in df.columns:
        df["equity_value_亿元"] = df["equity_value"] / 100000000
    if "enterprise_value" in df.columns:
        df["enterprise_value_亿元"] = df["enterprise_value"] / 100000000
    summary = summarize_valuation_range(df, total_share=snapshot.get("total_share"))
    for key, value in summary.items():
        df[key] = value
    return df


def test_valuation(ts_code, trade_date=None, current_price=None, pro=None, pe_target=None, ps_target=None, pb_target=None, peg_target=1.0, ev_ebitda_target=None, dcf_kwargs=None, ddm_kwargs=None, sw_history_kwargs=None, scarcity_kwargs=None, scenario_model="fcff_dcf", scenario_overrides=None, sensitivity_grid=None, strict_express_match=True, express_max_age_days=180, allow_express_adjustment=True, prefer_sw_history_targets=False, **_ignored_kwargs):
    forced_report_end_date = _ignored_kwargs.get("forced_report_end_date")
    snapshot = get_stock_valuation_snapshot(
        ts_code=ts_code,
        trade_date=trade_date,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
        forced_report_end_date=forced_report_end_date,
        allow_express_adjustment=allow_express_adjustment,
    )
    resolved_current_price = current_price if current_price is not None else snapshot.get("close_price")
    dcf_kwargs = dcf_kwargs or {}
    ddm_kwargs = ddm_kwargs or {}
    valuations = estimate_all_supported_methods(ts_code=ts_code, trade_date=trade_date, pro=pro, pe_target=pe_target, ps_target=ps_target, pb_target=pb_target, peg_target=peg_target, ev_ebitda_target=ev_ebitda_target, dcf_kwargs=dcf_kwargs, ddm_kwargs=ddm_kwargs, sw_history_kwargs=sw_history_kwargs, scarcity_kwargs=scarcity_kwargs, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot, prefer_sw_history_targets=prefer_sw_history_targets)
    formatted_range = format_valuation_range_output(valuations, total_share=snapshot.get("total_share"), current_price=resolved_current_price)
    scenario_analysis = None
    scenario_model_map = {"fcff_dcf": estimate_by_fcff_dcf, "ddm": estimate_by_ddm, "pe": estimate_by_pe, "ps": estimate_by_ps, "pb": estimate_by_pb, "ev_ebitda": estimate_by_ev_ebitda}
    scenario_func = scenario_model_map.get(scenario_model)
    base_kwargs_map = {
        "fcff_dcf": {"ts_code": ts_code, "trade_date": trade_date, "pro": pro, "strict_express_match": strict_express_match, "express_max_age_days": express_max_age_days, **dcf_kwargs},
        "ddm": {"ts_code": ts_code, "trade_date": trade_date, "pro": pro, "strict_express_match": strict_express_match, "express_max_age_days": express_max_age_days, **ddm_kwargs},
        "pe": {"ts_code": ts_code, "trade_date": trade_date, "pro": pro, "strict_express_match": strict_express_match, "express_max_age_days": express_max_age_days, "target_pe": pe_target or snapshot.get("pe_ttm")},
        "ps": {"ts_code": ts_code, "trade_date": trade_date, "pro": pro, "strict_express_match": strict_express_match, "express_max_age_days": express_max_age_days, "target_ps": ps_target or snapshot.get("ps_ttm")},
        "pb": {"ts_code": ts_code, "trade_date": trade_date, "pro": pro, "strict_express_match": strict_express_match, "express_max_age_days": express_max_age_days, "target_pb": pb_target or snapshot.get("pb")},
        "ev_ebitda": {"ts_code": ts_code, "trade_date": trade_date, "pro": pro, "strict_express_match": strict_express_match, "express_max_age_days": express_max_age_days, "target_ev_ebitda": ev_ebitda_target},
    }
    if scenario_model == "ev_ebitda":
        ev_target = base_kwargs_map.get("ev_ebitda", {}).get("target_ev_ebitda")
        if ev_target in (None, 0):
            scenario_func = None
    if scenario_func is not None:
        default_scenarios = {"bear": {}, "base": {}, "bull": {}}
        if scenario_model == "fcff_dcf":
            default_scenarios = {"bear": {"discount_rate": dcf_kwargs.get("discount_rate", 0.11), "terminal_growth_rate": dcf_kwargs.get("terminal_growth_rate", 0.02), "growth_rates": dcf_kwargs.get("growth_rates", [0.05, 0.04, 0.03, 0.03, 0.02])}, "base": {"discount_rate": dcf_kwargs.get("discount_rate", 0.1), "terminal_growth_rate": dcf_kwargs.get("terminal_growth_rate", 0.03), "growth_rates": dcf_kwargs.get("growth_rates", [0.08, 0.06, 0.05, 0.04, 0.03])}, "bull": {"discount_rate": dcf_kwargs.get("discount_rate", 0.09), "terminal_growth_rate": dcf_kwargs.get("terminal_growth_rate", 0.04), "growth_rates": dcf_kwargs.get("growth_rates", [0.12, 0.10, 0.08, 0.06, 0.05])}}
        elif scenario_model == "ddm":
            default_scenarios = {"bear": {"discount_rate": ddm_kwargs.get("discount_rate", 0.11), "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.01)}, "base": {"discount_rate": ddm_kwargs.get("discount_rate", 0.1), "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.03)}, "bull": {"discount_rate": ddm_kwargs.get("discount_rate", 0.09), "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.05)}}
        elif scenario_model == "pe":
            base_pe = pe_target or snapshot.get("pe_ttm")
            if base_pe is not None:
                default_scenarios = {"bear": {"target_pe": base_pe * 0.85}, "base": {"target_pe": base_pe}, "bull": {"target_pe": base_pe * 1.15}}
        elif scenario_model == "ps":
            base_ps = ps_target or snapshot.get("ps_ttm")
            if base_ps is not None:
                default_scenarios = {"bear": {"target_ps": base_ps * 0.85}, "base": {"target_ps": base_ps}, "bull": {"target_ps": base_ps * 1.15}}
        elif scenario_model == "pb":
            base_pb = pb_target or snapshot.get("pb")
            if base_pb is not None:
                default_scenarios = {"bear": {"target_pb": base_pb * 0.85}, "base": {"target_pb": base_pb}, "bull": {"target_pb": base_pb * 1.15}}
        elif scenario_model == "ev_ebitda" and ev_ebitda_target is not None:
            default_scenarios = {"bear": {"target_ev_ebitda": ev_ebitda_target * 0.85}, "base": {"target_ev_ebitda": ev_ebitda_target}, "bull": {"target_ev_ebitda": ev_ebitda_target * 1.15}}
        scenarios = scenario_overrides or default_scenarios
        try:
            scenario_analysis = run_valuation_scenarios(scenario_func, scenarios=scenarios, base_kwargs=base_kwargs_map.get(scenario_model, {}))
        except ValueError:
            scenario_analysis = None
    sensitivity_analysis = None
    if sensitivity_grid:
        sensitivity_func = scenario_func or estimate_by_fcff_dcf
        sensitivity_base_kwargs = base_kwargs_map.get(scenario_model, {}) if scenario_func is not None else {"ts_code": ts_code, "trade_date": trade_date, "pro": pro, "strict_express_match": strict_express_match, "express_max_age_days": express_max_age_days, **dcf_kwargs}
        try:
            sensitivity_analysis = run_sensitivity_analysis(sensitivity_func, base_kwargs=sensitivity_base_kwargs, variable_grid=sensitivity_grid)
        except (ValueError, TypeError):
            sensitivity_analysis = None
    return {"snapshot": snapshot, "valuations": valuations, "formatted_range": formatted_range, "scenario_analysis": scenario_analysis, "sensitivity_analysis": sensitivity_analysis}


def test_valuation_light(ts_code, trade_date=None, pro=None, pe_target=None, ps_target=None, pb_target=None, peg_target=1.0, ev_ebitda_target=None, dcf_kwargs=None, ddm_kwargs=None, sw_history_kwargs=None, scarcity_kwargs=None, strict_express_match=True, express_max_age_days=180, allow_express_adjustment=True, snapshot=None, **_ignored_kwargs):
    forced_report_end_date = _ignored_kwargs.get("forced_report_end_date")
    snapshot = _resolve_snapshot_for_valuation(
        ts_code=ts_code,
        trade_date=trade_date,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
        forced_report_end_date=forced_report_end_date,
        allow_express_adjustment=allow_express_adjustment,
        snapshot=snapshot,
    )
    valuations = estimate_all_supported_methods(ts_code=ts_code, trade_date=trade_date, pro=pro, pe_target=pe_target, ps_target=ps_target, pb_target=pb_target, peg_target=peg_target, ev_ebitda_target=ev_ebitda_target, dcf_kwargs=dcf_kwargs, ddm_kwargs=ddm_kwargs, sw_history_kwargs=sw_history_kwargs, scarcity_kwargs=scarcity_kwargs, strict_express_match=strict_express_match, express_max_age_days=express_max_age_days, snapshot=snapshot)
    return {"snapshot": snapshot, "valuations": valuations}


def demo_valuation_for_pingan(trade_date=None, pro=None):
    return test_valuation(ts_code="000001.SZ", trade_date=trade_date, pro=pro, pe_target=6.5, ps_target=1.2, pb_target=0.7, peg_target=0.9, ev_ebitda_target=5.5, dcf_kwargs={"discount_rate": 0.10, "terminal_growth_rate": 0.03, "growth_rates": [0.08, 0.06, 0.05, 0.04, 0.03]}, ddm_kwargs={"discount_rate": 0.10, "dividend_growth_rate": 0.03}, scenario_model="fcff_dcf", sensitivity_grid={"discount_rate": [0.09, 0.10, 0.11], "terminal_growth_rate": [0.02, 0.03, 0.04]})