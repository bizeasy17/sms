from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0009_earningssignalsnapshothistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="earningssignalsnapshot",
            name="target_market_cap",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshot",
            name="target_price",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshot",
            name="target_return_pct",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="target_market_cap",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="target_price",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="target_return_pct",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
