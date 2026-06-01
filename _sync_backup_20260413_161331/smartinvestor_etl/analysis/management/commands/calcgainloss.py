from django.core.management.base import BaseCommand, CommandError

from analysis.utils.analysis_utils import (
    calc_top_bottom_gain_loss,
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
            "--entry_type",
            type=str,
            required=True,
            help="Search Type, B for bottom, T for top",
        )
        parser.add_argument(
            "--resume", action="store_true", help="Resume from last run"
        )

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        entry_type = options["entry_type"]
        if entry_type not in ["B", "T"]:
            raise CommandError(
                "entry_type must be either 'B' for bottom or 'T' for top"
            )
        resume = options["resume"]

        # Calculate tops and bottoms entry pct gain & loss
        calc_top_bottom_gain_loss(
            ts_code=ts_code, freq=freq, entry_type=entry_type, resume=resume
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Running calculate_top_bottom_gain_loss_over_periods with ts_code={ts_code}, freq={freq}, entry_type={entry_type}, resume from {resume}"
            )
        )

        # TODO: Implement your analysis logic here
