from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financials', '0003_financialbalancesheetrecord_lt_borr_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='financialdisclosurerecord',
            index=models.Index(
                fields=['actual_date', 'security'],
                name='fin_disc_actual_sec',
            ),
        ),
    ]
