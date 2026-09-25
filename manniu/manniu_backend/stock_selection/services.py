from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata

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
from market_data.models import Security, StockDailyFundamentalHistory
from predictive_valuation.models import PredictiveValuationCurrent
from traditional_valuation.models import TraditionalValuationVariantSummaryLatest

PRESETS = {
    'maniu-selected': {
        'revenue_yoy_min': 8, 'profit_yoy_min': 8, 'ebit_yoy_min': 8,
        'roe_min': 15, 'roic_min': 12, 'gross_margin_improved': True,
        'operating_cash_flow_positive': True, 'free_cash_flow_positive': True,
        'debt_to_assets_max': 50, 'liquidity_ratio_min': 1.5,
        'pe_ttm_max': 25, 'dividend_yield_min': 2,
    },
    'buffett-moat': {
        'revenue_yoy_min': 5, 'profit_yoy_min': 5,
        'roe_min': 20, 'roic_min': 15, 'gross_margin_min': 40,
        'operating_cash_flow_positive': True, 'free_cash_flow_positive': True,
        'debt_to_assets_max': 50, 'pe_ttm_max': 30,
    },
    'high-growth': {
        'revenue_yoy_min': 20, 'profit_yoy_min': 20, 'ebit_yoy_min': 20,
        'roe_min': 10, 'operating_cash_flow_positive': True, 'peg_max': 1.5,
    },
    'cash-cow': {
        'roe_min': 15, 'roic_min': 12,
        'operating_cash_flow_positive': True, 'free_cash_flow_positive': True,
        'net_cash': True, 'pe_ttm_max': 20,
    },
    'undervalued': {
        'roe_min': 10, 'operating_cash_flow_positive': True,
        'debt_to_assets_max': 60, 'pe_ttm_max': 15, 'pb_max': 1.5,
    },
    'high-dividend': {
        'roe_min': 10, 'operating_cash_flow_positive': True, 'dividend_yield_min': 5,
    },
    'small-beautiful': {
        'revenue_yoy_min': 15, 'profit_yoy_min': 15, 'roe_min': 15,
        'operating_cash_flow_positive': True,
        'market_cap_min': 200_000, 'market_cap_max': 2_000_000,
    },
    'turnaround': {
        'revenue_yoy_min': 0, 'profit_yoy_min': 0, 'roe_min': 8,
        'operating_cash_flow_positive': True, 'pb_max': 2,
    },
    'net-cash-bargain': {
        'net_profit_positive': True, 'net_cash': True,
        'pe_ttm_max': 12, 'pb_max': 1.5,
    },
    'risk-scan': {},
}
SORT_KEYS = {
    'score', 'value_valuation_score', 'model_valuation_score', 'revenue_yoy', 'profit_yoy',
    'ebit_yoy', 'roe', 'roic', 'gross_margin', 'gross_margin_change', 'operating_cash_flow',
    'free_cash_flow', 'cash_profit_ratio', 'debt_to_assets', 'liquidity_ratio',
    'goodwill_to_equity', 'market_cap', 'pe_ttm', 'pb', 'peg', 'dividend_yield',
}
REPORT_MONTHS = {'Q1': 3, 'H1': 6, 'Q3': 9, 'FY': 12}
REPORT_TYPE_PATTERN = re.compile(r'^(?P<year>\d{2})(?P<period>Q1|H1|Q3|FY)$')
NUMERIC_FILTER_FIELDS = {
    'revenue_yoy': 'revenue_yoy',
    'profit_yoy': 'profit_yoy',
    'ebit_yoy': 'ebit_yoy',
    'roe': 'roe',
    'roic': 'roic',
    'gross_margin': 'gross_margin',
    'cash_profit_ratio': 'cash_profit_ratio',
    'debt_to_assets': 'debt_to_assets',
    'liquidity_ratio': 'liquidity_ratio',
    'goodwill_to_equity': 'goodwill_to_equity',
    'pe_ttm': 'pe_ttm',
    'pb': 'pb',
    'peg': 'peg',
    'dividend_yield': 'dividend_yield',
    'market_cap': 'market_cap_10k',
}
BOOLEAN_FILTER_FIELDS = {
    'net_profit_positive': 'net_profit_positive',
    'gross_margin_improved': 'gross_margin_change',
    'operating_cash_flow_positive': 'operating_cash_flow',
    'free_cash_flow_positive': 'free_cash_flow',
    'net_cash': 'net_cash',
}
RISK_RULES = (
    ('net_profit_yoy_negative_2y', 'net_profit_yoy_negative_2y', '连续两年净利润同比为负'),
    ('roe_below_5', 'roe', 'ROE < 5%'),
    ('operating_cash_flow_negative', 'operating_cash_flow', '经营现金流为负'),
    ('debt_to_assets_above_70', 'debt_to_assets', '资产负债率 > 70%'),
    ('goodwill_to_equity_above_30', 'goodwill_to_equity', '商誉/净资产 > 30%'),
)
RISK_THRESHOLDS = {
    'net_profit_yoy_negative_2y': '连续两个可比报告期同比 < 0%',
    'roe_below_5': '< 5%',
    'operating_cash_flow_negative': '< 0 CNY',
    'debt_to_assets_above_70': '> 70%',
    'goodwill_to_equity_above_30': '> 30%',
}


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
    unassessed_count: int = 0
    risk_summary: dict | None = None

    @property
    def has_next(self):
        return self.page * self.page_size < self.total


