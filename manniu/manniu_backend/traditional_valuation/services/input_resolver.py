from __future__ import annotations

from datetime import date
from django.db.models import Case, IntegerField, Value, When

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


def _ttm_value(current_value, annual_value, prior_period_value):
    if current_value is None:
        return None
    if annual_value is not None and prior_period_value is not None:
        return current_value + annual_value - prior_period_value
    return current_value


def _cashflow_fcff(row):
    if row is None or row.n_cashflow_act is None:
        return None
    payload = row.raw_payload or {}
    capex = payload.get('c_pay_acq_const_fiolta')
    if capex is None:
        capex = payload.get('c_pay_acq_const_fiolta_oth')
    try:
        return float(row.n_cashflow_act) - abs(float(capex or 0))
    except (TypeError, ValueError):
        return row.n_cashflow_act


def _balance_value(row, field_names):
    if row is None:
        return None
    for field_name in field_names:
        value = getattr(row, field_name, None)
        if value is None:
            value = (row.raw_payload or {}).get(field_name)
        if value is not None:
            return value
    return None


def _preferred_financial_record(queryset):
    return queryset.filter(update_flag__in=(0, 1)).order_by(
        '-end_date',
        Case(
            When(update_flag=1, then=Value(0)),
            When(update_flag=0, then=Value(1)),
            output_field=IntegerField(),
        ),
        '-ann_date',
        '-id',
    ).first()


class ValuationInputResolver:
    def resolve(self, security, asof_date, report_type='FY', financial_end_date=None, allow_express=False):
        end_filter = {}
        if financial_end_date:
            end_filter['end_date'] = financial_end_date
        else:
            end_filter = _period_filter(report_type)
        base_kwargs = {'security': security, 'ann_date__lte': asof_date, **end_filter}
        income = _preferred_financial_record(FinancialIncomeRecord.objects.filter(**base_kwargs))
        if income is None and financial_end_date:
            base_kwargs.pop('end_date', None)
            income = _preferred_financial_record(FinancialIncomeRecord.objects.filter(**base_kwargs))
        if income is None:
            raise ValueError(f'No eligible financial income record for {security.ts_code}/{report_type}')
        end_date = income.end_date
        common = {'security': security, 'ann_date__lte': asof_date, 'end_date': end_date}
        indicator = _preferred_financial_record(FinancialIndicatorRecord.objects.filter(**common))
        balance = _preferred_financial_record(FinancialBalanceSheetRecord.objects.filter(**common))
        cashflow = _preferred_financial_record(FinancialCashFlowRecord.objects.filter(**common))
        cash = _balance_value(balance, ('money_cap',))
        short_debt = _balance_value(balance, ('st_borr', 'short_borrow'))
        long_debt = _balance_value(balance, ('lt_borr', 'long_borrow'))
        bond_debt = _balance_value(balance, ('bond_payable',))
        current_maturity = _balance_value(balance, ('non_cur_liab_due_1y',))
        try:
            debt = sum(
                float(value or 0)
                for value in (short_debt, long_debt, bond_debt, current_maturity)
            )
        except (TypeError, ValueError):
            debt = None
        prior_year_end = date(end_date.year - 1, 12, 31)
        prior_period_end = date(end_date.year - 1, end_date.month, end_date.day)
        annual_income = _preferred_financial_record(FinancialIncomeRecord.objects.filter(
            security=security, ann_date__lte=asof_date, end_date=prior_year_end,
        ))
        prior_period_income = _preferred_financial_record(FinancialIncomeRecord.objects.filter(
            security=security, ann_date__lte=asof_date, end_date=prior_period_end,
        ))
        annual_cashflow = _preferred_financial_record(FinancialCashFlowRecord.objects.filter(
            security=security, ann_date__lte=asof_date, end_date=prior_year_end,
        ))
        prior_period_cashflow = _preferred_financial_record(FinancialCashFlowRecord.objects.filter(
            security=security, ann_date__lte=asof_date, end_date=prior_period_end,
        ))
        net_income = lambda row: getattr(row, 'n_income_attr_p', None) or getattr(row, 'n_income', None)
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
            'cash': cash,
            'debt': debt,
            'net_debt': None if cash is None or debt is None else debt - float(cash),
            'cashflow': cashflow,
            'ttm_net_income': _ttm_value(
                net_income(income), net_income(annual_income), net_income(prior_period_income),
            ),
            'ttm_revenue': _ttm_value(
                income.revenue, getattr(annual_income, 'revenue', None),
                getattr(prior_period_income, 'revenue', None),
            ),
            'ttm_cashflow': _ttm_value(
                _cashflow_fcff(cashflow),
                _cashflow_fcff(annual_cashflow),
                _cashflow_fcff(prior_period_cashflow),
            ),
            'dividend': dividend,
            'express': express,
            'financial_end_date': end_date,
            'financial_ann_date': income.ann_date,
            'profit_source': 'express_vip' if express else 'fina_indicator_income',
        }