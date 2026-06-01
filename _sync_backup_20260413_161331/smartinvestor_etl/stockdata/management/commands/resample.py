import pandas as pd
from django.core.management.base import BaseCommand
from stockdata.utils.resample_util import (
    resample_funda_history,
    resample_stock_trading_history,
)
from stockdata.models import Corporation
from stockdata.models import StockTradingHistory
from datetime import timedelta
from datetime import datetime
from stockdata.models import StockFundamentalHistory


class Command(BaseCommand):
    help = "Resample stock price data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tscode",
            type=str,
            help="Resampling interval (e.g., D, W, M)",
        )
        parser.add_argument(
            "--freq",
            type=str,
            default="W-FRI",
            help="Resampling interval (e.g., D, W, M)",
        )
        parser.add_argument(
            "--month", type=str, help="Resampling given month (e.g., 01, 02, ..., 12)"
        )
        parser.add_argument(
            "--dtype",
            type=str,
            default="TRADING",
            help="Data type (e.g., trading, funda)",
        )
        parser.add_argument("--resume", type=str, help="The resume tscode")
        parser.add_argument(
            "--force", nargs="?", type=bool, default=False, help="Force resampling"
        )

    def handle(self, *args, **options):
        tscode = options["tscode"]
        freq = options["freq"]
        dtype = options["dtype"]
        resume = options["resume"]
        force = options["force"]
        month = [int(m) for m in options["month"].split(",")] if options["month"] else None

        # If freq is 'W-FRI' and today is not Friday, Saturday, or Sunday, return early
        if freq == "W-FRI" and not force:
            today = datetime.today().weekday()  # Monday=0, Sunday=6
            if today not in (4, 5, 6):  # 4=Friday, 5=Saturday, 6=Sunday
                self.stdout.write(
                    self.style.WARNING(
                        "Today is not Friday, Saturday, or Sunday. Exiting."
                    )
                )
                return

        # If freq is 'M' and today is not the end of the month, return early
        if freq == "ME" and not force:
            if month:
                today = datetime.today()
                if not force and today.month != int(month[0]):
                    self.stdout.write(
                        self.style.WARNING(
                            f"Today is not the specified month ({month[0]}). Exiting."
                        )
                    )
                    return
            else:
                today = datetime.today()
                next_day = today + timedelta(days=1)
                if next_day.month == today.month:
                    self.stdout.write(
                        self.style.WARNING("Today is not the end of the month. Exiting.")
                    )
                    return

        # Example: Resample all stock prices by date
        # Determine queryset of corporations
        if tscode:
            corporations = Corporation.objects.filter(ts_code=tscode)
        else:
            filter_kwargs = {"ts_code__gte": resume} if resume else {}
            corporations = Corporation.objects.filter(**filter_kwargs)

        for corp in corporations:
            self.stdout.write(
                self.style.SUCCESS(f"Starting resampling: {corp.ts_code}")
            )
            if dtype == "TRADING":
                try:
                    # Call the trading resampling function
                    # Get the latest trading history record for this corporation
                    latest = (
                        StockTradingHistory.objects.filter(
                            ts_code=corp.ts_code, corporation=corp, freq=freq[0]
                        )
                        .order_by("-trade_date")
                        .first()
                    )
                    start_date = (
                        latest.trade_date + timedelta(days=1)
                        if latest
                        else corp.list_date
                    )
                    qs = StockTradingHistory.objects.filter(
                        corporation=corp, trade_date__gte=start_date, freq="D"
                    )
                    df = pd.DataFrame(list(qs.values()))
                    if df.empty:
                        continue
                    resampled_df = resample_stock_trading_history(corp.ts_code, df, freq)
                    for _, row in resampled_df.iterrows():
                        # If month is specified, only handle rows where trade_date's month matches
                        if month is not None:
                            if pd.to_datetime(row["trade_date"]).month not in month:
                                continue
                        # Convert NaN values to None for Django DecimalFields
                        clean_row = {
                            k: (None if pd.isna(row[k]) else row[k])
                            for k in row.index
                            if k not in ["id", "trade_date", "ts_code", "freq", "corporation", "is_pulled_by_client", "corporation_id"]
                        }
                          
                        StockTradingHistory.objects.update_or_create(
                            corporation=corp,
                            ts_code=corp.ts_code,
                            freq=freq[0],
                            trade_date=row["trade_date"],
                            is_pulled_by_client=False,
                            defaults=clean_row,
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error resampling {corp.ts_code} stock prices for {freq}: {e}"
                        )
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Resampled {corp.ts_code} stock prices for {freq}."
                    )
                )
            elif dtype == "FUNDA":
                try:
                    # Call the fundamental resampling function
                    latest_funda = (
                        StockFundamentalHistory.objects.filter(
                            ts_code=corp.ts_code, corporation=corp, freq=freq[0]
                        )
                        .order_by("-trade_date")
                        .first()
                    )
                    if latest_funda:
                        start_date = latest_funda.trade_date + timedelta(days=1)
                    else:
                        start_date = corp.list_date

                    funda_qs = StockFundamentalHistory.objects.filter(
                        ts_code=corp.ts_code,
                        corporation=corp,
                        trade_date__gte=start_date,
                        freq="D",
                    )
                    funda_df = pd.DataFrame(list(funda_qs.values()))
                    if funda_df.empty:
                        continue
                    resampled = resample_funda_history(funda_df, freq)
                    for _, row in resampled.iterrows():
                        if month is not None:
                            if pd.to_datetime(row["trade_date"]).month not in month:
                                continue
                        StockFundamentalHistory.objects.update_or_create(
                            corporation=corp,
                            ts_code=corp.ts_code,
                            freq=freq[0],
                            trade_date=row["trade_date"],
                            is_pulled_by_client=False,
                            defaults={
                                k: row[k]
                                for k in row.index
                                if k
                                not in [
                                    "id",
                                    "trade_date",
                                    "ts_code",
                                    "freq",
                                    "corporation",
                                ]
                            },
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error resampling {corp.ts_code} stock fundamental data for {freq}: {e}"
                        )
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Resampled {corp.ts_code} stock fundamental data for {freq}."
                    )
                )
        self.stdout.write(self.style.SUCCESS("Resampling complete for all stocks."))
