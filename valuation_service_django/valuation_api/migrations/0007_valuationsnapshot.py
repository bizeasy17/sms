from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("valuation_api", "0006_remove_stockfundamentalsnapshot_valuation_f_ts_code_d9803e_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ValuationSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=12)),
                ("trade_date", models.DateField(db_index=True)),
                ("market", models.CharField(db_index=True, default="CN", max_length=10)),
                ("valuation_method", models.CharField(db_index=True, max_length=32)),
                ("valuation_variant", models.CharField(db_index=True, default="default", max_length=128)),
                ("valuation_price", models.FloatField(null=True)),
                ("valuation_market_cap", models.FloatField(null=True)),
                ("source", models.CharField(default="live_compute", max_length=32)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "valuation_snapshot",
                "unique_together": {("ts_code", "trade_date", "market", "valuation_method", "valuation_variant")},
            },
        ),
        migrations.AddIndex(
            model_name="valuationsnapshot",
            index=models.Index(fields=["ts_code", "trade_date", "market", "valuation_method"], name="valuation_s_ts_code_6f8c9e_idx"),
        ),
    ]
