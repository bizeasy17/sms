from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
