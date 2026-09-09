from django.db import models


class Security(models.Model):
    class AssetType(models.TextChoices):
        STOCK = 'STOCK', 'Stock'
        INDEX = 'INDEX', 'Index'

    ts_code = models.CharField(max_length=16, unique=True)
    asset_type = models.CharField(max_length=8, choices=AssetType.choices)
    symbol = models.CharField(max_length=16, blank=True)
    name = models.CharField(max_length=128, blank=True)
    full_name = models.CharField(max_length=256, blank=True)
    market = models.CharField(max_length=32, blank=True, db_index=True)
    exchange = models.CharField(max_length=32, blank=True, db_index=True)
    list_status = models.CharField(max_length=16, blank=True, db_index=True)
    list_date = models.DateField(null=True, blank=True)
    delist_date = models.DateField(null=True, blank=True)
    is_hs = models.CharField(max_length=8, blank=True)
    area = models.ForeignKey('Province', null=True, blank=True, on_delete=models.PROTECT)
    industry = models.ForeignKey('Industry', null=True, blank=True, on_delete=models.PROTECT)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['asset_type', 'list_status']),
            models.Index(fields=['area', 'industry', 'list_status']),
        ]


class Region(models.Model):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=32, unique=True)


class Province(models.Model):
    name = models.CharField(max_length=64, unique=True)
    source_name = models.CharField(max_length=64, blank=True)


class City(models.Model):
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name='cities')
    name = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['province', 'name'], name='market_data_city_province_uniq'),
        ]


class Industry(models.Model):
    name = models.CharField(max_length=128)
    source_system = models.CharField(max_length=32, default='tushare')
    source_version = models.CharField(max_length=32, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'source_system', 'source_version'],
                name='market_data_industry_source_uniq',
            ),
        ]


class ProvinceRegionMapping(models.Model):
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name='region_mappings')
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name='province_mappings')
    mapping_version = models.CharField(max_length=32)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['province', 'mapping_version', 'effective_from'],
                name='market_data_prov_region_uniq',
            ),
        ]


class CompanyProfile(models.Model):
    security = models.OneToOneField(Security, on_delete=models.CASCADE, related_name='company_profile')
    chairman = models.CharField(max_length=128, blank=True)
    manager = models.CharField(max_length=128, blank=True)
    secretary = models.CharField(max_length=128, blank=True)
    registered_capital = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    setup_date = models.DateField(null=True, blank=True)
    province = models.ForeignKey(Province, null=True, blank=True, on_delete=models.PROTECT)
    city = models.ForeignKey(City, null=True, blank=True, on_delete=models.PROTECT)
    province_name = models.CharField(max_length=64, blank=True)
    city_name = models.CharField(max_length=64, blank=True)
    exchange = models.CharField(max_length=32, blank=True)
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    office = models.CharField(max_length=256, blank=True)
    employees = models.PositiveIntegerField(null=True, blank=True)
    main_business = models.TextField(blank=True)
    business_scope = models.TextField(blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['province', 'city']),
        ]


class MarketBarDailyHistory(models.Model):
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='daily_bars')
    trade_date = models.DateField()
    open = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    high = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    low = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    close = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pre_close = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    change = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pct_change = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    volume = models.BigIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    adj_factor = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    open_qfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    high_qfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    low_qfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    close_qfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pre_close_qfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    change_qfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pct_change_qfq = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    open_hfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    high_hfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    low_hfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    close_hfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pre_close_hfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    change_hfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pct_change_hfq = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['security', 'trade_date'], name='market_data_daily_bar_uniq'),
            models.CheckConstraint(
                condition=models.Q(volume__isnull=True) | models.Q(volume__gte=0),
                name='market_data_daily_bar_volume_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(amount__isnull=True) | models.Q(amount__gte=0),
                name='market_data_daily_bar_amount_nonnegative',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-trade_date']),
            models.Index(fields=['trade_date']),
        ]


