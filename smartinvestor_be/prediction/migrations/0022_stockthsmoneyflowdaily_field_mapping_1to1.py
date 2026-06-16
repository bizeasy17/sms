from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0021_stockthsmoneyflowfeaturedaily"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockthsmoneyflowdaily",
            name="net_amount",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="净流入额(net_amount)"),
        ),
        migrations.AddField(
            model_name="stockthsmoneyflowdaily",
            name="net_amount_rate",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True, verbose_name="净流入率"),
        ),
        migrations.AddField(
            model_name="stockthsmoneyflowdaily",
            name="net_mf_rate",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True, verbose_name="净流入率(net_mf_rate)"),
        ),
        migrations.AddField(
            model_name="stockthsmoneyflowdaily",
            name="net_pct",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True, verbose_name="净流入占比"),
        ),
    ]
