from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0020_stockthsmoneyflowdaily"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockThsMoneyflowFeatureDaily",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ts_code", models.CharField(db_index=True, max_length=10, verbose_name="交易代码")),
                ("trade_date", models.DateField(db_index=True, verbose_name="交易日")),
                ("mf_sum_5", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="5日净流入和")),
                ("mf_sum_10", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="10日净流入和")),
                ("mf_sum_15", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="15日净流入和")),
                ("mf_sum_30", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="30日净流入和")),
                ("mf_sum_60", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="60日净流入和")),
                ("obs_days_5", models.IntegerField(default=0, verbose_name="5日样本天数")),
                ("obs_days_10", models.IntegerField(default=0, verbose_name="10日样本天数")),
                ("obs_days_15", models.IntegerField(default=0, verbose_name="15日样本天数")),
                ("obs_days_30", models.IntegerField(default=0, verbose_name="30日样本天数")),
                ("obs_days_60", models.IntegerField(default=0, verbose_name="60日样本天数")),
            ],
            options={
                "verbose_name": "THS个股资金流特征日数据",
                "verbose_name_plural": "THS个股资金流特征日数据",
                "ordering": ["-trade_date", "ts_code"],
            },
        ),
        migrations.AddConstraint(
            model_name="stockthsmoneyflowfeaturedaily",
            constraint=models.UniqueConstraint(fields=("ts_code", "trade_date"), name="sthmffd_tsdate_uniq"),
        ),
        migrations.AddIndex(
            model_name="stockthsmoneyflowfeaturedaily",
            index=models.Index(fields=["trade_date", "ts_code"], name="sthmffd_date_codex"),
        ),
        migrations.AddIndex(
            model_name="stockthsmoneyflowfeaturedaily",
            index=models.Index(fields=["ts_code", "trade_date"], name="sthmffd_code_datex"),
        ),
    ]
