from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('traditional_valuation', '0003_traditionalvaluationeventstate_source_event_key_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='traditionalvaluationsnapshot',
            name='refresh_run_key',
            field=models.CharField(default='legacy', max_length=64),
        ),
        migrations.RemoveConstraint(
            model_name='traditionalvaluationsnapshot',
            name='tv_snapshot_identity_uniq',
        ),
        migrations.AddConstraint(
            model_name='traditionalvaluationsnapshot',
            constraint=models.UniqueConstraint(
                fields=(
                    'security', 'asof_date', 'source_trade_date', 'report_type',
                    'financial_end_date', 'profit_bucket', 'valuation_variant',
                    'parameter_version', 'valuation_engine_version', 'refresh_run_key',
                ),
                name='tv_snapshot_identity_run_uniq',
            ),
        ),
    ]