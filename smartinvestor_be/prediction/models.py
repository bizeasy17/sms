from django.db import models
from django.utils.translation import gettext_lazy as _

from datastore.models import Corporation


# Create your models here.
class StockPredictionFeature(models.Model):
    """
    Model to store 200 float features for stock prediction
    """

    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ts_code = models.CharField(max_length=10)
    trade_date = models.DateField()
    corporation = models.ForeignKey(
        Corporation, on_delete=models.CASCADE, related_name="stock_prediction_features"
    )

    # Dynamically create 200 float fields named feature_0 to feature_199
    for i in range(200):
        locals()[f"feature_{i}"] = models.FloatField(null=True, blank=True)


class StockPrediction(models.Model):
    """
    Stock prediction model
    """

    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)

    ts_code = models.CharField(max_length=10)
    trade_date = models.DateField()
    confidence = models.FloatField()
    applied_model = models.CharField(max_length=50)
    model_version = models.CharField(max_length=20)
    volatility = models.CharField(max_length=20)
    top_or_bottom = models.CharField(max_length=4, choices=[("B", "Bottom"), ("T", "Top")])
    corporation = models.ForeignKey(
        Corporation, on_delete=models.CASCADE, related_name="stock_predictions"
    )
    freq = models.CharField(max_length=10, default="D")
    is_temp = models.BooleanField(default=False)
    
    def to_dict(self):
        return {
            "id": self.id,
            "ts_code": self.ts_code,
            "trade_date": self.trade_date,
            "confidence": self.confidence,
            # "applied_model": self.applied_model,
            # "volatility": self.volatility,
            "top_or_bottom": self.top_or_bottom,
            "freq": self.freq,
        }

    def __str__(self):
        return f"{self.ts_code} - {self.trade_date}: {self.confidence} ({self.top_or_bottom})"


