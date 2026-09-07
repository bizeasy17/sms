from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Q

from financials.models import (
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialDisclosureRecord,
    FinancialIncomeRecord,
    FinancialIndicatorRecord,
)
from market_data.models import Security
from predictive_valuation.models import (
    PredictiveFinancialFeatureLatest,
    PredictiveFinancialFeaturePanel,
)


class PredictiveFinancialFeatureBuilder:
    """Build model-compatible, point-in-time financial projections from raw records."""

    @classmethod
    def rebuild_for_security(
        cls,
        security: Security | int,
        as_of_date: date | None = None,
    ) -> int:
        if isinstance(security, int):
            security = Security.objects.get(id=security)

        disclosure_dates = cls._effective_disclosure_dates(security)
        income_records = FinancialIncomeRecord.objects.filter(security=security)
        balance_records = FinancialBalanceSheetRecord.objects.filter(security=security)
        cashflow_records = FinancialCashFlowRecord.objects.filter(security=security)
        indicator_records = FinancialIndicatorRecord.objects.filter(security=security)

        periods = cls._periods(income_records, balance_records, cashflow_records, indicator_records)
        panels: list[PredictiveFinancialFeaturePanel] = []
        for end_date, report_type in periods:
            income = income_records.filter(end_date=end_date).order_by('-ann_date', '-id').first()
            balance = balance_records.filter(end_date=end_date).order_by('-ann_date', '-id').first()
            cashflow = cashflow_records.filter(end_date=end_date).order_by('-ann_date', '-id').first()
            indicator = indicator_records.filter(end_date=end_date).order_by('-ann_date', '-id').first()
            ann_date = cls._first_date(income, balance, cashflow, indicator)
            source_as_of_date = disclosure_dates.get(end_date) or ann_date
            if source_as_of_date is None or (as_of_date is not None and source_as_of_date > as_of_date):
                continue
            panels.append(
                cls._build_panel(
                    security=security,
                    end_date=end_date,
                    report_type=report_type,
                    ann_date=ann_date,
                    source_as_of_date=source_as_of_date,
                    income=income,
                    balance=balance,
                    cashflow=cashflow,
                    indicator=indicator,
                )
            )

        if not panels:
            return 0

        update_fields = [
            field.name
            for field in PredictiveFinancialFeaturePanel._meta.fields
            if field.name not in {'id', 'security', 'end_date', 'report_type', 'source_as_of_date', 'created_at'}
        ]
        with transaction.atomic():
            PredictiveFinancialFeaturePanel.objects.filter(security=security).exclude(
                Q(report_type__in=['Q1', 'H1', 'Q3', 'FY', 'OTHER'])
            ).delete()
            PredictiveFinancialFeaturePanel.objects.bulk_create(
                panels,
                update_conflicts=True,
                unique_fields=['security', 'end_date', 'report_type', 'source_as_of_date'],
                update_fields=update_fields,
            )
            if as_of_date is None:
                latest = max(panels, key=lambda panel: (panel.end_date, panel.source_as_of_date))
                latest_values = {
                    field.name: getattr(latest, field.name)
                    for field in PredictiveFinancialFeatureLatest._meta.fields
                    if field.name not in {'id', 'security', 'created_at', 'updated_at'}
                }
                PredictiveFinancialFeatureLatest.objects.update_or_create(
                    security=security,
                    defaults=latest_values,
                )
        return len(panels)

    @staticmethod
    def _effective_disclosure_dates(security: Security) -> dict[date, date]:
        dates: dict[date, date] = {}
        rows = FinancialDisclosureRecord.objects.filter(security=security).order_by('end_date', '-actual_date', '-ann_date', '-id')
        for row in rows:
            if row.end_date and row.end_date not in dates:
                effective_date = row.actual_date or row.ann_date
                if effective_date:
                    dates[row.end_date] = effective_date
        return dates

    @staticmethod
    def _periods(*querysets: Any) -> set[tuple[date, str]]:
        periods: set[tuple[date, str]] = set()
        for queryset in querysets:
            for row in queryset.values('end_date'):
                end_date = row['end_date']
                if end_date:
                    periods.add((end_date, PredictiveFinancialFeatureBuilder._report_type_from_end_date(end_date)))
        return periods

    @staticmethod
    def _report_type_from_end_date(end_date: date) -> str:
        return {
            (3, 31): 'Q1',
            (6, 30): 'H1',
            (9, 30): 'Q3',
            (12, 31): 'FY',
        }.get((end_date.month, end_date.day), 'OTHER')

    @staticmethod
    def _first_date(*records: Any) -> date | None:
        for record in records:
            if record and record.ann_date:
                return record.ann_date
        return None

    @classmethod
    def _build_panel(
        cls,
        *,
        security: Security,
        end_date: date,
        report_type: str,
        ann_date: date | None,
        source_as_of_date: date,
        income: FinancialIncomeRecord | None,
        balance: FinancialBalanceSheetRecord | None,
        cashflow: FinancialCashFlowRecord | None,
        indicator: FinancialIndicatorRecord | None,
    ) -> PredictiveFinancialFeaturePanel:
        cash_ratio = cls._divide(balance.money_cap, balance.total_cur_liab) if balance else None
        ocf_to_or = cls._divide(cashflow.n_cashflow_act, income.revenue) if cashflow and income else None
        return PredictiveFinancialFeaturePanel(
            security=security,
            end_date=end_date,
            ann_date=ann_date,
            source_as_of_date=source_as_of_date,
            fiscal_year=end_date.year,
            report_type=report_type,
            revenue=income.revenue if income else None,
            total_revenue=income.total_revenue if income else None,
            operate_profit=income.operate_profit if income else None,
            total_profit=income.total_profit if income else None,
            n_income=income.n_income if income else None,
            n_income_attr_p=income.n_income_attr_p if income else None,
            basic_eps=income.basic_eps if income else (indicator.eps if indicator else None),
            diluted_eps=income.diluted_eps if income else (indicator.dt_eps if indicator else None),
            roe=indicator.roe if indicator else None,
            roe_dt=indicator.roe_dt if indicator else None,
            roa=indicator.roa if indicator else None,
            tr_yoy=indicator.or_yoy if indicator else None,
            netprofit_yoy=indicator.netprofit_yoy if indicator else None,
            grossprofit_margin=indicator.grossprofit_margin if indicator else None,
            netprofit_margin=indicator.netprofit_margin if indicator else None,
            debt_to_assets=indicator.debt_to_assets if indicator else None,
            current_ratio=indicator.current_ratio if indicator else None,
            quick_ratio=indicator.quick_ratio if indicator else None,
            cash_ratio=cash_ratio,
            assets_turn=indicator.assets_turn if indicator else None,
            ocf_to_or=ocf_to_or,
            total_assets=balance.total_assets if balance else None,
            total_liab=balance.total_liab if balance else None,
            total_hldr_eqy_exc_min_int=balance.total_hldr_eqy_exc_min_int if balance else None,
            money_cap=balance.money_cap if balance else None,
            accounts_receiv=balance.accounts_receiv if balance else None,
            inventories=balance.inventories if balance else None,
            st_borr=balance.short_borrow if balance else None,
            lt_borr=balance.long_borrow if balance else None,
            n_cashflow_act=cashflow.n_cashflow_act if cashflow else None,
            n_cashflow_inv_act=cashflow.n_cashflow_inv_act if cashflow else None,
            n_cash_flows_fnc_act=cashflow.n_cash_flows_fnc_act if cashflow else None,
            n_incr_cash_cash_equ=cashflow.net_incr_cash_cash_equ if cashflow else None,
            raw_payload={
                'income_id': income.id if income else None,
                'balance_sheet_id': balance.id if balance else None,
                'cashflow_id': cashflow.id if cashflow else None,
                'indicator_id': indicator.id if indicator else None,
                'derived_fields': ['cash_ratio', 'ocf_to_or'],
                'unavailable_raw_fields': ['q_dt_roe'],
            },
        )

    @staticmethod
    def _divide(numerator: Any, denominator: Any) -> Any:
        if numerator is None or denominator in (None, 0):
            return None
        return numerator / denominator