from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0008_earningssignalsnapshot"),
    ]

    operations = [
        migrations.CreateModel(
            name="EarningsSignalSnapshotHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("model_version", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("signal_score", models.FloatField(blank=True, null=True)),
                ("action", models.CharField(default="HOLD", max_length=16)),
                ("risk_level", models.CharField(default="MEDIUM", max_length=16)),
                ("asof_date", models.DateField(blank=True, db_index=True, null=True)),
                ("explain", models.JSONField(blank=True, default=dict)),
                ("raw_result", models.JSONField(blank=True, default=dict)),
                ("feature_data_source", models.CharField(blank=True, default="", max_length=32)),
                ("batch_key", models.CharField(blank=True, db_index=True, default="manual", max_length=64)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "earnings_signal_snapshot_history",
            },
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshothistory",
            index=models.Index(fields=["ts_code", "model_version", "asof_date"], name="idx_esh_code_ver_dt"),
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshothistory",
            index=models.Index(fields=["batch_key", "created_at"], name="idx_esh_batch_ct"),
        ),
    ]
