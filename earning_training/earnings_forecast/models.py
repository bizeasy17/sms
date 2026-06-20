from django.db import models


class FinancialApiRecordBase(models.Model):
    """Base model for raw financial records, one concrete table per endpoint."""

    ts_code = models.CharField(max_length=16, db_index=True)
    ann_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    end_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    period = models.CharField(max_length=16, blank=True, default="", db_index=True)
    row_signature = models.CharField(max_length=64, blank=True, default="")
    source_file = models.CharField(max_length=512, blank=True, default="")
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class FinancialIncomeRecord(FinancialApiRecordBase):
    f_ann_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    report_type = models.CharField(max_length=32, blank=True, default="")
    comp_type = models.CharField(max_length=32, blank=True, default="")

    revenue = models.FloatField(null=True, blank=True)
    total_revenue = models.FloatField(null=True, blank=True)
    operate_profit = models.FloatField(null=True, blank=True)
    total_profit = models.FloatField(null=True, blank=True)
    n_income = models.FloatField(null=True, blank=True)
    n_income_attr_p = models.FloatField(null=True, blank=True)
    basic_eps = models.FloatField(null=True, blank=True)
    diluted_eps = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_income"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_income",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_income_ce"),
        ]


class FinancialBalanceSheetVipRecord(FinancialApiRecordBase):
    f_ann_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    report_type = models.CharField(max_length=32, blank=True, default="")
    comp_type = models.CharField(max_length=32, blank=True, default="")

    total_assets = models.FloatField(null=True, blank=True)
    total_liab = models.FloatField(null=True, blank=True)
    total_hldr_eqy_exc_min_int = models.FloatField(null=True, blank=True)
    money_cap = models.FloatField(null=True, blank=True)
    accounts_receiv = models.FloatField(null=True, blank=True)
    inventories = models.FloatField(null=True, blank=True)
    st_borr = models.FloatField(null=True, blank=True)
    lt_borr = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_balancesheet_vip"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_balvip",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_balvip_ce"),
        ]


class FinancialCashflowVipRecord(FinancialApiRecordBase):
    f_ann_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    report_type = models.CharField(max_length=32, blank=True, default="")
    comp_type = models.CharField(max_length=32, blank=True, default="")

    n_cashflow_act = models.FloatField(null=True, blank=True)
    n_cashflow_inv_act = models.FloatField(null=True, blank=True)
    n_cash_flows_fnc_act = models.FloatField(null=True, blank=True)
    n_incr_cash_cash_equ = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_cashflow_vip"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_cashvip",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_cashvip_ce"),
        ]


class FinancialForecastVipRecord(FinancialApiRecordBase):
    type = models.CharField(max_length=32, blank=True, default="")
    p_change_min = models.FloatField(null=True, blank=True)
    p_change_max = models.FloatField(null=True, blank=True)
    net_profit_min = models.FloatField(null=True, blank=True)
    net_profit_max = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_forecast_vip"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_forevip",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_forevip_ce"),
        ]


class FinancialExpressVipRecord(FinancialApiRecordBase):
    revenue = models.FloatField(null=True, blank=True)
    n_income = models.FloatField(null=True, blank=True)
    total_assets = models.FloatField(null=True, blank=True)
    diluted_eps = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_express_vip"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_exprvip",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_exprvip_ce"),
        ]


class FinancialDividendRecord(FinancialApiRecordBase):
    stk_div = models.FloatField(null=True, blank=True)
    cash_div = models.FloatField(null=True, blank=True)
    record_date = models.CharField(max_length=16, blank=True, default="")
    ex_date = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        db_table = "earnings_fin_dividend"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_div",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_div_ce"),
        ]


class FinancialFinaIndicatorVipRecord(FinancialApiRecordBase):
    f_ann_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    report_type = models.CharField(max_length=32, blank=True, default="")
    comp_type = models.CharField(max_length=32, blank=True, default="")

    roe = models.FloatField(null=True, blank=True)
    roe_dt = models.FloatField(null=True, blank=True)
    roa = models.FloatField(null=True, blank=True)
    q_dt_roe = models.FloatField(null=True, blank=True)
    tr_yoy = models.FloatField(null=True, blank=True)
    netprofit_yoy = models.FloatField(null=True, blank=True)
    grossprofit_margin = models.FloatField(null=True, blank=True)
    netprofit_margin = models.FloatField(null=True, blank=True)
    debt_to_assets = models.FloatField(null=True, blank=True)
    current_ratio = models.FloatField(null=True, blank=True)
    quick_ratio = models.FloatField(null=True, blank=True)
    cash_ratio = models.FloatField(null=True, blank=True)
    assets_turn = models.FloatField(null=True, blank=True)
    ocf_to_or = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_fina_indicator_vip"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_findvip",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_findvip_ce"),
        ]


