from django.core.management.base import BaseCommand, CommandError

from analysis.utils.analysis_utils import (
    calc_top_bottom_gain_loss,
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
        parser.add_argument("--distance", type=int, required=True, help="Distance")
        parser.add_argument(
            "--look_for_period", type=int, help="Look for period"
        )
        parser.add_argument(
            "--entry_type",
            type=str,
            required=True,
            help="Search Type, B for bottom, T for top",
        )
        parser.add_argument(
            "--resume", type=str, help="Resume from last run"
        )

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        look_for_period = options["look_for_period"]
        entry_type = options["entry_type"].split(",")
        if any(et not in ["B", "T"] for et in entry_type):
            raise CommandError(
                "entry_type must be either 'B' for bottom or 'T' for top"
            )
        resume = options["resume"]
        distance = options["distance"]

        if not look_for_period:
            look_for_period = 20 if freq == "D" else 120 if freq == "W" else 240

        # Calculate tops and bottoms entry pct gain & loss
        for typ in entry_type:
            calc_top_bottom_gain_loss(
                ts_code=ts_code,
                freq=freq,
                entry_type=typ,
                look_for_period=look_for_period,
                resume=resume,
                distance=distance,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Running calculate_top_bottom_gain_loss_over_periods with ts_code={ts_code}, freq={freq}, entry_type={entry_type}, resume from {resume}"
            )
        )

        # TODO: Implement your analysis logic here
