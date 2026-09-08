import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='LogRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('run_type', models.CharField(choices=[('HTTP', 'HTTP'), ('COMMAND', 'Command'), ('BATCH', 'Batch'), ('TASK', 'Task')], max_length=24)),
                ('name', models.CharField(max_length=96)),
                ('status', models.CharField(choices=[('RUNNING', 'Running'), ('SUCCEEDED', 'Succeeded'), ('FAILED', 'Failed'), ('CANCELLED', 'Cancelled'), ('ABANDONED', 'Abandoned')], default='RUNNING', max_length=16)),
                ('trigger', models.CharField(choices=[('SCHEDULE', 'Schedule'), ('MANUAL', 'Manual'), ('HTTP', 'HTTP'), ('SYSTEM', 'System')], default='MANUAL', max_length=24)),
                ('correlation_id', models.CharField(blank=True, max_length=64, null=True)),
                ('started_at', models.DateTimeField()),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('duration_ms', models.BigIntegerField(blank=True, null=True)),
                ('host_name', models.CharField(max_length=128)),
                ('process_id', models.IntegerField(blank=True, null=True)),
                ('exit_code', models.IntegerField(blank=True, null=True)),
                ('summary', models.TextField(blank=True, default='')),
                ('counters', models.JSONField(blank=True, default=dict)),
                ('parameters', models.JSONField(blank=True, default=dict)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('parent_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='child_runs', to='ops_logging.logrun')),
            ],
            options={
                'db_table': 'ops_log_run',
                'ordering': ('-started_at',),
            },
        ),
        migrations.CreateModel(
            name='LogEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('occurred_at', models.DateTimeField()),
                ('ingested_at', models.DateTimeField(auto_now_add=True)),
                ('level_no', models.SmallIntegerField()),
                ('level_name', models.CharField(max_length=10)),
                ('logger_name', models.CharField(max_length=160)),
                ('event_code', models.CharField(blank=True, max_length=96, null=True)),
                ('message', models.TextField()),
                ('context', models.JSONField(blank=True, default=dict)),
                ('exception_type', models.CharField(blank=True, max_length=160, null=True)),
                ('exception_message', models.TextField(blank=True, null=True)),
                ('exception_stack', models.TextField(blank=True, null=True)),
                ('fingerprint', models.CharField(blank=True, max_length=64, null=True)),
                ('source_module', models.CharField(blank=True, max_length=160, null=True)),
                ('source_function', models.CharField(blank=True, max_length=160, null=True)),
                ('source_line', models.IntegerField(blank=True, null=True)),
                ('correlation_id', models.CharField(blank=True, max_length=64, null=True)),
                ('request_id', models.CharField(blank=True, max_length=64, null=True)),
                ('host_name', models.CharField(max_length=128)),
                ('process_id', models.IntegerField(blank=True, null=True)),
                ('run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='ops_logging.logrun')),
            ],
            options={
                'db_table': 'ops_log_entry',
                'ordering': ('-occurred_at',),
            },
        ),
        migrations.AddIndex(model_name='logrun', index=models.Index(fields=['name', '-started_at'], name='ops_run_name_started_idx')),
        migrations.AddIndex(model_name='logrun', index=models.Index(fields=['status', '-started_at'], name='ops_run_status_time_idx')),
        migrations.AddIndex(model_name='logrun', index=models.Index(fields=['parent_run', 'started_at'], name='ops_run_parent_time_idx')),
        migrations.AddIndex(model_name='logrun', index=models.Index(fields=['correlation_id'], name='ops_run_corr_idx')),
        migrations.AddIndex(model_name='logentry', index=models.Index(fields=['-occurred_at'], name='ops_entry_time_idx')),
        migrations.AddIndex(model_name='logentry', index=models.Index(fields=['run', 'occurred_at'], name='ops_entry_run_time_idx')),
        migrations.AddIndex(model_name='logentry', index=models.Index(fields=['level_no', '-occurred_at'], name='ops_entry_level_time_idx')),
        migrations.AddIndex(model_name='logentry', index=models.Index(fields=['event_code', '-occurred_at'], name='ops_entry_event_time_idx')),
        migrations.AddIndex(model_name='logentry', index=models.Index(fields=['fingerprint', '-occurred_at'], name='ops_entry_fp_time_idx')),
    ]