class FinancialFinaAuditRecord(FinancialApiRecordBase):
    audit_result = models.CharField(max_length=128, blank=True, default="")
    audit_fees = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_fina_audit"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_finaudit",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_finaudit_ce"),
        ]


class FinancialFinaMainbzVipRecord(FinancialApiRecordBase):
    bz_item = models.CharField(max_length=128, blank=True, default="")
    bz_sales = models.FloatField(null=True, blank=True)
    bz_profit = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "earnings_fin_fina_mainbz_vip"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_mainbzv",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_mainbzv_ce"),
        ]


class FinancialDisclosureDateRecord(FinancialApiRecordBase):
    pre_date = models.CharField(max_length=16, blank=True, default="")
    actual_date = models.CharField(max_length=16, blank=True, default="")
    modify_date = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        db_table = "earnings_fin_disclosure_date"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                name="uq_earn_fin_discdt",
            )
        ]
        indexes = [
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_discdt_ce"),
        ]


FINANCIAL_ENDPOINT_MODEL_MAP = {
    "income": FinancialIncomeRecord,
    "balancesheet_vip": FinancialBalanceSheetVipRecord,
    "cashflow_vip": FinancialCashflowVipRecord,
    "forecast_vip": FinancialForecastVipRecord,
    "express_vip": FinancialExpressVipRecord,
    "dividend": FinancialDividendRecord,
    "fina_indicator_vip": FinancialFinaIndicatorVipRecord,
    "fina_audit": FinancialFinaAuditRecord,
    "fina_mainbz_vip": FinancialFinaMainbzVipRecord,
    "disclosure_date": FinancialDisclosureDateRecord,
}


def get_financial_endpoint_model(endpoint: str):
    return FINANCIAL_ENDPOINT_MODEL_MAP.get(str(endpoint or "").strip())


class FinancialCacheImportRun(models.Model):
    """Track import status for ETL financial cache ingestion."""

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cache_dir = models.CharField(max_length=512)
    endpoints = models.CharField(max_length=512)
    files_scanned = models.IntegerField(default=0)
    rows_parsed = models.IntegerField(default=0)
    rows_upserted = models.IntegerField(default=0)
    status = models.CharField(max_length=32, default="running")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "earnings_financial_cache_import_run"
        ordering = ["-started_at"]


class FinancialFeatureSnapshot(models.Model):
    """Flattened latest financial features per symbol for model training."""

    ts_code = models.CharField(max_length=16, unique=True, db_index=True)
    end_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    ann_date = models.CharField(max_length=16, blank=True, default="", db_index=True)

    revenue = models.FloatField(null=True, blank=True)
    total_revenue = models.FloatField(null=True, blank=True)
    operate_profit = models.FloatField(null=True, blank=True)
    total_profit = models.FloatField(null=True, blank=True)
    n_income = models.FloatField(null=True, blank=True)
    n_income_attr_p = models.FloatField(null=True, blank=True)
    basic_eps = models.FloatField(null=True, blank=True)
    diluted_eps = models.FloatField(null=True, blank=True)

    roe = models.FloatField(null=True, blank=True)
    roe_dt = models.FloatField(null=True, blank=True)
    roa = models.FloatField(null=True, blank=True)
    q_dt_roe = models.FloatField(null=True, blank=True)
    tr_yoy = models.FloatField(null=True, blank=True)
    netprofit_yoy = models.FloatField(null=True, blank=True)
    grossprofit_margin = models.FloatField(null=True, blank=True)
    netprofit_margin = models.FloatField(null=True, blank=True)
    debt_to_assets = models.FloatField(null=True, blank=True)
    current_ratio = models.FloatField(null=True, blank=True)
    quick_ratio = models.FloatField(null=True, blank=True)
    cash_ratio = models.FloatField(null=True, blank=True)
    assets_turn = models.FloatField(null=True, blank=True)
    ocf_to_or = models.FloatField(null=True, blank=True)

    total_assets = models.FloatField(null=True, blank=True)
    total_liab = models.FloatField(null=True, blank=True)
    total_hldr_eqy_exc_min_int = models.FloatField(null=True, blank=True)
    money_cap = models.FloatField(null=True, blank=True)
    accounts_receiv = models.FloatField(null=True, blank=True)
    inventories = models.FloatField(null=True, blank=True)
    st_borr = models.FloatField(null=True, blank=True)
    lt_borr = models.FloatField(null=True, blank=True)

    n_cashflow_act = models.FloatField(null=True, blank=True)
    n_cashflow_inv_act = models.FloatField(null=True, blank=True)
    n_cash_flows_fnc_act = models.FloatField(null=True, blank=True)
    n_incr_cash_cash_equ = models.FloatField(null=True, blank=True)

    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "earnings_financial_feature_snapshot"
        indexes = [
            models.Index(fields=["end_date"], name="idx_earn_fin_feat_end"),
            models.Index(fields=["ann_date"], name="idx_earn_fin_feat_ann"),
        ]


