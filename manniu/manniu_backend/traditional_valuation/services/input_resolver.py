from __future__ import annotations

from datetime import date

from financials.models import (
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialDividendRecord,
    FinancialDisclosureRecord,
    FinancialExpressRecord,
    FinancialIncomeRecord,
    FinancialIndicatorRecord,
)
from market_data.models import MarketBarDailyHistory, StockDailyFundamentalHistory


REPORT_SUFFIX = {'Q1': '0331', 'H1': '0630', 'Q3': '0930', 'FY': '1231', 'ANNUAL': '1231'}


def _period_filter(report_type, fiscal_year=None):
    suffix = REPORT_SUFFIX.get(str(report_type or '').upper())
    if not suffix:
        return {}
    if fiscal_year:
        return {'end_date': date(int(fiscal_year), int(suffix[:2]), int(suffix[2:]))}
    return {'end_date__month': int(suffix[:2]), 'end_date__day': int(suffix[2:])}


class ValuationInputResolver:
    def resolve(self, security, asof_date, report_type='FY', financial_end_date=None, allow_express=False):
        end_filter = {}
        if financial_end_date:
            end_filter['end_date'] = financial_end_date
        else:
            end_filter = _period_filter(report_type)
        base_kwargs = {'security': security, 'ann_date__lte': asof_date, **end_filter}
        income = FinancialIncomeRecord.objects.filter(**base_kwargs).order_by('-end_date', '-ann_date').first()
        if income is None and financial_end_date:
            base_kwargs.pop('end_date', None)
            income = FinancialIncomeRecord.objects.filter(**base_kwargs).order_by('-end_date', '-ann_date').first()
        if income is None:
            raise ValueError(f'No eligible financial income record for {security.ts_code}/{report_type}')
        end_date = income.end_date
        common = {'security': security, 'ann_date__lte': asof_date, 'end_date': end_date}
        indicator = FinancialIndicatorRecord.objects.filter(**common).order_by('-ann_date').first()
        balance = FinancialBalanceSheetRecord.objects.filter(**common).order_by('-ann_date').first()
        cashflow = FinancialCashFlowRecord.objects.filter(**common).order_by('-ann_date').first()
        dividend = FinancialDividendRecord.objects.filter(security=security, ann_date__lte=asof_date).order_by('-ann_date', '-ex_date').first()
        express = None
        if allow_express:
            express = FinancialExpressRecord.objects.filter(
                security=security, ann_date__lte=asof_date, end_date__gte=end_date,
            ).order_by('-ann_date').first()
        market = MarketBarDailyHistory.objects.filter(security=security, trade_date__lte=asof_date).order_by('-trade_date').first()
        fundamental = StockDailyFundamentalHistory.objects.filter(security=security, trade_date__lte=asof_date).order_by('-trade_date').first()
        return {
            'security': security,
            'asof_date': asof_date,
            'source_trade_date': market.trade_date if market else None,
            'current_price': market.close if market else None,
            'fundamental': fundamental,
            'income': income,
            'indicator': indicator,
            'balance': balance,
            'cashflow': cashflow,
            'dividend': dividend,
            'express': express,
            'financial_end_date': end_date,
            'financial_ann_date': income.ann_date,
            'profit_source': 'express_vip' if express else 'fina_indicator_income',
        }