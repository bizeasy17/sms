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
        unique_together = ("trade_date", "ts_code", "freq", "top_or_bottom", "period")
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
 
       

class StockFeatures(models.Model):
    """股票特征历史数据（交易、基本面、成本等合并）"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_features",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("公司"),
        help_text=_("关联的股票公司信息"),
    )
    ts_code = models.CharField(
        _("交易代码"),
        max_length=10,
        db_index=True,
        help_text=_("如 000001.SZ"),
    )
    trade_date = models.DateField(
        _("交易日"),
        db_index=True,
        help_text=_("如 2020-05-05"),
    )

    # 交易数据
    open = models.DecimalField(
        _("开盘价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    high = models.DecimalField(
        _("最高价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    low = models.DecimalField(
        _("最低价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pre_close = models.DecimalField(
        _("前日收盘价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close = models.DecimalField(
        _("收盘价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    change = models.DecimalField(
        _("价格变化"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pct_change = models.DecimalField(
        _("价格变化%"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol = models.BigIntegerField(
        _("交易量"),
        blank=True,
        null=True,
        help_text=_("单位：股"),
    )
    pct_vol_chg = models.DecimalField(
        _("交易量变化%"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_30d_10pct = models.DecimalField(
        _("30日内统计10%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_30d_25pct = models.DecimalField(
        _("30日内统计25%的vol_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_30d_50pct = models.DecimalField(
        _("30日内统计50%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_30d_75pct = models.DecimalField(
        _("30日内统计75%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_30d_90pct = models.DecimalField(
        _("30日内统计90%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_60d_10pct = models.DecimalField(
        _("60日内统计10%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_60d_25pct = models.DecimalField(
        _("60日内统计25%的vol_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_60d_50pct = models.DecimalField(
        _("60日内统计50%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_60d_75pct = models.DecimalField(
        _("60日内统计75%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_60d_90pct = models.DecimalField(
        _("60日内统计90%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_90d_10pct = models.DecimalField(
        _("90日内统计10%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_90d_25pct = models.DecimalField(
        _("90日内统计25%的vol_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_90d_50pct = models.DecimalField(
        _("90日内统计50%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_90d_75pct = models.DecimalField(
        _("90日内统计75%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_90d_90pct = models.DecimalField(
        _("90日内统计90%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_120d_10pct = models.DecimalField(
        _("120日内统计10%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_120d_25pct = models.DecimalField(
        _("120日内统计25%的vol_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_120d_50pct = models.DecimalField(
        _("120日内统计50%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_120d_75pct = models.DecimalField(
        _("120日内统计75%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_120d_90pct = models.DecimalField(
        _("120日内统计90%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_200d_10pct = models.DecimalField(
        _("200日内统计10%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_200d_25pct = models.DecimalField(
        _("200日内统计25%的vol_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_200d_50pct = models.DecimalField(
        _("200日内统计50%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_200d_75pct = models.DecimalField(
        _("200日内统计75%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    vol_200d_90pct = models.DecimalField(
        _("200日内统计90%的vol_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount = models.DecimalField(
        _("金额"),
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("单位：元"),
    )
    amount_30d_10pct = models.DecimalField(
        _("30日内统计10%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_30d_25pct = models.DecimalField(
        _("30日低于25%统计的成交额_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_30d_50pct = models.DecimalField(
        _("30日内统计50%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_30d_75pct = models.DecimalField(
        _("30日内统计75%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_30d_90pct = models.DecimalField(
        _("30日内统计90%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_60d_10pct = models.DecimalField(
        _("60日内统计10%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_60d_25pct = models.DecimalField(
        _("60日低于25%统计的成交额_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_60d_50pct = models.DecimalField(
        _("60日内统计50%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_60d_75pct = models.DecimalField(
        _("60日内统计75%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_60d_90pct = models.DecimalField(
        _("60日内统计90%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_90d_10pct = models.DecimalField(
        _("90日内统计10%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_90d_25pct = models.DecimalField(
        _("90日低于25%统计的成交额_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_90d_50pct = models.DecimalField(
        _("90日内统计50%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_90d_75pct = models.DecimalField(
        _("90日内统计75%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_90d_90pct = models.DecimalField(
        _("90日内统计90%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_120d_10pct = models.DecimalField(
        _("120日内统计10%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_120d_25pct = models.DecimalField(
        _("120日低于25%统计的成交额_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_120d_50pct = models.DecimalField(
        _("120日内统计50%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_120d_75pct = models.DecimalField(
        _("120日内统计75%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_120d_90pct = models.DecimalField(
        _("120日内统计90%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_200d_10pct = models.DecimalField(
        _("200日内统计10%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_200d_25pct = models.DecimalField(
        _("200日低于25%统计的成交额_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_200d_50pct = models.DecimalField(
        _("200日内统计50%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_200d_75pct = models.DecimalField(
        _("200日内统计75%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    amount_200d_90pct = models.DecimalField(
        _("200日内统计90%的成交额_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    adj_factor = models.DecimalField(
        _("复权因子"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    # 复权价格
    open_hfq = models.DecimalField(
        _("开盘价_hfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    open_qfq = models.DecimalField(
        _("开盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_hfq = models.DecimalField(
        _("收盘价_hfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq = models.DecimalField(
        _("收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_30d_10pct = models.DecimalField(
        _("30日内统计10%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_30d_25pct = models.DecimalField(
        _("25日低于25%统计的收盘价_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_30d_50pct = models.DecimalField(
        _("30日内统计50%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_30d_75pct = models.DecimalField(
        _("30日内统计75%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_30d_90pct = models.DecimalField(
        _("30日内统计90%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_60d_10pct = models.DecimalField(
        _("60日内统计10%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_60d_25pct = models.DecimalField(
        _("60日低于25%统计的收盘价_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_60d_50pct = models.DecimalField(
        _("60日内统计50%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_60d_75pct = models.DecimalField(
        _("60日内统计75%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_60d_90pct = models.DecimalField(
        _("60日内统计90%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_90d_10pct = models.DecimalField(
        _("90日内统计10%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_90d_25pct = models.DecimalField(
        _("90日低于25%统计的收盘价_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_90d_50pct = models.DecimalField(
        _("90日内统计50%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_90d_75pct = models.DecimalField(
        _("90日内统计75%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_90d_90pct = models.DecimalField(
        _("90日内统计90%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_120d_10pct = models.DecimalField(
        _("120日内统计10%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_120d_25pct = models.DecimalField(
        _("120日低于25%统计的收盘价_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_120d_50pct = models.DecimalField(
        _("120日内统计50%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_120d_75pct = models.DecimalField(
        _("120日内统计75%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_120d_90pct = models.DecimalField(
        _("120日内统计90%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_200d_10pct = models.DecimalField(
        _("200日内统计10%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_200d_25pct = models.DecimalField(
        _("200日低于25%统计的收盘价_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_200d_50pct = models.DecimalField(
        _("200日内统计50%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_200d_75pct = models.DecimalField(
        _("200日内统计75%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    close_qfq_200d_90pct = models.DecimalField(
        _("200日内统计90%的收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    high_hfq = models.DecimalField(
        _("最高价_hfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    high_qfq = models.DecimalField(
        _("最高价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    low_hfq = models.DecimalField(
        _("最低价_hfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    low_qfq = models.DecimalField(
        _("最低价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pre_close_hfq = models.DecimalField(
        _("前日收盘价_hfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pre_close_qfq = models.DecimalField(
        _("前日收盘价_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    change_hfq = models.DecimalField(
        _("价格变化_hfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    change_qfq = models.DecimalField(
        _("价格变化_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pct_change_hfq = models.DecimalField(
        _("价格变化%_hfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pct_change_qfq = models.DecimalField(
        _("价格变化%_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma6 = models.DecimalField(
        _("MA6"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma10 = models.DecimalField(
        _("MA10"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma16 = models.DecimalField(
        _("MA16"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma25 = models.DecimalField(
        _("MA25"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma43 = models.DecimalField(
        _("MA43"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma60 = models.DecimalField(
        _("MA60"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma90 = models.DecimalField(
        _("MA90"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma120 = models.DecimalField(
        _("MA120"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma200 = models.DecimalField(
        _("MA200"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ma6_trend = models.DecimalField(
        _("MA6_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma10_trend = models.DecimalField(
        _("MA10_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma16_trend = models.DecimalField(
        _("MA16_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma25_trend = models.DecimalField(
        _("MA25_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma43_trend = models.DecimalField(
        _("MA43_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma60_trend = models.DecimalField(
        _("MA60_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma90_trend = models.DecimalField(
        _("MA90_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma120_trend = models.DecimalField(
        _("MA120_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    ma200_trend = models.DecimalField(
        _("MA200_trend"),
        max_digits=1,
        decimal_places=0,
        blank=True,
        null=True,
    )
    atr_6 = models.DecimalField(
        _("ATR_6"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    atr_10 = models.DecimalField(
        _("ATR_10"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    atr_14 = models.DecimalField(
        _("ATR_14"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    atr_20 = models.DecimalField(
        _("ATR_20"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    atr_25 = models.DecimalField(
        _("ATR_25"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volatility_ratio_6 = models.DecimalField(
        _("波动率比_6"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volatility_ratio_10 = models.DecimalField(
        _("波动率比_10"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volatility_ratio_14 = models.DecimalField(
        _("波动率比_14"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volatility_ratio_20 = models.DecimalField(
        _("波动率比_20"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volatility_ratio_25 = models.DecimalField(
        _("波动率比_25"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )

    # 技术指标
    macd_dif = models.DecimalField(
        _("MACD_DIF"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    macd_dea = models.DecimalField(
        _("MACD_DEA"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    macd = models.DecimalField(
        _("MACD"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    kdj_k = models.DecimalField(
        _("KDJ_K"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    kdj_d = models.DecimalField(
        _("KDJ_D"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    kdj_j = models.DecimalField(
        _("KDJ_J"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    rsi_6 = models.DecimalField(
        _("RSI_6"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    rsi_12 = models.DecimalField(
        _("RSI_12"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    rsi_24 = models.DecimalField(
        _("RSI_24"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    boll_upper = models.DecimalField(
        _("BOLL_UPPER"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    boll_mid = models.DecimalField(
        _("BOLL_MIDDLE"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    boll_lower = models.DecimalField(
        _("BOLL_LOWER"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    cci = models.DecimalField(
        _("CCI"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )

    # 基本面数据
    turnover_rate = models.DecimalField(
        _("换手率"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
        help_text=_("单位：%"),
    )
    turnover_rate_f = models.DecimalField(
        _("换手率(自由流通)"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_30d_10pct = models.DecimalField(
        _("30日低于10%统计的换手率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_30d_25pct = models.DecimalField(
        _("30日低于25%统计的换手率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_30d_50pct = models.DecimalField(
        _("30日内统计50%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_30d_75pct = models.DecimalField(
        _("30日内统计75%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_30d_90pct = models.DecimalField(
        _("30日内统计90%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_60d_10pct = models.DecimalField(
        _("60日内统计10%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_60d_25pct = models.DecimalField(
        _("60日低于25%统计的换手率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_60d_50pct = models.DecimalField(
        _("60日内统计50%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_60d_75pct = models.DecimalField(
        _("60日内统计75%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_60d_90pct = models.DecimalField(
        _("60日内统计90%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_90d_10pct = models.DecimalField(
        _("90日内统计10%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_90d_25pct = models.DecimalField(
        _("90日低于25%统计的换手率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_90d_50pct = models.DecimalField(
        _("90日内统计50%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_90d_75pct = models.DecimalField(
        _("90日内统计75%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_90d_90pct = models.DecimalField(
        _("90日内统计90%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_120d_10pct = models.DecimalField(
        _("120日内统计10%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_120d_25pct = models.DecimalField(
        _("120日低于25%统计的换手率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_120d_50pct = models.DecimalField(
        _("120日内统计50%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_120d_75pct = models.DecimalField(
        _("120日内统计75%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_120d_90pct = models.DecimalField(
        _("120日内统计90%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_200d_10pct = models.DecimalField(
        _("200日内统计10%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_200d_25pct = models.DecimalField(
        _("200日低于25%统计的换手率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_200d_50pct = models.DecimalField(
        _("200日内统计50%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_200d_75pct = models.DecimalField(
        _("200日内统计75%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    turnover_rate_f_200d_90pct = models.DecimalField(
        _("200日内统计90%的换手率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )   
    volume_ratio = models.DecimalField(
        _("量比"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_30d_10pct = models.DecimalField(
        _("30日低于10%统计的量比_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_30d_25pct = models.DecimalField(
        _("30日低于25%统计的量比_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_30d_50pct = models.DecimalField(
        _("30日内统计50%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_30d_75pct = models.DecimalField(
        _("30日内统计75%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_30d_90pct = models.DecimalField(
        _("30日内统计90%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_60d_10pct = models.DecimalField(
        _("60日内统计10%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_60d_25pct = models.DecimalField(
        _("60日低于25%统计的量比_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_60d_50pct = models.DecimalField(
        _("60日内统计50%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_60d_75pct = models.DecimalField(
        _("60日内统计75%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_60d_90pct = models.DecimalField(
        _("60日内统计90%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_90d_10pct = models.DecimalField(
        _("90日内统计10%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_90d_25pct = models.DecimalField(
        _("90日低于25%统计的量比_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_90d_50pct = models.DecimalField(
        _("90日内统计50%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_90d_75pct = models.DecimalField(
        _("90日内统计75%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_90d_90pct = models.DecimalField(
        _("90日内统计90%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_120d_10pct = models.DecimalField(
        _("120日内统计10%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_120d_25pct = models.DecimalField(
        _("120日低于25%统计的量比_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_120d_50pct = models.DecimalField(
        _("120日内统计50%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_120d_75pct = models.DecimalField(
        _("120日内统计75%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_120d_90pct = models.DecimalField(
        _("120日内统计90%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_200d_10pct = models.DecimalField(
        _("200日内统计10%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_200d_25pct = models.DecimalField(
        _("200日低于25%统计的量比_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_200d_50pct = models.DecimalField(
        _("200日内统计50%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_200d_75pct = models.DecimalField(
        _("200日内统计75%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    volume_ratio_200d_90pct = models.DecimalField(
        _("200日内统计90%的量比_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe = models.DecimalField(
        _("市盈率"),
        max_digits=16,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_30d_10pct = models.DecimalField(
        _("30日低于10%统计的市盈率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_30d_25pct = models.DecimalField(
        _("30日低于25%统计的市盈率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_30d_50pct = models.DecimalField(
        _("30日内统计50%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_30d_75pct = models.DecimalField(
        _("30日内统计75%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_30d_90pct = models.DecimalField(
        _("30日内统计90%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_60d_10pct = models.DecimalField(
        _("60日内统计10%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_60d_25pct = models.DecimalField(
        _("60日低于25%统计的市盈率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_60d_50pct = models.DecimalField(
        _("60日内统计50%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_60d_75pct = models.DecimalField(
        _("60日内统计75%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_60d_90pct = models.DecimalField(
        _("60日内统计90%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_90d_10pct = models.DecimalField(
        _("90日内统计10%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_90d_25pct = models.DecimalField(
        _("90日低于25%统计的市盈率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_90d_50pct = models.DecimalField(
        _("90日内统计50%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_90d_75pct = models.DecimalField(
        _("90日内统计75%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_90d_90pct = models.DecimalField(
        _("90日内统计90%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_120d_10pct = models.DecimalField(
        _("120日内统计10%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_120d_25pct = models.DecimalField(
        _("120日低于25%统计的市盈率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_120d_50pct = models.DecimalField(
        _("120日内统计50%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_120d_75pct = models.DecimalField(
        _("120日内统计75%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_120d_90pct = models.DecimalField(
        _("120日内统计90%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_200d_10pct = models.DecimalField(
        _("200日内统计10%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_200d_25pct = models.DecimalField(
        _("200日低于25%统计的市盈率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_200d_50pct = models.DecimalField(
        _("200日内统计50%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_200d_75pct = models.DecimalField(
        _("200日内统计75%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_200d_90pct = models.DecimalField(
        _("200日内统计90%的市盈率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pe_ttm = models.DecimalField(
        _("市盈率TTM"),
        max_digits=16,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb = models.DecimalField(
        _("市净率"),
        max_digits=16,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_30d_10pct = models.DecimalField(
        _("30日低于10%统计的市净率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_30d_25pct = models.DecimalField(
        _("30日低于25%统计的市净率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_30d_50pct = models.DecimalField(
        _("30日内统计50%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_30d_75pct = models.DecimalField(
        _("30日内统计75%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_30d_90pct = models.DecimalField(
        _("30日内统计90%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_60d_10pct = models.DecimalField(
        _("60日内统计10%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_60d_25pct = models.DecimalField(
        _("60日低于25%统计的市净率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_60d_50pct = models.DecimalField(
        _("60日内统计50%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_60d_75pct = models.DecimalField(
        _("60日内统计75%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_60d_90pct = models.DecimalField(
        _("60日内统计90%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_90d_10pct = models.DecimalField(
        _("90日内统计10%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_90d_25pct = models.DecimalField(
        _("90日低于25%统计的市净率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_90d_50pct = models.DecimalField(
        _("90日内统计50%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_90d_75pct = models.DecimalField(
        _("90日内统计75%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_90d_90pct = models.DecimalField(
        _("90日内统计90%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_120d_10pct = models.DecimalField(
        _("120日内统计10%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_120d_25pct = models.DecimalField(
        _("120日低于25%统计的市净率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_120d_50pct = models.DecimalField(
        _("120日内统计50%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_120d_75pct = models.DecimalField(
        _("120日内统计75%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_120d_90pct = models.DecimalField(
        _("120日内统计90%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_200d_10pct = models.DecimalField(
        _("200日内统计10%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_200d_25pct = models.DecimalField(
        _("200日低于25%统计的市净率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_200d_50pct = models.DecimalField(
        _("200日内统计50%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_200d_75pct = models.DecimalField(
        _("200日内统计75%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pb_200d_90pct = models.DecimalField(
        _("200日内统计90%的市净率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps = models.DecimalField(
        _("市销率"),
        max_digits=16,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_30d_10pct = models.DecimalField(
        _("30日低于10%统计的市销率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_30d_25pct = models.DecimalField(
        _("30日低于25%统计的市销率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_30d_50pct = models.DecimalField(
        _("30日内统计50%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_30d_75pct = models.DecimalField(
        _("30日内统计75%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_30d_90pct = models.DecimalField(
        _("30日内统计90%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_60d_10pct = models.DecimalField(
        _("60日内统计10%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_60d_25pct = models.DecimalField(
        _("60日低于25%统计的市销率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_60d_50pct = models.DecimalField(
        _("60日内统计50%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_60d_75pct = models.DecimalField(
        _("60日内统计75%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_60d_90pct = models.DecimalField(
        _("60日内统计90%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_90d_10pct = models.DecimalField(
        _("90日内统计10%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_90d_25pct = models.DecimalField(
        _("90日低于25%统计的市销率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_90d_50pct = models.DecimalField(
        _("90日内统计50%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_90d_75pct = models.DecimalField(
        _("90日内统计75%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_90d_90pct = models.DecimalField(
        _("90日内统计90%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_120d_10pct = models.DecimalField(
        _("120日内统计10%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_120d_25pct = models.DecimalField(
        _("120日低于25%统计的市销率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_120d_50pct = models.DecimalField(
        _("120日内统计50%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_120d_75pct = models.DecimalField(
        _("120日内统计75%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_120d_90pct = models.DecimalField(
        _("120日内统计90%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_200d_10pct = models.DecimalField(
        _("200日内统计10%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_200d_25pct = models.DecimalField(
        _("200日低于25%统计的市销率_qfq"),   
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_200d_50pct = models.DecimalField(
        _("200日内统计50%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_200d_75pct = models.DecimalField(
        _("200日内统计75%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_200d_90pct = models.DecimalField(
        _("200日内统计90%的市销率_qfq"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    ps_ttm = models.DecimalField(
        _("市销率TTM"),
        max_digits=16,
        decimal_places=4,
        blank=True,
        null=True,
    )
    dv_ratio = models.DecimalField(
        _("股息"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    dv_ttm = models.DecimalField(
        _("股息率TTM"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    total_share = models.DecimalField(
        _("总股本"),
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("单位：股"),
    )
    float_share = models.DecimalField(
        _("流通股本"),
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("单位：股"),
    )
    free_share = models.DecimalField(
        _("自由流通股本"),
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("单位：股"),
    )
    total_mv = models.DecimalField(
        _("总市值"),
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("单位：元"),
    )
    circ_mv = models.DecimalField(
        _("流通市值"),
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("单位：元"),
    )

    # 成本数据
    his_low = models.DecimalField(
        _("历史最低价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    his_high = models.DecimalField(
        _("历史最高价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    cost_5pct = models.DecimalField(
        _("5分位成本"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    cost_15pct = models.DecimalField(
        _("15分位成本"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    cost_50pct = models.DecimalField(
        _("50分位成本"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    cost_85pct = models.DecimalField(
        _("85分位成本"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    cost_95pct = models.DecimalField(
        _("95分位成本"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    weight_avg = models.DecimalField(
        _("加权平均成本"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    winner_rate = models.DecimalField(
        _("胜率"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
        help_text=_("单位：%"),
    )

    freq = models.CharField(
        _("周期"),
        max_length=5,
        default="D",
        help_text=_("如 D 日线，W 周线，M 月线"),
    )
    
    # 波峰波谷相关
    top_or_bottom = models.CharField(_("scipy峰谷"), max_length=1, blank=True, null=True, default="N")
    top_or_bottom_optimized = models.CharField(_("优化校验峰谷"), max_length=25, blank=True, null=True)
    top_or_bottom_stat = models.CharField(_("统计峰谷"), max_length=1, blank=True, null=True)
    top_or_bottom_stat_optimized = models.CharField(_("优化统计峰谷"), max_length=25, blank=True, null=True)
    top_bottom_volatility_stat = models.CharField(_("统计涨跌幅大的峰谷"), max_length=1, blank=True, null=True)
    top_bottom_volatility_optimized = models.CharField(_("优化的涨跌幅大的峰谷"), max_length=25, blank=True, null=True)
    
    def __str__(self):
        return f"{self.ts_code} | {self.trade_date}"

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票特征历史")
        verbose_name_plural = verbose_name
        unique_together = ("ts_code", "trade_date", "freq")
        get_latest_by = "id"


class StockTechFeature(models.Model):
    """股票特征差分数据"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_feature_diffs",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("公司"),
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"), db_index=True)
    freq = models.CharField(_("周期"), max_length=5, default="D")

    open_pre_close_change = models.DecimalField(_("开盘-前收盘变化"), max_digits=12, decimal_places=4, blank=True, null=True)
    open_pre_close_pct_chg = models.DecimalField(_("开盘-前收盘变化%"), max_digits=12, decimal_places=4, blank=True, null=True)
    change = models.DecimalField(_("价格变化"), max_digits=12, decimal_places=4, blank=True, null=True)
    pct_change = models.DecimalField(_("价格变化%"), max_digits=12, decimal_places=4, blank=True, null=True)
    pct_vol_chg = models.DecimalField(_("交易量变化%"), max_digits=12, decimal_places=4, blank=True, null=True)

    vol_status_ma6 = models.DecimalField(_("交易量ma6状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma10 = models.DecimalField(_("交易量ma10状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma16 = models.DecimalField(_("交易量ma16状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma25 = models.DecimalField(_("交易量ma25状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma43 = models.DecimalField(_("交易量ma43状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma60 = models.DecimalField(_("交易量ma60状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma90 = models.DecimalField(_("交易量ma90状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma120 = models.DecimalField(_("交易量ma120状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma200 = models.DecimalField(_("交易量ma200状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    
    vol_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    vol_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    amount_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    amount_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    close_qfq_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_qfq_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    close_ma6_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma6_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma6_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma10_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma10_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma10_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma16_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma16_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma16_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma25_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma25_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma25_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma43_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma43_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma43_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma60_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma60_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma60_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma90_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma90_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma90_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma120_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma120_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma120_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_ma200_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_ma200_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_ma200_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    ma6_ma10_entangled = models.CharField(max_length=1, blank=True, null=True)
    ma6_ma10_ma25_entangled = models.CharField(max_length=1, blank=True, null=True)
    ma6_ma10_ma25_ma60_entangled = models.CharField(max_length=1, blank=True, null=True)
    ma6_ma10_ma25_ma60_ma120_ma200_entangled = models.CharField(max_length=1, blank=True, null=True)
    
    ma6_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma10_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma16_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma25_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma43_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma60_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma90_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma120_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)
    ma200_trend = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)

    atr_6 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    atr_10 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    atr_14 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    atr_20 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    atr_25 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    close_atr_6_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_6_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_6_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_10_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_10_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_10_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_14_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_14_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_14_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_20_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_20_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_20_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_25_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_25_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_25_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    
    close_atr_6_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_6_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_6_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_10_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_10_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_10_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_14_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_14_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_14_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_20_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_20_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_20_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_25_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_25_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_25_x2_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    
    close_atr_6_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_6_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_6_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_10_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_10_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_10_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_14_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_14_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_14_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_20_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_20_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_20_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_25_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_25_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_25_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    
    close_atr_6_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_6_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_6_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_10_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_10_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_10_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_14_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_14_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_14_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_20_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_20_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_20_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_atr_25_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_atr_25_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_atr_25_x2_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    volatility_ratio_6 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volatility_ratio_10 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volatility_ratio_14 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volatility_ratio_20 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volatility_ratio_25 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    macd_dif = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    macd_dea = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    macd = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_k = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_d = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_j = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_6 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_12 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_24 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    high_boll_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_boll_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_boll_upper_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_boll_mid_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_boll_mid_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_boll_mid_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    high_boll_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    close_boll_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    low_boll_lower_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    cci = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    is_bullish_and_divergent = models.CharField(max_length=1, blank=True, null=True)
    is_bearish_and_divergent = models.CharField(max_length=1, blank=True, null=True)
    is_t_shape = models.CharField(max_length=1, blank=True, null=True)
    is_lower_shadow_shape = models.CharField(max_length=1, blank=True, null=True)
    is_upper_shadow_shape = models.CharField(max_length=1, blank=True, null=True)
    is_double_top = models.CharField(max_length=1, blank=True, null=True)
    
    def __str__(self):
        return f"{self.ts_code} | {self.trade_date}"

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票特征差分")
        verbose_name_plural = verbose_name
        unique_together = ("ts_code", "trade_date", "freq")
        get_latest_by = "id"
        
        
class StockFundamentalFeature(models.Model):
    """股票基本面特征及相关差分数据"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_fundamental_features",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("公司"),
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"), db_index=True)
    freq = models.CharField(_("周期"), max_length=5, default="D")

    turnover_rate = models.DecimalField(_("换手率"), max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f = models.DecimalField(_("换手率(自由流通)"), max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    volume_ratio = models.DecimalField(_("量比"), max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    volume_ratio_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    pe = models.DecimalField(_("市盈率"), max_digits=16, decimal_places=4, blank=True, null=True)
    pe_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pe_ttm = models.DecimalField(_("市盈率TTM"), max_digits=16, decimal_places=4, blank=True, null=True)

    pb = models.DecimalField(_("市净率"), max_digits=16, decimal_places=4, blank=True, null=True)
    pb_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    pb_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    ps = models.DecimalField(_("市销率"), max_digits=16, decimal_places=4, blank=True, null=True)
    ps_30d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_30d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_30d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_30d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_30d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_60d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_60d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_60d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_60d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_60d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_90d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_90d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_90d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_90d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_90d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_120d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_120d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_120d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_120d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_120d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_200d_10pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_200d_25pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_200d_50pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_200d_75pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_200d_90pct_diff = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    ps_ttm = models.DecimalField(_("市销率TTM"), max_digits=16, decimal_places=4, blank=True, null=True)

    dv_ratio = models.DecimalField(_("股息"), max_digits=12, decimal_places=4, blank=True, null=True)
    dv_ttm = models.DecimalField(_("股息率TTM"), max_digits=12, decimal_places=4, blank=True, null=True)
    total_share = models.DecimalField(_("总股本"), max_digits=20, decimal_places=2, blank=True, null=True)
    float_share = models.DecimalField(_("流通股本"), max_digits=20, decimal_places=2, blank=True, null=True)
    free_share = models.DecimalField(_("自由流通股本"), max_digits=20, decimal_places=2, blank=True, null=True)
    total_mv = models.DecimalField(_("总市值"), max_digits=20, decimal_places=2, blank=True, null=True)
    circ_mv = models.DecimalField(_("流通市值"), max_digits=20, decimal_places=2, blank=True, null=True)

    def __str__(self):
        return f"{self.ts_code} | {self.trade_date}"

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票基本面特征")
        verbose_name_plural = verbose_name
        unique_together = ("ts_code", "trade_date", "freq")
        get_latest_by = "id"
        
        
class StockCostFeature(models.Model):
    """股票成本相关特征及差分数据"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_cost_features",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("公司"),
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"), db_index=True)
    freq = models.CharField(_("周期"), max_length=5, default="D")

    close_his_low_diff = models.DecimalField(_("收盘-历史最低价差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_his_high_diff = models.DecimalField(_("收盘-历史最高价差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_5pct_diff = models.DecimalField(_("收盘-5分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_15pct_diff = models.DecimalField(_("收盘-15分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_50pct_diff = models.DecimalField(_("收盘-50分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_85pct_diff = models.DecimalField(_("收盘-85分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_95pct_diff = models.DecimalField(_("收盘-95分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_weight_avg_diff = models.DecimalField(_("收盘-加权平均成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_weight_avg_diff = models.DecimalField(_("最高-加权平均成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_weight_avg_diff = models.DecimalField(_("最低-加权平均成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_5pct_diff = models.DecimalField(_("最高-5分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_15pct_diff = models.DecimalField(_("最高-15分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_50pct_diff = models.DecimalField(_("最高-50分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_85pct_diff = models.DecimalField(_("最高-85分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_95pct_diff = models.DecimalField(_("最高-95分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_5pct_diff = models.DecimalField(_("最低-5分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_15pct_diff = models.DecimalField(_("最低-15分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_50pct_diff = models.DecimalField(_("最低-50分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_85pct_diff = models.DecimalField(_("最低-85分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_95pct_diff = models.DecimalField(_("最低-95分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    winner_rate = models.DecimalField(_("胜率"), max_digits=12, decimal_places=4, blank=True, null=True, help_text=_("单位：%"))

    def __str__(self):
        return f"{self.ts_code} | {self.trade_date}"

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票成本特征")
        verbose_name_plural = verbose_name
        unique_together = ("ts_code", "trade_date", "freq")
        get_latest_by = "id"


class StockCombinedFeature(models.Model):
    """股票技术、基本面、成本特征及相关差分数据（合并模型）"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_combined_features",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("公司"),
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"), db_index=True)
    freq = models.CharField(_("周期"), max_length=5, default="D")

    # 技术特征
    open_pre_close_change = models.DecimalField(_("开盘-前收盘变化"), max_digits=12, decimal_places=4, blank=True, null=True)
    open_pre_close_pct_chg = models.DecimalField(_("开盘-前收盘变化%"), max_digits=12, decimal_places=4, blank=True, null=True)
    change = models.DecimalField(_("价格变化"), max_digits=12, decimal_places=4, blank=True, null=True)
    pct_change = models.DecimalField(_("价格变化%"), max_digits=12, decimal_places=4, blank=True, null=True)
    pct_vol_chg = models.DecimalField(_("交易量变化%"), max_digits=12, decimal_places=4, blank=True, null=True)

    # 交易量状态
    vol_status_ma6 = models.DecimalField(_("交易量ma6状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma10 = models.DecimalField(_("交易量ma10状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma16 = models.DecimalField(_("交易量ma16状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma25 = models.DecimalField(_("交易量ma25状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma43 = models.DecimalField(_("交易量ma43状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma60 = models.DecimalField(_("交易量ma60状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma90 = models.DecimalField(_("交易量ma90状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma120 = models.DecimalField(_("交易量ma120状态"), max_digits=2, decimal_places=0, blank=True, null=True)
    vol_status_ma200 = models.DecimalField(_("交易量ma200状态"), max_digits=2, decimal_places=0, blank=True, null=True)

    # 交易量、成交额、收盘价差分
    for prefix in ["vol", "amount", "close_qfq"]:
        for period in ["30d", "60d", "90d", "120d", "200d"]:
            for pct in ["10pct", "25pct", "50pct", "75pct", "90pct"]:
                field_name = f"{prefix}_{period}_{pct}_diff"
                locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    # 均线差分
    for price in ["close", "high", "low"]:
        for ma in ["ma6", "ma10", "ma16", "ma25", "ma43", "ma60", "ma90", "ma120", "ma200"]:
            field_name = f"{price}_{ma}_diff"
            locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    # 均线纠缠
    ma6_ma10_entangled = models.CharField(max_length=1, blank=True, null=True)
    ma6_ma10_ma25_entangled = models.CharField(max_length=1, blank=True, null=True)
    ma6_ma10_ma25_ma60_entangled = models.CharField(max_length=1, blank=True, null=True)
    ma6_ma10_ma25_ma60_ma120_ma200_entangled = models.CharField(max_length=1, blank=True, null=True)

    # 均线趋势
    for ma in ["ma6", "ma10", "ma16", "ma25", "ma43", "ma60", "ma90", "ma120", "ma200"]:
        field_name = f"{ma}_trend"
        locals()[field_name] = models.DecimalField(max_digits=1, decimal_places=0, blank=True, null=True)

    # ATR相关
    for atr in ["atr_6", "atr_10", "atr_14", "atr_20", "atr_25"]:
        locals()[atr] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
        for suffix in ["upper_diff", "x2_upper_diff", "lower_diff", "x2_lower_diff"]:
            for price in ["close", "high", "low"]:
                field_name = f"{price}_{atr}_{suffix}"
                locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    # 波动率比
    for vr in ["volatility_ratio_6", "volatility_ratio_10", "volatility_ratio_14", "volatility_ratio_20", "volatility_ratio_25"]:
        locals()[vr] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    # 技术指标
    macd_dif = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    macd_dea = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    macd = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_k = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_d = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    kdj_j = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_6 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_12 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    rsi_24 = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    # BOLL相关
    for price in ["high", "close", "low"]:
        for boll in ["boll_upper", "boll_mid", "boll_lower"]:
            field_name = f"{price}_{boll}_diff"
            locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    cci = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    # 形态相关
    is_bullish_and_divergent = models.CharField(max_length=1, blank=True, null=True)
    is_bearish_and_divergent = models.CharField(max_length=1, blank=True, null=True)
    is_t_shape = models.CharField(max_length=1, blank=True, null=True)
    is_lower_shadow_shape = models.CharField(max_length=1, blank=True, null=True)
    is_upper_shadow_shape = models.CharField(max_length=1, blank=True, null=True)
    is_double_top = models.CharField(max_length=1, blank=True, null=True)

    # 基本面特征及差分
    turnover_rate = models.DecimalField(_("换手率"), max_digits=12, decimal_places=4, blank=True, null=True)
    turnover_rate_f = models.DecimalField(_("换手率(自由流通)"), max_digits=12, decimal_places=4, blank=True, null=True)
    for period in ["30d", "60d", "90d", "120d", "200d"]:
        for pct in ["10pct", "25pct", "50pct", "75pct", "90pct"]:
            field_name = f"turnover_rate_f_{period}_{pct}_diff"
            locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    volume_ratio = models.DecimalField(_("量比"), max_digits=12, decimal_places=4, blank=True, null=True)
    for period in ["30d", "60d", "90d", "120d", "200d"]:
        for pct in ["10pct", "25pct", "50pct", "75pct", "90pct"]:
            field_name = f"volume_ratio_{period}_{pct}_diff"
            locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    pe = models.DecimalField(_("市盈率"), max_digits=16, decimal_places=4, blank=True, null=True)
    pe_ttm = models.DecimalField(_("市盈率TTM"), max_digits=16, decimal_places=4, blank=True, null=True)
    for period in ["30d", "60d", "90d", "120d", "200d"]:
        for pct in ["10pct", "25pct", "50pct", "75pct", "90pct"]:
            field_name = f"pe_{period}_{pct}_diff"
            locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    pb = models.DecimalField(_("市净率"), max_digits=16, decimal_places=4, blank=True, null=True)
    for period in ["30d", "60d", "90d", "120d", "200d"]:
        for pct in ["10pct", "25pct", "50pct", "75pct", "90pct"]:
            field_name = f"pb_{period}_{pct}_diff"
            locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    ps = models.DecimalField(_("市销率"), max_digits=16, decimal_places=4, blank=True, null=True)
    ps_ttm = models.DecimalField(_("市销率TTM"), max_digits=16, decimal_places=4, blank=True, null=True)
    for period in ["30d", "60d", "90d", "120d", "200d"]:
        for pct in ["10pct", "25pct", "50pct", "75pct", "90pct"]:
            field_name = f"ps_{period}_{pct}_diff"
            locals()[field_name] = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)

    dv_ratio = models.DecimalField(_("股息"), max_digits=12, decimal_places=4, blank=True, null=True)
    dv_ttm = models.DecimalField(_("股息率TTM"), max_digits=12, decimal_places=4, blank=True, null=True)
    total_share = models.DecimalField(_("总股本"), max_digits=20, decimal_places=2, blank=True, null=True)
    float_share = models.DecimalField(_("流通股本"), max_digits=20, decimal_places=2, blank=True, null=True)
    free_share = models.DecimalField(_("自由流通股本"), max_digits=20, decimal_places=2, blank=True, null=True)
    total_mv = models.DecimalField(_("总市值"), max_digits=20, decimal_places=2, blank=True, null=True)
    circ_mv = models.DecimalField(_("流通市值"), max_digits=20, decimal_places=2, blank=True, null=True)

    # 成本相关特征及差分
    close_his_low_diff = models.DecimalField(_("收盘-历史最低价差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_his_high_diff = models.DecimalField(_("收盘-历史最高价差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_5pct_diff = models.DecimalField(_("收盘-5分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_15pct_diff = models.DecimalField(_("收盘-15分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_50pct_diff = models.DecimalField(_("收盘-50分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_85pct_diff = models.DecimalField(_("收盘-85分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_cost_95pct_diff = models.DecimalField(_("收盘-95分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    close_weight_avg_diff = models.DecimalField(_("收盘-加权平均成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_weight_avg_diff = models.DecimalField(_("最高-加权平均成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_weight_avg_diff = models.DecimalField(_("最低-加权平均成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_5pct_diff = models.DecimalField(_("最高-5分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_15pct_diff = models.DecimalField(_("最高-15分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_50pct_diff = models.DecimalField(_("最高-50分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_85pct_diff = models.DecimalField(_("最高-85分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    high_cost_95pct_diff = models.DecimalField(_("最高-95分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_5pct_diff = models.DecimalField(_("最低-5分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_15pct_diff = models.DecimalField(_("最低-15分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_50pct_diff = models.DecimalField(_("最低-50分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_85pct_diff = models.DecimalField(_("最低-85分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    low_cost_95pct_diff = models.DecimalField(_("最低-95分位成本差分"), max_digits=12, decimal_places=4, blank=True, null=True)
    winner_rate = models.DecimalField(_("胜率"), max_digits=12, decimal_places=4, blank=True, null=True, help_text=_("单位：%"))
    
    # 新K线形态特征
    upper_shadow = models.DecimalField(_("上影线"), max_digits=12, decimal_places=4, blank=True, null=True)
    lower_shadow = models.DecimalField(_("下影线"), max_digits=12, decimal_places=4, blank=True, null=True)
    shadow_ratio = models.DecimalField(_("影线比率"), max_digits=12, decimal_places=4, blank=True, null=True)
    body = models.DecimalField(_("主体"), max_digits=12, decimal_places=4, blank=True, null=True)
    pct_o2c = models.DecimalField(_("开盘-收盘%"), max_digits=12, decimal_places=4, blank=True, null=True)
    
    # 新特征2026-01-23
    chip_concentration = models.DecimalField(_("筹码集中度"), max_digits=12, decimal_places=4, blank=True, null=True)

    def __str__(self):
        return f"{self.ts_code} | {self.trade_date}"

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票合并特征")
        verbose_name_plural = verbose_name
        unique_together = ("ts_code", "trade_date", "freq")
        get_latest_by = "id"
    