from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from math import isfinite
from typing import Any

from django.db.models import Q

from financials.models import (
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialIncomeRecord,
    FinancialIndicatorRecord,
)
from market_data.models import Security

CALCULATION_VERSION = 'cgps-v1'
PROFILE_VERSION = 'cgps-non-financial-v1'
PEER_MIN_SAMPLE = 20
DIMENSIONS = (
    ('demand_momentum', '需求与收入动能', 0.20),
    ('order_visibility', '订单与收入能见度', 0.15),
    ('profitability_leverage', '盈利能力与经营杠杆', 0.15),
    ('earnings_quality', '利润质量与可持续性', 0.15),
    ('cash_conversion', '回款与现金转化', 0.15),
    ('growth_investment', '成长投入与产能准备', 0.10),
    ('balance_operation_safety', '资产负债与营运安全', 0.10),
)

_TABLES = {
    'income': FinancialIncomeRecord,
    'balance_sheet': FinancialBalanceSheetRecord,
    'cashflow': FinancialCashFlowRecord,
    'indicator': FinancialIndicatorRecord,
}
_CORE_DIMENSIONS = {
    'demand_momentum',
    'profitability_leverage',
    'cash_conversion',
    'balance_operation_safety',
}
_DIMENSION_FACTORS = {
    'demand_momentum': [('g_rev', 0.65, 'higher') , ('accel_rev', 0.35, 'higher')],
    'order_visibility': [('d_cl', 0.60, 'higher'), ('d_prepay', 0.40, 'higher')],
    'profitability_leverage': [
        ('g_op', 0.40, 'higher'),
        ('d_gross_margin', 0.30, 'higher'),
        ('d_net_margin', 0.30, 'higher'),
    ],
    'earnings_quality': [
        ('g_deducted_profit', 0.50, 'higher'),
        ('dtprofit_to_profit', 0.30, 'higher'),
        ('nop_to_ebt', 0.20, 'lower'),
    ],
    'cash_conversion': [
        ('salescash_to_or', 0.40, 'higher'),
        ('ocf_to_or', 0.35, 'higher'),
        ('ocf_to_profit', 0.25, 'higher'),
    ],
    'growth_investment': [
        ('d_rd', 0.40, 'higher'),
        ('d_capex', 0.30, 'higher'),
        ('d_cip', 0.30, 'higher'),
    ],
    'balance_operation_safety': [
        ('gap_ar', 0.25, 'lower'),
        ('gap_inv', 0.25, 'lower'),
        ('debt_to_assets', 0.20, 'lower'),
        ('current_ratio', 0.15, 'higher'),
        ('d_assets_turn', 0.15, 'higher'),
    ],
}
_FACTOR_SOURCES = {
    'g_rev': ['q_sales_yoy', 'revenue'],
    'accel_rev': ['q_sales_yoy', 'revenue'],
    'd_cl': ['contract_liab', 'revenue'],
    'd_prepay': ['prepayment', 'revenue'],
    'g_op': ['q_op_yoy', 'operate_profit'],
    'd_gross_margin': ['q_gsprofit_margin', 'revenue', 'oper_cost'],
    'd_net_margin': ['q_netprofit_margin', 'n_income_attr_p', 'revenue'],
    'g_deducted_profit': ['q_dtprofit', 'profit_dedt'],
    'dtprofit_to_profit': ['dtprofit_to_profit', 'profit_dedt', 'n_income_attr_p'],
    'nop_to_ebt': ['nop_to_ebt', 'non_op_profit', 'total_profit'],
    'salescash_to_or': ['c_fr_sale_sg', 'revenue'],
    'ocf_to_or': ['n_cashflow_act', 'revenue'],
    'ocf_to_profit': ['n_cashflow_act', 'operate_profit'],
    'd_rd': ['rd_exp', 'revenue'],
    'd_capex': ['c_pay_acq_const_fiolta', 'revenue'],
    'd_cip': ['cip', 'revenue'],
    'gap_ar': ['accounts_receiv', 'revenue'],
    'gap_inv': ['inventories', 'revenue'],
    'debt_to_assets': ['debt_to_assets', 'total_liab', 'total_assets'],
    'current_ratio': ['current_ratio', 'total_cur_assets', 'total_cur_liab'],
    'd_assets_turn': ['assets_turn'],
}


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    try:
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _row_fields(row: Any) -> dict[str, Any]:
    """Expose every typed and raw Tushare field through one read-only mapping."""
    payload = getattr(row, 'raw_payload', None)
    fields = dict(payload) if isinstance(payload, dict) else {}
    for name, value in vars(row).items():
        if name.startswith('_') or name in {'id', 'security_id', 'raw_payload'}:
            continue
        if value is not None:
            fields[name] = value
    return fields


