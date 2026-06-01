from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0013_earningsbacktestrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="anchor_mode",
            field=models.CharField(blank=True, db_index=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="backfill_run_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="is_backfill",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="market_regime",
            field=models.CharField(blank=True, db_index=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="run_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="snapshot_source",
            field=models.CharField(blank=True, db_index=True, default="", max_length=32),
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshothistory",
            index=models.Index(fields=["asof_date", "report_type", "created_at"], name="idx_esh_date_rt_ct"),
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshothistory",
            index=models.Index(fields=["is_backfill", "created_at"], name="idx_esh_bf_ct"),
        ),
    ]