def _number(value):
    return float(value) if isinstance(value, Decimal) else value


def _date(value):
    return value.isoformat() if value else None


def _raw_decimal(row, key):
    payload = getattr(row, 'raw_payload', None) or {}
    value = payload.get(key) if isinstance(payload, dict) else None
    if value in (None, ''):
        return None
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _growth_percent(rows, field, period):
    growth = _period_growth(rows, field, period)
    return growth * 100 if growth is not None else None


def _period_amount(rows, period, field):
    row = _latest_row(rows, period)
    if row is None or row.end_date != period:
        return None
    return _number(getattr(row, field, None))


def _two_year_negative_growth(rows, period):
    previous_period = period.replace(year=period.year - 1)
    prior_period = period.replace(year=period.year - 2)
    current = _period_amount(rows, period, 'n_income')
    previous = _period_amount(rows, previous_period, 'n_income')
    prior = _period_amount(rows, prior_period, 'n_income')
    if current is None or previous in (None, 0) or prior in (None, 0):
        return None
    return (current - previous) / abs(previous) < 0 and (previous - prior) / abs(prior) < 0


def _matches_filters(values, filters):
    missing = []
    matches = True
    for name, field in NUMERIC_FILTER_FIELDS.items():
        value = values.get(field)
        for bound, comparator in (('min', lambda actual, limit: actual >= limit), ('max', lambda actual, limit: actual <= limit)):
            key = f'{name}_{bound}'
            if key not in filters or filters[key] is None:
                continue
            if value is None:
                missing.append(key)
            elif not comparator(value, filters[key]):
                matches = False

    for key, field in BOOLEAN_FILTER_FIELDS.items():
        if not filters.get(key, False):
            continue
        value = values.get(field)
        if value is None:
            missing.append(key)
        elif key in {'gross_margin_improved', 'operating_cash_flow_positive', 'free_cash_flow_positive'}:
            if value <= 0:
                matches = False
        elif not value:
            matches = False
    return matches and not missing, missing


def _risk_evaluation(values):
    flags = []
    unassessed = []
    summary = {}
    for rule_key, field, label in RISK_RULES:
        value = values.get(field)
        if value is None:
            summary[rule_key] = 'unassessed'
            unassessed.append(rule_key)
            continue
        hit = value is True if field == 'net_profit_yoy_negative_2y' else (
            value < 5 if rule_key == 'roe_below_5' else (
                value < 0 if rule_key == 'operating_cash_flow_negative' else value > (70 if rule_key == 'debt_to_assets_above_70' else 30)
            )
        )
        summary[rule_key] = 'hit' if hit else 'clear'
        if hit:
            flags.append({'rule': rule_key, 'label': label, 'value': value, 'threshold': RISK_THRESHOLDS[rule_key]})
    return flags, unassessed, summary


