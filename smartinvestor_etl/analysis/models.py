from django.db import models
from django.utils.translation import gettext_lazy as _
from stockdata.models import Corporation

# Create your models here.
class StockTopBottomHistory(models.Model):
    """
    ts_code	str	股票代码
    trade_date=str	交易日期
    """
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # ForeignKey to Corporation model
    corporation = models.ForeignKey(
        Corporation,
        related_name="top_bottom",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"))
    close = models.FloatField(_("收盘价"), blank=True, null=True) # need to add close price
    freq = models.CharField(_("周期"), max_length=5, default="D")
    asset = models.CharField(_("股票或指数"), max_length=1, default="E")

    # 涨幅统计
    period = models.IntegerField(_("一个周期长度"), blank=True, null=True,)
    
    pct_gain_1p = models.FloatField(_("一个周期涨幅"), blank=True, null=True)
    pct_gain_1p_date = models.DateField(_("一个周期涨幅匹配日期"), blank=True, null=True)
    pct_gain_2p = models.FloatField(_("两个周期涨幅"), blank=True, null=True)
    pct_gain_2p_date = models.DateField(_("两个周期涨幅匹配日期"), blank=True, null=True)
    pct_gain_3p = models.FloatField(_("三个周期涨幅"), blank=True, null=True)
    pct_gain_3p_date = models.DateField(_("三个周期涨幅匹配日期"), blank=True, null=True)
    pct_gain_5p = models.FloatField(_("五个周期涨幅"), blank=True, null=True)
    pct_gain_5p_date = models.DateField(_("五个周期涨幅匹配日期"), blank=True, null=True)

    # 跌幅统计
    pct_loss_1p = models.FloatField(_("一个周期跌幅"), blank=True, null=True)
    pct_loss_1p_date = models.DateField(_("一个周期跌幅匹配日期"), blank=True, null=True)
    pct_loss_2p = models.FloatField(_("两个周期跌幅"), blank=True, null=True)
    pct_loss_2p_date = models.DateField(_("两个周期跌幅匹配日期"), blank=True, null=True)
    pct_loss_3p = models.FloatField(_("三个周期跌幅"), blank=True, null=True)
    pct_loss_3p_date = models.DateField(_("三个周期跌幅匹配日期"), blank=True, null=True)
    pct_loss_5p = models.FloatField(_("五个周期跌幅"), blank=True, null=True)
    pct_loss_5p_date = models.DateField(_("五个周期跌幅匹配日期"), blank=True, null=True)

    # 波峰波谷相关
    top_or_bottom = models.CharField(_("scipy峰谷"), max_length=1, blank=True, null=True, default="N")
    top_or_bottom_optimized = models.CharField(_("优化校验峰谷"), max_length=25, blank=True, null=True)
    top_or_bottom_stat = models.CharField(_("统计峰谷"), max_length=1, blank=True, null=True)
    top_or_bottom_stat_optimized = models.CharField(_("优化统计峰谷"), max_length=25, blank=True, null=True)
    top_bottom_volatility_stat = models.CharField(_("统计涨跌幅大的峰谷"), max_length=1, blank=True, null=True)
    top_bottom_volatility_optimized = models.CharField(_("优化的涨跌幅大的峰谷"), max_length=25, blank=True, null=True)
    
    def __str__(self):
        return self.ts_code

    class Meta:
        ordering = ["trade_date"]
        verbose_name = _("历史高低点")
        unique_together = ("trade_date", "ts_code", "freq", "top_or_bottom")
        verbose_name_plural = verbose_name
        get_latest_by = "id"
        
        
# Create your models here.
class StockGainLossQuantile(models.Model):
    """
    ts_code    str 股票代码
    trade_date str 交易日期
    """
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_gain_loss_quantiles",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    freq = models.CharField(_("交易周期"), max_length=5, default="D")
    quantile = models.FloatField(_("分位数"), blank=True, null=True)

    # 涨幅统计
    pct_gain_1p = models.FloatField(_("1个周期涨幅"), blank=True, null=True)
    pct_gain_2p = models.FloatField(_("2个周期涨幅"), blank=True, null=True)
    pct_gain_3p = models.FloatField(_("3个周期涨幅"), blank=True, null=True)
    pct_gain_5p = models.FloatField(_("5个周期涨幅"), blank=True, null=True)

    # 跌幅统计
    pct_loss_1p = models.FloatField(_("1个周期跌幅"), blank=True, null=True)
    pct_loss_2p = models.FloatField(_("2个周期跌幅"), blank=True, null=True)
    pct_loss_3p = models.FloatField(_("3个周期跌幅"), blank=True, null=True)
    pct_loss_5p = models.FloatField(_("5个周期跌幅"), blank=True, null=True)

    top_or_bottom = models.CharField(_("顶底"), max_length=1, blank=True, null=True, default="B")
    period = models.IntegerField(_("一个周期跨度"), blank=True, null=True, default=34)

    def is_top(self):
        return self.top_or_bottom == "T"

    def is_bottom(self):
        return self.top_or_bottom == "B"

    @property
    def corporation_name(self):
        return self.corporation.name if self.corporation else None

    def __str__(self):
        return f"{self.ts_code} {self.freq} {self.quantile} {self.top_or_bottom}"

    class Meta:
        ordering = ["ts_code"]
        verbose_name = _("分位数高低点")
        verbose_name_plural = verbose_name
        get_latest_by = "id"