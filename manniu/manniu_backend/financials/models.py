from __future__ import annotations

from django.db import models
from market_data.models import Security


class RawFinancialAuditModel(models.Model):
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    ts_code = models.CharField(max_length=16)
    ann_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    period = models.CharField(max_length=16, blank=True)
    row_signature = models.CharField(max_length=64)
    source_revision_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=32, default='tushare')
    imported_at = models.DateTimeField(auto_now_add=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True


class FinancialIncomeRecord(RawFinancialAuditModel):
    f_ann_date = models.DateField(null=True, blank=True)
    report_type = models.CharField(max_length=16, blank=True)
    comp_type = models.CharField(max_length=16, blank=True)
    revenue = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_revenue = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    oper_cost = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    operate_profit = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_profit = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    income_tax = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    n_income = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    n_income_attr_p = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    basic_eps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    diluted_eps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

    class Meta:
        db_table = 'financials_income_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_income_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialBalanceSheetRecord(RawFinancialAuditModel):
    f_ann_date = models.DateField(null=True, blank=True)
    report_type = models.CharField(max_length=16, blank=True)
    comp_type = models.CharField(max_length=16, blank=True)
    total_assets = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_liab = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_hldr_eqy_exc_min_int = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_hldr_eqy_inc_min_int = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    money_cap = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    accounts_receiv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    inventories = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    short_borrow = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    long_borrow = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_cur_assets = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_cur_liab = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'financials_balance_sheet_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_bs_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialCashFlowRecord(RawFinancialAuditModel):
    f_ann_date = models.DateField(null=True, blank=True)
    report_type = models.CharField(max_length=16, blank=True)
    comp_type = models.CharField(max_length=16, blank=True)
    n_cashflow_act = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    n_cashflow_inv_act = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    n_cash_flows_fnc_act = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    c_cash_equ_end_period = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    net_incr_cash_cash_equ = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'financials_cashflow_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_cf_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialIndicatorRecord(RawFinancialAuditModel):
    roe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    roe_waa = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    roe_dt = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    roa = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    grossprofit_margin = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    netprofit_margin = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    debt_to_assets = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    current_ratio = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    quick_ratio = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    assets_turn = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    bps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    eps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    dt_eps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    ocfps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    or_yoy = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    netprofit_yoy = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

    class Meta:
        db_table = 'financials_indicator_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_ind_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialForecastRecord(RawFinancialAuditModel):
    type = models.CharField(max_length=32, blank=True)
    p_change_min = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    p_change_max = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    net_profit_min = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    net_profit_max = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    last_parent_net = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    summary = models.TextField(blank=True)
    change_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'financials_forecast_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_fc_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialExpressRecord(RawFinancialAuditModel):
    revenue = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    operate_profit = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_profit = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    n_income = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_assets = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    total_hldr_eqy_exc_min_int = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    basic_eps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    roe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    growth_yoy = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

    class Meta:
        db_table = 'financials_express_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_exp_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialDividendRecord(RawFinancialAuditModel):
    stk_div = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    cash_div_tax = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    record_date = models.DateField(null=True, blank=True)
    ex_date = models.DateField(null=True, blank=True)
    pay_date = models.DateField(null=True, blank=True)
    div_proc = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = 'financials_dividend_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_div_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-ex_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialAuditRecord(RawFinancialAuditModel):
    audit_result = models.CharField(max_length=128, blank=True)
    audit_agency = models.CharField(max_length=256, blank=True)
    audit_sign = models.CharField(max_length=128, blank=True)
    audit_fees = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'financials_audit_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_audit_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialMainBusinessRecord(RawFinancialAuditModel):
    bz_item = models.CharField(max_length=256, blank=True)
    bz_sales = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    bz_profit = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    bz_cost = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    curr_type = models.CharField(max_length=16, blank=True)
    type = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = 'financials_main_business_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_mb_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-end_date']),
            models.Index(fields=['ann_date']),
        ]


class FinancialDisclosureRecord(RawFinancialAuditModel):
    pre_date = models.DateField(null=True, blank=True)
    actual_date = models.DateField(null=True, blank=True)
    modify_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'financials_disclosure_record'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'ann_date', 'end_date', 'period', 'row_signature'],
                name='financials_disc_natural_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['ann_date', 'security']),
            models.Index(fields=['security', '-end_date']),
        ]


class FinancialIngestionRun(models.Model):
    class Mode(models.TextChoices):
        BACKFILL = 'BACKFILL', 'Backfill'
        QUARTERLY = 'QUARTERLY', 'Quarterly'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        RUNNING = 'RUNNING', 'Running'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'

    mode = models.CharField(max_length=16, choices=Mode.choices)
    endpoints = models.CharField(max_length=256)
    scope = models.CharField(max_length=32)
    scope_key = models.CharField(max_length=64)
    period = models.CharField(max_length=16, blank=True)
    requested_start_date = models.DateField(null=True, blank=True)
    requested_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    source_row_count = models.PositiveBigIntegerField(default=0)
    accepted_row_count = models.PositiveBigIntegerField(default=0)
    upserted_row_count = models.PositiveBigIntegerField(default=0)
    rejected_row_count = models.PositiveBigIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    projection_rebuild_count = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)

    class Meta:
        db_table = 'financials_ingestion_run'
        indexes = [
            models.Index(fields=['status', '-id']),
        ]


class FinancialIngestionWatermark(models.Model):
    endpoint = models.CharField(max_length=32)
    scope_key = models.CharField(max_length=64)
    last_complete_source_date = models.DateField(null=True, blank=True)
    last_complete_period = models.CharField(max_length=16, blank=True)
    last_complete_run = models.ForeignKey(FinancialIngestionRun, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, choices=FinancialIngestionRun.Status.choices, default=FinancialIngestionRun.Status.PENDING)
    retry_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'financials_ingestion_watermark'
        constraints = [
            models.UniqueConstraint(
                fields=['endpoint', 'scope_key'],
                name='financials_watermark_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['endpoint', '-updated_at']),
        ]
