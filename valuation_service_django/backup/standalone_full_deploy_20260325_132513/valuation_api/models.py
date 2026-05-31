from django.db import models


class Industry(models.Model):
    name = models.CharField(max_length=50, unique=True, db_index=True)
    name_pinyin = models.CharField(max_length=50, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_industry"


class Area(models.Model):
    name = models.CharField(max_length=50, db_index=True)
    country = models.CharField(max_length=50, default="中国", blank=True)
    name_pinyin = models.CharField(max_length=50, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_area"
        unique_together = ("name", "country")


class City(models.Model):
    name = models.CharField(max_length=50, db_index=True)
    area = models.ForeignKey(Area, related_name="cities", on_delete=models.SET_NULL, blank=True, null=True)
    name_pinyin = models.CharField(max_length=50, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_city"
        unique_together = ("name", "area")


class Corporation(models.Model):
    ts_code = models.CharField(max_length=12, unique=True, db_index=True)
    name = models.CharField(max_length=50, db_index=True)
    area = models.ForeignKey(Area, related_name="corporations", on_delete=models.SET_NULL, blank=True, null=True)
    industry = models.ForeignKey(Industry, related_name="corporations", on_delete=models.SET_NULL, blank=True, null=True)
    fullname = models.CharField(max_length=100, blank=True, null=True)
    enname = models.CharField(max_length=100, blank=True, null=True)
    cnspell = models.CharField(max_length=50, blank=True, null=True)
    market = models.CharField(max_length=50, blank=True, null=True)
    exchange = models.CharField(max_length=10, blank=True, null=True)
    curr_type = models.CharField(max_length=10, blank=True, null=True)
    list_status = models.CharField(max_length=1, blank=True, null=True)
    list_date = models.DateField(blank=True, null=True)
    delist_date = models.DateField(blank=True, null=True)
    act_name = models.CharField(max_length=50, blank=True, null=True)
    act_ent_type = models.CharField(max_length=50, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_corporation"


class CorporationBasic(models.Model):
    corporation = models.ForeignKey(
        Corporation,
        related_name="basic_info",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    ts_code = models.CharField(max_length=12, unique=True, db_index=True)
    exchange = models.CharField(max_length=10, blank=True, null=True)
    chairman = models.CharField(max_length=50, blank=True, null=True)
    manager = models.CharField(max_length=50, blank=True, null=True)
    secretary = models.CharField(max_length=50, blank=True, null=True)
    reg_capital = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    setup_date = models.DateField(blank=True, null=True)
    area = models.ForeignKey(Area, related_name="corporation_basic_area", on_delete=models.SET_NULL, blank=True, null=True)
    city = models.ForeignKey(City, related_name="corporation_basic_city", on_delete=models.SET_NULL, blank=True, null=True)
    introduction = models.TextField(blank=True, null=True)
    website = models.CharField(max_length=128, blank=True, null=True)
    email = models.EmailField(max_length=128, blank=True, null=True)
    office = models.CharField(max_length=200, blank=True, null=True)
    employees = models.PositiveIntegerField(blank=True, null=True)
    main_business = models.TextField(blank=True, null=True)
    business_scope = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_corporation_basic"


class CompanyProfile(models.Model):
    ts_code = models.CharField(max_length=12, primary_key=True)
    name = models.CharField(max_length=128, blank=True, default="")
    industry = models.CharField(max_length=128, blank=True, default="")
    market = models.CharField(max_length=8, default="CN")
    main_business = models.TextField(blank=True, default="")
    business_scope = models.TextField(blank=True, default="")
    introduction = models.TextField(blank=True, default="")
    citic_l1_name = models.CharField(max_length=128, blank=True, default="")
    citic_l2_name = models.CharField(max_length=128, blank=True, default="")
    citic_l3_name = models.CharField(max_length=128, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_company_profile"


class StockTradingHistory(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    corporation = models.ForeignKey(
        Corporation,
        related_name="trading_history",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    ts_code = models.CharField(max_length=10)
    trade_date = models.DateField()
    freq = models.CharField(max_length=5, default="D")
    open = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pre_close = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    change = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pct_change = models.DecimalField(max_digits=8, decimal_places=4, blank=True, null=True)
    vol = models.BigIntegerField(blank=True, null=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    adj_factor = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    open_hfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    open_qfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_hfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_hfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_qfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_hfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_qfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pre_close_hfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pre_close_qfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    change_hfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    change_qfq = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pct_change_hfq = models.DecimalField(max_digits=8, decimal_places=4, blank=True, null=True)
    pct_change_qfq = models.DecimalField(max_digits=8, decimal_places=4, blank=True, null=True)
    macd_dif = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    macd_dea = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    macd = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_k = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_d = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_j = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_6 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_12 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_24 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    boll_upper = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    boll_mid = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    boll_lower = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    cci = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_trading_history"
        unique_together = ("ts_code", "trade_date", "freq")
        indexes = [
            models.Index(fields=["ts_code", "freq", "trade_date"]),
        ]


class StockFundamentalSnapshot(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    corporation = models.ForeignKey(
        Corporation,
        related_name="fundamental_history",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    ts_code = models.CharField(max_length=10)
    trade_date = models.DateField(blank=True, null=True)
    freq = models.CharField(max_length=10, default="D")
    close = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe = models.DecimalField(max_digits=16, decimal_places=4, blank=True, null=True)
    pe_ttm = models.DecimalField(max_digits=16, decimal_places=4, blank=True, null=True)
    pb = models.DecimalField(max_digits=16, decimal_places=4, blank=True, null=True)
    ps = models.DecimalField(max_digits=16, decimal_places=4, blank=True, null=True)
    ps_ttm = models.DecimalField(max_digits=16, decimal_places=4, blank=True, null=True)
    dv_ratio = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    dv_ttm = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    total_share = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    float_share = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    free_share = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    total_mv = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    circ_mv = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_fundamental_snapshot"
        unique_together = ("ts_code", "trade_date", "freq")
        indexes = [
            models.Index(fields=["ts_code", "trade_date", "freq"]),
        ]


class StockExpressVip(models.Model):
    ts_code = models.CharField(max_length=12, db_index=True)
    ann_date = models.DateField(blank=True, null=True, db_index=True)
    end_date = models.DateField(blank=True, null=True, db_index=True)
    revenue = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    total_revenue = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    oper_rev = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    n_income = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    n_income_attr_p = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    profit_dedt = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    yoy_net_profit = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    yoy_dedu_np = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    yoy_sales = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    yoy_np = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    netprofit_yoy = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    tr_yoy = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    or_yoy = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_express_vip"
        unique_together = ("ts_code", "ann_date", "end_date")
        indexes = [
            models.Index(fields=["ts_code", "end_date", "ann_date"]),
        ]


class ValuationSnapshot(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    ts_code = models.CharField(max_length=12, db_index=True)
    trade_date = models.DateField(db_index=True)
    market = models.CharField(max_length=10, default="CN", db_index=True)
    valuation_method = models.CharField(max_length=32, db_index=True)
    valuation_variant = models.CharField(max_length=128, default="default", db_index=True)
    valuation_price = models.FloatField(null=True)
    valuation_market_cap = models.FloatField(null=True)
    source = models.CharField(max_length=32, default="live_compute")
    industry_level = models.CharField(max_length=16, blank=True, null=True, db_index=True)
    industry_code = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    industry_name = models.CharField(max_length=128, blank=True, null=True)
    compare_group = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    match_score = models.FloatField(blank=True, null=True)
    profit_data_source = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    profit_report_end_date = models.DateField(blank=True, null=True, db_index=True)
    profit_report_type = models.CharField(max_length=16, blank=True, null=True, db_index=True)
    express_end_date = models.DateField(blank=True, null=True, db_index=True)
    express_ann_date = models.DateField(blank=True, null=True, db_index=True)
    express_apply_reason = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    express_block_reason = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    strict_express_match = models.BooleanField(blank=True, null=True)
    express_max_age_days = models.IntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_snapshot"
        unique_together = ("ts_code", "trade_date", "market", "valuation_method", "valuation_variant")
        indexes = [
            models.Index(fields=["ts_code", "trade_date", "market", "valuation_method"]),
        ]


class ValuationSnapshotLatest(models.Model):
    ts_code = models.CharField(max_length=12, db_index=True)
    latest_trade_date = models.DateField(db_index=True)
    market = models.CharField(max_length=10, default="CN", db_index=True)
    valuation_method = models.CharField(max_length=32, db_index=True)
    valuation_variant = models.CharField(max_length=128, default="default", db_index=True)
    valuation_price = models.FloatField(null=True)
    valuation_market_cap = models.FloatField(null=True)
    source = models.CharField(max_length=32, default="legacy_snapshot")
    industry_level = models.CharField(max_length=16, blank=True, null=True, db_index=True)
    industry_code = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    industry_name = models.CharField(max_length=128, blank=True, null=True)
    compare_group = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    match_score = models.FloatField(blank=True, null=True)
    profit_data_source = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    profit_report_end_date = models.DateField(blank=True, null=True, db_index=True)
    profit_report_type = models.CharField(max_length=16, blank=True, null=True, db_index=True)
    express_end_date = models.DateField(blank=True, null=True, db_index=True)
    express_ann_date = models.DateField(blank=True, null=True, db_index=True)
    express_apply_reason = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    express_block_reason = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    strict_express_match = models.BooleanField(blank=True, null=True)
    express_max_age_days = models.IntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_snapshot_latest"
        unique_together = ("ts_code", "market", "valuation_method", "valuation_variant")
        indexes = [
            models.Index(fields=["ts_code", "market", "latest_trade_date"]),
        ]


class ValuationAssumption(models.Model):
    industry = models.CharField(max_length=128, unique=True)
    pe_target = models.FloatField(default=15.0)
    pb_target = models.FloatField(default=2.0)
    ps_target = models.FloatField(default=2.0)
    peg_target = models.FloatField(default=1.0)
    discount_rate = models.FloatField(default=0.10)
    terminal_growth_rate = models.FloatField(default=0.03)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_assumption"
