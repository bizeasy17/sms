from django.db import migrations, models


def _backfill_history_financial_period(apps, _schema_editor):
    History = apps.get_model("earnings_forecast", "EarningsSignalSnapshotHistory")
    for row in History.objects.all().iterator(chunk_size=500):
        raw = row.raw_result or {}
        if not isinstance(raw, dict):
            raw = {}

        raw_report_type = str(
            raw.get("financial_report_type")
            or raw.get("latest_available_report_type")
            or row.report_type
            or "UNKNOWN"
        ).strip().upper()
        row.financial_report_type = (raw_report_type[:16] if raw_report_type else "UNKNOWN") or "UNKNOWN"
        row.financial_ann_date = str(raw.get("financial_ann_date") or "").strip()
        row.financial_end_date = str(raw.get("financial_end_date") or "").strip()

        fiscal_year = raw.get("financial_fiscal_year")
        try:
            row.financial_fiscal_year = int(fiscal_year) if fiscal_year not in (None, "") else None
        except (TypeError, ValueError):
            row.financial_fiscal_year = None

        row.save(
            update_fields=[
                "financial_report_type",
                "financial_ann_date",
                "financial_end_date",
                "financial_fiscal_year",
            ]
        )


def _noop_reverse(_apps, _schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("earnings_forecast", "0011_snapshot_report_type_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="financial_ann_date",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="financial_end_date",
            field=models.CharField(blank=True, db_index=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="financial_fiscal_year",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="earningssignalsnapshothistory",
            name="financial_report_type",
            field=models.CharField(blank=True, db_index=True, default="UNKNOWN", max_length=16),
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshothistory",
            index=models.Index(fields=["ts_code", "financial_fiscal_year", "financial_report_type"], name="idx_esh_code_fy_rt"),
        ),
        migrations.AddIndex(
            model_name="earningssignalsnapshothistory",
            index=models.Index(fields=["financial_fiscal_year", "financial_report_type", "created_at"], name="idx_esh_fy_rt_ct"),
        ),
        migrations.RunPython(_backfill_history_financial_period, _noop_reverse),
    ]