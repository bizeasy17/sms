from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ValuationRiskSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ts_code', models.CharField(db_index=True, max_length=10, verbose_name='交易代码')),
                ('trade_date', models.DateField(db_index=True, verbose_name='交易日')),
                ('market', models.CharField(db_index=True, default='CN', max_length=10, verbose_name='市场')),
                ('valuation_variant', models.CharField(db_index=True, default='default', max_length=128, verbose_name='估值变体键')),
                ('profit_report_type', models.CharField(blank=True, db_index=True, max_length=16, null=True, verbose_name='利润口径报告类型')),
                ('profit_report_end_date', models.DateField(blank=True, db_index=True, null=True, verbose_name='利润口径报告期')),
                ('profit_report_ann_date', models.DateField(blank=True, db_index=True, null=True, verbose_name='利润口径公告日')),
                ('profit_data_source', models.CharField(blank=True, db_index=True, max_length=64, null=True, verbose_name='利润口径来源')),
                ('risk_score', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name='风险总分')),
                ('risk_level', models.CharField(db_index=True, default='UNKNOWN', max_length=16, verbose_name='风险等级')),
                ('confidence', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name='置信度')),
                ('summary', models.TextField(blank=True, default='', verbose_name='风险摘要')),
                ('engine_version', models.CharField(db_index=True, default='v0_scaffold', max_length=32, verbose_name='引擎版本')),
                ('status', models.CharField(db_index=True, default='PENDING', max_length=16, verbose_name='计算状态')),
                ('metadata', models.JSONField(blank=True, default=dict, verbose_name='扩展元数据')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': '估值风险快照',
                'verbose_name_plural': '估值风险快照',
                'ordering': ['-trade_date', 'ts_code'],
                'unique_together': {('ts_code', 'trade_date', 'market', 'valuation_variant', 'profit_report_type')},
            },
        ),
        migrations.CreateModel(
            name='ValuationRiskFactor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('dimension', models.CharField(db_index=True, max_length=32, verbose_name='风险维度')),
                ('factor_code', models.CharField(db_index=True, max_length=64, verbose_name='因子编码')),
                ('factor_name', models.CharField(max_length=128, verbose_name='因子名称')),
                ('severity', models.CharField(db_index=True, default='INFO', max_length=16, verbose_name='严重级别')),
                ('factor_score', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name='因子分值')),
                ('factor_value', models.CharField(blank=True, default='', max_length=128, verbose_name='因子值')),
                ('threshold', models.CharField(blank=True, default='', max_length=128, verbose_name='阈值')),
                ('reason', models.TextField(blank=True, default='', verbose_name='触发原因')),
                ('is_triggered', models.BooleanField(db_index=True, default=False, verbose_name='是否触发')),
                ('sort_order', models.IntegerField(default=0, verbose_name='排序')),
                ('payload', models.JSONField(blank=True, default=dict, verbose_name='扩展载荷')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('snapshot', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='factors', to='valuation_risk.valuationrisksnapshot')),
            ],
            options={
                'verbose_name': '估值风险因子',
                'verbose_name_plural': '估值风险因子',
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='valuationrisksnapshot',
            index=models.Index(fields=['market', 'trade_date', 'risk_level'], name='valuation_ri_market__44bf45_idx'),
        ),
        migrations.AddIndex(
            model_name='valuationrisksnapshot',
            index=models.Index(fields=['ts_code', 'profit_report_end_date'], name='valuation_ri_ts_code_9e92d7_idx'),
        ),
        migrations.AddIndex(
            model_name='valuationriskfactor',
            index=models.Index(fields=['dimension', 'severity'], name='valuation_ri_dimensi_69fbb9_idx'),
        ),
        migrations.AddIndex(
            model_name='valuationriskfactor',
            index=models.Index(fields=['factor_code', 'is_triggered'], name='valuation_ri_factor__6a8893_idx'),
        ),
    ]