def _field(row: Any, name: str) -> Any:
    if row is None:
        return None
    fields = _row_fields(row)
    return fields.get(name)


def _value(row: Any, name: str) -> float | None:
    return _number(_field(row, name))


def _ann_date(row: Any) -> date | None:
    return _to_date(_field(row, 'f_ann_date') or _field(row, 'ann_date'))


def _report_type(row: Any) -> str:
    return str(_field(row, 'report_type') or '').strip()


def _visible_rows(
    model: Any,
    security_ids: list[int],
    asof_date: date,
    start_date: date,
    period_dates: set[date] | None = None,
) -> list[Any]:
    if not security_ids:
        return []
    query = model.objects.filter(
        security_id__in=security_ids,
        end_date__gte=start_date,
        end_date__lte=asof_date,
    ).filter(Q(ann_date__lte=asof_date) | Q(ann_date__isnull=True)).order_by('end_date', 'id')
    if period_dates:
        query = query.filter(end_date__in=period_dates)
    return [row for row in query if (announced := _ann_date(row)) is not None and announced <= asof_date]


def _period_map(rows: list[Any]) -> dict[int, dict[date, list[Any]]]:
    selected: dict[tuple[int, date, str], Any] = {}
    for row in rows:
        if row.end_date is None:
            continue
        key = (row.security_id, row.end_date, _report_type(row))
        old = selected.get(key)
        rank = (_field(row, 'update_flag') == '1', _ann_date(row) or date.min, row.id)
        old_rank = (_field(old, 'update_flag') == '1', _ann_date(old) or date.min, old.id) if old else None
        if old_rank is None or rank > old_rank:
            selected[key] = row
    result: dict[int, dict[date, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for (security_id, end_date, _), row in selected.items():
        result[security_id][end_date].append(row)
    return result


def _pick(rows: list[Any] | None, single_quarter: bool = False) -> Any | None:
    if not rows:
        return None
    preferred = ('2', '3', '7', '8') if single_quarter else ('1', '')
    for report_type in preferred:
        row = next((item for item in rows if _report_type(item) == report_type), None)
        if row is not None:
            return row
    return rows[0]


def _quarter_end(value: date) -> date:
    ends = (date(value.year, 3, 31), date(value.year, 6, 30), date(value.year, 9, 30), date(value.year, 12, 31))
    return next(end for end in ends if value <= end and value.month <= end.month)


def _period_offset(value: date, quarters: int) -> date:
    current = _quarter_end(value)
    ordinal = current.year * 4 + ((current.month - 1) // 3) - quarters
    year, quarter = divmod(ordinal, 4)
    return (date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31))[quarter]


def _factor_periods(end_date: date) -> set[date]:
    return {_period_offset(end_date, offset) for offset in range(9)}


def _flow_value(periods: dict[date, list[Any]], end_date: date, field: str) -> float | None:
    rows = periods.get(end_date, [])
    single = _pick(rows, single_quarter=True)
    if single is not None and _report_type(single) in {'2', '3', '7', '8'}:
        return _value(single, field)
    cumulative = _value(_pick(rows), field)
    if cumulative is None or _quarter_end(end_date).month == 3:
        return cumulative
    previous_cumulative = _value(_pick(periods.get(_period_offset(end_date, 1))), field)
    return cumulative - previous_cumulative if previous_cumulative is not None else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    value = numerator / denominator
    return value if isfinite(value) else None


def _ratio_percent(numerator: float | None, denominator: float | None) -> float | None:
    value = _ratio(numerator, denominator)
    return value * 100 if value is not None else None


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0 or current * previous < 0:
        return None
    return 100.0 * (current / previous - 1.0)


def _raw_factors(
    data: dict[str, dict[int, dict[date, list[Any]]]],
    security_id: int,
    end_date: date,
) -> dict[str, float | None]:
    tables = {key: value.get(security_id, {}) for key, value in data.items()}
    income, balance = tables['income'], tables['balance_sheet']
    cashflow, indicator = tables['cashflow'], tables['indicator']
    prev_year = _period_offset(end_date, 4)
    prev_q = _period_offset(end_date, 1)

    def flow(table: dict[date, list[Any]], period: date, name: str) -> float | None:
        return _flow_value(table, period, name)

    revenue = flow(income, end_date, 'revenue')
    prior_revenue = flow(income, prev_year, 'revenue')
    ttm_revenue_values = [flow(income, _period_offset(end_date, offset), 'revenue') for offset in range(4)]
    revenue_ttm = sum(ttm_revenue_values) if all(value is not None for value in ttm_revenue_values) else None
    prior_ttm_values = [flow(income, _period_offset(prev_year, offset), 'revenue') for offset in range(4)]
    prior_revenue_ttm = sum(prior_ttm_values) if all(value is not None for value in prior_ttm_values) else None

    current_indicator = _pick(indicator.get(end_date))
    previous_year_indicator = _pick(indicator.get(prev_year))
    previous_quarter_indicator = _pick(indicator.get(prev_q))
    g_rev = _value(current_indicator, 'q_sales_yoy')
    if g_rev is None:
        g_rev = _growth(revenue, prior_revenue)
    previous_g_rev = _value(previous_quarter_indicator, 'q_sales_yoy')
    if previous_g_rev is None:
        previous_g_rev = _growth(
            flow(income, prev_q, 'revenue'),
            flow(income, _period_offset(end_date, 5), 'revenue'),
        )

    operate_profit = flow(income, end_date, 'operate_profit')
    prior_operate_profit = flow(income, prev_year, 'operate_profit')
    g_op = _value(current_indicator, 'q_op_yoy')
    if g_op is None:
        g_op = _growth(operate_profit, prior_operate_profit)

    gross_margin = _value(current_indicator, 'q_gsprofit_margin')
    if gross_margin is None:
        gross_margin = _ratio_percent(
            revenue - flow(income, end_date, 'oper_cost'), revenue
        ) if revenue is not None and flow(income, end_date, 'oper_cost') is not None else None
    prior_gross_margin = _value(previous_year_indicator, 'q_gsprofit_margin')
    if prior_gross_margin is None:
        prior_cost = flow(income, prev_year, 'oper_cost')
        prior_gross_margin = _ratio_percent(
            prior_revenue - prior_cost, prior_revenue
        ) if prior_revenue is not None and prior_cost is not None else None

    net_income = flow(income, end_date, 'n_income_attr_p')
    prior_net_income = flow(income, prev_year, 'n_income_attr_p')
    net_margin = _value(current_indicator, 'q_netprofit_margin')
    if net_margin is None:
        net_margin = _ratio_percent(net_income, revenue)
    prior_net_margin = _value(previous_year_indicator, 'q_netprofit_margin')
    if prior_net_margin is None:
        prior_net_margin = _ratio_percent(prior_net_income, prior_revenue)

    deducted_profit = _value(current_indicator, 'q_dtprofit')
    if deducted_profit is None:
        deducted_profit = _flow_value(indicator, end_date, 'profit_dedt')
    prior_deducted = _value(previous_year_indicator, 'q_dtprofit')
    if prior_deducted is None:
        prior_deducted = _flow_value(indicator, prev_year, 'profit_dedt')
    total_profit = flow(income, end_date, 'total_profit')
    dtprofit_to_profit = _value(current_indicator, 'dtprofit_to_profit')
    if dtprofit_to_profit is None:
        dtprofit_to_profit = _ratio(deducted_profit, net_income)
    nop_to_ebt = _value(current_indicator, 'nop_to_ebt')
    if nop_to_ebt is None:
        nop_to_ebt = _ratio(_value(current_indicator, 'non_op_profit'), total_profit)

    sales_cash = flow(cashflow, end_date, 'c_fr_sale_sg')
    operating_cash = flow(cashflow, end_date, 'n_cashflow_act')
    current_balance = _pick(balance.get(end_date))
    previous_balance = _pick(balance.get(prev_year))
    current_assets = _value(current_balance, 'total_cur_assets')
    current_liabilities = _value(current_balance, 'total_cur_liab')
    debt_to_assets = _value(current_indicator, 'debt_to_assets')
    if debt_to_assets is None:
        debt_to_assets = _ratio(_value(current_balance, 'total_liab'), _value(current_balance, 'total_assets'))
    current_ratio = _value(current_indicator, 'current_ratio')
    if current_ratio is None:
        current_ratio = _ratio(current_assets, current_liabilities)
    assets_turn = _value(current_indicator, 'assets_turn')
    prior_assets_turn = _value(previous_year_indicator, 'assets_turn')

    rd_ttm_values = [flow(income, _period_offset(end_date, offset), 'rd_exp') for offset in range(4)]
    prior_rd_ttm_values = [flow(income, _period_offset(prev_year, offset), 'rd_exp') for offset in range(4)]
    capex_ttm_values = [flow(cashflow, _period_offset(end_date, offset), 'c_pay_acq_const_fiolta') for offset in range(4)]
    prior_capex_ttm_values = [flow(cashflow, _period_offset(prev_year, offset), 'c_pay_acq_const_fiolta') for offset in range(4)]
    rd_ttm = sum(rd_ttm_values) if all(value is not None for value in rd_ttm_values) else None
    prior_rd_ttm = sum(prior_rd_ttm_values) if all(value is not None for value in prior_rd_ttm_values) else None
    capex_ttm = sum(capex_ttm_values) if all(value is not None for value in capex_ttm_values) else None
    prior_capex_ttm = sum(prior_capex_ttm_values) if all(value is not None for value in prior_capex_ttm_values) else None
    rd_intensity = _ratio(rd_ttm, revenue_ttm)
    prior_rd_intensity = _ratio(prior_rd_ttm, prior_revenue_ttm)
    capex_intensity = _ratio(capex_ttm, revenue_ttm)
    prior_capex_intensity = _ratio(prior_capex_ttm, prior_revenue_ttm)
    cip_intensity = _ratio(_value(current_balance, 'cip'), revenue_ttm)
    prior_cip_intensity = _ratio(_value(previous_balance, 'cip'), prior_revenue_ttm)

    def balance_growth(field: str) -> float | None:
        return _growth(_value(current_balance, field), _value(previous_balance, field))

    g_ar = balance_growth('accounts_receiv')
    g_inventory = balance_growth('inventories')
    cl_now = _ratio(_value(current_balance, 'contract_liab'), revenue_ttm)
    cl_prior = _ratio(_value(previous_balance, 'contract_liab'), prior_revenue_ttm)
    prepay_now = _ratio(_value(current_balance, 'prepayment'), revenue_ttm)
    prepay_prior = _ratio(_value(previous_balance, 'prepayment'), prior_revenue_ttm)

    return {
        'g_rev': g_rev,
        'accel_rev': g_rev - previous_g_rev if g_rev is not None and previous_g_rev is not None else None,
        'd_cl': cl_now - cl_prior if cl_now is not None and cl_prior is not None else None,
        'd_prepay': prepay_now - prepay_prior if prepay_now is not None and prepay_prior is not None else None,
        'g_op': g_op,
        'd_gross_margin': gross_margin - prior_gross_margin if gross_margin is not None and prior_gross_margin is not None else None,
        'd_net_margin': net_margin - prior_net_margin if net_margin is not None and prior_net_margin is not None else None,
        'g_deducted_profit': _growth(deducted_profit, prior_deducted),
        'dtprofit_to_profit': dtprofit_to_profit,
        'nop_to_ebt': nop_to_ebt,
        'salescash_to_or': _ratio(sales_cash, revenue),
        'ocf_to_or': _ratio(operating_cash, revenue),
        'ocf_to_profit': _ratio(operating_cash, operate_profit),
        'd_rd': rd_intensity - prior_rd_intensity if rd_intensity is not None and prior_rd_intensity is not None else None,
        'd_capex': capex_intensity - prior_capex_intensity if capex_intensity is not None and prior_capex_intensity is not None else None,
        'd_cip': cip_intensity - prior_cip_intensity if cip_intensity is not None and prior_cip_intensity is not None else None,
        'gap_ar': g_ar - g_rev if g_ar is not None and g_rev is not None else None,
        'gap_inv': g_inventory - g_rev if g_inventory is not None and g_rev is not None else None,
        'debt_to_assets': debt_to_assets,
        'current_ratio': current_ratio,
        'd_assets_turn': assets_turn - prior_assets_turn if assets_turn is not None and prior_assets_turn is not None else None,
        'g_contract_assets': balance_growth('contract_assets'),
    }


def _percentile_score(target: float, peers: list[float], direction: str) -> float | None:
    values = sorted(value for value in peers if isfinite(value))
    if len(values) < 2 or target not in values:
        return None
    lower_count = sum(value < target for value in values)
    equal_count = sum(value == target for value in values)
    average_rank = lower_count + (equal_count + 1) / 2.0
    score = 100.0 * (average_rank - 1.0) / (len(values) - 1.0)
    return 100.0 - score if direction == 'lower' else score


def _dimension_results(
    target: dict[str, float | None],
    industry_peers: list[dict[str, float | None]],
    market_peers: list[dict[str, float | None]],
) -> list[dict[str, Any]]:
    results = []
    for key, name, weight in DIMENSIONS:
        scored: list[tuple[float, float]] = []
        evidence = []
        for factor, factor_weight, direction in _DIMENSION_FACTORS[key]:
            raw = target.get(factor)
            industry_values = [item[factor] for item in industry_peers if item.get(factor) is not None]
            use_market = len(industry_values) < PEER_MIN_SAMPLE
            peer_values = [item[factor] for item in market_peers if item.get(factor) is not None] if use_market else industry_values
            score = _percentile_score(raw, peer_values, direction) if raw is not None and len(peer_values) >= PEER_MIN_SAMPLE else None
            evidence.append({
                'factor': factor,
                'source_fields': _FACTOR_SOURCES.get(factor, []),
                'raw_value': raw,
                'unit': 'ratio' if factor in {'d_cl', 'd_prepay', 'dtprofit_to_profit', 'nop_to_ebt', 'salescash_to_or', 'ocf_to_or', 'ocf_to_profit', 'debt_to_assets', 'current_ratio'} else 'percent_or_percentage_points',
                'direction': 'higher_better' if direction == 'higher' else 'lower_better',
                'normalized_score': round(score, 4) if score is not None else None,
                'peer_scope': 'non_financial_market' if use_market else 'industry',
                'peer_sample_count': len(peer_values),
                'status': 'AVAILABLE' if score is not None else 'INSUFFICIENT_DATA' if raw is not None else 'MISSING',
            })
            if score is not None:
                scored.append((score, factor_weight))
        available_weight = sum(factor_weight for _, factor_weight in scored)
        score = (
            sum(value * factor_weight for value, factor_weight in scored) / available_weight
            if available_weight >= 0.5 else None
        )
        results.append({
            'key': key,
            'name': name,
            'weight': weight,
            'score': round(score, 2) if score is not None else None,
            'status': 'NOT_AVAILABLE' if score is None else 'PARTIAL' if available_weight < 1.0 else 'VALID',
            'factor_weight_coverage': round(available_weight, 4),
            'evidence': evidence,
        })
    by_key = {item['key']: item for item in results}
    investment = by_key['growth_investment']
    demand_score = by_key['demand_momentum']['score']
    cash_score = by_key['cash_conversion']['score']
    gate = (demand_score is not None and demand_score < 50) or (cash_score is not None and cash_score < 40)
    if investment['score'] is not None and gate:
        investment['score'] = min(investment['score'], 50.0)
        investment['investment_gate_applied'] = True
    else:
        investment['investment_gate_applied'] = False
    return results


def _non_financial(security_id: int, data: dict[str, dict[int, dict[date, list[Any]]]], end_date: date) -> bool:
    for table in data.values():
        rows = table.get(security_id, {}).get(end_date, [])
        for row in rows:
            comp_type = str(_field(row, 'comp_type') or '').strip()
            if comp_type in {'2', '3', '4', '7'}:
                return False
    return True


def _load_data(
    security_ids: list[int],
    cutoff: date,
    start_date: date,
    period_dates: set[date] | None = None,
) -> dict[str, dict[int, dict[date, list[Any]]]]:
    return {
        name: _period_map(_visible_rows(model, security_ids, cutoff, start_date, period_dates))
        for name, model in _TABLES.items()
    }


def compute_growth_potential_score(ts_code: str, asof_date: date | str) -> dict[str, Any]:
    """Compute CGPS from persisted financial reports visible at ``asof_date``; no writes."""
    cutoff = _as_date(asof_date)
    security_manager = getattr(Security, 'objects')
    security = security_manager.select_related('industry').filter(
        ts_code=str(ts_code).strip().upper(),
        asset_type=Security.AssetType.STOCK,
    ).first()
    if security is None:
        raise LookupError('security not found')

    empty_dimensions = [key for key, _, _ in DIMENSIONS]
    if not security.industry_id:
        return {
            'score_type': 'COMPANY_GROWTH_POTENTIAL',
            'calculation_version': CALCULATION_VERSION,
            'profile_version': PROFILE_VERSION,
            'ts_code': security.ts_code,
            'asof_date': cutoff.isoformat(),
            'score': None,
            'status': 'INSUFFICIENT_DATA',
            'coverage': 0.0,
            'dimensions': [],
            'missing_dimensions': empty_dimensions,
            'warnings': ['industry_missing'],
        }

    history_start = date(cutoff.year - 5, 1, 1)
    target_data = _load_data([security.id], cutoff, history_start)
    common_dates = set.intersection(*(
        set(target_data[name].get(security.id, {})) for name in _TABLES
    ))
    if not common_dates:
        return {
            'score_type': 'COMPANY_GROWTH_POTENTIAL',
            'calculation_version': CALCULATION_VERSION,
            'profile_version': PROFILE_VERSION,
            'ts_code': security.ts_code,
            'asof_date': cutoff.isoformat(),
            'score': None,
            'status': 'INSUFFICIENT_DATA',
            'coverage': 0.0,
            'dimensions': [],
            'missing_dimensions': empty_dimensions,
            'warnings': ['aligned_financial_period_missing'],
        }
    end_date = max(common_dates)
    if not _non_financial(security.id, target_data, end_date):
        return {
            'score_type': 'COMPANY_GROWTH_POTENTIAL',
            'calculation_version': CALCULATION_VERSION,
            'profile_version': PROFILE_VERSION,
            'ts_code': security.ts_code,
            'asof_date': cutoff.isoformat(),
            'financial_end_date': end_date.isoformat(),
            'score': None,
            'status': 'NOT_APPLICABLE',
            'coverage': 0.0,
            'dimensions': [],
            'missing_dimensions': empty_dimensions,
            'warnings': ['financial_company_type_not_supported'],
        }
    industry_ids = list(security_manager.filter(
        asset_type=Security.AssetType.STOCK,
        industry_id=security.industry_id,
    ).values_list('id', flat=True))
    history_start = date(end_date.year - 5, 1, 1)
    factor_periods = _factor_periods(end_date)
    industry_data = _load_data(industry_ids, cutoff, history_start, factor_periods)
    target_factors = _raw_factors(industry_data, security.id, end_date)
    industry_peers = [
        _raw_factors(industry_data, peer_id, end_date)
        for peer_id in industry_ids
        if _non_financial(peer_id, industry_data, end_date)
        and all(end_date in industry_data[name].get(peer_id, {}) for name in _TABLES)
    ]

    needs_market = any(
        sum(peer.get(factor) is not None for peer in industry_peers) < PEER_MIN_SAMPLE
        for specs in _DIMENSION_FACTORS.values()
        for factor, _, _ in specs
    )
    market_peers: list[dict[str, float | None]] = []
    if needs_market:
        market_ids = list(security_manager.filter(
            asset_type=Security.AssetType.STOCK,
            industry_id__isnull=False,
        ).values_list('id', flat=True))
        market_data = _load_data(market_ids, cutoff, history_start, factor_periods)
        target_factors = _raw_factors(market_data, security.id, end_date)
        market_peers = [
            _raw_factors(market_data, peer_id, end_date)
            for peer_id in market_ids
            if _non_financial(peer_id, market_data, end_date)
            and all(end_date in market_data[name].get(peer_id, {}) for name in _TABLES)
        ]

    dimensions = _dimension_results(target_factors, industry_peers, market_peers)
    available = {item['key']: item for item in dimensions if item['score'] is not None}
    coverage = sum(weight for key, _, weight in DIMENSIONS if key in available)
    score_valid = coverage >= 0.80 and _CORE_DIMENSIONS.issubset(available)
    score = (
        sum(item['score'] * item['weight'] for item in available.values()) / coverage
        if score_valid and coverage else None
    )
    if score is None:
        label, status = None, 'INSUFFICIENT_DATA'
    else:
        label = 'STRONG' if score >= 80 else 'ABOVE_AVERAGE' if score >= 65 else 'NEUTRAL' if score >= 45 else 'BELOW_AVERAGE' if score >= 30 else 'WEAK'
        status = 'PARTIAL' if coverage < 1.0 else 'VALID'

    source_periods = {
        name: {
            'end_date': end_date.isoformat(),
            'announcement_date': announced.isoformat() if (announced := _ann_date(_pick(target_data[name][security.id][end_date]))) else None,
            'available_fields': sorted(_row_fields(_pick(target_data[name][security.id][end_date]))),
        }
        for name in _TABLES
    }
    warnings = []
    if any(item['peer_scope'] == 'non_financial_market' for dim in dimensions for item in dim['evidence']):
        warnings.append('peer_fallback_non_financial_market')
    if any(item['score'] is None for item in dimensions):
        warnings.append('dimension_coverage_partial')
    return {
        'score_type': 'COMPANY_GROWTH_POTENTIAL',
        'calculation_version': CALCULATION_VERSION,
        'profile_version': PROFILE_VERSION,
        'peer_mapping_version': f"{security.industry.source_system}:{security.industry.source_version or 'local'}",
        'ts_code': security.ts_code,
        'name': security.name,
        'industry': security.industry.name if security.industry else None,
        'asof_date': cutoff.isoformat(),
        'financial_end_date': end_date.isoformat(),
        'source_periods': source_periods,
        'peer_industry_sample_count': len(industry_peers),
        'peer_market_sample_count': len(market_peers),
        'score': round(score, 2) if score is not None else None,
        'label': label,
        'status': status,
        'coverage': round(coverage, 4),
        'dimensions': dimensions,
        'missing_dimensions': [key for key, _, _ in DIMENSIONS if key not in available],
        'factor_values': target_factors,
        'warnings': warnings,
    }