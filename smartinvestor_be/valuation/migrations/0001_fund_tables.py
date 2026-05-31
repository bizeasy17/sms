from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ValuationFundBasic",
            fields=[
                ("ts_code", models.CharField(max_length=16, primary_key=True, serialize=False)),
                ("name", models.CharField(blank=True, default="", max_length=128)),
                ("management", models.CharField(blank=True, default="", max_length=128)),
                ("custodian", models.CharField(blank=True, default="", max_length=128)),
                ("fund_type", models.CharField(blank=True, default="", max_length=64)),
                ("found_date", models.CharField(blank=True, default="", max_length=8)),
                ("due_date", models.CharField(blank=True, default="", max_length=8)),
                ("status", models.CharField(blank=True, default="", max_length=16)),
                ("market", models.CharField(blank=True, default="", max_length=8)),
                ("is_updated", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "valuation_fund_basic",
            },
        ),
        migrations.CreateModel(
            name="ValuationFundNav",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fund_ts_code", models.CharField(max_length=16)),
                ("nav_date", models.CharField(max_length=8)),
                ("unit_nav", models.FloatField(blank=True, null=True)),
                ("accum_nav", models.FloatField(blank=True, null=True)),
                ("adj_nav", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "valuation_fund_nav",
                "unique_together": {("fund_ts_code", "nav_date")},
            },
        ),
        migrations.CreateModel(
            name="ValuationFundPortfolio",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fund_ts_code", models.CharField(max_length=16)),
                ("stock_ts_code", models.CharField(max_length=16)),
                ("stock_symbol", models.CharField(blank=True, default="", max_length=16)),
                ("end_date", models.CharField(max_length=8)),
                ("ann_date", models.CharField(blank=True, default="", max_length=8)),
                ("mkv", models.FloatField(blank=True, null=True)),
                ("amount", models.FloatField(blank=True, null=True)),
                ("stk_mkv_ratio", models.FloatField(blank=True, null=True)),
                ("stk_float_ratio", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "valuation_fund_portfolio",
                "unique_together": {("fund_ts_code", "stock_ts_code", "end_date")},
            },
        ),
        migrations.AddIndex(
            model_name="valuationfundbasic",
            index=models.Index(fields=["name"], name="vfb_name_idx"),
        ),
        migrations.AddIndex(
            model_name="valuationfundbasic",
            index=models.Index(fields=["status"], name="vfb_status_idx"),
        ),
        migrations.AddIndex(
            model_name="valuationfundnav",
            index=models.Index(fields=["fund_ts_code", "nav_date"], name="vfn_fund_navdate_idx"),
        ),
        migrations.AddIndex(
            model_name="valuationfundportfolio",
            index=models.Index(fields=["stock_ts_code", "end_date"], name="vfp_stock_end_idx"),
        ),
        migrations.AddIndex(
            model_name="valuationfundportfolio",
            index=models.Index(fields=["fund_ts_code", "end_date"], name="vfp_fund_end_idx"),
        ),
    ]
