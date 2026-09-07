from __future__ import annotations

import logging
from typing import Any, Type

from django.db import transaction
from django.utils import timezone
from market_data.models import Security

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
    FinancialIngestionRun,
    FinancialIngestionWatermark,
    FinancialMainBusinessRecord,
    RawFinancialAuditModel,
)
from financials.services.normalization import (
    compute_row_signature,
    normalize_date,
    normalize_decimal,
    normalize_value,
)

logger = logging.getLogger(__name__)

ENDPOINT_MODEL_MAP: dict[str, Type[RawFinancialAuditModel]] = {
    'income_vip': FinancialIncomeRecord,
    'income': FinancialIncomeRecord,
    'balancesheet_vip': FinancialBalanceSheetRecord,
    'balancesheet': FinancialBalanceSheetRecord,
    'cashflow_vip': FinancialCashFlowRecord,
    'cashflow': FinancialCashFlowRecord,
    'fina_indicator_vip': FinancialIndicatorRecord,
    'fina_indicator': FinancialIndicatorRecord,
    'forecast_vip': FinancialForecastRecord,
    'forecast': FinancialForecastRecord,
    'express_vip': FinancialExpressRecord,
    'express': FinancialExpressRecord,
    'dividend': FinancialDividendRecord,
    'fina_audit': FinancialAuditRecord,
    'fina_mainbz_vip': FinancialMainBusinessRecord,
    'fina_mainbz': FinancialMainBusinessRecord,
    'disclosure_date': FinancialDisclosureRecord,
}


