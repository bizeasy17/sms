import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datastore", "0001_initial"),
        ("prediction", "0007_stockvaluationsnapshot_valuation_market_cap"),
    ]

    operations = [
        migrations.CreateModel(
            name="BacktestValuationSnapshot",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ts_code", models.CharField(db_index=True, max_length=10, verbose_name="交易代码")),
                ("trade_date", models.DateField(db_index=True, verbose_name="交易日")),
                ("market", models.CharField(db_index=True, default="CN", max_length=10, verbose_name="市场")),
                ("valuation_method", models.CharField(db_index=True, max_length=32, verbose_name="估值方法")),
                (
                    "valuation_price",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True, verbose_name="估值价格"),
                ),
                (
                    "valuation_market_cap",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="估值对应的股权价值，单位：元",
                        max_digits=24,
                        null=True,
                        verbose_name="估值市值",
                    ),
                ),
                ("source", models.CharField(default="live_backtest", max_length=32, verbose_name="来源")),
                ("batch_key", models.CharField(db_index=True, default="default", max_length=64, verbose_name="回测批次")),
                (
                    "corporation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="backtest_valuation_snapshots",
                        to="datastore.corporation",
                    ),
                ),
            ],
            options={
                "verbose_name": "回测估值临时快照",
                "verbose_name_plural": "回测估值临时快照",
                "ordering": ["-trade_date", "ts_code"],
                "unique_together": {("ts_code", "trade_date", "market", "valuation_method", "batch_key")},
            },
        ),
        migrations.AddIndex(
            model_name="backtestvaluationsnapshot",
            index=models.Index(fields=["batch_key", "trade_date", "valuation_method"], name="prediction__batch_k_4e4d76_idx"),
        ),
        migrations.AddIndex(
            model_name="backtestvaluationsnapshot",
            index=models.Index(fields=["batch_key", "ts_code", "trade_date"], name="prediction__batch_k_570eb9_idx"),
        ),
    ]