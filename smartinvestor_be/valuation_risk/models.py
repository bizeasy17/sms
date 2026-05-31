from django.db import models


class ValuationRiskSnapshot(models.Model):
    ts_code = models.CharField('交易代码', max_length=10, db_index=True)
    trade_date = models.DateField('交易日', db_index=True)
    market = models.CharField('市场', max_length=10, default='CN', db_index=True)
    valuation_variant = models.CharField('估值变体键', max_length=128, default='default', db_index=True)
    profit_report_type = models.CharField('利润口径报告类型', max_length=16, blank=True, null=True, db_index=True)
    profit_report_end_date = models.DateField('利润口径报告期', blank=True, null=True, db_index=True)
    profit_report_ann_date = models.DateField('利润口径公告日', blank=True, null=True, db_index=True)
    profit_data_source = models.CharField('利润口径来源', max_length=64, blank=True, null=True, db_index=True)
    risk_score = models.DecimalField('风险总分', max_digits=10, decimal_places=4, blank=True, null=True)
    risk_level = models.CharField('风险等级', max_length=16, default='UNKNOWN', db_index=True)
    confidence = models.DecimalField('置信度', max_digits=10, decimal_places=4, blank=True, null=True)
    summary = models.TextField('风险摘要', blank=True, default='')
    engine_version = models.CharField('引擎版本', max_length=32, default='v0_scaffold', db_index=True)
    status = models.CharField('计算状态', max_length=16, default='PENDING', db_index=True)
    metadata = models.JSONField('扩展元数据', default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-trade_date', 'ts_code']
        verbose_name = '估值风险快照'
        verbose_name_plural = verbose_name
        unique_together = ('ts_code', 'trade_date', 'market', 'valuation_variant', 'profit_report_type')
        indexes = [
            models.Index(fields=['market', 'trade_date', 'risk_level']),
            models.Index(fields=['ts_code', 'profit_report_end_date']),
        ]

    def __str__(self):
        return f'{self.ts_code} {self.trade_date} {self.profit_report_type or "LATEST"} {self.valuation_variant}'


class ValuationRiskFactor(models.Model):
    snapshot = models.ForeignKey(
        ValuationRiskSnapshot,
        related_name='factors',
        on_delete=models.CASCADE,
    )
    dimension = models.CharField('风险维度', max_length=32, db_index=True)
    factor_code = models.CharField('因子编码', max_length=64, db_index=True)
    factor_name = models.CharField('因子名称', max_length=128)
    severity = models.CharField('严重级别', max_length=16, default='INFO', db_index=True)
    factor_score = models.DecimalField('因子分值', max_digits=10, decimal_places=4, blank=True, null=True)
    factor_value = models.CharField('因子值', max_length=128, blank=True, default='')
    threshold = models.CharField('阈值', max_length=128, blank=True, default='')
    reason = models.TextField('触发原因', blank=True, default='')
    is_triggered = models.BooleanField('是否触发', default=False, db_index=True)
    sort_order = models.IntegerField('排序', default=0)
    payload = models.JSONField('扩展载荷', default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = '估值风险因子'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['dimension', 'severity']),
            models.Index(fields=['factor_code', 'is_triggered']),
        ]

    def __str__(self):
        return self.factor_code
