from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from calendar import isleap
from decimal import Decimal

from django.db.models import Q

from financials.models import (
    FinancialAuditRecord,
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialDisclosureRecord,
    FinancialDividendRecord,
    FinancialExpressRecord,
    FinancialForecastRecord,
    FinancialIncomeRecord,
    FinancialIndicatorRecord,
    FinancialMainBusinessRecord,
)
from market_data.models import Security


DATASET_MODELS = {
    'income': FinancialIncomeRecord,
    'balance_sheet': FinancialBalanceSheetRecord,
    'cashflow': FinancialCashFlowRecord,
    'indicator': FinancialIndicatorRecord,
    'forecast': FinancialForecastRecord,
    'express': FinancialExpressRecord,
    'dividend': FinancialDividendRecord,
    'audit': FinancialAuditRecord,
    'main_business': FinancialMainBusinessRecord,
}

PUBLIC_FIELDS = {
    'income': ('f_ann_date', 'report_type', 'comp_type', 'revenue', 'total_revenue', 'oper_cost', 'operate_profit', 'total_profit', 'income_tax', 'n_income', 'n_income_attr_p', 'basic_eps', 'diluted_eps'),
    'balance_sheet': ('f_ann_date', 'report_type', 'comp_type', 'total_assets', 'total_liab', 'total_hldr_eqy_exc_min_int', 'total_hldr_eqy_inc_min_int', 'money_cap', 'accounts_receiv', 'inventories', 'st_borr', 'lt_borr', 'short_borrow', 'long_borrow', 'total_cur_assets', 'total_cur_liab'),
    'cashflow': ('f_ann_date', 'report_type', 'comp_type', 'n_cashflow_act', 'n_cashflow_inv_act', 'n_cash_flows_fnc_act', 'c_cash_equ_end_period', 'n_incr_cash_cash_equ', 'net_incr_cash_cash_equ'),
    'indicator': ('roe', 'roe_waa', 'roe_dt', 'roa', 'q_dt_roe', 'grossprofit_margin', 'netprofit_margin', 'debt_to_assets', 'current_ratio', 'quick_ratio', 'cash_ratio', 'assets_turn', 'ocf_to_or', 'bps', 'eps', 'dt_eps', 'ocfps', 'or_yoy', 'netprofit_yoy'),
    'forecast': ('type', 'p_change_min', 'p_change_max', 'net_profit_min', 'net_profit_max', 'last_parent_net', 'summary', 'change_reason'),
    'express': ('revenue', 'operate_profit', 'total_profit', 'n_income', 'total_assets', 'total_hldr_eqy_exc_min_int', 'basic_eps', 'roe', 'growth_yoy'),
    'dividend': ('stk_div', 'cash_div_tax', 'record_date', 'ex_date', 'pay_date', 'div_proc'),
    'audit': ('audit_result', 'audit_agency', 'audit_sign', 'audit_fees'),
    'main_business': ('bz_item', 'bz_sales', 'bz_profit', 'bz_cost', 'curr_type', 'type'),
    'disclosures': (),
}


@dataclass(frozen=True)
class FinancialPage:
    items: list[dict]
    page: int
    page_size: int
    total: int

    @property
    def has_next(self):
        return self.page * self.page_size < self.total


def _date(value):
    return value.isoformat() if value else None


def _value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _effective_date(row):
    actual_date = getattr(row, 'actual_date', None)
    return actual_date or row.ann_date


def _payload(row, dataset):
    payload = {
        'ts_code': row.security.ts_code,
        'dataset': dataset,
        'ann_date': _date(row.ann_date),
        'actual_date': _date(getattr(row, 'actual_date', None)),
        'effective_date': _date(_effective_date(row)),
        'end_date': _date(row.end_date),
        'period': row.period,
        'source': row.source,
        'source_revision': row.source_revision_at.isoformat() if row.source_revision_at else None,
    }
    payload.update({field: _value(getattr(row, field)) for field in PUBLIC_FIELDS[dataset]})
    return payload


