from django.db import migrations, models
import django.db.models.deletion


def backfill_latest_snapshots(apps, schema_editor):
    Snapshot = apps.get_model("prediction", "StockValuationSnapshot")
    SnapshotLatest = apps.get_model("prediction", "StockValuationSnapshotLatest")

    SnapshotLatest.objects.all().delete()

    rows = (
        Snapshot.objects.all()
        .order_by(
            "ts_code",
            "market",
            "valuation_method",
            "valuation_variant",
            "-trade_date",
            "-updated_at",
            "-id",
        )
    )

    latest_objects = []
    seen_keys = set()
    for row in rows.iterator(chunk_size=2000):
        key = (row.ts_code, row.market, row.valuation_method, row.valuation_variant)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        latest_objects.append(
            SnapshotLatest(
                corporation_id=row.corporation_id,
                ts_code=row.ts_code,
                latest_trade_date=row.trade_date,
                market=row.market,
                valuation_method=row.valuation_method,
                valuation_variant=row.valuation_variant,
                valuation_price=row.valuation_price,
                valuation_market_cap=row.valuation_market_cap,
                source=row.source,
                industry_level=row.industry_level,
                industry_code=row.industry_code,
                industry_name=row.industry_name,
                compare_group=row.compare_group,
                match_score=row.match_score,
                profit_data_source=row.profit_data_source,
                profit_report_end_date=row.profit_report_end_date,
                profit_report_type=row.profit_report_type,
                express_end_date=row.express_end_date,
                express_ann_date=row.express_ann_date,
                express_apply_reason=row.express_apply_reason,
                express_block_reason=row.express_block_reason,
                strict_express_match=row.strict_express_match,
                express_max_age_days=row.express_max_age_days,
            )
        )

    if latest_objects:
        SnapshotLatest.objects.bulk_create(latest_objects, batch_size=2000)


def noop_reverse(_apps, _schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("datastore", "0001_initial"),
        ("prediction", "0011_stockvaluationsnapshot_multi_industry_variants"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockValuationSnapshotLatest",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ts_code", models.CharField(db_index=True, max_length=10, verbose_name="交易代码")),
                ("latest_trade_date", models.DateField(db_index=True, verbose_name="最新交易日")),
                ("market", models.CharField(db_index=True, default="CN", max_length=10, verbose_name="市场")),
                ("valuation_method", models.CharField(db_index=True, max_length=32, verbose_name="估值方法")),
                (
                    "valuation_variant",
                    models.CharField(
                        db_index=True,
                        default="default",
                        help_text="用于区分同一估值方法下的多行业匹配结果",
                        max_length=128,
                        verbose_name="估值变体键",
                    ),
                ),
                (
                    "valuation_price",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True, verbose_name="估值价格"),
                ),
                (
                    "valuation_market_cap",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="估值对应的股权价值，单位：元",
                        max_digits=24,
                        null=True,
                        verbose_name="估值市值",
                    ),
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
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text="如 express_vip / express_vip_blended / fina_indicator_income",
                        max_length=64,
                        null=True,
                        verbose_name="利润口径来源",
                    ),
                ),
                (
                    "profit_report_end_date",
                    models.DateField(
                        blank=True,
                        db_index=True,
                        help_text="用于估值时实际采用的报告期末日期",
                        null=True,
                        verbose_name="利润口径报告期",
                    ),
                ),
                (
                    "profit_report_type",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text="Q1 / H1 / Q3 / ANNUAL / OTHER",
                        max_length=16,
                        null=True,
                        verbose_name="利润口径报告类型",
                    ),
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
                (
                    "strict_express_match",
                    models.BooleanField(blank=True, null=True, verbose_name="是否启用快报严格匹配"),
                ),
                (
                    "express_max_age_days",
                    models.IntegerField(blank=True, null=True, verbose_name="快报时效窗口(天)"),
                ),
                (
                    "corporation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_valuation_snapshots_latest",
                        to="datastore.corporation",
                    ),
                ),
            ],
            options={
                "verbose_name": "估值最新快照",
                "verbose_name_plural": "估值最新快照",
                "ordering": ["ts_code"],
                "unique_together": {("ts_code", "market", "valuation_method", "valuation_variant")},
            },
        ),
        migrations.AddIndex(
            model_name="stockvaluationsnapshotlatest",
            index=models.Index(fields=["market", "latest_trade_date", "valuation_method"], name="prediction_s_market_b1ce11_idx"),
        ),
        migrations.AddIndex(
            model_name="stockvaluationsnapshotlatest",
            index=models.Index(fields=["market", "ts_code"], name="prediction_s_market_4bb834_idx"),
        ),
        migrations.RunPython(backfill_latest_snapshots, noop_reverse),
    ]
