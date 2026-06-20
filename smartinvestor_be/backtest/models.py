from django.db import models


class TraditionalBacktestRun(models.Model):
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    run_key = models.CharField(max_length=128, unique=True, db_index=True)
    batch_key = models.CharField(max_length=64, default="traditional_value_exit", db_index=True)
    strategy_name = models.CharField(max_length=64, default="traditional_value_exit", db_index=True)
    status = models.CharField(max_length=16, default="success", db_index=True)

    scope = models.CharField(max_length=32, default="ALL")
    market = models.CharField(max_length=10, default="CN")
    start_date = models.DateField(null=True, blank=True, db_index=True)
    end_date = models.DateField(null=True, blank=True, db_index=True)

    params_json = models.JSONField(default=dict, blank=True)
    summary_json = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)

    result_file = models.CharField(max_length=512, blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["batch_key", "updated_at"]),
            models.Index(fields=["strategy_name", "updated_at"]),
            models.Index(fields=["start_date", "end_date"]),
        ]


class TraditionalBacktestScanTask(models.Model):
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    task_key = models.CharField(max_length=128, unique=True, db_index=True)
    status = models.CharField(max_length=16, default="pending", db_index=True)
    strategy_name = models.CharField(max_length=64, default="traditional_value_exit", db_index=True)

    total_jobs = models.PositiveIntegerField(default=0)
    completed_jobs = models.PositiveIntegerField(default=0)
    failed_jobs = models.PositiveIntegerField(default=0)

    params_json = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "updated_at"], name="btscan_status_upd_idx"),
            models.Index(fields=["strategy_name", "updated_at"], name="btscan_strategy_upd_idx"),
        ]


class PredictiveBacktestScanTask(models.Model):
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    task_key = models.CharField(max_length=128, unique=True, db_index=True)
    status = models.CharField(max_length=16, default="pending", db_index=True)
    strategy_name = models.CharField(max_length=64, default="predictive_backtest", db_index=True)

    total_jobs = models.PositiveIntegerField(default=0)
    completed_jobs = models.PositiveIntegerField(default=0)
    failed_jobs = models.PositiveIntegerField(default=0)

    params_json = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "updated_at"], name="btpredscan_status_upd_idx"),
            models.Index(fields=["strategy_name", "updated_at"], name="btpredscan_strategy_upd_idx"),
        ]
