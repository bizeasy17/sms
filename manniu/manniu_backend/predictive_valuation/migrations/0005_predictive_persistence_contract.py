from django.db import migrations, models


def backfill_report_identity(apps, schema_editor):
    Snapshot = apps.get_model('predictive_valuation', 'PredictiveValuationSnapshot')
    Current = apps.get_model('predictive_valuation', 'PredictiveValuationCurrent')

    snapshots = list(Snapshot.objects.order_by('security_id', 'report_type', 'asof_date', '-created_at', '-id'))
    retained = {}
    duplicate_ids = []
    for snapshot in snapshots:
        report_type = snapshot.report_type or snapshot.financial_report_type or 'FUSION'
        if snapshot.report_type != report_type:
            snapshot.report_type = report_type
            snapshot.save(update_fields=['report_type'])
        key = (snapshot.security_id, report_type, snapshot.asof_date)
        if key in retained:
            duplicate_ids.append(snapshot.id)
        else:
            retained[key] = snapshot.id

    for current in Current.objects.all().iterator():
        report_type = current.report_type
        if not report_type:
            snapshot = Snapshot.objects.filter(pk=current.snapshot_id).first()
            report_type = (snapshot.report_type if snapshot else '') or 'FUSION'
            current.report_type = report_type
            current.save(update_fields=['report_type'])

    for duplicate_id in duplicate_ids:
        duplicate = Snapshot.objects.filter(pk=duplicate_id).first()
        if duplicate is None:
            continue
        key = (duplicate.security_id, duplicate.report_type, duplicate.asof_date)
        replacement_id = retained[key]
        Current.objects.filter(snapshot_id=duplicate_id).update(snapshot_id=replacement_id)
        duplicate.delete()

    seen_current_keys = set()
    for current in Current.objects.order_by('security_id', 'report_type', '-updated_at', '-id'):
        key = (current.security_id, current.report_type)
        if key in seen_current_keys:
            current.delete()
        else:
            seen_current_keys.add(key)


class Migration(migrations.Migration):
    dependencies = [
        ('predictive_valuation', '0004_predictive_tiered_template'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='predictivevaluationcurrent',
            name='pv_current_uniq',
        ),
        migrations.RemoveConstraint(
            model_name='predictivevaluationsnapshot',
            name='pv_snapshot_uniq',
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='action',
            field=models.CharField(default='HOLD', max_length=16),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='artifact_hash',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='batch_key',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='explain',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='feature_contract_version',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='feature_data_source',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='last_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='raw_result',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='refresh_detail',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='refresh_reason',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='report_type',
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='target_market_cap',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='target_price_high',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='target_price_low',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='target_return_high_pct',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='target_return_low_pct',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='triggered_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationcurrent',
            name='up_probability',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='action',
            field=models.CharField(default='HOLD', max_length=16),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='anchor_mode',
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='backfill_run_id',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='batch_key',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='financial_fiscal_year',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='is_backfill',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='last_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='refresh_detail',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='refresh_reason',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='report_type',
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='run_key',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='snapshot_source',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='predictivevaluationsnapshot',
            name='triggered_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_report_identity, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='predictivevaluationsnapshot',
            constraint=models.UniqueConstraint(fields=('security', 'report_type', 'asof_date'), name='pv_snapshot_uniq'),
        ),
        migrations.AddConstraint(
            model_name='predictivevaluationcurrent',
            constraint=models.UniqueConstraint(fields=('security', 'report_type'), name='pv_current_uniq'),
        ),
    ]