class FinancialFeaturePanel(models.Model):
    """Financial feature panel with multiple rows per symbol by report period."""

    ts_code = models.CharField(max_length=16, db_index=True)
    fiscal_year = models.IntegerField(db_index=True)
    report_type = models.CharField(max_length=16, db_index=True)
    end_date = models.CharField(max_length=16, blank=True, default="", db_index=True)
    ann_date = models.CharField(max_length=16, blank=True, default="", db_index=True)

    revenue = models.FloatField(null=True, blank=True)
    total_revenue = models.FloatField(null=True, blank=True)
    operate_profit = models.FloatField(null=True, blank=True)
    total_profit = models.FloatField(null=True, blank=True)
    n_income = models.FloatField(null=True, blank=True)
    n_income_attr_p = models.FloatField(null=True, blank=True)
    basic_eps = models.FloatField(null=True, blank=True)
    diluted_eps = models.FloatField(null=True, blank=True)

    roe = models.FloatField(null=True, blank=True)
    roe_dt = models.FloatField(null=True, blank=True)
    roa = models.FloatField(null=True, blank=True)
    q_dt_roe = models.FloatField(null=True, blank=True)
    tr_yoy = models.FloatField(null=True, blank=True)
    netprofit_yoy = models.FloatField(null=True, blank=True)
    grossprofit_margin = models.FloatField(null=True, blank=True)
    netprofit_margin = models.FloatField(null=True, blank=True)
    debt_to_assets = models.FloatField(null=True, blank=True)
    current_ratio = models.FloatField(null=True, blank=True)
    quick_ratio = models.FloatField(null=True, blank=True)
    cash_ratio = models.FloatField(null=True, blank=True)
    assets_turn = models.FloatField(null=True, blank=True)
    ocf_to_or = models.FloatField(null=True, blank=True)

    total_assets = models.FloatField(null=True, blank=True)
    total_liab = models.FloatField(null=True, blank=True)
    total_hldr_eqy_exc_min_int = models.FloatField(null=True, blank=True)
    money_cap = models.FloatField(null=True, blank=True)
    accounts_receiv = models.FloatField(null=True, blank=True)
    inventories = models.FloatField(null=True, blank=True)
    st_borr = models.FloatField(null=True, blank=True)
    lt_borr = models.FloatField(null=True, blank=True)

    n_cashflow_act = models.FloatField(null=True, blank=True)
    n_cashflow_inv_act = models.FloatField(null=True, blank=True)
    n_cash_flows_fnc_act = models.FloatField(null=True, blank=True)
    n_incr_cash_cash_equ = models.FloatField(null=True, blank=True)

    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "earnings_financial_feature_panel"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "end_date", "report_type"],
                name="uq_earn_fin_feat_panel",
            )
        ]
        indexes = [
            models.Index(fields=["fiscal_year", "report_type"], name="idx_earn_fin_panel_yr_rt"),
            models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_panel_code_end"),
            models.Index(fields=["ann_date"], name="idx_earn_fin_panel_ann"),
        ]


class LocalTradingHistory(models.Model):
    """Local mirror for market trading history used by prepare stage."""

    ts_code = models.CharField(max_length=16, db_index=True)
    trade_date = models.DateField(db_index=True)
    freq = models.CharField(max_length=8, default="D", db_index=True)
    close = models.FloatField(null=True, blank=True)
    pct_change = models.FloatField(null=True, blank=True)
    vol = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "earnings_mkt_trading_history"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "trade_date", "freq"],
                name="uq_earn_mkt_trade_code_date_freq",
            )
        ]
        indexes = [
            models.Index(fields=["trade_date", "freq"], name="idx_earn_mkt_trade_date_freq"),
            models.Index(fields=["ts_code", "trade_date"], name="idx_earn_mkt_trade_code_date"),
        ]