def _main_business_summary(value):
    text = str(value or '').strip()
    for index, character in enumerate(text):
        if unicodedata.category(character).startswith('P'):
            return text[:index].strip()
    return text


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
    years = range(report_year - 2, report_year + 1)
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
        total_assets = _number(balance.total_assets) if balance else None
        total_liab = _number(balance.total_liab) if balance else None
        net_income = _number(income.n_income) if income else None
        operating_cash_flow = _number(_amount_value(cashflow, 'n_cashflow_act'))
        cash = _number(balance.money_cap) if balance else None
        short_debt = _number(balance.st_borr if balance.st_borr is not None else balance.short_borrow) if balance else None
        long_debt = _number(balance.lt_borr if balance.lt_borr is not None else balance.long_borrow) if balance else None
        current_ratio = _number(indicator.current_ratio) if indicator else None
        gross_margin = _number(indicator.grossprofit_margin) if indicator else None
        previous_gross_margin = _number(previous_indicator.grossprofit_margin) if previous_indicator else None
        equity_for_goodwill = total_assets - total_liab if total_assets is not None and total_liab is not None else None
        goodwill = _raw_decimal(balance, 'goodwill')
        goodwill_to_equity = (
            _number(goodwill / Decimal(str(equity_for_goodwill)) * 100)
            if goodwill is not None and equity_for_goodwill is not None and equity_for_goodwill > 0
            else None
        )
        free_cash_flow = _raw_decimal(cashflow, 'free_cashflow')
        cash_profit_ratio = (
            operating_cash_flow / net_income
            if operating_cash_flow is not None and net_income is not None and net_income > 0
            else None
        )
        revenue_yoy = _number(indicator.or_yoy) if indicator and indicator.or_yoy is not None else _growth_percent(income_rows, 'revenue', period)
        profit_yoy = _number(indicator.netprofit_yoy) if indicator and indicator.netprofit_yoy is not None else _growth_percent(income_rows, 'n_income', period)
        ebit_yoy = _growth_percent(income_rows, 'operate_profit', period)
        roe = _number(indicator.roe) if indicator else None
        roic = _number(_raw_decimal(indicator, 'roic')) if indicator else None
        result[security.id] = {
            'financial_score': evaluation['overall']['score'],
            'revenue_yoy': revenue_yoy,
            'profit_yoy': profit_yoy,
            'ebit_yoy': ebit_yoy,
            'roe': roe,
            'roic': roic,
            'gross_margin': gross_margin,
            'gross_margin_change': _rate_yoy(gross_margin, previous_gross_margin),
            'operating_cash_flow': operating_cash_flow,
            'free_cash_flow': _number(free_cash_flow),
            'cash_profit_ratio': _number(cash_profit_ratio),
            'debt_to_assets': _number(indicator.debt_to_assets) if indicator else None,
            'liquidity_ratio': current_ratio,
            'goodwill_to_equity': goodwill_to_equity,
            'net_cash': (
                cash >= short_debt + long_debt
                if cash is not None and short_debt is not None and long_debt is not None
                else None
            ),
            'net_profit_positive': net_income > 0 if net_income is not None else None,
            'net_profit_yoy_negative_2y': _two_year_negative_growth(income_rows, period),
            'financial_end_date': period.isoformat(),
            'financial_status': 'COMPLETE',
        }
    return result


def _market_fundamental_values(securities, asof_date):
    ids = [security.id for security in securities]
    rows = StockDailyFundamentalHistory.objects.filter(
        security_id__in=ids, trade_date__lte=asof_date,
    ).order_by('security_id', '-trade_date', '-id').distinct('security_id')
    latest_by_security = {row.security_id: row for row in rows}
    values = {}
    for security in securities:
        row = latest_by_security.get(security.id)
        raw_pe_ttm = _number(row.pe_ttm) if row and row.pe_ttm is not None else None
        raw_pb = _number(row.pb) if row and row.pb is not None else None
        pe_ttm = raw_pe_ttm if raw_pe_ttm is not None and raw_pe_ttm > 0 else None
        pb = raw_pb if raw_pb is not None and raw_pb > 0 else None
        dividend_yield = _number(row.dv_ratio) if row and row.dv_ratio is not None else None
        total_mv = _number(row.total_mv) if row and row.total_mv is not None else None
        values[security.id] = {
            'pe_ttm': pe_ttm,
            'pb': pb,
            'peg': None,
            'dividend_yield': dividend_yield,
            'market_cap_10k': total_mv,
            'market_cap': total_mv / 10_000 if total_mv is not None else None,
            'market_fundamental_date': _date(row.trade_date) if row else None,
        }
    return values


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