class MarketBarLatest(models.Model):
    class Frequency(models.TextChoices):
        DAILY = 'D', 'Daily'
        WEEKLY = 'W', 'Weekly'
        MONTHLY = 'M', 'Monthly'

    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='latest_bars')
    frequency = models.CharField(max_length=1, choices=Frequency.choices)
    trade_date = models.DateField()
    close = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    pct_change = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    close_qfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    close_hfq = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    volume = models.BigIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['security', 'frequency'], name='market_data_latest_bar_uniq'),
        ]
        indexes = [
            models.Index(fields=['frequency', '-trade_date']),
        ]


class DailySnapshotAuditModel(models.Model):
    trade_date = models.DateField()
    source_updated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class StockDailyFundamentalHistory(DailySnapshotAuditModel):
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='daily_fundamentals')
    close = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    turnover_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    turnover_rate_f = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    volume_ratio = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    pe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pe_ttm = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pb = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    ps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    ps_ttm = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    dv_ratio = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    dv_ttm = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    total_share = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)
    float_share = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)
    free_share = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)
    total_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    circ_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['security', 'trade_date'], name='market_data_stock_fund_uniq'),
        ]
        indexes = [
            models.Index(fields=['security', '-trade_date']),
            models.Index(fields=['trade_date', 'security']),
        ]


class StockDailyFundamentalLatest(DailySnapshotAuditModel):
    security = models.OneToOneField(Security, on_delete=models.CASCADE, related_name='latest_daily_fundamental')
    close = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    turnover_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    turnover_rate_f = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    volume_ratio = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    pe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pe_ttm = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pb = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    ps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    ps_ttm = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    dv_ratio = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    dv_ttm = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    total_share = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)
    float_share = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)
    free_share = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)
    total_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    circ_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['-trade_date']),
        ]


class StockCostDistributionHistory(DailySnapshotAuditModel):
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='daily_cost_distributions')
    his_low = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    his_high = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_5pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_15pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_50pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_85pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_95pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    weight_avg = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    winner_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['security', 'trade_date'], name='market_data_stock_cost_uniq'),
        ]
        indexes = [
            models.Index(fields=['security', '-trade_date']),
            models.Index(fields=['trade_date', 'security']),
        ]


class StockCostDistributionLatest(DailySnapshotAuditModel):
    security = models.OneToOneField(Security, on_delete=models.CASCADE, related_name='latest_cost_distribution')
    his_low = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    his_high = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_5pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_15pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_50pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_85pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_95pct = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    weight_avg = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    winner_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)


class IndexDailyFundamentalHistory(DailySnapshotAuditModel):
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='daily_index_fundamentals')
    pe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pe_ttm = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pb = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    turnover_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    turnover_rate_f = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    total_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    float_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['security', 'trade_date'], name='market_data_index_fund_uniq'),
        ]
        indexes = [
            models.Index(fields=['security', '-trade_date']),
            models.Index(fields=['trade_date', 'security']),
        ]


class IndexDailyFundamentalLatest(DailySnapshotAuditModel):
    security = models.OneToOneField(Security, on_delete=models.CASCADE, related_name='latest_index_fundamental')
    pe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pe_ttm = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    pb = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    turnover_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    turnover_rate_f = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    total_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    float_mv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['-trade_date']),
        ]


class IngestionRun(models.Model):
    class Mode(models.TextChoices):
        BACKFILL = 'BACKFILL', 'Backfill'
        DAILY = 'DAILY', 'Daily'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        RUNNING = 'RUNNING', 'Running'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'

    dataset = models.CharField(max_length=32)
    mode = models.CharField(max_length=16, choices=Mode.choices)
    frequency = models.CharField(max_length=1, blank=True)
    scope_key = models.CharField(max_length=64)
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
    error_summary = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['dataset', 'status', '-id']),
        ]


class IngestionWatermark(models.Model):
    dataset = models.CharField(max_length=32)
    scope_key = models.CharField(max_length=64)
    frequency = models.CharField(max_length=1, blank=True)
    last_complete_source_date = models.DateField(null=True, blank=True)
    last_complete_run = models.ForeignKey(IngestionRun, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, choices=IngestionRun.Status.choices, default=IngestionRun.Status.PENDING)
    overlap_days = models.PositiveSmallIntegerField(default=3)
    retry_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['dataset', 'scope_key', 'frequency'],
                name='market_data_watermark_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['status', '-updated_at']),
        ]


