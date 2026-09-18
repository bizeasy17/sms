from uuid import uuid4

from django.db import migrations, models


def ensure_snapshot_run_keys(apps, schema_editor):
    Snapshot = apps.get_model('predictive_valuation', 'PredictiveValuationSnapshot')
    seen = set()
    for snapshot in Snapshot.objects.order_by('id').iterator():
        run_key = str(snapshot.run_key or '').strip()
        if not run_key or run_key in seen:
            run_key = uuid4().hex[:32]
            snapshot.run_key = run_key
            snapshot.save(update_fields=['run_key'])
        seen.add(run_key)


class Migration(migrations.Migration):

    dependencies = [
        ('predictive_valuation', '0006_predictivevaluationeventstate_scope_key_and_more'),
    ]

    operations = [
        migrations.RunPython(ensure_snapshot_run_keys, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='predictivevaluationsnapshot',
            name='pv_snapshot_uniq',
        ),
        migrations.AddConstraint(
            model_name='predictivevaluationsnapshot',
            constraint=models.UniqueConstraint(
                fields=('security', 'report_type', 'asof_date', 'run_key'),
                name='pv_snapshot_uniq',
            ),
        ),
    ]