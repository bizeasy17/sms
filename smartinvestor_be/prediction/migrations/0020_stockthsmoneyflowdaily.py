from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0019_rename_variant_summary_table_prefix"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockThsMoneyflowDaily",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ts_code", models.CharField(db_index=True, max_length=10, verbose_name="交易代码")),
                ("trade_date", models.DateField(db_index=True, verbose_name="交易日")),
                ("buy_sm_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="小单买入额")),
                ("sell_sm_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="小单卖出额")),
                ("buy_md_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="中单买入额")),
                ("sell_md_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="中单卖出额")),
                ("buy_lg_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="大单买入额")),
                ("sell_lg_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="大单卖出额")),
                ("buy_elg_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="特大单买入额")),
                ("sell_elg_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="特大单卖出额")),
                ("net_mf_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="净流入额")),
                ("raw_payload", models.JSONField(blank=True, default=dict, verbose_name="原始载荷")),
            ],
            options={
                "verbose_name": "THS个股资金流日数据",
                "verbose_name_plural": "THS个股资金流日数据",
                "ordering": ["-trade_date", "ts_code"],
            },
        ),
        migrations.AddConstraint(
            model_name="stockthsmoneyflowdaily",
            constraint=models.UniqueConstraint(fields=("ts_code", "trade_date"), name="sthsmfd_tsdate_uniq"),
        ),
        migrations.AddIndex(
            model_name="stockthsmoneyflowdaily",
            index=models.Index(fields=["trade_date", "ts_code"], name="sthsmfd_date_code_ix"),
        ),
        migrations.AddIndex(
            model_name="stockthsmoneyflowdaily",
            index=models.Index(fields=["ts_code", "trade_date"], name="sthsmfd_code_date_ix"),
        ),
    ]