class LocalFundamentalHistory(models.Model):
    """Local mirror for market fundamental history used by prepare stage."""

    ts_code = models.CharField(max_length=16, db_index=True)
    trade_date = models.DateField(db_index=True)
    freq = models.CharField(max_length=8, default="D", db_index=True)
    pe = models.FloatField(null=True, blank=True)
    pb = models.FloatField(null=True, blank=True)
    ps = models.FloatField(null=True, blank=True)
    total_mv = models.FloatField(null=True, blank=True)
    circ_mv = models.FloatField(null=True, blank=True)
    turnover_rate = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "earnings_mkt_fundamental_history"
        constraints = [
            models.UniqueConstraint(
                fields=["ts_code", "trade_date", "freq"],
                name="uq_earn_mkt_funda_code_date_freq",
            )
        ]
        indexes = [
            models.Index(fields=["trade_date", "freq"], name="idx_earn_mkt_funda_date_freq"),
            models.Index(fields=["ts_code", "trade_date"], name="idx_earn_mkt_funda_code_date"),
        ]


class LocalIndustry(models.Model):
    """Local mirror for industry dimension."""

    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "earnings_dim_industry"


class LocalCorporation(models.Model):
    """Local mirror for stock -> industry mapping."""

    ts_code = models.CharField(max_length=16, unique=True, db_index=True)
    industry_id = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "earnings_dim_corporation"


class EarningsSignalSnapshot(models.Model):
    """Persisted forecast signal snapshot for API read path."""

    ts_code = models.CharField(max_length=16, db_index=True)
    report_type = models.CharField(max_length=16, db_index=True, blank=True, default="UNKNOWN")
    signal_score = models.FloatField(null=True, blank=True)
    target_return_pct = models.FloatField(null=True, blank=True)
    target_price = models.FloatField(null=True, blank=True)
    target_market_cap = models.FloatField(null=True, blank=True)
    action = models.CharField(max_length=16, default="HOLD")
    risk_level = models.CharField(max_length=16, default="MEDIUM")
    model_version = models.CharField(max_length=128, blank=True, default="")
    asof_date = models.DateField(null=True, blank=True, db_index=True)
    explain = models.JSONField(blank=True, default=dict)
    raw_result = models.JSONField(blank=True, default=dict)
    feature_data_source = models.CharField(max_length=32, blank=True, default="")
    batch_key = models.CharField(max_length=64, blank=True, default="manual", db_index=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "earnings_signal_snapshot"
        constraints = [
            models.UniqueConstraint(fields=["ts_code", "report_type"], name="uq_earn_sig_code_rt"),
        ]
        indexes = [
            models.Index(fields=["batch_key", "updated_at"], name="idx_earn_sig_batch_updated"),
            models.Index(fields=["ts_code", "report_type", "updated_at"], name="idx_earn_sig_code_rt_upd"),
        ]


class EarningsSignalSnapshotHistory(models.Model):
    """Append-only snapshot history for comparing multiple model versions."""

    ts_code = models.CharField(max_length=16, db_index=True)
    report_type = models.CharField(max_length=16, db_index=True, blank=True, default="UNKNOWN")
    financial_report_type = models.CharField(max_length=16, db_index=True, blank=True, default="UNKNOWN")
    model_version = models.CharField(max_length=128, blank=True, default="", db_index=True)
    signal_score = models.FloatField(null=True, blank=True)
    target_return_pct = models.FloatField(null=True, blank=True)
    target_price = models.FloatField(null=True, blank=True)
    target_market_cap = models.FloatField(null=True, blank=True)
    action = models.CharField(max_length=16, default="HOLD")
    risk_level = models.CharField(max_length=16, default="MEDIUM")
    asof_date = models.DateField(null=True, blank=True, db_index=True)
    financial_ann_date = models.CharField(max_length=32, blank=True, default="")
    financial_end_date = models.CharField(max_length=32, db_index=True, blank=True, default="")
    financial_fiscal_year = models.IntegerField(null=True, blank=True, db_index=True)
    explain = models.JSONField(blank=True, default=dict)
    raw_result = models.JSONField(blank=True, default=dict)
    feature_data_source = models.CharField(max_length=32, blank=True, default="")
    batch_key = models.CharField(max_length=64, blank=True, default="manual", db_index=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "earnings_signal_snapshot_history"
        indexes = [
            models.Index(fields=["ts_code", "report_type", "model_version", "asof_date"], name="idx_esh_code_rt_ver_dt"),
            models.Index(fields=["batch_key", "created_at"], name="idx_esh_batch_ct"),
            models.Index(fields=["ts_code", "financial_fiscal_year", "financial_report_type"], name="idx_esh_code_fy_rt"),
            models.Index(fields=["financial_fiscal_year", "financial_report_type", "created_at"], name="idx_esh_fy_rt_ct"),
        ]
