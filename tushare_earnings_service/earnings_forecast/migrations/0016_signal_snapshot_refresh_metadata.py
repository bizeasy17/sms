from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("earnings_forecast", "0015_stockregimestate")]

    operations = [
        migrations.AddField(model_name="earningssignalsnapshot", name="refresh_reason", field=models.CharField(blank=True, db_index=True, default="", max_length=32)),
        migrations.AddField(model_name="earningssignalsnapshot", name="refresh_detail", field=models.CharField(blank=True, default="", max_length=128)),
        migrations.AddField(model_name="earningssignalsnapshot", name="market_regime", field=models.CharField(blank=True, db_index=True, default="", max_length=16)),
        migrations.AddField(model_name="earningssignalsnapshot", name="stock_regime", field=models.CharField(blank=True, db_index=True, default="", max_length=16)),
        migrations.AddField(model_name="earningssignalsnapshot", name="triggered_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="earningssignalsnapshothistory", name="refresh_reason", field=models.CharField(blank=True, db_index=True, default="", max_length=32)),
        migrations.AddField(model_name="earningssignalsnapshothistory", name="refresh_detail", field=models.CharField(blank=True, default="", max_length=128)),
        migrations.AddField(model_name="earningssignalsnapshothistory", name="stock_regime", field=models.CharField(blank=True, db_index=True, default="", max_length=16)),
        migrations.AddField(model_name="earningssignalsnapshothistory", name="triggered_at", field=models.DateTimeField(blank=True, null=True)),
    ]