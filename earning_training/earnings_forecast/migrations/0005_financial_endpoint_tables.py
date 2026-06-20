from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0004_financialfeaturepanel"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialIncomeRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_income",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_income_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_income",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialBalanceSheetVipRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_balancesheet_vip",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_balvip_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_balvip",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialCashflowVipRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_cashflow_vip",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_cashvip_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_cashvip",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialForecastVipRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_forecast_vip",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_forevip_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_forevip",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialExpressVipRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_express_vip",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_exprvip_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_exprvip",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialDividendRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_dividend",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_div_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_div",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialFinaIndicatorVipRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_fina_indicator_vip",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_findvip_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_findvip",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialFinaAuditRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_fina_audit",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_finaudit_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_finaudit",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialFinaMainbzVipRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_fina_mainbz_vip",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_mainbzv_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_mainbzv",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FinancialDisclosureDateRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("period", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("row_signature", models.CharField(max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("source_file", models.CharField(blank=True, default="", max_length=512)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_fin_disclosure_date",
                "indexes": [models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_discdt_ce")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ts_code", "ann_date", "end_date", "period", "row_signature"),
                        name="uq_earn_fin_discdt",
                    )
                ],
            },
        ),
        migrations.DeleteModel(
            name="FinancialCacheRecord",
        ),
    ]