class FinancialRepository:
    def __init__(self):
        # Cache securities by ts_code
        self._security_cache: dict[str, Security] = {}

    def get_security(self, ts_code: str) -> Security | None:
        if not ts_code:
            return None
        code = ts_code.strip().upper()
        if code in self._security_cache:
            return self._security_cache[code]
        try:
            sec = Security.objects.get(ts_code=code)
            self._security_cache[code] = sec
            return sec
        except Security.DoesNotExist:
            return None

    def upsert_raw_records(
        self,
        endpoint: str,
        records: list[dict[str, Any]],
        batch_size: int = 1000,
    ) -> tuple[int, int, int]:
        """
        Returns (accepted_count, upserted_count, rejected_count)
        """
        model_cls = ENDPOINT_MODEL_MAP.get(endpoint)
        if model_cls is None:
            raise ValueError(f'No model mapping found for endpoint {endpoint}')

        if not records:
            return 0, 0, 0

        instances_to_create: list[RawFinancialAuditModel] = []
        accepted = 0
        rejected = 0

        for r in records:
            ts_code = normalize_value(r.get('ts_code'))
            if not ts_code:
                rejected += 1
                continue
            sec = self.get_security(ts_code)
            if not sec:
                # If security is not found in market_data.Security master, reject
                rejected += 1
                continue

            ann_date = normalize_date(r.get('ann_date') or r.get('f_ann_date') or r.get('publish_date'))
            end_date = normalize_date(r.get('end_date'))
            period = str(normalize_value(r.get('period') or (end_date.strftime('%Y%m%d') if end_date else '')) or '')
            row_sig = compute_row_signature(r)

            common_kwargs = {
                'security': sec,
                'ts_code': ts_code,
                'ann_date': ann_date,
                'end_date': end_date,
                'period': period,
                'row_signature': row_sig,
                'source': 'tushare',
                'raw_payload': {k: normalize_value(v) for k, v in r.items()},
            }

            inst = self._build_model_instance(model_cls, r, common_kwargs)
            instances_to_create.append(inst)
            accepted += 1

        if not instances_to_create:
            return accepted, 0, rejected

        upserted = 0
        update_fields = [
            f.name
            for f in model_cls._meta.fields
            if f.name not in {'id', 'security', 'ann_date', 'end_date', 'period', 'row_signature', 'imported_at'}
        ]

        with transaction.atomic():
            for i in range(0, len(instances_to_create), batch_size):
                chunk = instances_to_create[i : i + batch_size]
                model_cls.objects.bulk_create(
                    chunk,
                    update_conflicts=True,
                    unique_fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                    update_fields=update_fields,
                )
                upserted += len(chunk)

        return accepted, upserted, rejected

    def _build_model_instance(
        self,
        model_cls: Type[RawFinancialAuditModel],
        raw_row: dict[str, Any],
        common_kwargs: dict[str, Any],
    ) -> RawFinancialAuditModel:
        kwargs = dict(common_kwargs)

        if issubclass(model_cls, FinancialIncomeRecord):
            kwargs.update({
                'f_ann_date': normalize_date(raw_row.get('f_ann_date')),
                'report_type': str(normalize_value(raw_row.get('report_type')) or ''),
                'comp_type': str(normalize_value(raw_row.get('comp_type')) or ''),
                'revenue': normalize_decimal(raw_row.get('revenue')),
                'total_revenue': normalize_decimal(raw_row.get('total_revenue')),
                'oper_cost': normalize_decimal(raw_row.get('oper_cost')),
                'operate_profit': normalize_decimal(raw_row.get('operate_profit')),
                'total_profit': normalize_decimal(raw_row.get('total_profit')),
                'income_tax': normalize_decimal(raw_row.get('income_tax')),
                'n_income': normalize_decimal(raw_row.get('n_income')),
                'n_income_attr_p': normalize_decimal(raw_row.get('n_income_attr_p')),
                'basic_eps': normalize_decimal(raw_row.get('basic_eps')),
                'diluted_eps': normalize_decimal(raw_row.get('diluted_eps')),
            })
        elif issubclass(model_cls, FinancialBalanceSheetRecord):
            kwargs.update({
                'f_ann_date': normalize_date(raw_row.get('f_ann_date')),
                'report_type': str(normalize_value(raw_row.get('report_type')) or ''),
                'comp_type': str(normalize_value(raw_row.get('comp_type')) or ''),
                'total_assets': normalize_decimal(raw_row.get('total_assets')),
                'total_liab': normalize_decimal(raw_row.get('total_liab')),
                'total_hldr_eqy_exc_min_int': normalize_decimal(raw_row.get('total_hldr_eqy_exc_min_int')),
                'total_hldr_eqy_inc_min_int': normalize_decimal(raw_row.get('total_hldr_eqy_inc_min_int')),
                'money_cap': normalize_decimal(raw_row.get('money_cap')),
                'accounts_receiv': normalize_decimal(raw_row.get('accounts_receiv')),
                'inventories': normalize_decimal(raw_row.get('inventories')),
                'short_borrow': normalize_decimal(raw_row.get('short_borrow')),
                'long_borrow': normalize_decimal(raw_row.get('long_borrow')),
                'total_cur_assets': normalize_decimal(raw_row.get('total_cur_assets')),
                'total_cur_liab': normalize_decimal(raw_row.get('total_cur_liab')),
            })
        elif issubclass(model_cls, FinancialCashFlowRecord):
            kwargs.update({
                'f_ann_date': normalize_date(raw_row.get('f_ann_date')),
                'report_type': str(normalize_value(raw_row.get('report_type')) or ''),
                'comp_type': str(normalize_value(raw_row.get('comp_type')) or ''),
                'n_cashflow_act': normalize_decimal(raw_row.get('n_cashflow_act')),
                'n_cashflow_inv_act': normalize_decimal(raw_row.get('n_cashflow_inv_act')),
                'n_cash_flows_fnc_act': normalize_decimal(raw_row.get('n_cash_flows_fnc_act')),
                'c_cash_equ_end_period': normalize_decimal(raw_row.get('c_cash_equ_end_period')),
                'net_incr_cash_cash_equ': normalize_decimal(raw_row.get('net_incr_cash_cash_equ')),
            })
        elif issubclass(model_cls, FinancialIndicatorRecord):
            kwargs.update({
                'roe': normalize_decimal(raw_row.get('roe')),
                'roe_waa': normalize_decimal(raw_row.get('roe_waa')),
                'roe_dt': normalize_decimal(raw_row.get('roe_dt')),
                'roa': normalize_decimal(raw_row.get('roa')),
                'grossprofit_margin': normalize_decimal(raw_row.get('grossprofit_margin')),
                'netprofit_margin': normalize_decimal(raw_row.get('netprofit_margin')),
                'debt_to_assets': normalize_decimal(raw_row.get('debt_to_assets')),
                'current_ratio': normalize_decimal(raw_row.get('current_ratio')),
                'quick_ratio': normalize_decimal(raw_row.get('quick_ratio')),
                'assets_turn': normalize_decimal(raw_row.get('assets_turn')),
                'bps': normalize_decimal(raw_row.get('bps')),
                'eps': normalize_decimal(raw_row.get('eps')),
                'dt_eps': normalize_decimal(raw_row.get('dt_eps')),
                'ocfps': normalize_decimal(raw_row.get('ocfps')),
                'or_yoy': normalize_decimal(raw_row.get('or_yoy')),
                'netprofit_yoy': normalize_decimal(raw_row.get('netprofit_yoy')),
            })
        elif issubclass(model_cls, FinancialForecastRecord):
            kwargs.update({
                'type': str(normalize_value(raw_row.get('type')) or ''),
                'p_change_min': normalize_decimal(raw_row.get('p_change_min')),
                'p_change_max': normalize_decimal(raw_row.get('p_change_max')),
                'net_profit_min': normalize_decimal(raw_row.get('net_profit_min')),
                'net_profit_max': normalize_decimal(raw_row.get('net_profit_max')),
                'last_parent_net': normalize_decimal(raw_row.get('last_parent_net')),
                'summary': str(normalize_value(raw_row.get('summary')) or ''),
                'change_reason': str(normalize_value(raw_row.get('change_reason')) or ''),
            })
        elif issubclass(model_cls, FinancialExpressRecord):
            kwargs.update({
                'revenue': normalize_decimal(raw_row.get('revenue')),
                'operate_profit': normalize_decimal(raw_row.get('operate_profit')),
                'total_profit': normalize_decimal(raw_row.get('total_profit')),
                'n_income': normalize_decimal(raw_row.get('n_income')),
                'total_assets': normalize_decimal(raw_row.get('total_assets')),
                'total_hldr_eqy_exc_min_int': normalize_decimal(raw_row.get('total_hldr_eqy_exc_min_int')),
                'basic_eps': normalize_decimal(raw_row.get('basic_eps')),
                'roe': normalize_decimal(raw_row.get('roe')),
                'growth_yoy': normalize_decimal(raw_row.get('growth_yoy')),
            })
        elif issubclass(model_cls, FinancialDividendRecord):
            kwargs.update({
                'stk_div': normalize_decimal(raw_row.get('stk_div')),
                'cash_div_tax': normalize_decimal(raw_row.get('cash_div_tax')),
                'record_date': normalize_date(raw_row.get('record_date')),
                'ex_date': normalize_date(raw_row.get('ex_date')),
                'pay_date': normalize_date(raw_row.get('pay_date')),
                'div_proc': str(normalize_value(raw_row.get('div_proc')) or ''),
            })
        elif issubclass(model_cls, FinancialAuditRecord):
            kwargs.update({
                'audit_result': str(normalize_value(raw_row.get('audit_result')) or ''),
                'audit_agency': str(normalize_value(raw_row.get('audit_agency')) or ''),
                'audit_sign': str(normalize_value(raw_row.get('audit_sign')) or ''),
                'audit_fees': normalize_decimal(raw_row.get('audit_fees')),
            })
        elif issubclass(model_cls, FinancialMainBusinessRecord):
            kwargs.update({
                'bz_item': str(normalize_value(raw_row.get('bz_item')) or ''),
                'bz_sales': normalize_decimal(raw_row.get('bz_sales')),
                'bz_profit': normalize_decimal(raw_row.get('bz_profit')),
                'bz_cost': normalize_decimal(raw_row.get('bz_cost')),
                'curr_type': str(normalize_value(raw_row.get('curr_type')) or ''),
                'type': str(normalize_value(raw_row.get('type')) or ''),
            })
        elif issubclass(model_cls, FinancialDisclosureRecord):
            kwargs.update({
                'pre_date': normalize_date(raw_row.get('pre_date')),
                'actual_date': normalize_date(raw_row.get('actual_date')),
                'modify_date': normalize_date(raw_row.get('modify_date')),
            })

        return model_cls(**kwargs)

    def create_ingestion_run(
        self,
        mode: str,
        endpoints: str,
        scope: str,
        scope_key: str,
        period: str = '',
        start_date: Any = None,
        end_date: Any = None,
    ) -> FinancialIngestionRun:
        return FinancialIngestionRun.objects.create(
            mode=mode.upper(),
            endpoints=endpoints,
            scope=scope,
            scope_key=scope_key,
            period=period,
            requested_start_date=start_date,
            requested_end_date=end_date,
            status=FinancialIngestionRun.Status.RUNNING,
            started_at=timezone.now(),
        )

    def finish_ingestion_run(
        self,
        run: FinancialIngestionRun,
        status: str,
        source_count: int,
        accepted_count: int,
        upserted_count: int,
        rejected_count: int,
        retry_count: int,
        projection_count: int = 0,
        error_summary: str = '',
    ) -> None:
        run.status = status
        run.source_row_count = source_count
        run.accepted_row_count = accepted_count
        run.upserted_row_count = upserted_count
        run.rejected_row_count = rejected_count
        run.retry_count = retry_count
        run.projection_rebuild_count = projection_count
        run.error_summary = error_summary
        run.finished_at = timezone.now()
        run.save()

    def advance_watermark(
        self,
        endpoint: str,
        scope_key: str,
        last_date: Any = None,
        last_period: str = '',
        run: FinancialIngestionRun | None = None,
    ) -> FinancialIngestionWatermark:
        watermark, _ = FinancialIngestionWatermark.objects.get_or_create(
            endpoint=endpoint,
            scope_key=scope_key,
        )
        watermark.last_complete_source_date = last_date or watermark.last_complete_source_date
        watermark.last_complete_period = last_period or watermark.last_complete_period
        watermark.last_complete_run = run
        watermark.status = FinancialIngestionRun.Status.SUCCEEDED
        watermark.save()
        return watermark
