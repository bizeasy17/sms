from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from decimal import Decimal
import re

from financials.models import (
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialIncomeRecord,
    FinancialIndicatorRecord,
)
from financials.services.query import (
    _amount_value,
    _latest_row,
    _period_growth,
    _period_score,
    _rate_yoy,
)
from market_data.models import Security
from predictive_valuation.models import PredictiveValuationCurrent
from traditional_valuation.models import TraditionalValuationVariantSummaryLatest

PRESETS = {
    'quality-growth': {'revenue_yoy_min': 10, 'profit_yoy_min': 10, 'ebit_yoy_min': 10, 'roe_min': 10, 'gross_margin_improved': True, 'operating_cash_flow_positive': True, 'liquidity_ratio_min': 1.5, 'net_cash': True},
    'steady-growth': {'revenue_yoy_min': 5, 'profit_yoy_min': 5, 'ebit_yoy_min': 5, 'roe_min': 10, 'gross_margin_improved': False, 'operating_cash_flow_positive': True, 'liquidity_ratio_min': 1.2, 'net_cash': False},
    'cash-flow': {'revenue_yoy_min': 0, 'profit_yoy_min': 0, 'ebit_yoy_min': 0, 'roe_min': 0, 'gross_margin_improved': False, 'operating_cash_flow_positive': True, 'liquidity_ratio_min': 1.5, 'net_cash': True},
    'low-risk': {'revenue_yoy_min': 0, 'profit_yoy_min': 0, 'ebit_yoy_min': 0, 'roe_min': 10, 'gross_margin_improved': False, 'operating_cash_flow_positive': True, 'liquidity_ratio_min': 1.8, 'net_cash': True},
}
SORT_KEYS = {'score', 'value_valuation_score', 'model_valuation_score', 'revenue_yoy', 'profit_yoy', 'ebit_yoy', 'roe', 'liquidity_ratio'}
REPORT_MONTHS = {'Q1': 3, 'H1': 6, 'Q3': 9, 'FY': 12}
REPORT_TYPE_PATTERN = re.compile(r'^(?P<year>\d{2})(?P<period>Q1|H1|Q3|FY)$')


class StockSelectionRequestError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class Page:
    items: list[dict]
    page: int
    page_size: int
    total: int

    @property
    def has_next(self):
        return self.page * self.page_size < self.total


def _number(value):
    return float(value) if isinstance(value, Decimal) else value


def _date(value):
    return value.isoformat() if value else None


def _market_match(ts_code, market):
    if market == 'all':
        return True
    code, _, exchange = ts_code.upper().partition('.')
    if market == 'sh-main':
        return exchange == 'SH' and not code.startswith('688')
    if market == 'sz-main':
        return exchange == 'SZ' and not code.startswith(('300', '301'))
    if market == 'cyb':
        return exchange == 'SZ' and code.startswith(('300', '301'))
    return exchange == 'SH' and code.startswith('688')


def _parse_report_type(report_type):
    normalized = str(report_type or '').strip().upper()
    match = REPORT_TYPE_PATTERN.fullmatch(normalized)
    if not match:
        raise StockSelectionRequestError(
            'UNSUPPORTED_REPORT_TYPE',
            'report_type 必须使用 YYQ1、YYH1、YYQ3 或 YYFY 格式，例如 26H1',
        )
    year = 2000 + int(match.group('year'))
    period = match.group('period')
    return normalized, year, REPORT_MONTHS[period]


