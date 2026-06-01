from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0012_signal_history_financial_period"),
    ]

    operations = [
        migrations.CreateModel(
            name="EarningsBacktestRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("run_key", models.CharField(db_index=True, max_length=64, unique=True)),
                ("batch_key", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("status", models.CharField(db_index=True, default="running", max_length=32)),
                ("params", models.JSONField(blank=True, default=dict)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_backtest_run",
                "indexes": [
                    models.Index(fields=["batch_key", "started_at"], name="idx_ebr_batch_start"),
                    models.Index(fields=["status", "started_at"], name="idx_ebr_status_start"),
                ],
            },
        ),
    ]
