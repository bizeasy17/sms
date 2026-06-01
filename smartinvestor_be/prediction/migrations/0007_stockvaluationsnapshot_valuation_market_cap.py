from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0006_stockvaluationsnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="valuation_market_cap",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="估值对应的股权价值，单位：元",
                max_digits=24,
                null=True,
                verbose_name="估值市值",
            ),
        ),
    ]
