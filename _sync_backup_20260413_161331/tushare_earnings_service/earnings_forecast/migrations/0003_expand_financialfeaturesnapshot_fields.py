from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0002_financialfeaturesnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="accounts_receiv",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="assets_turn",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="basic_eps",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="cash_ratio",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="current_ratio",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="debt_to_assets",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="diluted_eps",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="inventories",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="lt_borr",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="money_cap",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="n_cash_flows_fnc_act",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="n_cashflow_act",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="n_cashflow_inv_act",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="n_income_attr_p",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="n_incr_cash_cash_equ",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="netprofit_yoy",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="ocf_to_or",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="operate_profit",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="quick_ratio",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="roa",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="roe_dt",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="st_borr",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="total_assets",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="total_hldr_eqy_exc_min_int",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="total_liab",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="total_profit",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="total_revenue",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfeaturesnapshot",
            name="tr_yoy",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
