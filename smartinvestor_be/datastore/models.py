from django.db import models
from django.utils.translation import gettext_lazy as _


# Create your models here.
class Industry(models.Model):
    """Industry"""

    id = models.BigAutoField(primary_key=True)
    # 这里使用 BigAutoField 以支持更大的 ID 范围
    # Django 3.2+ 默认使用 BigAutoField 作为默认的 AutoField
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(
        "行业名称",
        max_length=50,
        unique=True,
        db_index=True,
    )
    name_pinyin = models.CharField(
        "行业名称拼音",
        max_length=50,
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        verbose_name = "行业"
        verbose_name_plural = "行业"


class Area(models.Model):
    """
    Area
    """

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(
        verbose_name=_("省份"),
        max_length=50,
        unique=True,
        db_index=True,
    )
    country = models.CharField(
        verbose_name=_("国家"),
        max_length=50,
        default="中国",
        blank=True,
    )
    name_pinyin = models.CharField(
        verbose_name=_("省份拼音"),
        max_length=50,
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        unique_together = ("name", "country")
        verbose_name = _("省份")
        verbose_name_plural = verbose_name


class City(models.Model):
    """城市"""

    id = models.BigAutoField(primary_key=True)
    # 这里使用 BigAutoField 以支持更大的 ID 范围
    # Django 3.2+ 默认使用 BigAutoField
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(
        _("城市"),
        max_length=50,
        db_index=True,
    )
    area = models.ForeignKey(
        Area,
        related_name="cities",
        on_delete=models.SET_NULL,
        verbose_name=_("省份"),
        blank=True,
        null=True,
    )
    name_pinyin = models.CharField(
        _("城市拼音"),
        max_length=50,
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        unique_together = ("name", "area")
        verbose_name = _("城市")
        verbose_name_plural = verbose_name


class Corporation(models.Model):
    """
    股票公司信息表
    """

    id = models.BigAutoField(primary_key=True)
    # 这里使用 BigAutoField 以支持更大的 ID 范围
    # Django 3.2+ 默认使用 BigAutoField
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ts_code = models.CharField(_("交易代码"), max_length=10, unique=True, db_index=True)

    name = models.CharField(
        _("股票名称"),
        max_length=50,
        db_index=True,
        help_text=_("股票简称"),
    )

    area = models.ForeignKey(
        Area,
        related_name="corporations",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("省份"),
        help_text=_("公司注册省份"),
    )
    industry = models.ForeignKey(
        Industry,
        related_name="corporations",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("行业"),
        help_text=_("所属行业"),
    )
    sw_l3_code = models.CharField(
        _("SW三级行业编码"),
        max_length=32,
        blank=True,
        null=True,
        db_index=True,
        help_text=_("申万三级行业编码，如 850325.SI"),
    )
    sw_l3_name = models.CharField(
        _("SW三级行业名称"),
        max_length=128,
        blank=True,
        null=True,
        help_text=_("申万三级行业名称"),
    )

    fullname = models.CharField(
        _("公司名称"),
        max_length=100,
        blank=True,
        null=True,
        help_text=_("公司全称"),
    )
    enname = models.CharField(
        _("英文全称"),
        max_length=100,
        blank=True,
        null=True,
        help_text=_("公司英文全称"),
    )

    cnspell = models.CharField(
        _("股票名称拼音"),
        max_length=50,
        blank=True,
        null=True,
        help_text=_("股票简称拼音"),
    )
    market = models.CharField(
        _("市场类型"),
        max_length=50,
        blank=True,
        null=True,
        help_text=_("主板/创业板/科创板等"),
    )
    exchange = models.CharField(
        _("交易所代码"),
        max_length=10,
        blank=True,
        null=True,
        help_text=_("如 SZSE/SHSE"),
    )
    curr_type = models.CharField(
        _("货币类型"),
        max_length=10,
        help_text=_("交易货币类型，如 CNY"),
    )
    list_status = models.CharField(
        _("上市状态"),
        max_length=1,
        blank=True,
        null=True,
        choices=(
            ("L", _("上市")),
            ("D", _("退市")),
            ("P", _("暂停上市")),
        ),
        help_text=_("L:上市 D:退市 P:暂停上市"),
    )
    list_date = models.DateField(
        _("上市日期"),
        blank=True,
        null=True,
        help_text=_("公司上市日期"),
    )
    delist_date = models.DateField(
        _("退市日期"),
        blank=True,
        null=True,
        help_text=_("公司退市日期"),
    )
    is_hs = models.CharField(
        _("是否沪深港通标的"),
        max_length=10,
        blank=True,
        null=True,
        choices=(
            ("S", _("沪股通")),
            ("H", _("深股通")),
            ("N", _("否")),
        ),
        help_text=_("S:沪股通 H:深股通 N:否"),
    )
    act_name = models.CharField(
        _("实控人名称"),
        max_length=50,
        blank=True,
        null=True,
        help_text=_("实际控制人名称"),
    )
    act_ent_type = models.CharField(
        _("实控人企业性质"),
        max_length=50,
        blank=True,
        null=True,
        help_text=_("实际控制人企业性质"),
    )
    asset = models.CharField(
        _("股票/指数"),
        max_length=1,
        blank=True,
        null=True,
        default="E",
        choices=(
            ("E", _("股票")),
            ("I", _("指数")),
        ),
        help_text=_("E:股票 I:指数"),
    )
    trading_inited = models.BooleanField(
        _("交易数据已初始化"),
        default=False,
        help_text=_("是否已初始化交易数据"),
    )
    funda_inited = models.BooleanField(
        _("基本面数据已初始化"),
        default=False,
        help_text=_("是否已初始化基本面数据"),
    )
    cost_inited = models.BooleanField(
        _("成本数据已初始化"),
        default=False,
        help_text=_("是否已初始化成本数据"),
    )
    weekly_trading_inited = models.BooleanField(
        _("周交易数据已初始化"),
        default=False,
        help_text=_("是否已初始化周交易数据"),
    )
    monthly_trading_inited = models.BooleanField(
        _("月交易数据已初始化"),
        default=False,
        help_text=_("是否已初始化月交易数据"),
    )
    weekly_funda_inited = models.BooleanField(
        _("周基本面数据已初始化"),
        default=False,
        help_text=_("是否已初始化周基本面数据"),
    )
    monthly_funda_inited = models.BooleanField(
        _("月基本面数据已初始化"),
        default=False,
        help_text=_("是否已初始化月基本面数据"),
    )
    weekly_cost_inited = models.BooleanField(
        _("周成本数据已初始化"),
        default=False,
        help_text=_("是否已初始化周成本数据"),
    )
    monthly_cost_inited = models.BooleanField(
        _("月成本数据已初始化"),
        default=False,
        help_text=_("是否已初始化月成本数据"),
    )

    def get_industry_name(self):
        return self.industry.name if self.industry else None

    def get_area_name(self):
        return self.area.name if self.area else None

    def is_listed(self):
        return self.list_status == "L"

    def is_delisted(self):
        return self.list_status == "D"

    def get_full_display_name(self):
        return f"{self.name} ({self.ts_code})"

    @classmethod
    def get_by_ts_code(cls, ts_code):
        try:
            return cls.objects.get(ts_code=ts_code)
        except cls.DoesNotExist:
            return None

    def __str__(self):
        return self.ts_code

    class Meta:
        ordering = ["ts_code"]
        verbose_name = _("股票公司信息")
        verbose_name_plural = verbose_name
        get_latest_by = "id"


class CorporationBasic(models.Model):
    '公司基本信息'
    id = models.BigAutoField(primary_key=True, verbose_name=_("Id"), help_text=_("Id"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("创建时间"), help_text=_("创建时间"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("修改时间"), help_text=_("修改时间"))

    corporation = models.ForeignKey(
        Corporation,
        related_name="basic_info",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("公司"),
        help_text=_("关联的股票公司信息"),
    )
    ts_code = models.CharField(
        _("交易代码"), max_length=10, unique=True, db_index=True, help_text=_("如 000001.SZ")
    )
    exchange = models.CharField(_("交易所代码"), max_length=10, blank=True, null=True, help_text=_("如 SZSE/SHSE"))
    chairman = models.CharField(_("法人代表"), max_length=50, blank=True, null=True)
    manager = models.CharField(_("总经理"), max_length=50, blank=True, null=True)
    secretary = models.CharField(_("董秘"), max_length=50, blank=True, null=True)
    reg_capital = models.DecimalField(_("注册资本"), max_digits=20, decimal_places=2, blank=True, null=True, help_text=_("单位：万元"))
    setup_date = models.DateField(_("注册日期"), blank=True, null=True)
    area = models.ForeignKey(
        Area,
        related_name="corporation_basic_area",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("省份"),
        help_text=_("公司注册省份"),
    )
    city = models.ForeignKey(
        City,
        related_name="corporation_basic_city",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("城市"),
        help_text=_("公司注册城市"),
    )
    introduction = models.TextField(_("介绍"), max_length=5000, blank=True, null=True)
    website = models.CharField(_("主页"), max_length=128, blank=True, null=True)
    email = models.EmailField(_("邮件"), max_length=128, blank=True, null=True)
    office = models.CharField(_("办公地址"), max_length=200, blank=True, null=True)
    employees = models.PositiveIntegerField(_("员工数"), blank=True, null=True)
    main_business = models.TextField(_("主营业务"), max_length=5000, blank=True, null=True)
    business_scope = models.TextField(_("经营范围"), max_length=5000, blank=True, null=True)

    def __str__(self):
        return self.ts_code

    def website_url(self):
        website = str(self.website or "").strip().replace(" ", "")
        if not website:
            return None
        if website.lower().startswith(("http://", "https://")):
            return website
        return f"https://{website}"

    def to_dict(self):
        return {
            "id": self.id,
            "corporation": self.corporation.name if self.corporation else None,
            "ts_code": self.ts_code,
            "exchange": self.exchange,
            "chairman": self.chairman,
            "manager": self.manager,
            "secretary": self.secretary,
            "reg_capital": float(self.reg_capital) if self.reg_capital is not None else None,
            "setup_date": self.setup_date,
            "area": self.area.name if self.area else None,
            "city": self.city.name if self.city else None,
            "introduction": self.introduction,
            "website": self.website,
            "website_url": self.website_url(),
            "email": self.email,
            "office": self.office,
            "employees": self.employees,
            "main_business": self.main_business,
            "business_scope": self.business_scope,
        }
        
    def to_dict_short(self):
        return {
            "id": self.id,
            "ts_code": self.ts_code,
            "corporation": self.corporation.name if self.corporation else None,
            "setup_date": self.setup_date,
            "website": self.website,
            "website_url": self.website_url(),
            "area": self.area.name if self.area else None,
            "city": self.city.name if self.city else None,
            "main_business": self.main_business,
        }
        
    class Meta:
        ordering = ["ts_code"]
        verbose_name = _("公司基本信息")
        verbose_name_plural = verbose_name
        get_latest_by = "id"
        

class StockTradingHistory(models.Model):
    """股票交易历史"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    corporation = models.ForeignKey(
        Corporation,
        related_name="trading_history",
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
        max_digits=8,
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
    amount = models.DecimalField(
        _("金额"),
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=_("单位：元"),
    )
    adj_factor = models.DecimalField(
        _("复权因子"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
    # 复权价格
    # hfq: 后复权
    # qfq: 前复权
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
        max_digits=8,
        decimal_places=4,
        blank=True,
        null=True,
    )
    pct_change_qfq = models.DecimalField(
        _("价格变化%_qfq"),
        max_digits=8,
        decimal_places=4,
        blank=True,
        null=True,
    )

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
    freq = models.CharField(
        _("周期"),
        max_length=5,
        default="D",
        help_text=_("如 D 日线，W 周线，M 月线"),
    )
    
    def to_dict(self):
        return {
            "ts_code": self.ts_code,
            "trade_date": self.trade_date,
            "close_qfq": self.close_qfq,
            "pct_change_qfq": self.pct_change_qfq,
        }

    def __str__(self):
        return self.ts_code

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票交易历史")
        unique_together = ("trade_date", "ts_code", "freq")
        indexes = [
            models.Index(
                fields=["freq", "ts_code", "trade_date"],
                name="dst_trd_freq_code_date_idx",
            ),
        ]
        verbose_name_plural = verbose_name
        get_latest_by = "id"


class StockFundamentalHistory(models.Model):
    """公司基本面历史数据"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    corporation = models.ForeignKey(
        Corporation,
        related_name="fundamental_history",
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
        _("交易日期"),
        db_index=True,
        blank=True,
        null=True,
        help_text=_("如 2020-05-05"),
    )
    freq = models.CharField(
        _("周期"),
        max_length=10,  # <-- Increase from 5 to 10 to avoid "value too long" error
        default="D",
        help_text=_("如 D 日线，W 周线，M 月线"),
    )
    close = models.DecimalField(
        _("收盘价"),
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
    )
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
        help_text=_("单位：%"),
    )
    volume_ratio = models.DecimalField(
        _("量比"),
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
    ps = models.DecimalField(
        _("市销率"),
        max_digits=16,
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
    
    def to_dict(self):
        return {
            "id": self.id,
            "ts_code": self.ts_code,
            "trade_date": self.trade_date,
            "turnover_rate": self.turnover_rate,
            "volume_ratio": self.volume_ratio,
            "pe": self.pe,
            "pe_ttm": self.pe_ttm,
            "pb": self.pb,
            "ps": self.ps,
            "ps_ttm": self.ps_ttm,
            "total_mv": self.total_mv,
            "circ_mv": self.circ_mv,
        }
    
    def __str__(self):
        return f"{self.ts_code} | 换手率: {self.turnover_rate} | 市盈率: {self.pe} | 市净率: {self.pb} | 市销率: {self.ps}"

    def to_dict(self):
        return {
            "id": self.id,
            "ts_code": self.ts_code,
            "trade_date": self.trade_date,
            "freq": self.freq,
            "close": self.close,
            "turnover_rate": self.turnover_rate,
            "turnover_rate_f": self.turnover_rate_f,
            "volume_ratio": self.volume_ratio,
            "pe": self.pe,
            "pe_ttm": self.pe_ttm,
            "pb": self.pb,
            "ps": self.ps,
            "ps_ttm": self.ps_ttm,
            "dv_ratio": self.dv_ratio,
            "dv_ttm": self.dv_ttm,
            "total_share": self.total_share,
            "float_share": self.float_share,
            "free_share": self.free_share,
            "total_mv": round(self.total_mv / 1000, 2),
            "circ_mv": round(self.circ_mv / 1000, 2),
        }
    
    class Meta:
        ordering = ["-ts_code"]
        verbose_name = _("公司基本面")
        verbose_name_plural = verbose_name
        get_latest_by = "id"
        unique_together = (
            "ts_code",
            "trade_date",
            "freq",
        )


class StockCostHistory(models.Model):
    """股票成本历史数据"""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    ts_code = models.CharField(
        _("股票代码"),
        max_length=10,
        db_index=True,
        help_text=_("如 000001.SZ"),
    )
    corporation = models.ForeignKey(
        Corporation,
        related_name="cost_history",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("公司"),
        help_text=_("关联的股票公司信息"),
    )
    trade_date = models.DateField(
        _("交易日期"),
        db_index=True,
        help_text=_("如 2020-05-05"),
    )
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
    # is_pulled_by_client = models.BooleanField(
    #     _("是否由客户端拉取"),
    #     default=False,
    #     help_text=_("该数据是否由客户端拉取"),
    # )

    def __str__(self):
        return f"{self.ts_code} | {self.trade_date}"

    class Meta:
        ordering = ["-trade_date"]
        verbose_name = _("股票成本历史")
        verbose_name_plural = verbose_name
        unique_together = ("ts_code", "trade_date")