def _batch_financial_values(securities, asof_date, report_year, report_month):
    security_ids = [security.id for security in securities]
    years = (report_year - 1, report_year)
    common_filters = {
        'security_id__in': security_ids,
        'ann_date__isnull': False,
        'ann_date__lte': asof_date,
        'end_date__year__in': years,
        'end_date__month': report_month,
    }
    rows_by_model = {}
    for model in (
        FinancialIncomeRecord,
        FinancialCashFlowRecord,
        FinancialIndicatorRecord,
        FinancialBalanceSheetRecord,
    ):
        rows_by_model[model] = {}
        rows = model.objects.filter(**common_filters).order_by('security_id', '-end_date', '-ann_date', '-id')
        for row in rows:
            rows_by_model[model].setdefault(row.security_id, []).append(row)

    result = {}
    for security in securities:
        income_rows = rows_by_model[FinancialIncomeRecord].get(security.id, [])
        cashflow_rows = rows_by_model[FinancialCashFlowRecord].get(security.id, [])
        indicator_rows = rows_by_model[FinancialIndicatorRecord].get(security.id, [])
        balance_rows = rows_by_model[FinancialBalanceSheetRecord].get(security.id, [])
        candidate_rows = income_rows + cashflow_rows + indicator_rows
        current = _latest_row(
            [row for row in candidate_rows if row.end_date and row.end_date.year == report_year],
        )
        if current is None:
            continue
        period = current.end_date
        evaluation = _period_score(
            period=period,
            income_rows=income_rows,
            cashflow_rows=cashflow_rows,
            indicator_rows=indicator_rows,
            balance_rows=balance_rows,
        )
        income = _latest_row(income_rows, period)
        cashflow = _latest_row(cashflow_rows, period)
        indicator = _latest_row(indicator_rows, period)
        balance = _latest_row(balance_rows, period)
        previous_indicator = _latest_row(indicator_rows, period.replace(year=period.year - 1))
        current_assets = _number(balance.total_cur_assets) if balance else None
        current_liab = _number(balance.total_cur_liab) if balance else None
        cash = _number(balance.money_cap) if balance else None
        short_debt = _number(balance.st_borr or balance.short_borrow) if balance else None
        long_debt = _number(balance.lt_borr or balance.long_borrow) if balance else None
        result[security.id] = {
            'financial_score': evaluation['overall']['score'],
            'revenue_yoy': _period_growth(income_rows, 'revenue', period),
            'profit_yoy': _period_growth(income_rows, 'n_income_attr_p', period) or _period_growth(income_rows, 'n_income', period),
            'ebit_yoy': _period_growth(income_rows, 'operate_profit', period),
            'roe': getattr(indicator, 'roe', None) if indicator else None,
            'gross_margin_change': _rate_yoy(
                getattr(indicator, 'grossprofit_margin', None) if indicator else None,
                getattr(previous_indicator, 'grossprofit_margin', None) if previous_indicator else None,
            ),
            'operating_cash_flow': _number(_amount_value(cashflow, 'n_cashflow_act')),
            'liquidity_ratio': current_assets / current_liab if current_assets is not None and current_liab else None,
            'net_cash': cash is not None and short_debt is not None and long_debt is not None and cash >= short_debt + long_debt,
            'financial_end_date': period.isoformat(),
            'financial_status': 'COMPLETE',
        }
    return result


def _valuation_rows(securities, asof_date):
    ids = [security.id for security in securities]
    traditional = TraditionalValuationVariantSummaryLatest.objects.filter(
        security_id__in=ids, profit_bucket='formal', style_profile='baseline', is_active_variant=True,
    ).order_by('security_id', '-asof_date', '-updated_at')
    traditional_by_security = {}
    for row in traditional:
        if row.asof_date <= asof_date:
            traditional_by_security.setdefault(row.security_id, row)
    predictive = PredictiveValuationCurrent.objects.select_related('snapshot').filter(security_id__in=ids).order_by('security_id', '-asof_date', '-updated_at')
    predictive_by_security = {}
    for row in predictive:
        if row.asof_date <= asof_date:
            predictive_by_security.setdefault(row.security_id, row)
    result = {}
    for security in securities:
        traditional_row = traditional_by_security.get(security.id)
        predictive_row = predictive_by_security.get(security.id)
        traditional_score = None
        if traditional_row:
            traditional_score = (traditional_row.provenance or {}).get('buy_candidate_summary', {}).get('undervalue_score')
        result[security.id] = {
            'value_valuation_score': _number(traditional_score),
            'model_valuation_score': _number(predictive_row.signal_score) if predictive_row else None,
            'traditional_status': 'OK' if traditional_score is not None else 'NOT_AVAILABLE',
            'predictive_status': 'OK' if predictive_row and predictive_row.signal_score is not None else 'NOT_AVAILABLE',
            'traditional_asof_date': _date(traditional_row.asof_date) if traditional_row else None,
            'predictive_asof_date': _date(predictive_row.asof_date) if predictive_row else None,
            'model_version': predictive_row.model_version if predictive_row else None,
        }
    return result


