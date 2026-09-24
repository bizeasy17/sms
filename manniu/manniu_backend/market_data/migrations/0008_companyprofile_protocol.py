from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('market_data', '0007_swindustrydailylatest_swindustrydailyhistory'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyprofile',
            name='protocol',
            field=models.CharField(blank=True, max_length=8),
        ),
    ]