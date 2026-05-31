import datetime
from functools import lru_cache
import math
import os
from pathlib import Path
import pandas as pd
from django.conf import settings
from django.db import transaction

from .models import (
    CompanyProfile,
    StockExpressVip,
    StockFundamentalSnapshot,
    StockTradingHistory,
    ValuationSnapshot,
    ValuationAssumption,
    ValuationSnapshotLatest,
)
from .valuation_config import resolve_template_params


def _safe_float(value):
    if value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return val


def _parse_any_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    text = text.replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _get_tushare_pro_client():
    try:
        import tushare as ts
    except ImportError:
        return None

    token = (
        os.getenv("TUSHARE_TOKEN")
        or os.getenv("TUSHARE_PRO_TOKEN")
        or str(getattr(settings, "TUSHARE_TOKEN", "") or "").strip()
    )
    if token:
        ts.set_token(token)

    try:
        return ts.pro_api()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _select_financial_row(df, trade_date=None):
    if df is None or df.empty:
        return None

    target_date = _resolve_trade_date(trade_date)
    records = df.fillna("").to_dict(orient="records")
    if not records:
        return None

    if target_date is None:
        return records[0]

    def _record_ann_date(row):
        return _parse_any_date(row.get("ann_date")) or _parse_any_date(row.get("end_date"))

    def _normalize_record_dates(row):
        normalized = dict(row)
        for key in ("ann_date", "end_date"):
            parsed = _parse_any_date(normalized.get(key))
            if parsed is not None:
                normalized[key] = parsed
        return normalized

    eligible = [row for row in records if _record_ann_date(row) and _record_ann_date(row) <= target_date]
    if eligible:
        eligible.sort(key=lambda row: _record_ann_date(row) or datetime.date.min, reverse=True)
        return _normalize_record_dates(eligible[0])
    return _normalize_record_dates(records[0])


