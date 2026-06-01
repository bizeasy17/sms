from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0010_stockvaluationsnapshot_profit_trace_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="valuation_variant",
            field=models.CharField(
                db_index=True,
                default="default",
                help_text="用于区分同一估值方法下的多行业匹配结果",
                max_length=128,
                verbose_name="估值变体键",
            ),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="industry_level",
            field=models.CharField(blank=True, db_index=True, max_length=16, null=True, verbose_name="行业层级"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="industry_code",
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True, verbose_name="行业编码"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="industry_name",
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name="行业名称"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="compare_group",
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True, verbose_name="估值对比组"),
        ),
        migrations.AddField(
            model_name="stockvaluationsnapshot",
            name="match_score",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                max_digits=10,
                null=True,
                verbose_name="行业匹配得分",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="stockvaluationsnapshot",
            unique_together={(
                "ts_code",
                "trade_date",
                "market",
                "valuation_method",
                "valuation_variant",
            )},
        ),
    ]
