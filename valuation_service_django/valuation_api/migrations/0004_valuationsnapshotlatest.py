from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("valuation_api", "0003_market_reference_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="ValuationSnapshotLatest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=12)),
                ("latest_trade_date", models.DateField(db_index=True)),
                ("market", models.CharField(db_index=True, default="CN", max_length=10)),
                ("valuation_method", models.CharField(db_index=True, max_length=32)),
                ("valuation_variant", models.CharField(db_index=True, default="default", max_length=128)),
                ("valuation_price", models.FloatField(null=True)),
                ("valuation_market_cap", models.FloatField(null=True)),
                ("source", models.CharField(default="legacy_snapshot", max_length=32)),
                ("industry_level", models.CharField(blank=True, db_index=True, max_length=16, null=True)),
                ("industry_code", models.CharField(blank=True, db_index=True, max_length=32, null=True)),
                ("industry_name", models.CharField(blank=True, max_length=128, null=True)),
                ("compare_group", models.CharField(blank=True, db_index=True, max_length=32, null=True)),
                ("match_score", models.FloatField(blank=True, null=True)),
                ("profit_data_source", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("profit_report_end_date", models.DateField(blank=True, db_index=True, null=True)),
                ("profit_report_type", models.CharField(blank=True, db_index=True, max_length=16, null=True)),
                ("express_end_date", models.DateField(blank=True, db_index=True, null=True)),
                ("express_ann_date", models.DateField(blank=True, db_index=True, null=True)),
                ("express_apply_reason", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("express_block_reason", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("strict_express_match", models.BooleanField(blank=True, null=True)),
                ("express_max_age_days", models.IntegerField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "valuation_snapshot_latest",
                "unique_together": {("ts_code", "market", "valuation_method", "valuation_variant")},
            },
        ),
        migrations.AddIndex(
            model_name="valuationsnapshotlatest",
            index=models.Index(fields=["ts_code", "market", "latest_trade_date"], name="valuation_a_ts_code_4ae0a8_idx"),
        ),
    ]