def _fetch_tushare_financial_metrics(ts_code, trade_date=None):
    pro = _get_tushare_pro_client()
    if pro is None:
        return {
            "ebitda": None,
            "cash": None,
            "debt": None,
            "netprofit": None,
            "revenue": None,
            "equity_book_value": None,
            "fcff": None,
            "dividend_per_10": None,
            "peg_growth_yoy_pct": None,
            "source": None,
            "reason": "tushare_unavailable",
        }

    try:
        fina_df = pro.fina_indicator(
            ts_code=ts_code,
            limit=8,
            fields=(
                "ts_code,ann_date,end_date,ebitda,ebitda2,ebit,ebit2,depr,amortization,"
                "netprofit_yoy,dt_netprofit_yoy,tr_yoy,or_yoy"
            ),
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        fina_df = None

    try:
        bal_df = pro.balancesheet(
            ts_code=ts_code,
            limit=8,
            fields=(
                "ts_code,ann_date,end_date,money_cap,monetary_cap,total_liab,st_borr,lt_borr,"
                "bond_payable,other_payable,non_cur_liab_due_1y,total_hldr_eqy_exc_min_int,"
                "total_hldr_eqy_inc_min_int,total_assets"
            ),
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        bal_df = None

    try:
        income_df = pro.income_vip(
            ts_code=ts_code,
            limit=8,
            fields=(
                "ts_code,ann_date,end_date,ebitda,ebit,operate_profit,op_income,depr,amortization,"
                "n_income_attr_p,n_income,net_profit,profit_dedt,revenue,total_revenue,oper_rev"
            ),
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        income_df = None

    try:
        cashflow_df = pro.cashflow(
            ts_code=ts_code,
            limit=8,
            fields=(
                "ts_code,ann_date,end_date,c_cash_equ_end_period,cash_equ_end_period,"
                "n_cashflow_act,n_cashflow_oper_act,c_pay_acq_const_fiolta,c_pay_acq_const_fiolta_oth,"
                "depr_fa_coga_dpba,amort_intang_assets"
            ),
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        cashflow_df = None

    try:
        dividend_df = pro.dividend(
            ts_code=ts_code,
            limit=8,
            fields="ts_code,ann_date,end_date,cash_div_tax",
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        dividend_df = None

    fina_row = _select_financial_row(fina_df, trade_date=trade_date)
    bal_row = _select_financial_row(bal_df, trade_date=trade_date)
    income_row = _select_financial_row(income_df, trade_date=trade_date)
    cashflow_row = _select_financial_row(cashflow_df, trade_date=trade_date)
    dividend_row = _select_financial_row(dividend_df, trade_date=trade_date)

    report_end_candidates = [
        _parse_any_date((fina_row or {}).get("end_date")),
        _parse_any_date((income_row or {}).get("end_date")),
    ]
    report_end_candidates = [item for item in report_end_candidates if item is not None]
    report_end_date = max(report_end_candidates) if report_end_candidates else None

    ebitda = _pick_row_value(fina_row or {}, ["ebitda", "ebitda2"])
    if ebitda is None:
        operating_income = _pick_row_value(income_row or {}, ["operate_profit", "op_income"])
        depreciation = _pick_row_value(fina_row or {}, ["depr"])
        if depreciation is None:
            depreciation = _pick_row_value(income_row or {}, ["depr"])
        if depreciation is None:
            depreciation = _pick_row_value(cashflow_row or {}, ["depr_fa_coga_dpba"])
        amortization = _pick_row_value(fina_row or {}, ["amortization"])
        if amortization is None:
            amortization = _pick_row_value(income_row or {}, ["amortization"])
        if amortization is None:
            amortization = _pick_row_value(cashflow_row or {}, ["amort_intang_assets"])
        if operating_income is not None:
            ebitda = operating_income + (depreciation or 0.0) + (amortization or 0.0)

    netprofit = _pick_row_value(
        income_row or {},
        ["n_income_attr_p", "n_income", "net_profit", "profit_dedt"],
    )
    revenue = _pick_row_value(
        income_row or {},
        ["revenue", "total_revenue", "oper_rev"],
    )

    cash = _pick_row_value(bal_row or {}, ["money_cap", "monetary_cap"])
    if cash is None:
        cash = _pick_row_value(cashflow_row or {}, ["c_cash_equ_end_period", "cash_equ_end_period"])

    debt_components = [
        _pick_row_value(bal_row or {}, ["st_borr"]),
        _pick_row_value(bal_row or {}, ["lt_borr"]),
        _pick_row_value(bal_row or {}, ["bond_payable"]),
        _pick_row_value(bal_row or {}, ["non_cur_liab_due_1y"]),
    ]
    debt = sum(component for component in debt_components if component is not None)
    equity_book_value = _pick_row_value(
        bal_row or {},
        ["total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int", "total_assets"],
    )

    peg_growth_yoy_pct = _pick_row_value(
        fina_row or {},
        ["netprofit_yoy", "dt_netprofit_yoy", "tr_yoy", "or_yoy"],
    )

    ocf = _pick_row_value(cashflow_row or {}, ["n_cashflow_act", "n_cashflow_oper_act"])
    capex = _pick_row_value(
        cashflow_row or {},
        ["c_pay_acq_const_fiolta", "c_pay_acq_const_fiolta_oth"],
    )
    fcff = None
    if ocf is not None:
        fcff = ocf - abs(capex or 0.0)

    dividend_per_10 = _pick_row_value(dividend_row or {}, ["cash_div_tax"])

    if (
        ebitda is None
        and cash is None
        and debt is None
        and netprofit is None
        and revenue is None
        and equity_book_value is None
        and fcff is None
        and dividend_per_10 is None
        and peg_growth_yoy_pct is None
    ):
        return {
            "ebitda": None,
            "cash": None,
            "debt": None,
            "netprofit": None,
            "revenue": None,
            "equity_book_value": None,
            "fcff": None,
            "dividend_per_10": None,
            "peg_growth_yoy_pct": None,
            "report_end_date": report_end_date,
            "source": None,
            "reason": "tushare_no_financial_fields",
        }

    return {
        "ebitda": ebitda,
        "cash": cash,
        "debt": debt,
        "netprofit": netprofit,
        "revenue": revenue,
        "equity_book_value": equity_book_value,
        "fcff": fcff,
        "dividend_per_10": dividend_per_10,
        "peg_growth_yoy_pct": peg_growth_yoy_pct,
        "report_end_date": report_end_date,
        "source": "tushare_financial",
        "reason": None,
    }


def _fetch_tushare_express_row(ts_code, trade_date=None):
    pro = _get_tushare_pro_client()
    if pro is None:
        return None

    try:
        express_df = pro.express_vip(ts_code=ts_code, limit=8)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None

    return _select_financial_row(express_df, trade_date=trade_date)


def _resolve_valuation_variant(persist_context):
    persist_context = persist_context or {}
    explicit_variant = str(persist_context.get("valuation_variant") or "").strip()
    if explicit_variant:
        return explicit_variant

    compare_group = str(persist_context.get("compare_group") or "").strip()
    if not compare_group:
        return "default"

    level = str(persist_context.get("industry_level") or "").strip()
    code = str(persist_context.get("industry_code") or "").strip()
    name = str(persist_context.get("industry_name") or "").strip()
    if any([level, code, name]):
        return "|".join([compare_group, level, code, name])
    return compare_group


def _apply_snapshot_overrides(snapshot, snapshot_overrides):
    if not isinstance(snapshot_overrides, dict):
        return snapshot

    # Keep overrides constrained to valuation inputs that are safe to replace.
    allowed_numeric_fields = {
        "close_price",
        "total_share",
        "market_cap",
        "netprofit",
        "revenue",
        "equity_book_value",
        "ebitda",
        "cash",
        "debt",
        "peg_growth_yoy_pct",
        "fcff_per_share",
        "dividend_per_share",
    }
    for key in allowed_numeric_fields:
        if key not in snapshot_overrides:
            continue
        coerced = _safe_float(snapshot_overrides.get(key))
        if coerced is None:
            continue
        snapshot[key] = coerced
    return snapshot


def _positive(value):
    val = _safe_float(value)
    return val if val is not None and val > 0 else None


def _equity_value_to_price(equity_value, total_share):
    equity = _safe_float(equity_value)
    shares = _positive(total_share)
    if equity is None or shares is None:
        return None
    return equity / shares


def _resolve_trade_date(trade_date):
    if not trade_date:
        return None
    if isinstance(trade_date, datetime.date):
        return trade_date
    try:
        return datetime.datetime.strptime(str(trade_date), "%Y-%m-%d").date()
    except ValueError:
        return None


def _pick_row_value(row, keys):
    for key in keys:
        if key in row and row.get(key) is not None:
            val = _safe_float(row.get(key))
            if val is not None:
                return val
    return None


def _is_express_vip_eligible_local(express_row, base_end_date, trade_date, strict_match=True, max_age_days=180):
    if not express_row:
        return False, "missing_express_row"
    if not strict_match:
        return True, "strict_disabled"

    ann_date = _parse_any_date(express_row.get("ann_date"))
    trade_date = _parse_any_date(trade_date)
    base_end_date = _parse_any_date(base_end_date)
    if ann_date is None:
        return False, "ann_date_missing"
    if trade_date is not None and ann_date > trade_date:
        return False, "ann_date_after_trade_date"

    express_end_date = _parse_any_date(express_row.get("end_date"))
    is_period_upgrade = False
    if base_end_date is not None:
        if express_end_date is None:
            return False, "express_end_date_missing"
        if express_end_date < base_end_date:
            return False, "express_end_before_base_end"
        if express_end_date > base_end_date:
            is_period_upgrade = True

    if trade_date is not None and max_age_days is not None and not is_period_upgrade:
        try:
            age_limit = int(max_age_days)
        except (TypeError, ValueError):
            age_limit = 180
        if age_limit >= 0 and (trade_date - ann_date).days > age_limit:
            return False, "ann_date_stale"

    if is_period_upgrade:
        return True, "eligible_period_upgrade"
    return True, "eligible"


def _resolve_express_growth_pct_local(express_row):
    direct_growth = _pick_row_value(
        express_row,
        ["yoy_dedu_np", "yoy_np", "yoy_sales", "tr_yoy", "or_yoy", "netprofit_yoy"],
    )
    if direct_growth is not None and abs(direct_growth) <= 1000:
        return direct_growth

    yoy_net_profit = _pick_row_value(express_row, ["yoy_net_profit"])
    if yoy_net_profit is not None and abs(yoy_net_profit) > 1000:
        current_netprofit = _pick_row_value(
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


def _blend_preferred_local(primary, fallback, alpha=0.7):
    if primary is None and fallback is None:
        return None
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    return alpha * primary + (1.0 - alpha) * fallback


def _apply_express_vip_adjustments_local(snapshot, express_row, base_end_date=None):
    if not express_row:
        return snapshot

    adjusted = dict(snapshot)
    adjusted["base_peg_growth_yoy_pct"] = snapshot.get("peg_growth_yoy_pct")
    adjusted["base_netprofit"] = snapshot.get("netprofit")
    adjusted["base_revenue"] = snapshot.get("revenue")
    adjusted["express_blend_alpha"] = 0.7

    express_yoy = _resolve_express_growth_pct_local(express_row)
    if express_yoy is not None:
        adjusted["peg_growth_yoy_pct"] = express_yoy

    express_netprofit = _pick_row_value(
        express_row,
        ["n_income_attr_p", "n_income", "net_profit", "profit_dedt", "deduct_np"],
    )
    express_revenue = _pick_row_value(
        express_row,
        ["revenue", "total_revenue", "oper_rev"],
    )

    period_end = _parse_any_date(express_row.get("end_date"))
    parsed_base_end_date = _parse_any_date(base_end_date)
    if isinstance(period_end, datetime.date) and period_end.month < 12:
        annual_factor = min(12.0 / max(period_end.month, 1), 1.8)
        if express_netprofit is not None:
            express_netprofit = express_netprofit * annual_factor
        if express_revenue is not None:
            express_revenue = express_revenue * annual_factor

    if express_netprofit is not None:
        adjusted["netprofit"] = _blend_preferred_local(express_netprofit, adjusted.get("netprofit"), alpha=0.7)
    if express_revenue is not None:
        adjusted["revenue"] = _blend_preferred_local(express_revenue, adjusted.get("revenue"), alpha=0.7)

    adjusted["express_end_date"] = express_row.get("end_date")
    adjusted["express_ann_date"] = express_row.get("ann_date")
    adjusted["profit_data_source"] = "express_vip"
    if (
        parsed_base_end_date is not None
        and period_end is not None
        and period_end <= parsed_base_end_date
    ):
        adjusted["profit_data_source"] = "express_vip_blended"
    return adjusted


def _db_assumption_to_dict(assumption_obj, source):
    return {
        "pe_target": assumption_obj.pe_target,
        "pb_target": assumption_obj.pb_target,
        "ps_target": assumption_obj.ps_target,
        "peg_target": assumption_obj.peg_target,
        "ev_ebitda_target": None,
        "discount_rate": assumption_obj.discount_rate,
        "terminal_growth_rate": assumption_obj.terminal_growth_rate,
        "dcf_kwargs": {
            "discount_rate": assumption_obj.discount_rate,
            "terminal_growth_rate": assumption_obj.terminal_growth_rate,
        },
        "ddm_kwargs": {
            "discount_rate": assumption_obj.discount_rate,
            "dividend_growth_rate": assumption_obj.terminal_growth_rate,
        },
        "scenario_model": "fcff_dcf",
        "assumption_industry": assumption_obj.industry,
        "source": source,
    }


def _template_to_assumption(template_payload):
    params = (template_payload or {}).get("params") or {}
    dcf_kwargs = params.get("dcf_kwargs") or {}
    ddm_kwargs = params.get("ddm_kwargs") or {}
    discount_rate = _positive(dcf_kwargs.get("discount_rate"))
    if discount_rate is None:
        discount_rate = 0.10
    terminal_growth_rate = _safe_float(dcf_kwargs.get("terminal_growth_rate"))
    if terminal_growth_rate is None:
        terminal_growth_rate = 0.03

    return {
        "pe_target": _positive(params.get("pe_target")) or 15.0,
        "pb_target": _positive(params.get("pb_target")) or 2.0,
        "ps_target": _positive(params.get("ps_target")) or 2.0,
        "peg_target": _positive(params.get("peg_target")) or 1.0,
        "ev_ebitda_target": _positive(params.get("ev_ebitda_target")),
        "discount_rate": discount_rate,
        "terminal_growth_rate": terminal_growth_rate,
        "dcf_kwargs": {
            "discount_rate": discount_rate,
            "terminal_growth_rate": terminal_growth_rate,
            "growth_rates": dcf_kwargs.get("growth_rates"),
        },
        "ddm_kwargs": {
            "discount_rate": _positive(ddm_kwargs.get("discount_rate")) or discount_rate,
            "dividend_growth_rate": _safe_float(ddm_kwargs.get("dividend_growth_rate"))
            if _safe_float(ddm_kwargs.get("dividend_growth_rate")) is not None
            else terminal_growth_rate,
        },
        "scenario_model": params.get("scenario_model") or "fcff_dcf",
        "sensitivity_grid": params.get("sensitivity_grid"),
        "method_weights": params.get("method_weights") if isinstance(params.get("method_weights"), dict) else None,
        "scarcity_kwargs": params.get("scarcity_kwargs") if isinstance(params.get("scarcity_kwargs"), dict) else None,
        "assumption_metrics": template_payload.get("metrics") if isinstance(template_payload.get("metrics"), dict) else None,
        "assumption_industry_name": template_payload.get("industry_name"),
        "assumption_hierarchy": template_payload.get("hierarchy"),
        "source": template_payload.get("source") or "template",
    }


def _is_bank_like_snapshot(snapshot):
    industry = str(snapshot.get("industry") or "")
    assumption = snapshot.get("assumption") or {}
    assumption_industry = str(assumption.get("assumption_industry") or "")
    assumption_industry_name = str(assumption.get("assumption_industry_name") or "")
    hierarchy = assumption.get("assumption_hierarchy") or {}
    l1_name = str(hierarchy.get("l1_name") or "")
    return any("银行" in value for value in [industry, assumption_industry, assumption_industry_name, l1_name])


def _ev_ebitda_block_reason(snapshot):
    if _is_bank_like_snapshot(snapshot):
        return "industry_not_applicable_bank"
    if _safe_float(snapshot.get("ebitda")) in (None, 0):
        return "missing_ebitda"
    return None


def _fallback_model_for_bank(snapshot):
    if _positive(snapshot.get("pb")) and _positive((snapshot.get("assumption") or {}).get("pb_target")):
        return "pb"
    if _positive(snapshot.get("pe_ttm")) and _positive((snapshot.get("assumption") or {}).get("pe_target")):
        return "pe"
    return "fcff_dcf"


def _get_assumption(ts_code, industry):
    template_payload = resolve_template_params(
        base_dir=Path(settings.BASE_DIR),
        ts_code=ts_code,
        industry=industry or "",
        market="CN",
    )
    if template_payload:
        return _template_to_assumption(template_payload)

    if industry:
        industry_override = ValuationAssumption.objects.filter(industry=industry).first()
        if industry_override is not None:
            return _db_assumption_to_dict(industry_override, source="db_industry_override")

    default_override = ValuationAssumption.objects.filter(industry="__default__").first()
    if default_override is not None:
        return _db_assumption_to_dict(default_override, source="db_default_override")

    return {
        "pe_target": 15.0,
        "pb_target": 2.0,
        "ps_target": 2.0,
        "peg_target": 1.0,
        "ev_ebitda_target": 9.0,
        "discount_rate": 0.10,
        "terminal_growth_rate": 0.03,
        "dcf_kwargs": {
            "discount_rate": 0.10,
            "terminal_growth_rate": 0.03,
        },
        "ddm_kwargs": {
            "discount_rate": 0.10,
            "dividend_growth_rate": 0.03,
        },
        "scenario_model": "fcff_dcf",
        "method_weights": None,
        "scarcity_kwargs": None,
        "source": "hardcoded_default",
    }


def _normalize_method_weight_map(weight_map):
    if not isinstance(weight_map, dict):
        return {}
    normalized = {}
    for key, value in weight_map.items():
        method = str(key or "").strip().lower()
        weight = _safe_float(value)
        if not method or weight is None or weight <= 0:
            continue
        normalized[method] = weight
    return normalized


def _normalize_history_years(years):
    if years is None:
        return [3, 5, 10]
    if isinstance(years, (int, float)):
        values = [int(years)]
    else:
        values = []
        for item in years:
            try:
                values.append(int(item))
            except (TypeError, ValueError):
                continue
    deduped = sorted({value for value in values if value > 0})
    return deduped or [3, 5, 10]


def _build_sw_history_variant(sw_history_kwargs=None):
    payload = sw_history_kwargs or {}
    years = _normalize_history_years(payload.get("history_years"))
    quantile = _safe_float(payload.get("history_quantile"))
    if quantile is None:
        quantile = 0.5
    min_samples = int(_safe_float(payload.get("history_min_samples")) or 120)
    year_part = "-".join(str(year) for year in years)
    quantile_part = int(round(quantile * 100))
    return f"hist_y{year_part}_q{quantile_part}_m{min_samples}"


def _build_sw_history_component_rows(snapshot, valuations_df, sw_history_kwargs=None):
    if valuations_df is None or valuations_df.empty:
        return []
    if "method" not in valuations_df.columns or "implied_price" not in valuations_df.columns:
        return []

    variant = _build_sw_history_variant(sw_history_kwargs)
    rows = []
    for method in ["pe", "pb", "ps"]:
        method_rows = valuations_df[valuations_df["method"].astype(str).str.lower() == method]
        if method_rows.empty:
            continue

        implied_series = pd.to_numeric(method_rows["implied_price"], errors="coerce").dropna()
        if implied_series.empty:
            continue
        implied_price = float(implied_series.iloc[0])

        equity_value = None
        if "equity_value" in method_rows.columns:
            equity_series = pd.to_numeric(method_rows["equity_value"], errors="coerce").dropna()
            if not equity_series.empty:
                equity_value = float(equity_series.iloc[0])

        rows.append(
            {
                "method": method,
                "equity_value": equity_value,
                "implied_price": implied_price,
                "valuation_variant": variant,
                "compare_group": "sw_history_anchor",
                "industry_level": None,
                "industry_code": None,
                "industry_name": snapshot.get("industry"),
            }
        )
    return rows


def _build_sw_history_aggregate(component_rows):
    if not component_rows:
        return None
    implied_prices = [
        _safe_float(row.get("implied_price"))
        for row in component_rows
        if _safe_float(row.get("implied_price")) is not None
    ]
    if not implied_prices:
        return None

    equity_values = [
        _safe_float(row.get("equity_value"))
        for row in component_rows
        if _safe_float(row.get("equity_value")) is not None
    ]

    return {
        "method": "sw_history",
        "equity_value": float(pd.Series(equity_values, dtype="float64").median()) if equity_values else None,
        "implied_price": float(pd.Series(implied_prices, dtype="float64").median()),
        "valuation_variant": component_rows[0].get("valuation_variant"),
        "compare_group": "sw_history_anchor",
        "industry_level": component_rows[0].get("industry_level"),
        "industry_code": component_rows[0].get("industry_code"),
        "industry_name": component_rows[0].get("industry_name"),
    }


def _clamp_unit(value, default=None):
    value_float = _safe_float(value)
    if value_float is None:
        return default
    return max(0.0, min(1.0, value_float))


def _resolve_scarcity_inputs(snapshot, valuations_df, scarcity_kwargs=None):
    assumption = snapshot.get("assumption") or {}
    payload = dict(assumption.get("scarcity_kwargs") or {})
    if isinstance(scarcity_kwargs, dict):
        for key, value in scarcity_kwargs.items():
            if value is not None:
                payload[key] = value

    enabled = payload.get("enabled")
    if enabled is None:
        enabled = False
    if not bool(enabled):
        return None

    beta = _safe_float(payload.get("beta"))
    if beta is None:
        beta = 1.0
    cap_pct = _safe_float(payload.get("cap_pct"))
    if cap_pct is None:
        cap_pct = 80.0

    metrics = assumption.get("assumption_metrics") or {}
    member_count = _safe_float(metrics.get("member_count"))
    sample_count = _safe_float(metrics.get("sample_count"))
    growth_median_pct = _safe_float(metrics.get("growth_median_pct"))

    score = _clamp_unit(payload.get("score"))
    if score is None:
        member_scarcity = 0.35
        if member_count is not None:
            if member_count <= 5:
                member_scarcity = 1.0
            elif member_count <= 10:
                member_scarcity = 0.85
            elif member_count <= 20:
                member_scarcity = 0.65
            elif member_count <= 40:
                member_scarcity = 0.45
            else:
                member_scarcity = 0.25
        growth_signal = _clamp_unit((growth_median_pct or 0.0) / 40.0, default=0.0) or 0.0
        score = max(0.0, min(1.0, member_scarcity * 0.7 + growth_signal * 0.3))

    confidence = _clamp_unit(payload.get("confidence"))
    if confidence is None:
        sample_factor = _clamp_unit((sample_count or 0.0) / 3.0, default=0.0) or 0.0
        report_type = _infer_report_type(_parse_any_date(snapshot.get("report_date")))
        report_factor = {
            "ANNUAL": 1.0,
            "Q3": 0.85,
            "H1": 0.75,
            "Q1": 0.65,
        }.get(report_type, 0.7)

        anchor_count = 0
        if valuations_df is not None and not valuations_df.empty and "method" in valuations_df.columns:
            for method in ["pe", "pb", "ps", "sw_history"]:
                row_df = valuations_df[valuations_df["method"].astype(str).str.lower() == method]
                if row_df.empty:
                    continue
                if "implied_price" not in row_df.columns:
                    continue
                series = pd.to_numeric(row_df["implied_price"], errors="coerce").dropna()
                if not series.empty and float(series.iloc[0]) > 0:
                    anchor_count += 1
        anchor_factor = _clamp_unit(anchor_count / 3.0, default=0.0) or 0.0
        confidence = sample_factor * 0.5 + report_factor * 0.3 + anchor_factor * 0.2

    confidence_floor = _clamp_unit(payload.get("confidence_floor"), default=0.35)
    confidence = max(confidence, confidence_floor)

    premium_pct = min(max(beta * score * confidence * 100.0, 0.0), max(cap_pct, 0.0))
    if premium_pct <= 0:
        return None

    return {
        "beta": beta,
        "cap_pct": cap_pct,
        "score": score,
        "confidence": confidence,
        "premium_pct": premium_pct,
    }


def _select_scarcity_base_row(valuations_df):
    if valuations_df is None or valuations_df.empty:
        return None
    if "method" not in valuations_df.columns or "implied_price" not in valuations_df.columns:
        return None

    candidates = []
    for _, row in valuations_df.iterrows():
        method = str(row.get("method") or "").strip().lower()
        implied_price = _safe_float(row.get("implied_price"))
        equity_value = _safe_float(row.get("equity_value"))
        variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
        if not method or implied_price is None or implied_price <= 0:
            continue
        if variant != "default":
            continue
        candidates.append(
            {
                "method": method,
                "implied_price": implied_price,
                "equity_value": equity_value,
                "industry_level": row.get("industry_level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
            }
        )

    if not candidates:
        return None

    preference = {"sw_history": 0, "weighted": 1, "ps": 2, "pb": 3, "pe": 4}
    candidates.sort(key=lambda item: preference.get(item.get("method"), 100))
    return candidates[0]


def _build_scarcity_overlay_row(snapshot, valuations_df, scarcity_kwargs=None):
    base_row = _select_scarcity_base_row(valuations_df)
    if base_row is None:
        return None

    scarcity_inputs = _resolve_scarcity_inputs(
        snapshot=snapshot,
        valuations_df=valuations_df,
        scarcity_kwargs=scarcity_kwargs,
    )
    if scarcity_inputs is None:
        return None

    multiplier = 1.0 + scarcity_inputs["premium_pct"] / 100.0
    base_price = base_row.get("implied_price")
    base_equity = base_row.get("equity_value")
    scarcity_price = base_price * multiplier if base_price is not None else None
    scarcity_equity = base_equity * multiplier if base_equity is not None else None

    return {
        "method": "scarcity_overlay",
        "equity_value": scarcity_equity,
        "implied_price": scarcity_price,
        "valuation_variant": "default",
        "compare_group": "scarcity_overlay",
        "industry_level": base_row.get("industry_level"),
        "industry_code": base_row.get("industry_code"),
        "industry_name": base_row.get("industry_name") or snapshot.get("industry"),
        "source": "scarcity_model",
        "scarcity_base_method": base_row.get("method"),
        "scarcity_score": round(scarcity_inputs["score"], 4),
        "scarcity_confidence": round(scarcity_inputs["confidence"], 4),
        "scarcity_beta": round(scarcity_inputs["beta"], 4),
        "scarcity_cap_pct": round(scarcity_inputs["cap_pct"], 2),
        "scarcity_premium_pct": round(scarcity_inputs["premium_pct"], 2),
    }


def _normalize_valuation_variant(value, fallback="default"):
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return fallback
    return text


def _build_weighted_valuation(snapshot, valuations_df):
    if valuations_df is None or valuations_df.empty:
        return {
            "weighted_price": None,
            "weighted_equity_value": None,
            "weights": {},
            "weight_source": None,
        }

    preferred = _normalize_method_weight_map((snapshot.get("assumption") or {}).get("method_weights"))
    weight_source = "assumption"

    candidate_rows = []
    for _, row in valuations_df.iterrows():
        method = str(row.get("method") or "").strip().lower()
        valuation_variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
        if valuation_variant != "default":
            continue
        implied_price = _positive(row.get("implied_price"))
        if not method or implied_price is None:
            continue
        if method == "market_cap":
            continue
        weight = preferred.get(method)
        if weight is None:
            continue
        candidate_rows.append((method, implied_price, float(weight)))

    if not candidate_rows:
        return {
            "weighted_price": None,
            "weighted_equity_value": None,
            "weights": {},
            "weight_source": weight_source if preferred else None,
        }

    total_weight = sum(weight for _, _, weight in candidate_rows)
    if total_weight <= 0:
        return {
            "weighted_price": None,
            "weighted_equity_value": None,
            "weights": {},
            "weight_source": weight_source if preferred else None,
        }

    normalized_rows = []
    for method, price, weight in candidate_rows:
        normalized_rows.append((method, price, weight / total_weight))

    weighted_price = sum(price * weight for _, price, weight in normalized_rows)
    shares = _positive(snapshot.get("total_share"))
    weighted_equity = weighted_price * shares if shares is not None else None

    return {
        "weighted_price": weighted_price,
        "weighted_equity_value": weighted_equity,
        "weights": {method: round(weight, 6) for method, _, weight in normalized_rows},
        "weight_source": weight_source,
    }


def _infer_report_type(report_date):
    if not isinstance(report_date, datetime.date):
        return None
    if report_date.month == 3:
        return "Q1"
    if report_date.month == 6:
        return "H1"
    if report_date.month == 9:
        return "Q3"
    if report_date.month == 12:
        return "ANNUAL"
    return "OTHER"


def _resolve_snapshot_industry_meta(snapshot):
    assumption = snapshot.get("assumption") or {}
    hierarchy = assumption.get("assumption_hierarchy") or {}

    for level_key, code_key, name_key in [
        ("L3", "l3_code", "l3_name"),
        ("L2", "l2_code", "l2_name"),
        ("L1", "l1_code", "l1_name"),
    ]:
        code = hierarchy.get(code_key)
        name = hierarchy.get(name_key)
        if code or name:
            return {
                "industry_level": level_key,
                "industry_code": code,
                "industry_name": name or snapshot.get("industry"),
            }

    return {
        "industry_level": None,
        "industry_code": None,
        "industry_name": snapshot.get("industry"),
    }


def _persist_valuation_rows(snapshot, valuations_df, weighted_payload=None, market="CN", persist_context=None):
    if valuations_df is None or valuations_df.empty:
        return
    ts_code = str(snapshot.get("ts_code") or "").strip()
    trade_date = _parse_any_date(snapshot.get("trade_date"))
    if not ts_code or trade_date is None:
        return

    persist_context = persist_context or {}
    default_variant = _resolve_valuation_variant(persist_context)

    rows = []
    for _, row in valuations_df.iterrows():
        method = str(row.get("method") or "").strip().lower()
        implied_price = _safe_float(row.get("implied_price"))
        if not method or implied_price is None:
            continue
        rows.append(
            {
                "valuation_method": method,
                "valuation_price": implied_price,
                "valuation_market_cap": _safe_float(row.get("equity_value")),
                "valuation_variant": _normalize_valuation_variant(row.get("valuation_variant"), fallback=default_variant),
                "source": str(row.get("source") or "live_compute"),
                "industry_level": row.get("industry_level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
                "compare_group": row.get("compare_group"),
            }
        )

    weighted_payload = weighted_payload or {}
    weighted_price = _safe_float(weighted_payload.get("weighted_price"))
    if weighted_price is not None:
        rows.append(
            {
                "valuation_method": "weighted",
                "valuation_price": weighted_price,
                "valuation_market_cap": _safe_float(weighted_payload.get("weighted_equity_value")),
                "valuation_variant": default_variant,
                "source": "live_weighted",
            }
        )

    if not rows:
        return

    industry_meta = _resolve_snapshot_industry_meta(snapshot)
    report_end_date = _parse_any_date(snapshot.get("report_date"))
    express_end_date = _parse_any_date(snapshot.get("express_end_date"))
    express_ann_date = _parse_any_date(snapshot.get("express_ann_date"))
    report_type = _infer_report_type(report_end_date)

    extra_defaults = {
        "industry_level": persist_context.get("industry_level") or industry_meta.get("industry_level"),
        "industry_code": persist_context.get("industry_code") or industry_meta.get("industry_code"),
        "industry_name": persist_context.get("industry_name") or industry_meta.get("industry_name"),
        "compare_group": persist_context.get("compare_group"),
        "match_score": _safe_float(persist_context.get("match_score")),
        "profit_data_source": snapshot.get("profit_data_source"),
        "profit_report_end_date": report_end_date,
        "profit_report_type": report_type,
        "express_end_date": express_end_date,
        "express_ann_date": express_ann_date,
        "express_apply_reason": snapshot.get("express_apply_reason"),
        "express_block_reason": snapshot.get("express_block_reason"),
        "strict_express_match": snapshot.get("strict_express_match"),
        "express_max_age_days": snapshot.get("express_max_age_days"),
    }

    with transaction.atomic():
        for row in rows:
            row_industry_level = row.get("industry_level") or persist_context.get("industry_level") or industry_meta.get("industry_level")
            row_industry_code = row.get("industry_code") or persist_context.get("industry_code") or industry_meta.get("industry_code")
            row_industry_name = row.get("industry_name") or persist_context.get("industry_name") or industry_meta.get("industry_name")
            row_compare_group = row.get("compare_group") or persist_context.get("compare_group")
            defaults = {
                "valuation_price": row["valuation_price"],
                "valuation_market_cap": row["valuation_market_cap"],
                "source": row["source"],
                **{
                    **extra_defaults,
                    "industry_level": row_industry_level,
                    "industry_code": row_industry_code,
                    "industry_name": row_industry_name,
                    "compare_group": row_compare_group,
                },
            }
            ValuationSnapshot.objects.update_or_create(
                ts_code=ts_code,
                trade_date=trade_date,
                market=market,
                valuation_method=row["valuation_method"],
                valuation_variant=row["valuation_variant"],
                defaults=defaults,
            )
            ValuationSnapshotLatest.objects.update_or_create(
                ts_code=ts_code,
                market=market,
                valuation_method=row["valuation_method"],
                valuation_variant=row["valuation_variant"],
                defaults={
                    "latest_trade_date": trade_date,
                    **defaults,
                },
            )


def get_local_valuation_snapshot(
    ts_code,
    trade_date=None,
    freq="D",
    strict_express_match=True,
    express_max_age_days=180,
):
    target_date = _resolve_trade_date(trade_date)

    trading_qs = StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
    if target_date is not None:
        trading_qs = trading_qs.filter(trade_date__lte=target_date)
    trading_row = (
        trading_qs.order_by("-trade_date")
        .values("trade_date", "close_qfq", "close")
        .first()
    )

    current_price = None
    total_share = None
    market_cap = None
    if trading_row:
        current_price = trading_row.get("close_qfq")

    profile = CompanyProfile.objects.filter(ts_code=ts_code).first()
    industry = profile.industry if profile else ""
    assumption = _get_assumption(ts_code, industry)

    fundamental_qs = StockFundamentalSnapshot.objects.filter(ts_code=ts_code, freq=freq)
    if target_date is not None:
        fundamental_qs = fundamental_qs.filter(trade_date__lte=target_date)
    fundamental = fundamental_qs.order_by("-trade_date").first()

    if fundamental is not None:
        # Prefer migrated local fundamental snapshot as the primary source.
        total_share = getattr(fundamental, "total_share", None)
        market_cap = getattr(fundamental, "total_mv", None)

    total_share = _safe_float(total_share)
    market_cap = _safe_float(market_cap)
    if total_share is not None:
        total_share *= 10000.0
    if market_cap is not None:
        market_cap *= 10000.0

    pe_ttm = _positive(getattr(fundamental, "pe_ttm", None))
    pb = _positive(getattr(fundamental, "pb", None))
    ps_ttm = _positive(getattr(fundamental, "ps_ttm", None))
    np_yoy = None
    netprofit = None
    revenue = None
    equity_book_value = None
    fcff_per_share = None
    dividend_per_share = None
    ebitda = None
    cash = None
    debt = None
    financial_metrics = None
    financial_data_source = None
    financial_data_reason = None

    express_qs = StockExpressVip.objects.filter(ts_code=ts_code)
    if target_date is not None:
        express_qs = express_qs.filter(ann_date__lte=target_date)
    express_row_obj = express_qs.order_by("-end_date", "-ann_date").first()
    express_row = None
    if express_row_obj is not None:
        express_row = {
            "ann_date": _parse_any_date(getattr(express_row_obj, "ann_date", None)),
            "end_date": _parse_any_date(getattr(express_row_obj, "end_date", None)),
            "revenue": getattr(express_row_obj, "revenue", None),
            "total_revenue": getattr(express_row_obj, "total_revenue", None),
            "oper_rev": getattr(express_row_obj, "oper_rev", None),
            "n_income": getattr(express_row_obj, "n_income", None),
            "n_income_attr_p": getattr(express_row_obj, "n_income_attr_p", None),
            "profit_dedt": getattr(express_row_obj, "profit_dedt", None),
            "yoy_net_profit": getattr(express_row_obj, "yoy_net_profit", None),
            "yoy_dedu_np": getattr(express_row_obj, "yoy_dedu_np", None),
            "yoy_sales": getattr(express_row_obj, "yoy_sales", None),
            "yoy_np": getattr(express_row_obj, "yoy_np", None),
            "netprofit_yoy": getattr(express_row_obj, "netprofit_yoy", None),
            "tr_yoy": getattr(express_row_obj, "tr_yoy", None),
            "or_yoy": getattr(express_row_obj, "or_yoy", None),
        }
    elif bool(getattr(settings, "ENABLE_TUSHARE_FINANCIAL_FALLBACK", True)):
        express_row = _fetch_tushare_express_row(ts_code=ts_code, trade_date=target_date)

    if market_cap is None:
        price_val = _positive(current_price)
        shares = _positive(total_share)
        if price_val is not None and shares is not None:
            market_cap = price_val * shares

    if bool(getattr(settings, "ENABLE_TUSHARE_FINANCIAL_FALLBACK", True)):
        financial_metrics = _fetch_tushare_financial_metrics(ts_code=ts_code, trade_date=target_date)
        if ebitda is None:
            ebitda = _safe_float(financial_metrics.get("ebitda"))
        if cash is None:
            cash = _safe_float(financial_metrics.get("cash"))
        if debt is None:
            debt = _safe_float(financial_metrics.get("debt"))
        if netprofit is None:
            netprofit = _safe_float(financial_metrics.get("netprofit"))
        if revenue is None:
            revenue = _safe_float(financial_metrics.get("revenue"))
        if equity_book_value is None:
            equity_book_value = _safe_float(financial_metrics.get("equity_book_value"))
        if np_yoy is None:
            np_yoy = _safe_float(financial_metrics.get("peg_growth_yoy_pct"))
        if fcff_per_share is None:
            fcff_total = _safe_float(financial_metrics.get("fcff"))
            shares_val = _positive(total_share)
            if fcff_total is not None and shares_val is not None:
                fcff_per_share = fcff_total / shares_val
        if dividend_per_share is None:
            dividend_per_10 = _safe_float(financial_metrics.get("dividend_per_10"))
            if dividend_per_10 is not None:
                dividend_per_share = dividend_per_10 / 10.0
        financial_data_source = financial_metrics.get("source")
        financial_data_reason = financial_metrics.get("reason")

    report_end_date = _parse_any_date(financial_metrics.get("report_end_date")) if financial_metrics else None
    if report_end_date is None:
        report_end_date = _parse_any_date(getattr(fundamental, "trade_date", None))

    if netprofit is None and market_cap is not None and pe_ttm not in (None, 0):
        netprofit = market_cap / pe_ttm
    if revenue is None and market_cap is not None and ps_ttm not in (None, 0):
        revenue = market_cap / ps_ttm
    if equity_book_value is None and market_cap is not None and pb not in (None, 0):
        equity_book_value = market_cap / pb

    base_end_date = report_end_date
    profit_data_source = "local_fundamental_snapshot"
    express_apply_reason = "no_express_row"
    express_block_reason = None
    express_end_date = None
    express_ann_date = None

    snapshot = {
        "ts_code": ts_code,
        "trade_date": (
            trading_row.get("trade_date") if trading_row else getattr(fundamental, "trade_date", None)
        ),
        "report_date": report_end_date,
        "close_price": _safe_float(current_price),
        "total_share": _safe_float(total_share),
        "market_cap": _safe_float(market_cap),
        "industry": industry,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "ps_ttm": ps_ttm,
        "peg_growth_yoy_pct": _safe_float(np_yoy),
        "fcff": _safe_float(financial_metrics.get("fcff")) if financial_metrics else None,
        "fcff_per_share": _safe_float(fcff_per_share),
        "dividend_per_share": _safe_float(dividend_per_share),
        "profit_data_source": profit_data_source,
        "base_peg_growth_yoy_pct": _safe_float(np_yoy),
        "base_netprofit": _safe_float(netprofit),
        "base_revenue": _safe_float(revenue),
        "netprofit": _safe_float(netprofit),
        "revenue": _safe_float(revenue),
        "equity_book_value": _safe_float(equity_book_value),
        "ebitda": _safe_float(ebitda),
        "cash": _safe_float(cash),
        "debt": _safe_float(debt),
        "financial_data_source": financial_data_source,
        "financial_data_reason": financial_data_reason,
        "strict_express_match": bool(strict_express_match),
        "express_max_age_days": int(express_max_age_days),
        "express_end_date": express_end_date,
        "express_ann_date": express_ann_date,
        "express_apply_reason": express_apply_reason,
        "express_block_reason": express_block_reason,
        "assumption": assumption,
        "assumption_source": assumption.get("source"),
    }

    if express_row:
        eligible, reason = _is_express_vip_eligible_local(
            express_row=express_row,
            base_end_date=base_end_date,
            trade_date=snapshot.get("trade_date"),
            strict_match=strict_express_match,
            max_age_days=express_max_age_days,
        )
        snapshot["express_end_date"] = express_row.get("end_date")
        snapshot["express_ann_date"] = express_row.get("ann_date")
        snapshot["express_apply_reason"] = reason
        if eligible:
            snapshot = _apply_express_vip_adjustments_local(
                snapshot=snapshot,
                express_row=express_row,
                base_end_date=base_end_date,
            )
            snapshot["express_apply_reason"] = reason
            snapshot["express_block_reason"] = None
        else:
            snapshot["express_block_reason"] = reason
    else:
        snapshot["express_block_reason"] = "express_vip_not_available_in_local_snapshot"

    return snapshot


def _with_price_info(result, snapshot):
    payload = dict(result)
    payload["total_share"] = snapshot.get("total_share")
    payload["trade_date"] = snapshot.get("trade_date")
    payload["close_price"] = snapshot.get("close_price")
    if payload.get("equity_value") is not None and payload.get("implied_price") is None:
        payload["implied_price"] = _equity_value_to_price(payload.get("equity_value"), snapshot.get("total_share"))
    return payload


def estimate_market_value_local(snapshot):
    market_cap = _safe_float(snapshot.get("market_cap"))
    result = {
        "method": "market_cap",
        "equity_value": market_cap,
        "implied_price": _equity_value_to_price(market_cap, snapshot.get("total_share")),
    }
    return _with_price_info(result, snapshot)


def estimate_by_pe_local(snapshot, target_pe=None):
    price = _positive(snapshot.get("close_price"))
    current_pe = _positive(snapshot.get("pe_ttm"))
    netprofit = _safe_float(snapshot.get("netprofit"))
    shares = _positive(snapshot.get("total_share"))
    applied_pe = _positive(target_pe) or _positive(snapshot.get("assumption", {}).get("pe_target"))
    if applied_pe is None:
        raise ValueError("PE valuation requires close_price, pe_ttm and target_pe.")
    if netprofit is not None and shares is not None:
        equity_value = netprofit * applied_pe
        implied = equity_value / shares
    elif price is not None and current_pe is not None:
        implied = price * applied_pe / current_pe
        equity_value = implied * shares if shares is not None else None
    else:
        raise ValueError("PE valuation requires close_price, pe_ttm and target_pe.")
    result = {
        "method": "pe",
        "implied_price": implied,
        "equity_value": equity_value,
        "applied_multiple": applied_pe,
        "current_multiple": current_pe,
    }
    return _with_price_info(result, snapshot)


def estimate_by_ps_local(snapshot, target_ps=None):
    price = _positive(snapshot.get("close_price"))
    current_ps = _positive(snapshot.get("ps_ttm"))
    revenue = _safe_float(snapshot.get("revenue"))
    shares = _positive(snapshot.get("total_share"))
    applied_ps = _positive(target_ps) or _positive(snapshot.get("assumption", {}).get("ps_target"))
    if applied_ps is None:
        raise ValueError("PS valuation requires close_price, ps_ttm and target_ps.")
    if revenue is not None and shares is not None:
        equity_value = revenue * applied_ps
        implied = equity_value / shares
    elif price is not None and current_ps is not None:
        implied = price * applied_ps / current_ps
        equity_value = implied * shares if shares is not None else None
    else:
        raise ValueError("PS valuation requires close_price, ps_ttm and target_ps.")
    result = {
        "method": "ps",
        "implied_price": implied,
        "equity_value": equity_value,
        "applied_multiple": applied_ps,
        "current_multiple": current_ps,
    }
    return _with_price_info(result, snapshot)


def estimate_by_pb_local(snapshot, target_pb=None):
    price = _positive(snapshot.get("close_price"))
    current_pb = _positive(snapshot.get("pb"))
    equity_book_value = _safe_float(snapshot.get("equity_book_value"))
    shares = _positive(snapshot.get("total_share"))
    applied_pb = _positive(target_pb) or _positive(snapshot.get("assumption", {}).get("pb_target"))
    if applied_pb is None:
        raise ValueError("PB valuation requires close_price, pb and target_pb.")
    if equity_book_value is not None and shares is not None:
        equity_value = equity_book_value * applied_pb
        implied = equity_value / shares
    elif price is not None and current_pb is not None:
        implied = price * applied_pb / current_pb
        equity_value = implied * shares if shares is not None else None
    else:
        raise ValueError("PB valuation requires close_price, pb and target_pb.")
    result = {
        "method": "pb",
        "implied_price": implied,
        "equity_value": equity_value,
        "applied_multiple": applied_pb,
        "current_multiple": current_pb,
    }
    return _with_price_info(result, snapshot)


PEG_MIN_GROWTH_PCT = 1.0
PEG_MAX_GROWTH_PCT = 80.0
PEG_MIN_TARGET_PE = 5.0
PEG_MAX_TARGET_PE = 45.0


def _resolve_peg_inputs(target_peg, growth_pct):
    applied_target_peg = _positive(target_peg)
    if applied_target_peg is None:
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


def estimate_by_peg_local(snapshot, target_peg=None, growth_rate_pct=None):
    growth_pct = growth_rate_pct if growth_rate_pct is not None else snapshot.get("peg_growth_yoy_pct")
    default_target = snapshot.get("assumption", {}).get("peg_target")
    peg_inputs = _resolve_peg_inputs(target_peg if target_peg is not None else default_target, growth_pct)
    result = estimate_by_pe_local(snapshot, target_pe=peg_inputs["derived_target_pe"])
    result.update({"method": "peg", **peg_inputs})
    return result


def estimate_by_fcff_dcf_local(
    snapshot,
    forecast_fcff=None,
    base_fcff=None,
    growth_rates=None,
    discount_rate=None,
    terminal_growth_rate=None,
):
    assumption = snapshot.get("assumption", {})
    dcf_assumption = assumption.get("dcf_kwargs") or {}
    dr = _positive(discount_rate) or _positive(dcf_assumption.get("discount_rate")) or _positive(assumption.get("discount_rate"))
    tgr = _safe_float(terminal_growth_rate)
    if tgr is None:
        tgr = _safe_float(dcf_assumption.get("terminal_growth_rate"))
    if tgr is None:
        tgr = _safe_float(assumption.get("terminal_growth_rate"))
    if dr is None or tgr is None or dr <= tgr:
        raise ValueError("discount_rate must be greater than terminal_growth_rate.")

    if forecast_fcff is None:
        starting_fcff = _safe_float(base_fcff)
        if starting_fcff is None:
            starting_fcff = _safe_float(snapshot.get("fcff"))
        if starting_fcff is None:
            per_share_fcff = _safe_float(snapshot.get("fcff_per_share"))
            shares = _positive(snapshot.get("total_share"))
            if per_share_fcff is not None and shares is not None:
                starting_fcff = per_share_fcff * shares
        if starting_fcff is None:
            raise ValueError("FCFF-DCF requires forecast_fcff or base_fcff/fcff/fcff_per_share.")
        rates = growth_rates or dcf_assumption.get("growth_rates") or [0.08, 0.06, 0.05, 0.04, 0.03]
        forecast_fcff = []
        current_fcff = starting_fcff
        for growth in rates:
            current_fcff = current_fcff * (1 + float(growth))
            forecast_fcff.append(current_fcff)

    present_values = []
    for idx, fcff in enumerate(forecast_fcff, start=1):
        present_values.append(float(fcff) / ((1 + dr) ** idx))

    terminal_fcff = float(forecast_fcff[-1]) * (1 + tgr)
    terminal_value = terminal_fcff / (dr - tgr)
    terminal_pv = terminal_value / ((1 + dr) ** len(forecast_fcff))
    enterprise_value = sum(present_values) + terminal_pv
    debt_value = _safe_float(snapshot.get("debt")) or 0.0
    cash_value = _safe_float(snapshot.get("cash")) or 0.0
    effective_net_debt = debt_value - cash_value
    equity_value = enterprise_value - effective_net_debt

    result = {
        "method": "fcff_dcf",
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "forecast_fcff": forecast_fcff,
        "discount_rate": dr,
        "terminal_growth_rate": tgr,
        "terminal_value": terminal_value,
        "net_debt": effective_net_debt,
    }
    return _with_price_info(result, snapshot)


def estimate_by_ddm_local(
    snapshot,
    annual_dividend=None,
    discount_rate=None,
    dividend_growth_rate=None,
    stage_dividends=None,
    terminal_growth_rate=None,
):
    assumption = snapshot.get("assumption", {})
    ddm_assumption = assumption.get("ddm_kwargs") or {}
    dr = _positive(discount_rate) or _positive(ddm_assumption.get("discount_rate")) or _positive(assumption.get("discount_rate"))
    dgr = _safe_float(dividend_growth_rate)
    if dgr is None:
        dgr = _safe_float(ddm_assumption.get("dividend_growth_rate"))
    if dgr is None:
        dgr = _safe_float(assumption.get("terminal_growth_rate"))
    tgr = dgr if terminal_growth_rate is None else float(terminal_growth_rate)
    if dr is None:
        raise ValueError("DDM requires discount_rate.")

    if stage_dividends:
        if dr <= tgr:
            raise ValueError("discount_rate must be greater than terminal_growth_rate.")
        present_values = [
            float(dividend) / ((1 + dr) ** idx)
            for idx, dividend in enumerate(stage_dividends, start=1)
        ]
        final_dividend = float(stage_dividends[-1]) * (1 + tgr)
        terminal_value = final_dividend / (dr - tgr)
        implied_price = sum(present_values) + terminal_value / ((1 + dr) ** len(stage_dividends))
        result = {
            "method": "ddm",
            "implied_price": implied_price,
            "equity_value": implied_price * float(snapshot.get("total_share")) if _positive(snapshot.get("total_share")) else None,
            "stage_dividends": stage_dividends,
            "discount_rate": dr,
            "terminal_growth_rate": tgr,
        }
        return _with_price_info(result, snapshot)

    dividend_per_share = _safe_float(annual_dividend)
    if dividend_per_share is None:
        dividend_per_share = _safe_float(snapshot.get("dividend_per_share"))
    if dividend_per_share is None:
        raise ValueError("DDM requires annual_dividend or dividend_per_share.")
    if dr <= dgr:
        raise ValueError("discount_rate must be greater than dividend_growth_rate.")

    implied_price = dividend_per_share * (1 + dgr) / (dr - dgr)
    result = {
        "method": "ddm",
        "implied_price": implied_price,
        "equity_value": implied_price * float(snapshot.get("total_share")) if _positive(snapshot.get("total_share")) else None,
        "annual_dividend": dividend_per_share,
        "discount_rate": dr,
        "dividend_growth_rate": dgr,
    }
    return _with_price_info(result, snapshot)


def estimate_by_ev_ebitda_local(snapshot, target_ev_ebitda=None):
    block_reason = _ev_ebitda_block_reason(snapshot)
    if block_reason == "industry_not_applicable_bank":
        raise ValueError("EV/EBITDA valuation skipped: industry not applicable for banks.")

    ebitda = _safe_float(snapshot.get("ebitda"))
    if ebitda in (None, 0):
        raise ValueError("EV/EBITDA valuation requires EBITDA.")
    applied_target = _positive(target_ev_ebitda) or _positive(snapshot.get("assumption", {}).get("ev_ebitda_target"))
    if applied_target is None:
        raise ValueError("EV/EBITDA valuation requires ev_ebitda_target.")

    debt = _safe_float(snapshot.get("debt")) or 0.0
    cash = _safe_float(snapshot.get("cash")) or 0.0
    enterprise_value = ebitda * applied_target
    equity_value = enterprise_value - debt + cash
    result = {
        "method": "ev_ebitda",
        "implied_price": _equity_value_to_price(equity_value, snapshot.get("total_share")),
        "equity_value": equity_value,
        "enterprise_value": enterprise_value,
        "ebitda": ebitda,
        "target_ev_ebitda": applied_target,
        "cash": cash,
        "debt": debt,
    }
    return _with_price_info(result, snapshot)


def _run_model(snapshot, model_name, model_kwargs=None):
    kwargs = model_kwargs or {}
    if model_name == "fcff_dcf":
        return estimate_by_fcff_dcf_local(snapshot, **kwargs)
    if model_name == "ddm":
        return estimate_by_ddm_local(snapshot, **kwargs)
    if model_name == "pe":
        return estimate_by_pe_local(snapshot, target_pe=kwargs.get("target_pe"))
    if model_name == "ps":
        return estimate_by_ps_local(snapshot, target_ps=kwargs.get("target_ps"))
    if model_name == "pb":
        return estimate_by_pb_local(snapshot, target_pb=kwargs.get("target_pb"))
    if model_name == "ev_ebitda":
        return estimate_by_ev_ebitda_local(snapshot, target_ev_ebitda=kwargs.get("target_ev_ebitda"))
    raise ValueError(f"Unsupported model: {model_name}")


def summarize_valuation_range(valuation_results, total_share=None):
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
            "min_display": f"{_fmt_equity(equity_min)}{equity_unit_label}" if equity_min is not None else None,
            "max_display": f"{_fmt_equity(equity_max)}{equity_unit_label}" if equity_max is not None else None,
            "mid_display": f"{_fmt_equity(equity_mid)}{equity_unit_label}" if equity_mid is not None else None,
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
            "min_display": f"{_fmt_number(price_min, price_decimals)}元" if price_min is not None else None,
            "max_display": f"{_fmt_number(price_max, price_decimals)}元" if price_max is not None else None,
            "mid_display": f"{_fmt_number(price_mid, price_decimals)}元" if price_mid is not None else None,
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
            "min_display": f"{round(price_upside_min * 100, 2)}%" if price_upside_min is not None else None,
            "max_display": f"{round(price_upside_max * 100, 2)}%" if price_upside_max is not None else None,
            "mid_display": f"{round(price_upside_mid * 100, 2)}%" if price_upside_mid is not None else None,
        },
        "total_share": summary.get("total_share"),
        "current_price": current_price,
    }


def run_valuation_scenarios(snapshot, model_name, scenarios, base_kwargs=None):
    base_kwargs = base_kwargs or {}
    results = []
    for scenario_name, scenario_kwargs in scenarios.items():
        merged_kwargs = {**base_kwargs, **scenario_kwargs}
        valuation = _run_model(snapshot, model_name, merged_kwargs)
        valuation["scenario"] = scenario_name
        results.append(valuation)
    df = pd.DataFrame(results)
    summary = summarize_valuation_range(df, total_share=snapshot.get("total_share"))
    for key, value in summary.items():
        df[key] = value
    return df


def run_sensitivity_analysis(snapshot, model_name, base_kwargs, variable_grid):
    records = []
    for variable_name, values in variable_grid.items():
        for value in values:
            kwargs = dict(base_kwargs)
            kwargs[variable_name] = value
            valuation = _run_model(snapshot, model_name, kwargs)
            records.append(
                {
                    "variable": variable_name,
                    "value": value,
                    "method": valuation.get("method"),
                    "equity_value": valuation.get("equity_value"),
                    "implied_price": valuation.get("implied_price"),
                    "total_share": valuation.get("total_share"),
                }
            )
    df = pd.DataFrame(records)
    summary = summarize_valuation_range(df, total_share=snapshot.get("total_share"))
    for key, value in summary.items():
        df[key] = value
    return df


def estimate_all_supported_methods_local(
    snapshot,
    pe_target=None,
    ps_target=None,
    pb_target=None,
    peg_target=None,
    ev_ebitda_target=None,
    dcf_kwargs=None,
    ddm_kwargs=None,
    sw_history_kwargs=None,
    scarcity_kwargs=None,
):
    results = []
    market_val = estimate_market_value_local(snapshot)
    if market_val.get("equity_value") is not None:
        results.append(market_val)

    try:
        results.append(estimate_by_pe_local(snapshot, target_pe=pe_target))
    except ValueError:
        pass
    try:
        results.append(estimate_by_ps_local(snapshot, target_ps=ps_target))
    except ValueError:
        pass
    try:
        results.append(estimate_by_pb_local(snapshot, target_pb=pb_target))
    except ValueError:
        pass
    try:
        results.append(estimate_by_peg_local(snapshot, target_peg=peg_target))
    except ValueError:
        pass
    try:
        results.append(estimate_by_ev_ebitda_local(snapshot, target_ev_ebitda=ev_ebitda_target))
    except ValueError:
        pass

    dcf_kwargs = dcf_kwargs or {}
    ddm_kwargs = ddm_kwargs or {}
    try:
        results.append(estimate_by_fcff_dcf_local(snapshot, **dcf_kwargs))
    except ValueError:
        pass
    try:
        results.append(estimate_by_ddm_local(snapshot, **ddm_kwargs))
    except ValueError:
        pass

    base_df = pd.DataFrame(results)
    history_component_rows = _build_sw_history_component_rows(
        snapshot=snapshot,
        valuations_df=base_df,
        sw_history_kwargs=sw_history_kwargs,
    )
    if history_component_rows:
        results.extend(history_component_rows)
        history_aggregate = _build_sw_history_aggregate(history_component_rows)
        if history_aggregate is not None:
            results.append(history_aggregate)

    scarcity_overlay = _build_scarcity_overlay_row(
        snapshot=snapshot,
        valuations_df=pd.DataFrame(results),
        scarcity_kwargs=scarcity_kwargs,
    )
    if scarcity_overlay is not None:
        results.append(scarcity_overlay)

    df = pd.DataFrame(results)
    weighted_payload = _build_weighted_valuation(snapshot, df)
    if "method" in df.columns:
        weight_map = weighted_payload.get("weights") or {}
        df["method_weight"] = df["method"].apply(
            lambda method: _safe_float(weight_map.get(str(method or "").strip().lower()))
        )
    if "equity_value" in df.columns:
        df["equity_value_亿元"] = df["equity_value"] / 100000000
    summary = summarize_valuation_range(df, total_share=snapshot.get("total_share"))
    for key, value in summary.items():
        df[key] = value
    return df, weighted_payload


def test_valuation_local(
    ts_code,
    trade_date=None,
    current_price=None,
    freq="D",
    pe_target=None,
    ps_target=None,
    pb_target=None,
    peg_target=None,
    ev_ebitda_target=None,
    dcf_kwargs=None,
    ddm_kwargs=None,
    scenario_model="fcff_dcf",
    scenario_overrides=None,
    sensitivity_grid=None,
    snapshot_overrides=None,
    persist_context=None,
    sw_history_kwargs=None,
    scarcity_kwargs=None,
    strict_express_match=True,
    express_max_age_days=180,
):
    snapshot = get_local_valuation_snapshot(
        ts_code=ts_code,
        trade_date=trade_date,
        freq=freq,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    snapshot = _apply_snapshot_overrides(snapshot, snapshot_overrides)
    if current_price is not None:
        snapshot["close_price"] = _safe_float(current_price)

    requested_scenario_model = scenario_model
    ev_ebitda_block_reason = _ev_ebitda_block_reason(snapshot)
    snapshot["ev_ebitda_block_reason"] = ev_ebitda_block_reason
    snapshot["ev_ebitda_applicable"] = ev_ebitda_block_reason is None
    snapshot["requested_scenario_model"] = requested_scenario_model
    snapshot["effective_scenario_model"] = scenario_model
    snapshot["scenario_model_switch_reason"] = None

    if scenario_model == "ev_ebitda" and ev_ebitda_block_reason == "industry_not_applicable_bank":
        scenario_model = _fallback_model_for_bank(snapshot)
        snapshot["effective_scenario_model"] = scenario_model
        snapshot["scenario_model_switch_reason"] = "ev_ebitda_not_applicable_for_bank"

    valuations, weighted_payload = estimate_all_supported_methods_local(
        snapshot=snapshot,
        pe_target=pe_target,
        ps_target=ps_target,
        pb_target=pb_target,
        peg_target=peg_target,
        ev_ebitda_target=ev_ebitda_target,
        dcf_kwargs=dcf_kwargs,
        ddm_kwargs=ddm_kwargs,
        sw_history_kwargs=sw_history_kwargs,
        scarcity_kwargs=scarcity_kwargs,
    )

    formatted_range = format_valuation_range_output(
        valuations,
        total_share=snapshot.get("total_share"),
        current_price=snapshot.get("close_price"),
    )

    persist_enabled = bool(getattr(settings, "ENABLE_VALUATION_SNAPSHOT_PERSIST", True))
    if persist_enabled:
        _persist_valuation_rows(
            snapshot,
            valuations,
            weighted_payload=weighted_payload,
            market="CN",
            persist_context=persist_context,
        )

    dcf_kwargs = dcf_kwargs or {}
    ddm_kwargs = ddm_kwargs or {}

    base_kwargs_map = {
        "fcff_dcf": dict(dcf_kwargs),
        "ddm": dict(ddm_kwargs),
        "pe": {"target_pe": pe_target or snapshot.get("assumption", {}).get("pe_target")},
        "ps": {"target_ps": ps_target or snapshot.get("assumption", {}).get("ps_target")},
        "pb": {"target_pb": pb_target or snapshot.get("assumption", {}).get("pb_target")},
        "ev_ebitda": {
            "target_ev_ebitda": ev_ebitda_target or snapshot.get("assumption", {}).get("ev_ebitda_target")
        },
    }

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
                "discount_rate": dcf_kwargs.get("discount_rate", 0.10),
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
                "discount_rate": ddm_kwargs.get("discount_rate", 0.10),
                "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.03),
            },
            "bull": {
                "discount_rate": ddm_kwargs.get("discount_rate", 0.09),
                "dividend_growth_rate": ddm_kwargs.get("dividend_growth_rate", 0.05),
            },
        }
    elif scenario_model == "pe":
        base_pe = pe_target or snapshot.get("assumption", {}).get("pe_target")
        if _positive(base_pe):
            default_scenarios = {
                "bear": {"target_pe": float(base_pe) * 0.85},
                "base": {"target_pe": float(base_pe)},
                "bull": {"target_pe": float(base_pe) * 1.15},
            }
    elif scenario_model == "ps":
        base_ps = ps_target or snapshot.get("assumption", {}).get("ps_target")
        if _positive(base_ps):
            default_scenarios = {
                "bear": {"target_ps": float(base_ps) * 0.85},
                "base": {"target_ps": float(base_ps)},
                "bull": {"target_ps": float(base_ps) * 1.15},
            }
    elif scenario_model == "pb":
        base_pb = pb_target or snapshot.get("assumption", {}).get("pb_target")
        if _positive(base_pb):
            default_scenarios = {
                "bear": {"target_pb": float(base_pb) * 0.85},
                "base": {"target_pb": float(base_pb)},
                "bull": {"target_pb": float(base_pb) * 1.15},
            }
    elif scenario_model == "ev_ebitda":
        base_ev_ebitda = ev_ebitda_target or snapshot.get("assumption", {}).get("ev_ebitda_target")
        if _positive(base_ev_ebitda):
            default_scenarios = {
                "bear": {"target_ev_ebitda": float(base_ev_ebitda) * 0.85},
                "base": {"target_ev_ebitda": float(base_ev_ebitda)},
                "bull": {"target_ev_ebitda": float(base_ev_ebitda) * 1.15},
            }

    scenario_analysis = None
    if scenario_model in {"fcff_dcf", "ddm", "pe", "ps", "pb", "ev_ebitda"}:
        scenarios = scenario_overrides or default_scenarios
        try:
            scenario_analysis = run_valuation_scenarios(
                snapshot=snapshot,
                model_name=scenario_model,
                scenarios=scenarios,
                base_kwargs=base_kwargs_map.get(scenario_model, {}),
            )
        except ValueError:
            scenario_analysis = None

    sensitivity_analysis = None
    if sensitivity_grid:
        try:
            sensitivity_analysis = run_sensitivity_analysis(
                snapshot=snapshot,
                model_name=scenario_model if scenario_model in {"fcff_dcf", "ddm", "pe", "ps", "pb", "ev_ebitda"} else "fcff_dcf",
                base_kwargs=base_kwargs_map.get(scenario_model, dict(dcf_kwargs)),
                variable_grid=sensitivity_grid,
            )
        except ValueError:
            sensitivity_analysis = None

    return {
        "snapshot": snapshot,
        "valuations": valuations,
        "weighted_valuation": weighted_payload,
        "formatted_range": formatted_range,
        "scenario_analysis": scenario_analysis,
        "sensitivity_analysis": sensitivity_analysis,
    }


def local_test_valuation(ts_code, trade_date=None):
    """Backward-compatible wrapper used by existing API payload builders."""

    result = test_valuation_local(ts_code=ts_code, trade_date=trade_date, freq="D")
    return {
        "snapshot": result.get("snapshot") or {},
        "weighted_valuation": result.get("weighted_valuation") or {},
        "valuations": result.get("valuations") if result.get("valuations") is not None else pd.DataFrame(),
    }