def _queryset(model, security, asof_date):
    queryset = model.objects.select_related('security').filter(security=security)
    if model is FinancialMainBusinessRecord:
        pass
    elif hasattr(model, 'actual_date'):
        queryset = queryset.filter(
            Q(actual_date__isnull=False, actual_date__lte=asof_date)
            | Q(actual_date__isnull=True, ann_date__isnull=False, ann_date__lte=asof_date)
        )
    else:
        queryset = queryset.filter(ann_date__isnull=False, ann_date__lte=asof_date)
    return queryset.order_by('-end_date', '-ann_date', '-id')


def query_records(*, ts_code, dataset, asof_date, end_date=None, date_range=None, page=1, page_size=50):
    model = DATASET_MODELS[dataset]
    security = Security.objects.get(ts_code=ts_code)
    start_date = date_range[0] if date_range else None
    publication_end = date_range[1] if date_range else None
    queryset = _queryset(model, security, asof_date)
    if end_date is not None:
        queryset = queryset.filter(end_date=end_date)
    total = queryset.count()
    rows = queryset[(page - 1) * page_size:page * page_size]
    items = [_payload(row, dataset) for row in rows]
    return FinancialPage(items, page, page_size, total)


def query_disclosures(*, ts_code, asof_date, date_range=None, page=1, page_size=50):
    security = Security.objects.get(ts_code=ts_code)
    start_date = date_range[0] if date_range else None
    end_date = date_range[1] if date_range else None
    queryset = _queryset(FinancialDisclosureRecord, security, asof_date)
    if start_date is not None:
        queryset = queryset.filter(ann_date__gte=start_date)
    if end_date is not None:
        queryset = queryset.filter(ann_date__lte=end_date)
    total = queryset.count()
    rows = queryset[(page - 1) * page_size:page * page_size]
    items = []
    for row in rows:
        payload = _payload(row, 'disclosures')
        payload.update({
            'pre_date': _date(row.pre_date),
            'modify_date': _date(row.modify_date),
        })
        items.append(payload)
    return FinancialPage(items, page, page_size, total)


OVERVIEW_AMOUNT_METRICS = {
    'revenue': ('revenue', 'income'),
    'operating_cash_flow': ('n_cashflow_act', 'cashflow'),
    'net_profit': ('n_income_attr_p', 'income'),
    'ebit': ('operate_profit', 'income'),
}
OVERVIEW_RATE_METRICS = {
    'gross_margin': 'grossprofit_margin',
    'roe': 'roe',
    'net_margin': 'netprofit_margin',
    'debt_to_assets': 'debt_to_assets',
}


def _overview_rows(model, security, asof_date):
    return list(_queryset(model, security, asof_date).order_by('-end_date', '-ann_date', '-id'))


def _row_for_period(rows, end_date):
    return next((row for row in rows if row.end_date == end_date), None)


def _latest_row(rows, end_date=None):
    if end_date is None:
        return rows[0] if rows else None
    return next((row for row in rows if row.end_date and row.end_date <= end_date), None)


def _same_period_last_year(end_date):
    try:
        return end_date.replace(year=end_date.year - 1)
    except ValueError:
        return end_date.replace(year=end_date.year - 1, day=28 if isleap(end_date.year - 1) else 28)


def _three_years_before(asof_date):
    try:
        return asof_date.replace(year=asof_date.year - 3)
    except ValueError:
        return asof_date.replace(year=asof_date.year - 3, day=28)


def _report_type(row):
    if row is None:
        return None
    return getattr(row, 'report_type', None) or ('FY' if row.end_date and row.end_date.month == 12 else None)


def _amount_value(row, field):
    if row is None:
        return None
    value = getattr(row, field, None)
    if value is None and field == 'n_income_attr_p':
        value = getattr(row, 'n_income', None)
    return value


