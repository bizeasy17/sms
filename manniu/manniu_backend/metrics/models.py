from django.db import models


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
