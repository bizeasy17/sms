from django.conf import settings
from django.db import models

from prediction.models import (
    AnnualOutlookSnapshot,
    BacktestValuationSnapshot,
    StockValuationSnapshot,
    StockValuationSnapshotHistory,
    StockValuationSnapshotLatest,
)


def _resolve_prefix():
    prefix = str(getattr(settings, "VALUATION_TABLE_PREFIX", "prediction") or "prediction").strip().lower()
    if prefix not in {"prediction", "valuation"}:
        return "prediction"
    return prefix


def _apply_table_prefix(prefix):
    BacktestValuationSnapshot._meta.db_table = f"{prefix}_backtestvaluationsnapshot"
    AnnualOutlookSnapshot._meta.db_table = f"{prefix}_annualoutlooksnapshot"
    StockValuationSnapshot._meta.db_table = f"{prefix}_stockvaluationsnapshot"
    StockValuationSnapshotHistory._meta.db_table = f"{prefix}_stockvaluationsnapshothistory"
    StockValuationSnapshotLatest._meta.db_table = f"{prefix}_stockvaluationsnapshotlatest"


_apply_table_prefix(_resolve_prefix())


class ValuationFundBasic(models.Model):
    ts_code = models.CharField(max_length=16, primary_key=True)
    name = models.CharField(max_length=128, blank=True, default="")
    management = models.CharField(max_length=128, blank=True, default="")
    custodian = models.CharField(max_length=128, blank=True, default="")
    fund_type = models.CharField(max_length=64, blank=True, default="")
    found_date = models.CharField(max_length=8, blank=True, default="")
    due_date = models.CharField(max_length=8, blank=True, default="")
    status = models.CharField(max_length=16, blank=True, default="")
    market = models.CharField(max_length=8, blank=True, default="")
    is_updated = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "valuation_fund_basic"
        indexes = [
            models.Index(fields=["name"], name="vfb_name_idx"),
            models.Index(fields=["status"], name="vfb_status_idx"),
        ]


class ValuationFundPortfolio(models.Model):
    fund_ts_code = models.CharField(max_length=16)
    stock_ts_code = models.CharField(max_length=16)
    stock_symbol = models.CharField(max_length=16, blank=True, default="")
    end_date = models.CharField(max_length=8)
    ann_date = models.CharField(max_length=8, blank=True, default="")
    mkv = models.FloatField(null=True, blank=True)
    amount = models.FloatField(null=True, blank=True)
    stk_mkv_ratio = models.FloatField(null=True, blank=True)
    stk_float_ratio = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_fund_portfolio"
        unique_together = ("fund_ts_code", "stock_ts_code", "end_date")
        indexes = [
            models.Index(fields=["stock_ts_code", "end_date"], name="vfp_stock_end_idx"),
            models.Index(fields=["fund_ts_code", "end_date"], name="vfp_fund_end_idx"),
        ]


class ValuationFundNav(models.Model):
    fund_ts_code = models.CharField(max_length=16)
    nav_date = models.CharField(max_length=8)
    unit_nav = models.FloatField(null=True, blank=True)
    accum_nav = models.FloatField(null=True, blank=True)
    adj_nav = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "valuation_fund_nav"
        unique_together = ("fund_ts_code", "nav_date")
        indexes = [
            models.Index(fields=["fund_ts_code", "nav_date"], name="vfn_fund_navdate_idx"),
        ]


class IndustryVariantCache(models.Model):
    market = models.CharField(max_length=8, default="CN")
    variant_key = models.CharField(max_length=128)
    display_name = models.CharField(max_length=128, blank=True, default="")
    industry_code = models.CharField(max_length=32, blank=True, default="")
    industry_level = models.CharField(max_length=8, blank=True, default="")
    compare_group = models.CharField(max_length=32, blank=True, default="")
    member_count = models.IntegerField(default=0)
    max_match_score = models.FloatField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "valuation_industry_variant_cache"
        unique_together = ("market", "variant_key")
        indexes = [
            models.Index(fields=["market", "variant_key"], name="viv_mkt_variant_idx"),
            models.Index(fields=["market", "member_count"], name="viv_mkt_member_idx"),
        ]


class IndustryVariantMetricDaily(models.Model):
    market = models.CharField(max_length=8, default="CN")
    variant_key = models.CharField(max_length=128)
    metric = models.CharField(max_length=16)
    trade_date = models.DateField()
    median_value = models.FloatField(null=True, blank=True)
    sample_count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "valuation_industry_variant_metric_daily"
        unique_together = ("market", "variant_key", "metric", "trade_date")
        indexes = [
            models.Index(fields=["market", "variant_key", "metric", "trade_date"], name="vivmd_main_idx"),
            models.Index(fields=["market", "metric", "trade_date"], name="vivmd_mkt_metric_idx"),
        ]

__all__ = [
    "BacktestValuationSnapshot",
    "AnnualOutlookSnapshot",
    "StockValuationSnapshot",
    "StockValuationSnapshotHistory",
    "StockValuationSnapshotLatest",
    "ValuationFundBasic",
    "ValuationFundPortfolio",
    "ValuationFundNav",
    "IndustryVariantCache",
    "IndustryVariantMetricDaily",
]
