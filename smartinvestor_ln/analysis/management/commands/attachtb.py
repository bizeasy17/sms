from django.core.management.base import BaseCommand, CommandError
from analysis.models import StockCostFeature, StockFeatures, StockFundamentalFeature, StockTechFeature

from analysis.utils.analysis_utils import (
    attach_top_bottom,
)


class Command(BaseCommand):
    help = "Identify top and bottom assets based on time series analysis."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tscode", type=str, help="Time series code"
        )
        parser.add_argument(
            "--freq", type=str, required=True, help="Frequency (e.g., daily, weekly)"
        )
        parser.add_argument(
            "--distance",
            type=int,
            required=True,
            help="Distance for gain/loss calculation",
        )
        parser.add_argument(
            "--resume", type=str, help="Resume from last run"
        )

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        resume = options["resume"]
        distance = options["distance"]

        # Calculate tops and bottoms entry pct gain & loss
        # merge_multiple_datasets_with_top_bottoms(
        #     ts_code=ts_code, freq=freq, resume=resume, distance=distance
        # )
        fields = [field.name for field in StockCostFeature._meta.fields]
        print("features")
        for field in fields:
            print(f"- {field}")
        attach_top_bottom(ts_code=ts_code, freq=freq, resume=resume, distance=distance)
        self.stdout.write(
            self.style.SUCCESS(
                f"Running attach top bottom to feature list with ts_code={ts_code}, freq={freq}, resume from {resume}, distance={distance}"
            )
        )

        # TODO: Implement your analysis logic here