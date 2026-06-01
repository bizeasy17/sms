from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from datastore.models import StockFundamentalHistory, StockTradingHistory


class Command(BaseCommand):
    help = "Fix weekly trade_date from one day to another for trading/fundamental tables"

    def add_arguments(self, parser):
        parser.add_argument("--source", type=str, default="2026-05-01")
        parser.add_argument("--target", type=str, default="2026-04-30")
        parser.add_argument("--freq", type=str, default="W")

    def handle(self, *args, **options):
        source = date.fromisoformat(options["source"])
        target = date.fromisoformat(options["target"])
        freq = str(options["freq"] or "W").upper()

        for model, label in (
            (StockTradingHistory, "trading"),
            (StockFundamentalHistory, "fundamental"),
        ):
            with transaction.atomic():
                source_qs = model.objects.filter(freq=freq, trade_date=source)
                before_source = source_qs.count()
                conflict_codes = list(
                    model.objects.filter(
                        freq=freq,
                        trade_date=target,
                        ts_code__in=source_qs.values("ts_code"),
                    ).values_list("ts_code", flat=True)
                )
                conflict_deleted = (
                    model.objects.filter(
                        freq=freq,
                        trade_date=source,
                        ts_code__in=conflict_codes,
                    ).delete()[0]
                    if conflict_codes
                    else 0
                )
                moved = model.objects.filter(freq=freq, trade_date=source).update(
                    trade_date=target
                )
                after_source = model.objects.filter(freq=freq, trade_date=source).count()
                after_target = model.objects.filter(freq=freq, trade_date=target).count()

            self.stdout.write(
                f"{label}: before_source={before_source} conflict_deleted={conflict_deleted} moved={moved} after_source={after_source} after_target={after_target}"
            )