class BacktestValuationSnapshot(models.Model):
    """回测估值临时快照，供历史回测复用，避免重复实时估值。"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"), db_index=True)
    market = models.CharField(_("市场"), max_length=10, default="CN", db_index=True)
    valuation_method = models.CharField(_("估值方法"), max_length=32, db_index=True)
    valuation_price = models.DecimalField(
        _("估值价格"),
        max_digits=20,
        decimal_places=6,
        blank=True,
        null=True,
    )
    valuation_market_cap = models.DecimalField(
        _("估值市值"),
        max_digits=24,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("估值对应的股权价值，单位：元"),
    )
    source = models.CharField(_("来源"), max_length=32, default="live_backtest")
    batch_key = models.CharField(_("回测批次"), max_length=64, default="default", db_index=True)
    corporation = models.ForeignKey(
        Corporation,
        related_name="backtest_valuation_snapshots",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        verbose_name = _("回测估值临时快照")
        verbose_name_plural = verbose_name
        ordering = ["-trade_date", "ts_code"]
        unique_together = ("ts_code", "trade_date", "market", "valuation_method", "batch_key")
        indexes = [
            models.Index(fields=["batch_key", "trade_date", "valuation_method"]),
            models.Index(fields=["batch_key", "ts_code", "trade_date"]),
        ]


class AnnualOutlookSnapshot(models.Model):
    """年度业绩预测与估值展望快照（按版本和参数签名可追溯）。"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("估值交易日"), db_index=True)
    freq = models.CharField(_("周期"), max_length=10, default="D", db_index=True)
    scope = models.CharField(_("范围"), max_length=32, default="ALL")

    outlook_version = models.CharField(_("展望版本"), max_length=64, db_index=True)
    assumptions_signature = models.CharField(_("参数签名"), max_length=64, db_index=True)
    scenario = models.CharField(
        _("情景"),
        max_length=16,
        choices=[("bear", "bear"), ("base", "base"), ("bull", "bull")],
        db_index=True,
    )

    corporation = models.ForeignKey(
        Corporation,
        related_name="annual_outlook_snapshots",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )

    fundamental_trade_date = models.DateField(_("基准基本面日期"), blank=True, null=True)

    current_price = models.DecimalField(_("现价"), max_digits=20, decimal_places=6, blank=True, null=True)
    base_total_mv = models.DecimalField(_("基准总市值"), max_digits=24, decimal_places=2, blank=True, null=True)
    base_total_share = models.DecimalField(_("基准总股本"), max_digits=24, decimal_places=2, blank=True, null=True)

    profit_growth_pct = models.DecimalField(_("净利增速%"), max_digits=10, decimal_places=4, blank=True, null=True)
    revenue_growth_pct = models.DecimalField(_("营收增速%"), max_digits=10, decimal_places=4, blank=True, null=True)

    forecast_netprofit = models.DecimalField(_("预测净利润"), max_digits=24, decimal_places=2, blank=True, null=True)
    forecast_revenue = models.DecimalField(_("预测营收"), max_digits=24, decimal_places=2, blank=True, null=True)

    target_pe = models.DecimalField(_("目标PE"), max_digits=12, decimal_places=4, blank=True, null=True)
    target_ps = models.DecimalField(_("目标PS"), max_digits=12, decimal_places=4, blank=True, null=True)
    target_pb = models.DecimalField(_("目标PB"), max_digits=12, decimal_places=4, blank=True, null=True)

    implied_price_pe = models.DecimalField(_("PE隐含价格"), max_digits=20, decimal_places=6, blank=True, null=True)
    implied_price_ps = models.DecimalField(_("PS隐含价格"), max_digits=20, decimal_places=6, blank=True, null=True)
    implied_price_pb = models.DecimalField(_("PB隐含价格"), max_digits=20, decimal_places=6, blank=True, null=True)

    composite_price = models.DecimalField(_("组合估值价格"), max_digits=20, decimal_places=6, blank=True, null=True)
    upside_pct = models.DecimalField(_("上行空间%"), max_digits=12, decimal_places=4, blank=True, null=True)

    class Meta:
        verbose_name = _("年度展望估值快照")
        verbose_name_plural = verbose_name
        ordering = ["-trade_date", "ts_code", "scenario"]
        unique_together = (
            "ts_code",
            "trade_date",
            "freq",
            "outlook_version",
            "assumptions_signature",
            "scenario",
        )
        indexes = [
            models.Index(fields=["trade_date", "scope", "outlook_version"]),
            models.Index(fields=["outlook_version", "assumptions_signature", "scenario"]),
        ]


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

    upper_shadow = models.DecimalField(_("上影线"), max_digits=12, decimal_places=4, blank=True, null=True)
    lower_shadow = models.DecimalField(_("下影线"), max_digits=12, decimal_places=4, blank=True, null=True)
    body = models.DecimalField(_("主体"), max_digits=12, decimal_places=4, blank=True, null=True)
    shadow_ratio = models.DecimalField(_("影线比"), max_digits=12, decimal_places=4, blank=True, null=True)
    pct_o2c = models.DecimalField(_("开盘-收盘%"), max_digits=12, decimal_places=4, blank=True, null=True)

    def __str__(self):
        return f"{self.ts_code} | {self.trade_date}"

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票合并特征")
        verbose_name_plural = verbose_name
        unique_together = ("ts_code", "trade_date", "freq")
        get_latest_by = "id"
    
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

    top_or_bottom = models.CharField(
        _("顶底"), max_length=1, blank=True, null=True, default="B"
    )
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
    
    def to_dict(self):
        return {
            "ts_code": self.ts_code,
            "freq": self.freq,
            "quantile": self.quantile,
            "top_or_bottom": self.top_or_bottom,
            "period": self.period,
            "pct_gain_1p": self.pct_gain_1p,
            "pct_gain_2p": self.pct_gain_2p,
            "pct_gain_3p": self.pct_gain_3p,
            "pct_gain_5p": self.pct_gain_5p,
            "pct_loss_1p": self.pct_loss_1p,
            "pct_loss_2p": self.pct_loss_2p,
            "pct_loss_3p": self.pct_loss_3p,
            "pct_loss_5p": self.pct_loss_5p,
        }

    class Meta:
        ordering = ["ts_code"]
        verbose_name = _("分位数高低点")
        verbose_name_plural = verbose_name
        get_latest_by = "id"