class SWIndustryMappingVersion(models.Model):
    market = models.CharField(max_length=8, default='CN')
    taxonomy = models.CharField(max_length=16, default='SW2021')
    mapping_version = models.CharField(max_length=64)
    source_hash = models.CharField(max_length=128)
    source_trade_date = models.DateField(null=True, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    validation_summary = models.JSONField(default=dict, blank=True)
    artifact = models.JSONField(default=dict)
    is_active = models.BooleanField(default=False)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'market_data_sw_industry_mapping_version'
        constraints = [
            models.UniqueConstraint(
                fields=['market', 'taxonomy', 'mapping_version'],
                name='market_data_sw_mapping_version_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['market', 'taxonomy', 'is_active'], name='md_sw_mapping_active_idx'),
            models.Index(fields=['source_hash'], name='md_sw_mapping_hash_idx'),
        ]


class IndustryRegimeRuleVersion(models.Model):
    mapping_version = models.ForeignKey(
        SWIndustryMappingVersion,
        on_delete=models.PROTECT,
        related_name='regime_rule_versions',
    )
    rules_version = models.CharField(max_length=64)
    rules_hash = models.CharField(max_length=128)
    fallback_regime = models.CharField(max_length=32, default='balanced')
    rules = models.JSONField(default=dict)
    validation_summary = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'market_data_industry_regime_rule_version'
        constraints = [
            models.UniqueConstraint(
                fields=['mapping_version', 'rules_version'],
                name='market_data_industry_rule_version_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['mapping_version', 'is_active'], name='md_industry_rule_active_idx'),
            models.Index(fields=['rules_hash'], name='md_industry_rule_hash_idx'),
        ]


class CITICIndustryDimension(models.Model):
    market = models.CharField(max_length=8, default='CN')
    level = models.CharField(max_length=2)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    parent_code = models.CharField(max_length=32, blank=True)
    mapping_version = models.CharField(max_length=64)
    source_trade_date = models.DateField(null=True, blank=True)
    source_hash = models.CharField(max_length=128)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'market_data_citic_industry_dimension'
        constraints = [
            models.UniqueConstraint(
                fields=['market', 'level', 'code', 'mapping_version'],
                name='md_citic_dimension_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['market', 'level', 'code'], name='md_citic_dim_lookup_idx'),
            models.Index(fields=['market', 'mapping_version', 'is_active'], name='md_citic_dim_active_idx'),
        ]


class CITICSecurityIndustryMembership(models.Model):
    security = models.ForeignKey(Security, on_delete=models.PROTECT, related_name='citic_memberships')
    industry = models.ForeignKey(CITICIndustryDimension, on_delete=models.PROTECT, related_name='security_memberships')
    level = models.CharField(max_length=2)
    mapping_version = models.CharField(max_length=64)
    in_date = models.DateField(null=True, blank=True)
    out_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)
    source_trade_date = models.DateField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'market_data_citic_security_membership'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'industry', 'mapping_version', 'in_date'],
                name='md_citic_member_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', 'level', 'mapping_version', 'is_current'], name='md_citic_member_lookup_idx'),
            models.Index(fields=['mapping_version', 'level'], name='md_citic_member_version_idx'),
        ]


class CITICIndustryMappingRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'RUNNING', 'Running'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'

    market = models.CharField(max_length=8, default='CN')
    mapping_version = models.CharField(max_length=64)
    source_trade_date = models.DateField(null=True, blank=True)
    source_hash = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    source_count = models.PositiveIntegerField(default=0)
    dimension_count = models.PositiveIntegerField(default=0)
    membership_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'market_data_citic_mapping_run'
        indexes = [
            models.Index(fields=['market', '-created_at'], name='md_citic_run_created_idx'),
            models.Index(fields=['status', '-created_at'], name='md_citic_run_status_idx'),
        ]


