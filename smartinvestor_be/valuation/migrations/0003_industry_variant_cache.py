from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("valuation", "0002_snapshot_history_backfill_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="IndustryVariantCache",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("market", models.CharField(default="CN", max_length=8)),
                ("variant_key", models.CharField(max_length=128)),
                ("display_name", models.CharField(blank=True, default="", max_length=128)),
                ("industry_code", models.CharField(blank=True, default="", max_length=32)),
                ("industry_level", models.CharField(blank=True, default="", max_length=8)),
                ("compare_group", models.CharField(blank=True, default="", max_length=32)),
                ("member_count", models.IntegerField(default=0)),
                ("max_match_score", models.FloatField(blank=True, null=True)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "valuation_industry_variant_cache",
                "unique_together": {("market", "variant_key")},
            },
        ),
        migrations.CreateModel(
            name="IndustryVariantMetricDaily",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("market", models.CharField(default="CN", max_length=8)),
                ("variant_key", models.CharField(max_length=128)),
                ("metric", models.CharField(max_length=16)),
                ("trade_date", models.DateField()),
                ("median_value", models.FloatField(blank=True, null=True)),
                ("sample_count", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "valuation_industry_variant_metric_daily",
                "unique_together": {("market", "variant_key", "metric", "trade_date")},
            },
        ),
        migrations.AddIndex(
            model_name="industryvariantcache",
            index=models.Index(fields=["market", "variant_key"], name="viv_mkt_variant_idx"),
        ),
        migrations.AddIndex(
            model_name="industryvariantcache",
            index=models.Index(fields=["market", "member_count"], name="viv_mkt_member_idx"),
        ),
        migrations.AddIndex(
            model_name="industryvariantmetricdaily",
            index=models.Index(fields=["market", "variant_key", "metric", "trade_date"], name="vivmd_main_idx"),
        ),
        migrations.AddIndex(
            model_name="industryvariantmetricdaily",
            index=models.Index(fields=["market", "metric", "trade_date"], name="vivmd_mkt_metric_idx"),
        ),
    ]
