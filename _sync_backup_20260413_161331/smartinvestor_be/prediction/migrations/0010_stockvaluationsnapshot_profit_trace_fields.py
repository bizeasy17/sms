from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0009_annualoutlooksnapshot_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="profit_data_source",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="如 express_vip / express_vip_blended / fina_indicator_income",
                max_length=64,
                null=True,
                verbose_name="利润口径来源",
            ),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="profit_report_end_date",
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text="用于估值时实际采用的报告期末日期",
                null=True,
                verbose_name="利润口径报告期",
            ),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="profit_report_type",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Q1 / H1 / Q3 / ANNUAL / OTHER",
                max_length=16,
                null=True,
                verbose_name="利润口径报告类型",
            ),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="express_end_date",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="快报报告期"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="express_ann_date",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="快报公告日"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="express_apply_reason",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, verbose_name="快报应用原因"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="express_block_reason",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, verbose_name="快报拦截原因"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="strict_express_match",
            field=models.BooleanField(blank=True, null=True, verbose_name="是否启用快报严格匹配"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="express_max_age_days",
            field=models.IntegerField(blank=True, null=True, verbose_name="快报时效窗口(天)"),
        ),
    ]