class StockValuationSnapshot(models.Model):
    """股票估值快照缓存，用于选股页快速查询。"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_valuation_snapshots",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"), db_index=True)
    market = models.CharField(_("市场"), max_length=10, default="CN", db_index=True)
    valuation_method = models.CharField(_("估值方法"), max_length=32, db_index=True)
    valuation_variant = models.CharField(
        _("估值变体键"),
        max_length=128,
        default="default",
        db_index=True,
        help_text=_("用于区分同一估值方法下的多行业匹配结果"),
    )
    valuation_price = models.DecimalField(_("估值价格"), max_digits=20, decimal_places=6, null=True, blank=True)
    valuation_market_cap = models.DecimalField(
        _("估值市值"),
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("估值对应的股权价值，单位：元"),
    )
    source = models.CharField(_("来源"), max_length=32, default="live_compute")
    industry_level = models.CharField(_("行业层级"), max_length=16, blank=True, null=True, db_index=True)
    industry_code = models.CharField(_("行业编码"), max_length=32, blank=True, null=True, db_index=True)
    industry_name = models.CharField(_("行业名称"), max_length=128, blank=True, null=True)
    compare_group = models.CharField(_("估值对比组"), max_length=32, blank=True, null=True, db_index=True)
    match_score = models.DecimalField(_("行业匹配得分"), max_digits=10, decimal_places=4, blank=True, null=True)
    profit_data_source = models.CharField(
        _("利润口径来源"),
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text=_("如 express_vip / express_vip_blended / fina_indicator_income"),
    )
    profit_report_end_date = models.DateField(
        _("利润口径报告期"),
        blank=True,
        null=True,
        db_index=True,
        help_text=_("用于估值时实际采用的报告期末日期"),
    )
    profit_report_ann_date = models.DateField(
        _("利润口径公告日"),
        blank=True,
        null=True,
        db_index=True,
        help_text=_("用于估值时实际采用口径对应的公告日期"),
    )
    profit_report_type = models.CharField(
        _("利润口径报告类型"),
        max_length=16,
        blank=True,
        null=True,
        db_index=True,
        help_text=_("Q1 / H1 / Q3 / ANNUAL / OTHER"),
    )
    express_end_date = models.DateField(_("快报报告期"), blank=True, null=True, db_index=True)
    express_ann_date = models.DateField(_("快报公告日"), blank=True, null=True, db_index=True)
    express_apply_reason = models.CharField(_("快报应用原因"), max_length=64, blank=True, null=True, db_index=True)
    express_block_reason = models.CharField(_("快报拦截原因"), max_length=64, blank=True, null=True, db_index=True)
    strict_express_match = models.BooleanField(_("是否启用快报严格匹配"), blank=True, null=True)
    express_max_age_days = models.IntegerField(_("快报时效窗口(天)"), blank=True, null=True)

    class Meta:
        ordering = ["-trade_date", "ts_code"]
        verbose_name = _("估值快照")
        verbose_name_plural = verbose_name
        unique_together = (
            "ts_code",
            "trade_date",
            "market",
            "valuation_method",
            "valuation_variant",
            "profit_report_type",
            "profit_report_end_date",
            "profit_data_source",
        )
        indexes = [
            models.Index(fields=["market", "trade_date", "valuation_method"]),
            models.Index(fields=["market", "ts_code", "trade_date"]),
            models.Index(fields=["market", "ts_code", "profit_report_end_date", "valuation_method"]),
        ]


class StockValuationSnapshotHistory(models.Model):
    """股票估值快照历史表，记录被新快照覆盖前的旧值。"""

    id = models.BigAutoField(primary_key=True)
    archived_at = models.DateTimeField(auto_now_add=True, db_index=True)
    archive_reason = models.CharField(_("归档原因"), max_length=32, default="upsert_replace", db_index=True)
    is_backfill = models.BooleanField(_("是否历史回填"), default=False, db_index=True)
    backfill_run_id = models.CharField(_("回填运行ID"), max_length=64, blank=True, default="", db_index=True)
    refresh_policy = models.CharField(_("刷新策略"), max_length=16, blank=True, default="", db_index=True)
    price_anchor_mode = models.CharField(_("价格锚点模式"), max_length=24, blank=True, default="", db_index=True)
    target_report_type = models.CharField(_("目标报告类型"), max_length=16, blank=True, default="", db_index=True)
    profit_bucket_mode = models.CharField(_("利润桶模式"), max_length=16, blank=True, default="", db_index=True)

    source_snapshot_id = models.BigIntegerField(_("来源快照ID"), blank=True, null=True, db_index=True)
    snapshot_created_at = models.DateTimeField(_("来源创建时间"), blank=True, null=True)
    snapshot_updated_at = models.DateTimeField(_("来源更新时间"), blank=True, null=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_valuation_snapshot_histories",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    trade_date = models.DateField(_("交易日"), db_index=True)
    market = models.CharField(_("市场"), max_length=10, default="CN", db_index=True)
    valuation_method = models.CharField(_("估值方法"), max_length=32, db_index=True)
    valuation_variant = models.CharField(
        _("估值变体键"),
        max_length=128,
        default="default",
        db_index=True,
    )
    valuation_price = models.DecimalField(_("估值价格"), max_digits=20, decimal_places=6, null=True, blank=True)
    valuation_market_cap = models.DecimalField(
        _("估值市值"),
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
    )
    source = models.CharField(_("来源"), max_length=32, default="live_compute")
    industry_level = models.CharField(_("行业层级"), max_length=16, blank=True, null=True, db_index=True)
    industry_code = models.CharField(_("行业编码"), max_length=32, blank=True, null=True, db_index=True)
    industry_name = models.CharField(_("行业名称"), max_length=128, blank=True, null=True)
    compare_group = models.CharField(_("估值对比组"), max_length=32, blank=True, null=True, db_index=True)
    match_score = models.DecimalField(_("行业匹配得分"), max_digits=10, decimal_places=4, blank=True, null=True)
    profit_data_source = models.CharField(_("利润口径来源"), max_length=64, blank=True, null=True, db_index=True)
    profit_report_end_date = models.DateField(_("利润口径报告期"), blank=True, null=True, db_index=True)
    profit_report_ann_date = models.DateField(_("利润口径公告日"), blank=True, null=True, db_index=True)
    profit_report_type = models.CharField(_("利润口径报告类型"), max_length=16, blank=True, null=True, db_index=True)
    express_end_date = models.DateField(_("快报报告期"), blank=True, null=True, db_index=True)
    express_ann_date = models.DateField(_("快报公告日"), blank=True, null=True, db_index=True)
    express_apply_reason = models.CharField(_("快报应用原因"), max_length=64, blank=True, null=True, db_index=True)
    express_block_reason = models.CharField(_("快报拦截原因"), max_length=64, blank=True, null=True, db_index=True)
    strict_express_match = models.BooleanField(_("是否启用快报严格匹配"), blank=True, null=True)
    express_max_age_days = models.IntegerField(_("快报时效窗口(天)"), blank=True, null=True)

    class Meta:
        ordering = ["-archived_at", "-trade_date", "ts_code"]
        verbose_name = _("估值快照历史")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(
                fields=["ts_code", "trade_date", "market", "valuation_method"],
                name="prediction_s_ts_cod_6bfca1_idx",
            ),
            models.Index(
                fields=["ts_code", "profit_report_end_date", "valuation_method"],
                name="prediction_s_ts_cod_32002e_idx",
            ),
            models.Index(fields=["market", "archived_at"], name="prediction_s_market_5e2e4a_idx"),
            models.Index(fields=["market", "trade_date", "valuation_method"], name="idx_svsh_mkt_dt_method"),
            models.Index(fields=["is_backfill", "archived_at"], name="idx_svsh_bf_archived"),
        ]


class StockValuationSnapshotLatest(models.Model):
    """股票估值最新快照表，每个股票/方法/变体/利润口径保留最新一条。"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="stock_valuation_snapshots_latest",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    ts_code = models.CharField(_("交易代码"), max_length=10, db_index=True)
    latest_trade_date = models.DateField(_("最新交易日"), db_index=True)
    market = models.CharField(_("市场"), max_length=10, default="CN", db_index=True)
    valuation_method = models.CharField(_("估值方法"), max_length=32, db_index=True)
    valuation_variant = models.CharField(
        _("估值变体键"),
        max_length=128,
        default="default",
        db_index=True,
        help_text=_("用于区分同一估值方法下的多行业匹配结果"),
    )
    valuation_price = models.DecimalField(_("估值价格"), max_digits=20, decimal_places=6, null=True, blank=True)
    valuation_market_cap = models.DecimalField(
        _("估值市值"),
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("估值对应的股权价值，单位：元"),
    )
    source = models.CharField(_("来源"), max_length=32, default="live_compute")
    industry_level = models.CharField(_("行业层级"), max_length=16, blank=True, null=True, db_index=True)
    industry_code = models.CharField(_("行业编码"), max_length=32, blank=True, null=True, db_index=True)
    industry_name = models.CharField(_("行业名称"), max_length=128, blank=True, null=True)
    compare_group = models.CharField(_("估值对比组"), max_length=32, blank=True, null=True, db_index=True)
    match_score = models.DecimalField(_("行业匹配得分"), max_digits=10, decimal_places=4, blank=True, null=True)
    profit_data_source = models.CharField(
        _("利润口径来源"),
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text=_("如 express_vip / express_vip_blended / fina_indicator_income"),
    )
    profit_report_end_date = models.DateField(
        _("利润口径报告期"),
        blank=True,
        null=True,
        db_index=True,
        help_text=_("用于估值时实际采用的报告期末日期"),
    )
    profit_report_ann_date = models.DateField(
        _("利润口径公告日"),
        blank=True,
        null=True,
        db_index=True,
        help_text=_("用于估值时实际采用口径对应的公告日期"),
    )
    profit_report_type = models.CharField(
        _("利润口径报告类型"),
        max_length=16,
        blank=True,
        null=True,
        db_index=True,
        help_text=_("Q1 / H1 / Q3 / ANNUAL / OTHER"),
    )
    express_end_date = models.DateField(_("快报报告期"), blank=True, null=True, db_index=True)
    express_ann_date = models.DateField(_("快报公告日"), blank=True, null=True, db_index=True)
    express_apply_reason = models.CharField(_("快报应用原因"), max_length=64, blank=True, null=True, db_index=True)
    express_block_reason = models.CharField(_("快报拦截原因"), max_length=64, blank=True, null=True, db_index=True)
    strict_express_match = models.BooleanField(_("是否启用快报严格匹配"), blank=True, null=True)
    express_max_age_days = models.IntegerField(_("快报时效窗口(天)"), blank=True, null=True)

    class Meta:
        ordering = ["ts_code"]
        verbose_name = _("估值最新快照")
        verbose_name_plural = verbose_name
        unique_together = (
            "ts_code",
            "market",
            "valuation_method",
            "valuation_variant",
            "profit_report_type",
            "profit_data_source",
        )
        indexes = [
            models.Index(
                fields=["market", "latest_trade_date", "valuation_method"],
                name="prediction_s_market_b1ce11_idx",
            ),
            models.Index(fields=["market", "ts_code"], name="prediction_s_market_4bb834_idx"),
            models.Index(
                fields=["market", "ts_code", "profit_report_type", "profit_data_source"],
                name="prediction_s_latest_bucket_idx",
            ),
        ]
