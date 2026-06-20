from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0010_snapshot_quantitative_targets"),
    ]

    operations = [
        migrations.AddField(
            model_name="earningssignalsnapshot",
            name="report_type",
            field=models.CharField(blank=True, db_index=True, default="UNKNOWN", max_length=16),
        ),
        migrations.AlterField(
            model_name="earningssignalsnapshot",
            name="ts_code",
            field=models.CharField(db_index=True, max_length=16),
        ),
        migrations.AddConstraint(
            model_name="earningssignalsnapshot",
            constraint=models.UniqueConstraint(fields=("ts_code", "report_type"), name="uq_earn_sig_code_rt"),
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshot",
            index=models.Index(fields=["ts_code", "report_type", "updated_at"], name="idx_earn_sig_code_rt_upd"),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="report_type",
            field=models.CharField(blank=True, db_index=True, default="UNKNOWN", max_length=16),
        ),
        migrations.RemoveIndex(
            model_name="earningssignalsnapshothistory",
            name="idx_esh_code_ver_dt",
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshothistory",
            index=models.Index(fields=["ts_code", "report_type", "model_version", "asof_date"], name="idx_esh_code_rt_ver_dt"),
        ),
    ]
