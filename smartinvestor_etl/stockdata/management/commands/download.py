from datetime import date, timedelta
from django.core.management.base import BaseCommand, CommandError

from utils.data_utils import (
    fetch_and_store_cyq_data,
    fetch_and_store_daily_trading_history,
    fetch_and_store_fundamental_data,
)
from time import sleep


class Command(BaseCommand):
    help = "Describe the purpose of your command here"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tscode", type=str, help="Stock code to download data for"
        )
        parser.add_argument(
            "--freq", type=str, help="Frequency of the data (e.g., daily, weekly)"
        )
        parser.add_argument(
            "--dtype",
            type=str,
            default="TRADING",
            help="Type of data (e.g., price, volume)",
        )
        parser.add_argument(
            "--trade_date", type=str, help="Trade date (format: YYYYMMDD)"
        )
        parser.add_argument(
            "--start_date",
            type=str,
            help="Start date for data retrieval (format: YYYYMMDD)",
        )
        parser.add_argument(
            "--end_date",
            type=str,
            help="End date for data retrieval (format: YYYYMMDD)",
        )
        parser.add_argument("--env", type=str, help="Environment")
        parser.add_argument(
            "--resume", type=str, help="Resume from a specific date or point"
        )
        parser.add_argument(
            "--max_backfill_days",
            type=int,
            default=0,
            help="Max lookback days for implicit backfill when no date args are provided (0 means no cap)",
        )

    def handle(self, *args, **options):
        ts_code = options.get("tscode")
        freq = options.get("freq")
        dtype = options.get("dtype")
        trade_date = options.get("trade_date")
        start_date = options.get("start_date")
        end_date = options.get("end_date")
        resume = options.get("resume")
        env = options.get("env")
        max_backfill_days = options.get("max_backfill_days")

        # Validate arguments
        if not dtype or (dtype.upper() == "TRADING" and not freq):
            msg = (
                "The '--dtype' argument is required."
                if not dtype
                else "The '--freq' argument is required when dtype is 'TRADING'."
            )
            self.stderr.write(self.style.ERROR(msg))
            return
        
        # Default behavior for scheduled daily runs:
        # if no explicit date args are provided, backfill as a range ending today
        # from each symbol's local next missing trade_date.
        if not trade_date and not start_date and not end_date:
            end_date = date.today().strftime("%Y%m%d")
            if max_backfill_days and max_backfill_days > 0:
                start_date = (date.today() - timedelta(days=max_backfill_days)).strftime(
                    "%Y%m%d"
                )

        # Your command logic here
        try:
            if dtype.upper() == "TRADING":
                if freq == "D":
                    fetch_and_store_daily_trading_history(
                        ts_code=ts_code,
                        freq=freq,
                        trade_date=trade_date,
                        start_date=start_date,
                        end_date=end_date,
                        resume=resume,
                    )
                    #
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully processed trading data for {ts_code} in frequency {freq}"
                        )
                    )
                elif freq in ["W", "M"]:
                    # Implement weekly data fetching logic here
                    # resample_and_store_trading_history(
                    #     ts_code=ts_code,
                    #     start_date=start_date,
                    #     end_date=end_date,
                    #     freq=freq,
                    #     resume=resume,
                    # )
                    pass
            elif dtype.upper() == "FUNDAMENTAL":
                # Implement fundamental data fetching logic here
                fetch_and_store_fundamental_data(
                    ts_code=ts_code,
                    freq=freq,
                    trade_date=trade_date,
                    start_date=start_date,
                    end_date=end_date,
                    resume=resume,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully processed fundamental data for {ts_code} in frequency {freq}"
                    )
                )
            elif dtype.upper() == "CYQ":
                # Implement CYQ data fetching logic here
                fetch_and_store_cyq_data(
                    ts_code=ts_code,
                    freq=freq,
                    trade_date=trade_date,
                    start_date=start_date,
                    end_date=end_date,
                    resume=resume,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully processed CYQ data for {ts_code} in frequency {freq}"
                    )
                )
        except (ValueError, IOError) as e:
            raise CommandError(f"Error processing trading download: {e}") from e
