import uuid

from django.db import models


class LogRun(models.Model):
    class RunType(models.TextChoices):
        HTTP = 'HTTP', 'HTTP'
        COMMAND = 'COMMAND', 'Command'
        BATCH = 'BATCH', 'Batch'
        TASK = 'TASK', 'Task'

    class Status(models.TextChoices):
        RUNNING = 'RUNNING', 'Running'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        ABANDONED = 'ABANDONED', 'Abandoned'

    class Trigger(models.TextChoices):
        SCHEDULE = 'SCHEDULE', 'Schedule'
        MANUAL = 'MANUAL', 'Manual'
        HTTP = 'HTTP', 'HTTP'
        SYSTEM = 'SYSTEM', 'System'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_run = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='child_runs',
    )
    run_type = models.CharField(max_length=24, choices=RunType.choices)
    name = models.CharField(max_length=96)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    trigger = models.CharField(max_length=24, choices=Trigger.choices, default=Trigger.MANUAL)
    correlation_id = models.CharField(max_length=64, null=True, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.BigIntegerField(null=True, blank=True)
    host_name = models.CharField(max_length=128)
    process_id = models.IntegerField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    summary = models.TextField(blank=True, default='')
    counters = models.JSONField(default=dict, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'ops_log_run'
        ordering = ('-started_at',)
        indexes = [
            models.Index(fields=['name', '-started_at'], name='ops_run_name_started_idx'),
            models.Index(fields=['status', '-started_at'], name='ops_run_status_time_idx'),
            models.Index(fields=['parent_run', 'started_at'], name='ops_run_parent_time_idx'),
            models.Index(fields=['correlation_id'], name='ops_run_corr_idx'),
        ]


class LogEntry(models.Model):
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    run = models.ForeignKey(
        LogRun,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='entries',
    )
    occurred_at = models.DateTimeField()
    ingested_at = models.DateTimeField(auto_now_add=True)
    level_no = models.SmallIntegerField()
    level_name = models.CharField(max_length=10)
    logger_name = models.CharField(max_length=160)
    event_code = models.CharField(max_length=96, null=True, blank=True)
    message = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    exception_type = models.CharField(max_length=160, null=True, blank=True)
    exception_message = models.TextField(null=True, blank=True)
    exception_stack = models.TextField(null=True, blank=True)
    fingerprint = models.CharField(max_length=64, null=True, blank=True)
    source_module = models.CharField(max_length=160, null=True, blank=True)
    source_function = models.CharField(max_length=160, null=True, blank=True)
    source_line = models.IntegerField(null=True, blank=True)
    correlation_id = models.CharField(max_length=64, null=True, blank=True)
    request_id = models.CharField(max_length=64, null=True, blank=True)
    host_name = models.CharField(max_length=128)
    process_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'ops_log_entry'
        ordering = ('-occurred_at',)
        indexes = [
            models.Index(fields=['-occurred_at'], name='ops_entry_time_idx'),
            models.Index(fields=['run', 'occurred_at'], name='ops_entry_run_time_idx'),
            models.Index(fields=['level_no', '-occurred_at'], name='ops_entry_level_time_idx'),
            models.Index(fields=['event_code', '-occurred_at'], name='ops_entry_event_time_idx'),
            models.Index(fields=['fingerprint', '-occurred_at'], name='ops_entry_fp_time_idx'),
        ]