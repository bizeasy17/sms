from django.core.management.base import BaseCommand, CommandError

from analysis.utils.analysis_utils import (
    refine_top_bottom_extremes_by_price,
)


class Command(BaseCommand):
    help = "Identify top and bottom assets based on time series analysis."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tscode", type=str, required=True, help="Time series code"
        )
        parser.add_argument(
            "--freq", type=str, required=True, help="Frequency (e.g., daily, weekly)"
        )
        parser.add_argument(
            "--period",
            type=int,
            required=False,
            help="Period for gain/loss calculation",
        )
        parser.add_argument(
            "--resume", action="store_true", help="Resume from last run"
        )

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        resume = options["resume"]
        period = options["period"]

        # Calculate tops and bottoms entry pct gain & loss
        refine_top_bottom_extremes_by_price(
            ts_code=ts_code, freq=freq, resume=resume, period=period
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Running refine_top_bottom_extremes_by_price with ts_code={ts_code}, freq={freq}, resume from {resume}, period={period}"
            )
        )

        # TODO: Implement your analysis logic here