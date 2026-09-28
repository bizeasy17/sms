from django.db import models
from market_data.models import Security


class FinancialHealthSearchHistory(models.Model):
    user_key = models.CharField(max_length=64)
    ts_code = models.CharField(max_length=18)
    symbol = models.CharField(max_length=8, blank=True, default='')
    name = models.CharField(max_length=128, blank=True, default='')
    industry = models.CharField(max_length=128, blank=True, default='')
    searched_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'metrics_financial_health_search_history'
        constraints = [
            models.UniqueConstraint(fields=['user_key', 'ts_code'], name='metrics_fhsh_user_ts'),
        ]
        indexes = [
            models.Index(fields=['user_key', 'searched_at'], name='metrics_fhsh_user_time'),
        ]


class MetricsScoreSnapshot(models.Model):
    class ScoreType(models.TextChoices):
        FINANCIAL_HEALTH_6D = 'FINANCIAL_HEALTH_6D', 'Financial health 6D'
        MODEL_TOPN_6D = 'MODEL_TOPN_6D', 'Model TopN 6D'
        COMPANY_GROWTH_POTENTIAL = 'COMPANY_GROWTH_POTENTIAL', 'Company growth potential'

    class Status(models.TextChoices):
        VALID = 'VALID', 'Valid'
        PARTIAL = 'PARTIAL', 'Partial'
        INSUFFICIENT_DATA = 'INSUFFICIENT_DATA', 'Insufficient data'
        NOT_APPLICABLE = 'NOT_APPLICABLE', 'Not applicable'
        DEGRADED = 'DEGRADED', 'Degraded'
        NOT_AVAILABLE = 'NOT_AVAILABLE', 'Not available'

    security = models.ForeignKey(
        Security,
        on_delete=models.PROTECT,
        related_name='metrics_score_snapshots',
    )
    score_type = models.CharField(max_length=40, choices=ScoreType.choices)
    asof_date = models.DateField()
    financial_end_date = models.DateField(null=True, blank=True)
    market_asof_date = models.DateField(null=True, blank=True)
    report_type = models.CharField(max_length=16, blank=True, default='')
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    label = models.CharField(max_length=32, blank=True, default='')
    score_status = models.CharField(max_length=32, choices=Status.choices)
    coverage = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    calculation_version = models.CharField(max_length=64, blank=True, default='')
    scoring_version = models.CharField(max_length=64, blank=True, default='')
    profile_version = models.CharField(max_length=64, blank=True, default='')
    peer_mapping_version = models.CharField(max_length=64, blank=True, default='')
    model_version = models.CharField(max_length=128, blank=True, default='')
    feature_set_version = models.CharField(max_length=128, blank=True, default='')
    mapping_version = models.CharField(max_length=64, blank=True, default='')
    normalization_version = models.CharField(max_length=64, blank=True, default='')
    dimension_weight_version = models.CharField(max_length=64, blank=True, default='')
    score_topn = models.PositiveSmallIntegerField(null=True, blank=True)
    store_topn = models.PositiveSmallIntegerField(null=True, blank=True)
    model_scope = models.CharField(max_length=128, blank=True, default='')
    model_degraded = models.BooleanField(default=False)
    model_degrade_reason = models.CharField(max_length=512, blank=True, default='')
    source_periods = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    input_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'metrics_score_snapshot'
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'score_type', 'input_fingerprint'],
                name='mss_sec_type_fp',
            ),
        ]
        indexes = [
            models.Index(
                fields=['security', 'score_type', '-asof_date', '-created_at'],
                name='mss_sec_type_asof',
            ),
            models.Index(
                fields=['score_type', '-asof_date', 'score_status'],
                name='mss_type_date_status',
            ),
            models.Index(fields=['score_type', 'score'], name='mss_type_score'),
        ]


class MetricsScoreDimension(models.Model):
    snapshot = models.ForeignKey(
        MetricsScoreSnapshot,
        on_delete=models.CASCADE,
        related_name='dimensions',
    )
    dimension_key = models.CharField(max_length=64)
    dimension_name = models.CharField(max_length=128, blank=True, default='')
    weight = models.DecimalField(max_digits=7, decimal_places=4)
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=32)
    available_weight = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    evidence = models.JSONField(default=dict)

    class Meta:
        db_table = 'metrics_score_dimension'
        constraints = [
            models.UniqueConstraint(
                fields=['snapshot', 'dimension_key'],
                name='msd_snapshot_dimension',
            ),
        ]
        indexes = [
            models.Index(
                fields=['dimension_key', 'score', 'status'],
                name='msd_key_score_status',
            ),
        ]
