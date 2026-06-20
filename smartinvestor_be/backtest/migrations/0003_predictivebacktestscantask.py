from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backtest", "0002_traditionalbacktestscantask"),
    ]

    operations = [
        migrations.CreateModel(
            name="PredictiveBacktestScanTask",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("task_key", models.CharField(db_index=True, max_length=128, unique=True)),
                ("status", models.CharField(db_index=True, default="pending", max_length=16)),
                ("strategy_name", models.CharField(db_index=True, default="predictive_backtest", max_length=64)),
                ("total_jobs", models.PositiveIntegerField(default=0)),
                ("completed_jobs", models.PositiveIntegerField(default=0)),
                ("failed_jobs", models.PositiveIntegerField(default=0)),
                ("params_json", models.JSONField(blank=True, default=dict)),
                ("result_json", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["-updated_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="predictivebacktestscantask",
            index=models.Index(fields=["status", "updated_at"], name="btpredscan_status_upd_idx"),
        ),
        migrations.AddIndex(
            model_name="predictivebacktestscantask",
            index=models.Index(fields=["strategy_name", "updated_at"], name="btpredscan_strategy_upd_idx"),
        ),
    ]
