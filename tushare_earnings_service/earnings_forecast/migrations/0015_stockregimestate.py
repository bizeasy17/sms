from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("earnings_forecast", "0014_history_backfill_metadata")]

    operations = [
        migrations.CreateModel(
            name="StockRegimeState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16, unique=True)),
                ("regime", models.CharField(db_index=True, max_length=16)),
                ("previous_regime", models.CharField(blank=True, default="", max_length=16)),
                ("pending_regime", models.CharField(blank=True, default="", max_length=16)),
                ("pending_days", models.PositiveSmallIntegerField(default=0)),
                ("asof_trade_date", models.DateField(blank=True, db_index=True, null=True)),
                ("ma20", models.FloatField(blank=True, null=True)),
                ("ma60", models.FloatField(blank=True, null=True)),
                ("volatility_20d", models.FloatField(blank=True, null=True)),
                ("drawdown_60d", models.FloatField(blank=True, null=True)),
                ("last_triggered_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "earnings_stock_regime_state"},
        ),
        migrations.AddIndex(
            model_name="stockregimestate",
            index=models.Index(fields=["regime", "asof_trade_date"], name="idx_earn_stk_regime_dt"),
        ),
    ]