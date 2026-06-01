from django.db import migrations, models


def backfill_profit_report_ann_date(apps, schema_editor):
    Snapshot = apps.get_model("prediction", "StockValuationSnapshot")
    SnapshotLatest = apps.get_model("prediction", "StockValuationSnapshotLatest")

    Snapshot.objects.filter(
        profit_report_ann_date__isnull=True,
        express_ann_date__isnull=False,
    ).update(profit_report_ann_date=models.F("express_ann_date"))

    SnapshotLatest.objects.filter(
        profit_report_ann_date__isnull=True,
        express_ann_date__isnull=False,
    ).update(profit_report_ann_date=models.F("express_ann_date"))


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0012_stockvaluationsnapshotlatest"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="profit_report_ann_date",
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text="用于估值时实际采用口径对应的公告日期",
                null=True,
                verbose_name="利润口径公告日",
            ),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshotlatest",
            name="profit_report_ann_date",
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text="用于估值时实际采用口径对应的公告日期",
                null=True,
                verbose_name="利润口径公告日",
            ),
        ),
        migrations.RunPython(backfill_profit_report_ann_date, noop_reverse),
    ]
