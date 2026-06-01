from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0007_local_market_mirror_tables"),
    ]

    operations = [
        migrations.CreateModel(
            name="EarningsSignalSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16, unique=True)),
                ("signal_score", models.FloatField(blank=True, null=True)),
                ("action", models.CharField(default="HOLD", max_length=16)),
                ("risk_level", models.CharField(default="MEDIUM", max_length=16)),
                ("model_version", models.CharField(blank=True, default="", max_length=128)),
                ("asof_date", models.DateField(blank=True, db_index=True, null=True)),
                ("explain", models.JSONField(blank=True, default=dict)),
                ("raw_result", models.JSONField(blank=True, default=dict)),
                ("feature_data_source", models.CharField(blank=True, default="", max_length=32)),
                ("batch_key", models.CharField(blank=True, db_index=True, default="manual", max_length=64)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_signal_snapshot",
            },
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshot",
            index=models.Index(fields=["batch_key", "updated_at"], name="idx_earn_sig_batch_updated"),
        ),
    ]