def _ratio_yoy(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return float((current - previous) / abs(previous))


def _rate_yoy(current, previous):
    if current is None or previous is None:
        return None
    return float(current - previous)


def _rolling12(rows, field, current_row):
    if current_row is None or current_row.end_date is None:
        return None
    current_value = _amount_value(current_row, field)
    if current_value is None:
        return None
    if current_row.end_date.month == 12:
        return float(current_value)
    prior_fy_date = date(current_row.end_date.year - 1, 12, 31)
    prior_same_period = _same_period_last_year(current_row.end_date)
    prior_fy = _amount_value(_row_for_period(rows, prior_fy_date), field)
    prior_period = _amount_value(_row_for_period(rows, prior_same_period), field)
    if prior_fy is None or prior_period is None:
        return None
    return float(current_value + prior_fy - prior_period)


def _overview_metric(*, key, row, rows, field, source_dataset, amount):
    value = _amount_value(row, field) if amount else getattr(row, field, None) if row else None
    previous_row = _row_for_period(rows, _same_period_last_year(row.end_date)) if row and row.end_date else None
    previous = _amount_value(previous_row, field) if amount else getattr(previous_row, field, None) if previous_row else None
    return {
        'key': key,
        'value': float(value) if value is not None else None,
        'yoy': _ratio_yoy(value, previous) if amount else _rate_yoy(value, previous),
        'yoy_unit': 'ratio' if amount else 'percentage_points',
        'rolling12': _rolling12(rows, field, row) if amount else float(value) if value is not None else None,
        'rolling12_unit': 'CNY' if amount else 'percentage_points',
        'period': row.end_date.isoformat() if row and row.end_date else None,
        'source_dataset': source_dataset,
        'available': value is not None,
    }


EVALUATION_VERSION = 'fundamental-lite-v1'


def _float_value(value):
    return float(value) if value is not None else None


def _score_band(value, boundaries, scores):
    if value is None:
        return None
    for boundary, score in zip(boundaries, scores):
        if value < boundary:
            return score
    return scores[-1]


def _status(score):
    if score is None:
        return 'NOT_AVAILABLE'
    if score >= 80:
        return 'STRONG'
    if score >= 65:
        return 'HEALTHY'
    if score >= 50:
        return 'NEUTRAL'
    return 'WEAK'


def _dimension(score, *, available, missing_metrics=(), evidence=()):
    return {
        'score': round(score) if score is not None else None,
        'status': _status(score) if available else 'NOT_AVAILABLE',
        'available': available,
        'evidence': list(evidence),
        'missing_metrics': list(missing_metrics),
    }


def _period_values(rows, field, period):
    row = _latest_row(rows, period)
    return row, getattr(row, field, None) if row else None


def _period_growth(rows, field, period):
    row, value = _period_values(rows, field, period)
    if row is None or row.end_date is None:
        return None
    _, previous = _period_values(rows, field, _same_period_last_year(row.end_date))
    return _ratio_yoy(value, previous)


def _period_score(*, period, income_rows, cashflow_rows, indicator_rows, balance_rows):
    revenue_growth = _period_growth(income_rows, 'revenue', period)
    net_profit_growth = _period_growth(income_rows, 'n_income_attr_p', period)
    if net_profit_growth is None:
        net_profit_growth = _period_growth(income_rows, 'n_income', period)

    growth_parts = [
        _score_band(value, (-0.10, 0, 0.10, 0.20), (0, 25, 50, 75, 100))
        for value in (revenue_growth, net_profit_growth)
    ]
    growth_parts = [value for value in growth_parts if value is not None]
    growth_missing = [
        name for name, value in (
            ('revenue_yoy', revenue_growth), ('net_profit_yoy', net_profit_growth),
        ) if value is None
    ]
    growth_score = sum(growth_parts) / len(growth_parts) if growth_parts else None
    if net_profit_growth is not None and net_profit_growth < -0.20 and growth_score is not None:
        growth_score = min(growth_score, 49)

    indicator = _latest_row(indicator_rows, period)
    roe = getattr(indicator, 'roe_dt', None) if indicator else None
    if roe is None and indicator:
        roe = indicator.roe
    net_margin = getattr(indicator, 'netprofit_margin', None) if indicator else None
    profitability_parts = [
        _score_band(_float_value(value), (0, 8, 12, 18), (0, 25, 50, 75, 100))
        for value in (roe, net_margin)
    ]
    profitability_parts = [value for value in profitability_parts if value is not None]
    profitability_missing = [
        name for name, value in (('roe', roe), ('net_margin', net_margin)) if value is None
    ]
    profitability_score = (
        sum(profitability_parts) / len(profitability_parts) if profitability_parts else None
    )

    _, operating_cash_flow = _period_values(cashflow_rows, 'n_cashflow_act', period)
    _, revenue = _period_values(income_rows, 'revenue', period)
    ocf_to_revenue = (
        float(operating_cash_flow / revenue * 100)
        if operating_cash_flow is not None and revenue not in (None, 0) else None
    )
    ocf_growth = _period_growth(cashflow_rows, 'n_cashflow_act', period)
    cash_score = _score_band(ocf_to_revenue, (0, 5, 10, 20), (0, 25, 50, 75, 100))
    cash_missing = []
    if operating_cash_flow is None:
        cash_missing.append('operating_cash_flow')
    if ocf_to_revenue is None:
        cash_missing.append('ocf_to_revenue')
    if cash_score is not None and operating_cash_flow is not None and operating_cash_flow <= 0:
        cash_score = min(cash_score, 50)
    if cash_score is not None and ocf_growth is not None and net_profit_growth is not None:
        if ocf_growth >= net_profit_growth:
            cash_score = min(cash_score + 10, 100)
        elif ocf_growth < -0.10:
            cash_score = max(cash_score - 10, 0)

    indicator = indicator or _latest_row(indicator_rows, period)
    debt_to_assets = getattr(indicator, 'debt_to_assets', None) if indicator else None
    current_ratio = getattr(indicator, 'current_ratio', None) if indicator else None
    quick_ratio = getattr(indicator, 'quick_ratio', None) if indicator else None
    debt_score = _score_band(
        _float_value(debt_to_assets), (30, 50, 70, 85), (100, 75, 50, 25, 0),
    )
    current_score = _score_band(
        _float_value(current_ratio), (0.75, 1.0, 1.5, 2.0), (0, 25, 50, 75, 100),
    )
    coverage_parts = [value for value in (debt_score, current_score) if value is not None]
    if quick_ratio is not None:
        coverage_parts.append(_score_band(
            _float_value(quick_ratio), (0.75, 1.0, 1.5, 2.0), (0, 25, 50, 75, 100),
        ))
    solvency_score = sum(coverage_parts) / len(coverage_parts) if coverage_parts else None
    solvency_missing = [
        name for name, value in (
            ('debt_to_assets', debt_to_assets), ('current_ratio', current_ratio),
            ('quick_ratio', quick_ratio),
        ) if value is None
    ]

    dimensions = {
        'growth': _dimension(
            growth_score, available=growth_score is not None,
            missing_metrics=growth_missing,
            evidence=['income.revenue', 'income.n_income_attr_p or income.n_income'],
        ),
        'profitability': _dimension(
            profitability_score, available=profitability_score is not None,
            missing_metrics=profitability_missing,
            evidence=['indicator.roe_dt or indicator.roe', 'indicator.netprofit_margin'],
        ),
        'cash_flow_quality': _dimension(
            cash_score, available=cash_score is not None,
            missing_metrics=cash_missing,
            evidence=['cashflow.n_cashflow_act', 'derived operating cash flow / revenue'],
        ),
        'solvency': _dimension(
            solvency_score, available=solvency_score is not None,
            missing_metrics=solvency_missing,
            evidence=['indicator.debt_to_assets', 'indicator.current_ratio', 'indicator.quick_ratio'],
        ),
    }
    weights = {'growth': 30, 'profitability': 30, 'cash_flow_quality': 25, 'solvency': 15}
    available_weight = sum(weights[name] for name, value in dimensions.items() if value['available'])
    weighted_score = sum(
        dimensions[name]['score'] * weights[name]
        for name in dimensions
        if dimensions[name]['available']
    )
    # Dimension scores and weights are both expressed on a 0-100 scale.
    overall_score = weighted_score / available_weight if available_weight else None
    return {
        'period': period.isoformat() if period else None,
        'overall': {
            'score': round(overall_score) if overall_score is not None else None,
            'status': _status(overall_score) if available_weight >= 60 else 'NOT_AVAILABLE',
            'available_weight': available_weight,
            'missing_dimensions': [name for name, value in dimensions.items() if not value['available']],
        },
        'dimensions': dimensions,
        '_values': {
            'revenue_growth': revenue_growth,
            'net_profit_growth': net_profit_growth,
            'ocf_growth': ocf_growth,
            'operating_cash_flow': _float_value(operating_cash_flow),
            'net_profit': _float_value(_amount_value(_latest_row(income_rows, period), 'n_income_attr_p')),
            'debt_to_assets': _float_value(debt_to_assets),
            'current_ratio': _float_value(current_ratio),
            'quick_ratio': _float_value(quick_ratio),
        },
    }


def _evaluation_reports(rows, limit=5):
    reports = []
    seen = set()
    for row in rows:
        if not row.end_date or row.end_date in seen:
            continue
        seen.add(row.end_date)
        reports.append({
            'period': row.period or row.end_date.isoformat(),
            'report_type': _report_type(row),
            'end_date': row.end_date.isoformat(),
            'ann_date': _date(row.ann_date),
            'effective_date': _date(_effective_date(row)),
            'data_status': 'AVAILABLE',
            'source_revision': row.source_revision_at.isoformat() if row.source_revision_at else None,
        })
        if len(reports) >= limit:
            break
    return reports


def _signal(*, result, asof_date, signal_code, label, severity, status, evidence, metrics):
    return {
        'signal_code': signal_code,
        'label': label,
        'severity': severity,
        'status': status,
        'asof_date': asof_date.isoformat() if asof_date else None,
        'evidence': evidence,
        'metrics': metrics,
        'provenance': {
            'report_period': result.get('period'),
            'source_datasets': sorted({metric.split('.')[0] for metric in metrics if '.' in metric}),
        },
    }


def _evaluation_signals(result, asof_date):
    values = result['_values']
    signals = []
    if values['revenue_growth'] is not None and values['net_profit_growth'] is not None:
        if values['revenue_growth'] > 0 and values['net_profit_growth'] > 0:
            signals.append(_signal(
                result=result, asof_date=asof_date, signal_code='EARNINGS_IMPROVING', label='盈利改善',
                severity='POSITIVE', status='CONFIRMED', evidence='营收和净利润同比均为正',
                metrics=['income.revenue_yoy', 'income.net_profit_yoy'],
            ))
    if values['ocf_growth'] is not None and values['net_profit_growth'] is not None:
        if values['ocf_growth'] - values['net_profit_growth'] >= 0.05:
            signals.append(_signal(
                result=result, asof_date=asof_date, signal_code='CASH_FLOW_LEADS_PROFIT', label='现金流质量',
                severity='POSITIVE', status='CONFIRMED', evidence='经营现金流增速至少领先净利润增速 5 个百分点',
                metrics=['cashflow.operating_cash_flow_yoy', 'income.net_profit_yoy'],
            ))
    if values['net_profit'] is not None and values['net_profit'] > 0 and (
        values['operating_cash_flow'] is not None and values['operating_cash_flow'] < 0
    ):
        signals.append(_signal(
            result=result, asof_date=asof_date, signal_code='PROFIT_CASH_MISMATCH', label='利润现金流背离',
            severity='RISK', status='TRACKING', evidence='净利润为正但经营现金流为负',
            metrics=['income.net_profit', 'cashflow.operating_cash_flow'],
        ))
    if values['debt_to_assets'] is not None and values['debt_to_assets'] > 70:
        signals.append(_signal(
            result=result, asof_date=asof_date, signal_code='LEVERAGE_HIGH', label='财务风险',
            severity='RISK', status='TRACKING', evidence='负债率高于 70%',
            metrics=['indicator.debt_to_assets'],
        ))
    if ((values['current_ratio'] is not None and values['current_ratio'] < 1.0) or
            (values['quick_ratio'] is not None and values['quick_ratio'] < 0.8)):
        signals.append(_signal(
            result=result, asof_date=asof_date, signal_code='LIQUIDITY_PRESSURE', label='流动性压力',
            severity='RISK', status='TRACKING', evidence='流动比率或速动比率低于安全阈值',
            metrics=['indicator.current_ratio', 'indicator.quick_ratio'],
        ))
    return signals


def _build_fundamental_evaluation(*, income_rows, cashflow_rows, indicator_rows, balance_rows, asof_date):
    trend_start = _three_years_before(asof_date)
    periods = sorted({
        row.end_date for rows in (income_rows, cashflow_rows, indicator_rows, balance_rows)
        for row in rows
        if row.end_date and trend_start <= row.end_date <= asof_date
    })
    trend = []
    period_results = []
    for period in periods:
        period_result = _period_score(
            period=period, income_rows=income_rows, cashflow_rows=cashflow_rows,
            indicator_rows=indicator_rows, balance_rows=balance_rows,
        )
        period_results.append(period_result)
        trend.append({
            'period': period_result['period'],
            'overall': period_result['overall'],
            'dimensions': period_result['dimensions'],
            'source_period': period_result['period'],
        })
    current = period_results[-1] if period_results else _period_score(
        period=None, income_rows=[], cashflow_rows=[], indicator_rows=[], balance_rows=[],
    )
    reports = _evaluation_reports(income_rows)
    warnings = []
    if not reports:
        warnings.append('暂无可用财报档案')
    if not trend:
        warnings.append('过去三年暂无可用财务趋势')
    if current['overall']['available_weight'] < 100:
        warnings.append('部分评判维度缺少可用财务指标')
    signals = _evaluation_signals(current, asof_date)
    if current['overall']['available_weight'] < 60:
        signals.append(_signal(
            result=current, asof_date=asof_date, signal_code='DATA_PARTIAL', label='数据状态',
            severity='INFO', status='NOT_AVAILABLE', evidence='可用评判维度不足 60%', metrics=[],
        ))
    current.pop('_values', None)
    return {
        'evaluation_version': EVALUATION_VERSION,
        'overall': current['overall'],
        'dimensions': current['dimensions'],
        'trend': trend,
        'reports': reports,
        'signals': signals,
        'warnings': warnings,
    }


def query_financial_overview(*, ts_code, asof_date, report_type='LATEST'):
    security = Security.objects.get(ts_code=ts_code)
    income_rows = _overview_rows(FinancialIncomeRecord, security, asof_date)
    cashflow_rows = _overview_rows(FinancialCashFlowRecord, security, asof_date)
    indicator_rows = _overview_rows(FinancialIndicatorRecord, security, asof_date)
    balance_rows = _overview_rows(FinancialBalanceSheetRecord, security, asof_date)
    candidate_rows = income_rows + cashflow_rows + indicator_rows
    selected = _latest_row(sorted(candidate_rows, key=lambda row: (row.end_date or date.min, row.ann_date or date.min, row.id), reverse=True))
    period = selected.end_date if selected else None
    metrics = {}
    for key, (field, dataset) in OVERVIEW_AMOUNT_METRICS.items():
        rows = income_rows if dataset == 'income' else cashflow_rows
        row = _latest_row(rows, period)
        metrics[key] = _overview_metric(key=key, row=row, rows=rows, field=field, source_dataset=dataset, amount=True)
    for key, field in OVERVIEW_RATE_METRICS.items():
        row = _latest_row(indicator_rows, period)
        metrics[key] = _overview_metric(key=key, row=row, rows=indicator_rows, field=field, source_dataset='indicator', amount=False)
    available = sum(metric['available'] for metric in metrics.values())
    return {
        'ts_code': security.ts_code,
        'asof_date': asof_date.isoformat(),
        'period': period.isoformat() if period else None,
        'report_type': report_type,
        'metrics': metrics,
        'units': {
            'amount': 'CNY',
            'rate': 'percentage_points',
            'growth': 'ratio',
            'rolling12': 'CNY_or_percentage_points',
        },
        'source_dates': {
            'income': income_rows[0].end_date.isoformat() if income_rows else None,
            'cashflow': cashflow_rows[0].end_date.isoformat() if cashflow_rows else None,
            'indicator': indicator_rows[0].end_date.isoformat() if indicator_rows else None,
        },
        'evaluation': _build_fundamental_evaluation(
            income_rows=income_rows,
            cashflow_rows=cashflow_rows,
            indicator_rows=indicator_rows,
            balance_rows=balance_rows,
            asof_date=asof_date,
        ),
        'data_status': 'COMPLETE' if available else 'NOT_AVAILABLE',
        'warnings': [] if available == len(metrics) else ['部分财务指标暂无可用记录'],
    }
