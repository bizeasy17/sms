from django.db import models


class SentimentSnapshotBase(models.Model):
    trade_date = models.DateField()
    score = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    level = models.CharField(max_length=24, blank=True)
    status = models.CharField(max_length=24)
    raw_score = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    standardized_score = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    momentum = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    activity = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    fear = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    universe_count = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    coverage = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    engine_version = models.CharField(max_length=32)
    source_trade_date = models.DateField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    calculated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MarketSentimentSnapshot(SentimentSnapshotBase):
    market = models.CharField(max_length=8, default='CN')
    scope_type = models.CharField(max_length=16, default='MARKET')
    scope_code = models.CharField(max_length=32, default='ALL_A')

    class Meta:
        db_table = 'market_sentiment_snapshot'
        constraints = [
            models.UniqueConstraint(
                fields=['market', 'scope_type', 'scope_code', 'trade_date', 'engine_version'],
                name='ms_market_snapshot_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['market', 'scope_type', 'scope_code', 'engine_version', '-trade_date'], name='ms_market_scope_dt'),
        ]


class StockSentimentSnapshot(SentimentSnapshotBase):
    security = models.ForeignKey('market_data.Security', on_delete=models.CASCADE, related_name='sentiment_snapshots')
    peer_type = models.CharField(max_length=32, blank=True)
    peer_code = models.CharField(max_length=128, blank=True)
    peer_name = models.CharField(max_length=128, blank=True)
    peer_count = models.PositiveIntegerField(default=0)
    normalization_mode = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = 'stock_sentiment_snapshot'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'trade_date', 'engine_version'],
                name='ms_stock_snapshot_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['security', 'engine_version', '-trade_date'], name='ms_stock_sec_dt'),
            models.Index(fields=['trade_date', 'engine_version', '-score'], name='ms_stock_score_dt'),
        ]


class MarketSentimentFactor(models.Model):
    snapshot = models.ForeignKey(MarketSentimentSnapshot, on_delete=models.CASCADE, related_name='factors')
    factor_code = models.CharField(max_length=32)
    raw_value = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    normalized_value = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    effective_weight = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    contribution = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    available = models.BooleanField(default=True)
    reason = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'market_sentiment_factor'
        constraints = [
            models.UniqueConstraint(fields=['snapshot', 'factor_code'], name='ms_market_factor_uniq'),
        ]


class StockSentimentFactor(models.Model):
    snapshot = models.ForeignKey(StockSentimentSnapshot, on_delete=models.CASCADE, related_name='factors')
    factor_code = models.CharField(max_length=32)
    raw_value = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    normalized_value = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    effective_weight = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    contribution = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    available = models.BooleanField(default=True)
    reason = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'stock_sentiment_factor'
        constraints = [
            models.UniqueConstraint(fields=['snapshot', 'factor_code'], name='ms_stock_factor_uniq'),
        ]