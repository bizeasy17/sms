from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("datastore", "0011_corporation_sw_l3_fields"),
        ("prediction", "0013_stockvaluationsnapshot_profit_report_ann_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockValuationSnapshotHistory",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("archived_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "archive_reason",
                    models.CharField(db_index=True, default="upsert_replace", max_length=32, verbose_name="归档原因"),
                ),
                (
                    "source_snapshot_id",
                    models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="来源快照ID"),
                ),
                ("snapshot_created_at", models.DateTimeField(blank=True, null=True, verbose_name="来源创建时间")),
                ("snapshot_updated_at", models.DateTimeField(blank=True, null=True, verbose_name="来源更新时间")),
                ("ts_code", models.CharField(db_index=True, max_length=10, verbose_name="交易代码")),
                ("trade_date", models.DateField(db_index=True, verbose_name="交易日")),
                ("market", models.CharField(db_index=True, default="CN", max_length=10, verbose_name="市场")),
                ("valuation_method", models.CharField(db_index=True, max_length=32, verbose_name="估值方法")),
                (
                    "valuation_variant",
                    models.CharField(db_index=True, default="default", max_length=128, verbose_name="估值变体键"),
                ),
                (
                    "valuation_price",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True, verbose_name="估值价格"),
                ),
                (
                    "valuation_market_cap",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=24, null=True, verbose_name="估值市值"),
                ),
                ("source", models.CharField(default="live_compute", max_length=32, verbose_name="来源")),
                (
                    "industry_level",
                    models.CharField(blank=True, db_index=True, max_length=16, null=True, verbose_name="行业层级"),
                ),
                (
                    "industry_code",
                    models.CharField(blank=True, db_index=True, max_length=32, null=True, verbose_name="行业编码"),
                ),
                ("industry_name", models.CharField(blank=True, max_length=128, null=True, verbose_name="行业名称")),
                (
                    "compare_group",
                    models.CharField(blank=True, db_index=True, max_length=32, null=True, verbose_name="估值对比组"),
                ),
                (
                    "match_score",
                    models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name="行业匹配得分"),
                ),
                (
                    "profit_data_source",
                    models.CharField(blank=True, db_index=True, max_length=64, null=True, verbose_name="利润口径来源"),
                ),
                (
                    "profit_report_end_date",
                    models.DateField(blank=True, db_index=True, null=True, verbose_name="利润口径报告期"),
                ),
                (
                    "profit_report_ann_date",
                    models.DateField(blank=True, db_index=True, null=True, verbose_name="利润口径公告日"),
                ),
                (
                    "profit_report_type",
                    models.CharField(blank=True, db_index=True, max_length=16, null=True, verbose_name="利润口径报告类型"),
                ),
                ("express_end_date", models.DateField(blank=True, db_index=True, null=True, verbose_name="快报报告期")),
                ("express_ann_date", models.DateField(blank=True, db_index=True, null=True, verbose_name="快报公告日")),
                (
                    "express_apply_reason",
                    models.CharField(blank=True, db_index=True, max_length=64, null=True, verbose_name="快报应用原因"),
                ),
                (
                    "express_block_reason",
                    models.CharField(blank=True, db_index=True, max_length=64, null=True, verbose_name="快报拦截原因"),
                ),
                ("strict_express_match", models.BooleanField(blank=True, null=True, verbose_name="是否启用快报严格匹配")),
                ("express_max_age_days", models.IntegerField(blank=True, null=True, verbose_name="快报时效窗口(天)")),
                (
                    "corporation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_valuation_snapshot_histories",
                        to="datastore.corporation",
                    ),
                ),
            ],
            options={
                "verbose_name": "估值快照历史",
                "verbose_name_plural": "估值快照历史",
                "ordering": ["-archived_at", "-trade_date", "ts_code"],
            },
        ),
        migrations.AddIndex(
            model_name="stockvaluationsnapshothistory",
            index=models.Index(fields=["ts_code", "trade_date", "market", "valuation_method"], name="prediction_s_ts_cod_6bfca1_idx"),
        ),
        migrations.AddIndex(
            model_name="stockvaluationsnapshothistory",
            index=models.Index(fields=["ts_code", "profit_report_end_date", "valuation_method"], name="prediction_s_ts_cod_32002e_idx"),
        ),
        migrations.AddIndex(
            model_name="stockvaluationsnapshothistory",
            index=models.Index(fields=["market", "archived_at"], name="prediction_s_market_5e2e4a_idx"),
        ),
    ]
