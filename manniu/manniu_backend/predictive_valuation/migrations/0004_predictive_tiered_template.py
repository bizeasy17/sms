from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('predictive_valuation', '0004_remove_predictivevaluationsnapshot_pv_snapshot_uniq_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='predictive_tiered_template',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='predictive_tiered_template',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]