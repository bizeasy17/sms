from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("valuation_api", "0007_valuationsnapshot"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockExpressVip",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=12)),
                ("ann_date", models.DateField(blank=True, db_index=True, null=True)),
                ("end_date", models.DateField(blank=True, db_index=True, null=True)),
                ("revenue", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ("total_revenue", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ("oper_rev", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ("n_income", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ("n_income_attr_p", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ("profit_dedt", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ("yoy_net_profit", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("yoy_dedu_np", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("yoy_sales", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("yoy_np", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("netprofit_yoy", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("tr_yoy", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("or_yoy", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "valuation_express_vip",
                "unique_together": {("ts_code", "ann_date", "end_date")},
            },
        ),
        migrations.AddIndex(
            model_name="stockexpressvip",
            index=models.Index(fields=["ts_code", "end_date", "ann_date"], name="valuation_e_ts_code_61f9ca_idx"),
        ),
    ]