def screen(*, filters, report_type='26H1', asof_date=None, market='all', industry=None, page=1, page_size=20, sort_key='score', sort_direction='desc'):
    asof_date = asof_date or date.today()
    if asof_date > date.today():
        raise StockSelectionRequestError('INVALID_DATE', 'asof_date 不能晚于当前日期')
    report_type, report_year, report_month = _parse_report_type(report_type)
    if market not in {'all', 'sh-main', 'sz-main', 'cyb', 'star'}:
        raise StockSelectionRequestError('INVALID_REQUEST', 'market 不受支持')
    if sort_key not in SORT_KEYS or sort_direction not in {'asc', 'desc'}:
        raise StockSelectionRequestError('INVALID_REQUEST', '排序参数不受支持')
    if page < 1 or page_size < 1 or page_size > 200:
        raise StockSelectionRequestError('INVALID_REQUEST', 'page 或 page_size 超出允许范围')
    queryset = Security.objects.filter(asset_type=Security.AssetType.STOCK)
    if report_year:
        candidate_ids = FinancialIncomeRecord.objects.filter(
            end_date__year=report_year,
            end_date__month=report_month,
            ann_date__isnull=False,
            ann_date__lte=asof_date,
        ).values('security_id').distinct()
        queryset = queryset.filter(id__in=candidate_ids)
    queryset = queryset.order_by('ts_code')
    securities = [security for security in queryset if _market_match(security.ts_code, market)]
    if industry:
        securities = [security for security in securities if getattr(security, 'industry_code', '') == industry]
    financial_values = _batch_financial_values(securities, asof_date, report_year, report_month)
    matched = []
    for security in securities:
        values = financial_values.get(security.id)
        if not values:
            continue
        checks = {
            'revenue_yoy': values['revenue_yoy'] is not None and values['revenue_yoy'] * 100 >= filters['revenue_yoy_min'],
            'profit_yoy': values['profit_yoy'] is not None and values['profit_yoy'] * 100 >= filters['profit_yoy_min'],
            'ebit_yoy': values['ebit_yoy'] is not None and values['ebit_yoy'] * 100 >= filters['ebit_yoy_min'],
            'roe': values['roe'] is not None and values['roe'] >= filters['roe_min'],
            'gross_margin': not filters['gross_margin_improved'] or (values['gross_margin_change'] is not None and values['gross_margin_change'] > 0),
            'cash_flow': not filters['operating_cash_flow_positive'] or (values['operating_cash_flow'] is not None and values['operating_cash_flow'] > 0),
            'liquidity': values['liquidity_ratio'] is not None and values['liquidity_ratio'] >= filters['liquidity_ratio_min'],
            'net_cash': not filters['net_cash'] or values['net_cash'],
        }
        if all(checks.values()):
            matched.append((security, values))
    valuations = _valuation_rows([security for security, _ in matched], asof_date)
    items = []
    for security, values in matched:
        values.update(valuations[security.id])
        item = {'ts_code': security.ts_code, 'name': security.name, **values, 'data_status': 'PARTIAL_SUCCESS' if values['traditional_status'] != 'OK' or values['predictive_status'] != 'OK' else 'OK', 'warnings': []}
        items.append(item)
    key = 'financial_score' if sort_key == 'score' else sort_key
    items.sort(key=lambda item: (item.get(key) is None, item.get(key) if item.get(key) is not None else 0, item['ts_code']), reverse=sort_direction == 'desc')
    total = len(items)
    return (
        Page(items[(page - 1) * page_size:page * page_size], page, page_size, total),
        total,
        len(securities),
    )
