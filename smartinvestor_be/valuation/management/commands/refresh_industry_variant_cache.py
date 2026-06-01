import datetime
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count, Max
from django.utils import timezone

from datastore.models import StockFundamentalHistory, StockTradingHistory
from prediction.models import StockValuationSnapshotLatest
from valuation.models import IndustryVariantCache, IndustryVariantMetricDaily


def _to_positive_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _median(values):
    cleaned = sorted(v for v in values if isinstance(v, (int, float)))
    if not cleaned:
        return None
    n = len(cleaned)
    mid = n // 2
    if n % 2 == 1:
        return float(cleaned[mid])
    return float((cleaned[mid - 1] + cleaned[mid]) / 2.0)


class Command(BaseCommand):
    help = "Refresh persisted valuation-variant universe and daily metric medians."

    def add_arguments(self, parser):
        parser.add_argument("--market", default="CN", help="Market scope, default CN")
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=3650,
            help="How many days of history to rebuild per metric, default 3650",
        )
        parser.add_argument(
            "--metrics",
            default="pe,pb,close",
            help="Comma-separated metric list from pe,pb,close",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Full rebuild: clear market cache then rebuild",
        )

    def handle(self, *args, **options):
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        lookback_days = max(30, int(options.get("lookback_days") or 3650))
        full = bool(options.get("full"))

        requested_metrics = [
            str(item or "").strip().lower()
            for item in str(options.get("metrics") or "pe,pb,close").split(",")
        ]
        metrics = [item for item in requested_metrics if item in {"pe", "pb", "close"}]
        if not metrics:
            metrics = ["pe"]

        start_date = timezone.localdate() - datetime.timedelta(days=lookback_days)

        if full:
            IndustryVariantMetricDaily.objects.filter(market=market).delete()
            IndustryVariantCache.objects.filter(market=market).delete()

        variant_rows = list(
            StockValuationSnapshotLatest.objects.filter(market=market)
            .exclude(valuation_variant__isnull=True)
            .exclude(valuation_variant="")
            .values("valuation_variant", "industry_name", "industry_code", "industry_level", "compare_group")
            .annotate(
                member_count=Count("ts_code", distinct=True),
                max_match_score=Max("match_score"),
                source_updated_at=Max("updated_at"),
            )
            .order_by("valuation_variant")
        )

        active_variants = set()
        for row in variant_rows:
            variant_key = str(row.get("valuation_variant") or "").strip()
            if not variant_key:
                continue
            active_variants.add(variant_key)

            display_name = str(row.get("industry_name") or "").strip() or variant_key
            IndustryVariantCache.objects.update_or_create(
                market=market,
                variant_key=variant_key,
                defaults={
                    "display_name": display_name,
                    "industry_code": str(row.get("industry_code") or "").strip(),
                    "industry_level": str(row.get("industry_level") or "").strip(),
                    "compare_group": str(row.get("compare_group") or "").strip(),
                    "member_count": int(row.get("member_count") or 0),
                    "max_match_score": row.get("max_match_score"),
                    "source_updated_at": row.get("source_updated_at"),
                },
            )

        if active_variants:
            IndustryVariantCache.objects.filter(market=market).exclude(variant_key__in=active_variants).delete()
            IndustryVariantMetricDaily.objects.filter(market=market).exclude(variant_key__in=active_variants).delete()

        metric_cache_total = 0
        variant_qs = IndustryVariantCache.objects.filter(market=market).order_by("-member_count", "variant_key")

        for variant in variant_qs:
            ts_codes = list(
                StockValuationSnapshotLatest.objects.filter(
                    market=market,
                    valuation_variant=variant.variant_key,
                ).values_list("ts_code", flat=True).distinct()
            )
            if not ts_codes:
                continue

            for metric in metrics:
                by_date = defaultdict(list)

                if metric == "close":
                    rows = StockTradingHistory.objects.filter(
                        ts_code__in=ts_codes,
                        freq="D",
                        trade_date__gte=start_date,
                    ).values("trade_date", "close_qfq", "close")
                    for row in rows:
                        trade_date = row.get("trade_date")
                        if trade_date is None:
                            continue
                        value = _to_positive_float(row.get("close_qfq"))
                        if value is None:
                            value = _to_positive_float(row.get("close"))
                        if value is not None:
                            by_date[trade_date].append(value)
                else:
                    rows = StockFundamentalHistory.objects.filter(
                        ts_code__in=ts_codes,
                        freq="D",
                        trade_date__gte=start_date,
                    ).values("trade_date", metric)
                    for row in rows:
                        trade_date = row.get("trade_date")
                        if trade_date is None:
                            continue
                        value = _to_positive_float(row.get(metric))
                        if value is not None:
                            by_date[trade_date].append(value)

                IndustryVariantMetricDaily.objects.filter(
                    market=market,
                    variant_key=variant.variant_key,
                    metric=metric,
                    trade_date__gte=start_date,
                ).delete()

                create_rows = []
                for trade_date, values in by_date.items():
                    median_value = _median(values)
                    if median_value is None:
                        continue
                    create_rows.append(
                        IndustryVariantMetricDaily(
                            market=market,
                            variant_key=variant.variant_key,
                            metric=metric,
                            trade_date=trade_date,
                            median_value=round(float(median_value), 4),
                            sample_count=len(values),
                        )
                    )

                if create_rows:
                    IndustryVariantMetricDaily.objects.bulk_create(create_rows, batch_size=2000)
                    metric_cache_total += len(create_rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"industry_variant_cache refreshed: market={market}, variants={len(active_variants)}, metric_rows={metric_cache_total}, metrics={','.join(metrics)}, start_date={start_date}"
            )
        )