def screen(*, filters, report_type='26H1', asof_date=None, market='all', industry=None, page=1, page_size=20, sort_key='score', sort_direction='desc', screen_mode='screen'):
    asof_date = asof_date or date.today()
    if asof_date > date.today():
        raise StockSelectionRequestError('INVALID_DATE', 'asof_date 不能晚于当前日期')
    report_type, report_year, report_month = _parse_report_type(report_type)
    if market not in {'all', 'sh-main', 'sz-main', 'cyb', 'star'}:
        raise StockSelectionRequestError('INVALID_REQUEST', 'market 不受支持')
    if screen_mode not in {'screen', 'risk'}:
        raise StockSelectionRequestError('INVALID_REQUEST', 'screen_mode 不受支持')
    if sort_key not in SORT_KEYS or sort_direction not in {'asc', 'desc'}:
        raise StockSelectionRequestError('INVALID_REQUEST', '排序参数不受支持')
    if page < 1 or page_size < 1 or page_size > 200:
        raise StockSelectionRequestError('INVALID_REQUEST', 'page 或 page_size 超出允许范围')
    queryset = Security.objects.select_related('industry', 'company_profile').filter(asset_type=Security.AssetType.STOCK)
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
    market_values = _market_fundamental_values(securities, asof_date)
    matched = []
    unassessed_count = 0
    risk_counts = {
        rule_key: {
            'label': label,
            'threshold': RISK_THRESHOLDS[rule_key],
            'hit_count': 0,
            'unassessed_count': 0,
        }
        for rule_key, _, label in RISK_RULES
    }
    for security in securities:
        values = financial_values.get(security.id)
        if not values:
            continue
        values.update(market_values.get(security.id, {}))
        pe_ttm = values.get('pe_ttm')
        profit_yoy = values.get('profit_yoy')
        values['peg'] = pe_ttm / profit_yoy if pe_ttm is not None and profit_yoy is not None and profit_yoy > 0 else None
        if screen_mode == 'risk':
            risk_flags, unassessed_rules, risk_results = _risk_evaluation(values)
            for rule_key, result in risk_results.items():
                if result == 'hit':
                    risk_counts[rule_key]['hit_count'] += 1
                elif result == 'unassessed':
                    risk_counts[rule_key]['unassessed_count'] += 1
            if unassessed_rules:
                unassessed_count += 1
            if risk_flags:
                values['risk_flags'] = risk_flags
                values['unassessed_risk_rules'] = unassessed_rules
                matched.append((security, values))
            continue

        is_match, missing_filters = _matches_filters(values, filters)
        if missing_filters:
            unassessed_count += 1
        if is_match:
            values['risk_flags'] = []
            values['unassessed_risk_rules'] = []
            matched.append((security, values))

    valuations = _valuation_rows([security for security, _ in matched], asof_date)
    items = []
    for security, values in matched:
        values.pop('market_cap_10k', None)
        values.update(valuations[security.id])
        try:
            main_business = security.company_profile.main_business or ''
        except Security.company_profile.RelatedObjectDoesNotExist:
            main_business = ''
        warnings = []
        if values.get('unassessed_risk_rules'):
            warnings.append({'code': 'RISK_RULES_UNASSESSED', 'rules': values['unassessed_risk_rules']})
        missing_metrics = [
            field for field in (
                'revenue_yoy', 'profit_yoy', 'ebit_yoy', 'roe', 'roic', 'gross_margin',
                'gross_margin_change', 'operating_cash_flow', 'free_cash_flow',
                'cash_profit_ratio', 'debt_to_assets', 'liquidity_ratio',
                'goodwill_to_equity', 'market_cap', 'pe_ttm', 'pb', 'peg', 'dividend_yield',
            ) if values.get(field) is None
        ]
        if missing_metrics:
            warnings.append({'code': 'METRICS_UNAVAILABLE', 'fields': missing_metrics})
        item = {
            'ts_code': security.ts_code,
            'name': security.name,
            'industry': security.industry.name if security.industry_id else '',
            'main_business': _main_business_summary(main_business),
            **values,
            'data_status': 'PARTIAL_SUCCESS' if missing_metrics or values['traditional_status'] != 'OK' or values['predictive_status'] != 'OK' or values.get('unassessed_risk_rules') else 'OK',
            'warnings': warnings,
        }
        items.append(item)
    key = 'financial_score' if sort_key == 'score' else sort_key
    available_items = [item for item in items if item.get(key) is not None]
    unavailable_items = [item for item in items if item.get(key) is None]
    available_items.sort(key=lambda item: item['ts_code'])
    available_items.sort(key=lambda item: item[key], reverse=sort_direction == 'desc')
    unavailable_items.sort(key=lambda item: item['ts_code'])
    items = available_items + unavailable_items
    total = len(items)
    return (
        Page(
            items[(page - 1) * page_size:page * page_size], page, page_size, total,
            unassessed_count=unassessed_count,
            risk_summary={'version': 'risk_v1', 'rules': risk_counts} if screen_mode == 'risk' else None,
        ),
        total,
        len(securities),
    )