class BusinessIndustryMatchSnapshot(models.Model):
    security = models.ForeignKey(Security, on_delete=models.PROTECT, related_name='business_industry_match_snapshots')
    asof_date = models.DateField()
    level = models.CharField(max_length=2, default='L2')
    requested_top_n = models.PositiveSmallIntegerField(default=3)
    returned_count = models.PositiveSmallIntegerField(default=0)
    profile_hash = models.CharField(max_length=128, blank=True)
    profile_source = models.CharField(max_length=64, blank=True)
    profile_updated_at = models.DateTimeField(null=True, blank=True)
    mapping_version = models.CharField(max_length=64, blank=True)
    rules_version = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, default='VALID')
    degraded_reason = models.CharField(max_length=128, blank=True)
    matches = models.JSONField(default=list, blank=True)
    fallback = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'market_data_business_industry_match_snapshot'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'asof_date', 'level', 'requested_top_n', 'profile_hash', 'mapping_version', 'rules_version'],
                name='md_business_match_snapshot_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-asof_date'], name='md_business_match_sec_dt'),
            models.Index(fields=['status', '-asof_date'], name='md_business_match_status_dt'),
        ]


class MarketRegimeSnapshot(models.Model):
    benchmark_security = models.ForeignKey(
        Security, on_delete=models.PROTECT, related_name='market_regime_snapshots'
    )
    asof_trade_date = models.DateField()
    source_trade_date = models.DateField()
    regime = models.CharField(max_length=16)
    source = models.CharField(max_length=64)
    classifier_version = models.CharField(max_length=32)
    row_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=24, default='VALID')
    metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'market_data_market_regime_snapshot'
        constraints = [
            models.UniqueConstraint(
                fields=['benchmark_security', 'asof_trade_date', 'classifier_version'],
                name='market_data_market_regime_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['-asof_trade_date', 'regime'], name='market_data_market_regime_dt'),
        ]


class SecurityRegimeSnapshot(models.Model):
    security = models.ForeignKey(Security, on_delete=models.PROTECT, related_name='regime_snapshots')
    asof_trade_date = models.DateField()
    source_trade_date = models.DateField()
    regime = models.CharField(max_length=16)
    source = models.CharField(max_length=64, default='local_market_data')
    classifier_version = models.CharField(max_length=32)
    row_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=24, default='VALID')
    metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'market_data_security_regime_snapshot'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'asof_trade_date', 'classifier_version'],
                name='market_data_security_regime_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', '-asof_trade_date'], name='market_data_security_regime_dt'),
            models.Index(fields=['regime', '-asof_trade_date'], name='md_sec_regime_idx'),
        ]


class MarketRegimeState(models.Model):
    scope_key = models.CharField(max_length=32, unique=True)
    current_regime = models.CharField(max_length=16, blank=True)
    previous_regime = models.CharField(max_length=16, blank=True)
    last_valid_trade_date = models.DateField(null=True, blank=True)
    classifier_version = models.CharField(max_length=32)
    source_version = models.CharField(max_length=64, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'market_data_market_regime_state'


class SecurityRegimeState(models.Model):
    security = models.ForeignKey(Security, on_delete=models.PROTECT, related_name='regime_state_rows')
    classifier_version = models.CharField(max_length=32)
    current_regime = models.CharField(max_length=16, blank=True)
    previous_regime = models.CharField(max_length=16, blank=True)
    pending_regime = models.CharField(max_length=16, blank=True)
    pending_days = models.PositiveSmallIntegerField(default=0)
    last_valid_trade_date = models.DateField(null=True, blank=True)
    source_version = models.CharField(max_length=64, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'market_data_security_regime_state'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'classifier_version'],
                name='market_data_security_regime_state_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['current_regime', '-updated_at'], name='market_data_security_state_idx'),
        ]


class RegimeEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CONSUMED = 'CONSUMED', 'Consumed'

    event_type = models.CharField(max_length=32)
    event_key = models.CharField(max_length=128)
    security = models.ForeignKey(Security, null=True, blank=True, on_delete=models.PROTECT, related_name='regime_events')
    source_trade_date = models.DateField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'market_data_regime_event'
        constraints = [
            models.UniqueConstraint(fields=['event_type', 'event_key'], name='market_data_regime_event_uniq'),
        ]
        indexes = [
            models.Index(fields=['status', '-created_at'], name='md_regime_evt_status'),
            models.Index(fields=['event_type', '-source_trade_date'], name='market_data_regime_event_type'),
        ]
