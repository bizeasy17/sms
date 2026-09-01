from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from datastore.models import Corporation, StockTradingHistory
from stock_extremes.models import StockExtremeSnapshot
from stock_extremes.services.extreme_calculator import StockExtremeAccumulator


PRICE_FIELDS = {
    "qfq": "close_qfq",
    "hfq": "close_hfq",
    "raw": "close",
}
SNAPSHOT_FIELDS = [
    "name",
    "daily_max_return",
    "daily_min_return",
    "weekly_max_return",
    "weekly_min_return",
    "monthly_max_return",
    "monthly_min_return",
    "max_runup",
    "max_drawdown",
    "source_start_date",
    "source_end_date",
    "price_type",
    "calculated_at",
]


class Command(BaseCommand):
    help = "Refresh persisted A-share historical extreme snapshots"

    def add_arguments(self, parser):
        parser.add_argument("--price-type", choices=PRICE_FIELDS, default="qfq")
        parser.add_argument("--ts-code", help="Refresh one stock code only")
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        price_type = options["price_type"]
        price_field = PRICE_FIELDS[price_type]
        ts_code = options.get("ts_code")
        batch_size = max(options["batch_size"], 1)

        stock_codes = Corporation.objects.values("ts_code")
        queryset = StockTradingHistory.objects.filter(
            freq__in=("D", "W", "M"),
            ts_code__in=stock_codes,
        )
        if ts_code:
            queryset = queryset.filter(ts_code=ts_code.upper())
        rows = queryset.exclude(**{f"{price_field}__isnull": True}).order_by(
            "freq", "ts_code", "trade_date"
        ).values_list("freq", "ts_code", "trade_date", price_field)

        accumulators = {}
        previous_prices = {}
        for frequency, code, trade_date, raw_price in rows.iterator(chunk_size=5000):
            price = Decimal(raw_price)
            if price <= 0:
                continue
            accumulator = accumulators.setdefault(code, StockExtremeAccumulator())
            previous_key = (frequency, code)
            previous_price = previous_prices.get(previous_key)
            if previous_price is not None:
                accumulator.add_return(frequency, price / previous_price - Decimal("1"))
            previous_prices[previous_key] = price
            if frequency == "D":
                accumulator.add_daily_price(trade_date, price)

        names = dict(Corporation.objects.filter(ts_code__in=accumulators).values_list("ts_code", "name"))
        calculated_at = timezone.now()
        snapshots = [
            StockExtremeSnapshot(
                ts_code=code,
                name=names.get(code, ""),
                daily_max_return=result.daily_max_return,
                daily_min_return=result.daily_min_return,
                weekly_max_return=result.weekly_max_return,
                weekly_min_return=result.weekly_min_return,
                monthly_max_return=result.monthly_max_return,
                monthly_min_return=result.monthly_min_return,
                max_runup=result.max_runup,
                max_drawdown=result.max_drawdown,
                source_start_date=result.source_start_date,
                source_end_date=result.source_end_date,
                price_type=price_type,
                calculated_at=calculated_at,
            )
            for code, result in accumulators.items()
        ]
        StockExtremeSnapshot.objects.bulk_create(
            snapshots,
            batch_size=batch_size,
            update_conflicts=True,
            unique_fields=["ts_code"],
            update_fields=SNAPSHOT_FIELDS,
        )
        self.stdout.write(self.style.SUCCESS(f"Refreshed {len(snapshots)} stock extreme snapshots"))
