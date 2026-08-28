from django.db import models


class MarketSentimentSnapshot(models.Model):
    market = models.CharField(max_length=10, default='CN', db_index=True)
    scope_type = models.CharField(max_length=16, default='MARKET', db_index=True)
    scope_code = models.CharField(max_length=64, default='ALL_A', db_index=True)
    trade_date = models.DateField(db_index=True)
    sentiment_score = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    sentiment_level = models.CharField(max_length=32, default='WARMING_UP', db_index=True)
    raw_score = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)
    standardized_score = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)
    momentum_score = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)
    activity_score = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)
    fear_score = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)
    universe_size = models.IntegerField(default=0)
    valid_sample_size = models.IntegerField(default=0)
    coverage = models.DecimalField(max_digits=6, decimal_places=4, blank=True, null=True)
    engine_version = models.CharField(max_length=32, default='daily_v1_20260828', db_index=True)
    status = models.CharField(max_length=32, default='PENDING', db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-trade_date']
        unique_together = ('market', 'scope_type', 'scope_code', 'trade_date', 'engine_version')
        indexes = [
            models.Index(fields=['market', 'scope_type', 'scope_code', 'trade_date'], name='mkt_sent_scope_date_idx'),
        ]


class MarketSentimentFactor(models.Model):
    snapshot = models.ForeignKey(MarketSentimentSnapshot, related_name='factors', on_delete=models.CASCADE)
    dimension = models.CharField(max_length=32, db_index=True)
    factor_code = models.CharField(max_length=64, db_index=True)
    factor_name = models.CharField(max_length=128)
    raw_value = models.DecimalField(max_digits=18, decimal_places=8, blank=True, null=True)
    normalized_value = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)
    weight = models.DecimalField(max_digits=8, decimal_places=6, blank=True, null=True)
    contribution = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)
    available = models.BooleanField(default=True)
    reason = models.TextField(blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['dimension', 'factor_code'], name='mkt_sent_factor_idx'),
        ]
