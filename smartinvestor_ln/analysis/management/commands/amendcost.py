from datetime import datetime
import pandas as pd
import numpy as np
from django.core.management.base import BaseCommand, CommandError

from analysis.utils.data_util import calculate_moving_quantiles, get_multi_type_data
from analysis.models import StockFeatures
from stockdata.models import Corporation
from stockdata.models import StockCostHistory
from analysis.utils.stock_util import calc_tech_indicators  # Import the function


class Command(BaseCommand):
    help = "Combine data for a given ts_code"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="The ts_code to process")
        parser.add_argument(
            "--freq", type=str, help="Frequency of the data, e.g. D, W-FRI"
        )
        parser.add_argument("--resume", type=str, help="Resume from a specific ts_code")

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        resume = options["resume"]
        # Your data combining logic here

        if ts_code:
            corporations = [Corporation.objects.get(ts_code=ts_code)]
        else:
            corporations = list(Corporation.objects.all())
            if resume:
                try:
                    corporations = [c for c in corporations if c.ts_code >= resume]
                except ValueError:
                    pass
        for corp in corporations:
            print(
                f"start company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
            )

            # Fetch cost history queryset for the corporation
            cost_history_qs = StockCostHistory.objects.filter(
                ts_code=corp.ts_code, freq=freq
            ).order_by("trade_date")

            if not cost_history_qs.exists():
                print(f"No cost history found for {corp.ts_code}")
                continue

            # Fetch StockFeatures queryset for this corp and freq
            features_qs = StockFeatures.objects.filter(
                ts_code=corp.ts_code, freq=freq
            ).order_by("trade_date")

            if not features_qs.exists():
                print(f"No StockFeatures found for {corp.ts_code} with freq {freq}")
                continue

            # Map trade_date to StockFeatures objects for quick lookup
            features_map = {f.trade_date: f for f in features_qs}

            updated = []
            cost_cols = [
                "his_low",
                "his_high",
                "cost_5pct",
                "cost_15pct",
                "cost_50pct",
                "cost_85pct",
                "cost_95pct",
                "weight_avg",
                "winner_rate",
            ]

            for cost in cost_history_qs:
                feature = features_map.get(cost.trade_date)
                if feature:
                    for col in cost_cols:
                        setattr(feature, col, getattr(cost, col))
                    updated.append(feature)

            if updated:
                StockFeatures.objects.bulk_update(updated, cost_cols)

            if updated:
                print(f"updated {len(updated)} records")
                print(
                    f"updated {corp.ts_code}, end company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
                )
        self.stdout.write(
            self.style.SUCCESS(f"Successfully processed ts_code: {ts_code}")
        )
