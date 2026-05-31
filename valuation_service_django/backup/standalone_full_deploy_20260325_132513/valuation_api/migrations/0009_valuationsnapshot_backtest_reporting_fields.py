from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("valuation_api", "0008_stockexpressvip"),
    ]

    operations = [
        migrations.AddField(
            model_name="valuationsnapshot",
            name="compare_group",
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="express_ann_date",
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="express_apply_reason",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="express_block_reason",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="express_end_date",
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="express_max_age_days",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="industry_code",
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="industry_level",
            field=models.CharField(blank=True, db_index=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="industry_name",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="match_score",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="profit_data_source",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="profit_report_end_date",
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="profit_report_type",
            field=models.CharField(blank=True, db_index=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="valuationsnapshot",
            name="strict_express_match",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
