from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0003_expand_financialfeaturesnapshot_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialFeaturePanel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=16)),
                ("fiscal_year", models.IntegerField(db_index=True)),
                ("report_type", models.CharField(db_index=True, max_length=16)),
                ("end_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("ann_date", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("revenue", models.FloatField(blank=True, null=True)),
                ("total_revenue", models.FloatField(blank=True, null=True)),
                ("operate_profit", models.FloatField(blank=True, null=True)),
                ("total_profit", models.FloatField(blank=True, null=True)),
                ("n_income", models.FloatField(blank=True, null=True)),
                ("n_income_attr_p", models.FloatField(blank=True, null=True)),
                ("basic_eps", models.FloatField(blank=True, null=True)),
                ("diluted_eps", models.FloatField(blank=True, null=True)),
                ("roe", models.FloatField(blank=True, null=True)),
                ("roe_dt", models.FloatField(blank=True, null=True)),
                ("roa", models.FloatField(blank=True, null=True)),
                ("q_dt_roe", models.FloatField(blank=True, null=True)),
                ("tr_yoy", models.FloatField(blank=True, null=True)),
                ("netprofit_yoy", models.FloatField(blank=True, null=True)),
                ("grossprofit_margin", models.FloatField(blank=True, null=True)),
                ("netprofit_margin", models.FloatField(blank=True, null=True)),
                ("debt_to_assets", models.FloatField(blank=True, null=True)),
                ("current_ratio", models.FloatField(blank=True, null=True)),
                ("quick_ratio", models.FloatField(blank=True, null=True)),
                ("cash_ratio", models.FloatField(blank=True, null=True)),
                ("assets_turn", models.FloatField(blank=True, null=True)),
                ("ocf_to_or", models.FloatField(blank=True, null=True)),
                ("total_assets", models.FloatField(blank=True, null=True)),
                ("total_liab", models.FloatField(blank=True, null=True)),
                ("total_hldr_eqy_exc_min_int", models.FloatField(blank=True, null=True)),
                ("money_cap", models.FloatField(blank=True, null=True)),
                ("accounts_receiv", models.FloatField(blank=True, null=True)),
                ("inventories", models.FloatField(blank=True, null=True)),
                ("st_borr", models.FloatField(blank=True, null=True)),
                ("lt_borr", models.FloatField(blank=True, null=True)),
                ("n_cashflow_act", models.FloatField(blank=True, null=True)),
                ("n_cashflow_inv_act", models.FloatField(blank=True, null=True)),
                ("n_cash_flows_fnc_act", models.FloatField(blank=True, null=True)),
                ("n_incr_cash_cash_equ", models.FloatField(blank=True, null=True)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "earnings_financial_feature_panel",
                "indexes": [
                    models.Index(fields=["fiscal_year", "report_type"], name="idx_earn_fin_panel_yr_rt"),
                    models.Index(fields=["ts_code", "end_date"], name="idx_earn_fin_panel_code_end"),
                    models.Index(fields=["ann_date"], name="idx_earn_fin_panel_ann"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("ts_code", "end_date", "report_type"), name="uq_earn_fin_feat_panel")
                ],
            },
        ),
    ]
