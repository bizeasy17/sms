from django.conf import settings
from django.core.management.base import BaseCommand
import requests
from datetime import timedelta
from datastore.models import StockCostHistory, StockFundamentalHistory, StockTradingHistory
from datastore.models import Corporation

from datastore.utils.remote_utils import (
    save_cost_data_from_response,
    save_trading_history_from_response,
    save_fundamental_data_from_response,
    update_pull_status,
)

# BASE_ETL_URL = "http://127.0.0.1:8000/api/"


class Command(BaseCommand):
    help = "Fetch stock and fundamental data from ETL database via API endpoint"

    @staticmethod
    def _is_no_unpulled_404(err, url):
        response = getattr(err, "response", None)
        return (
            isinstance(err, requests.HTTPError)
            and response is not None
            and response.status_code == 404
            and "all-not-pulled" in str(url or "")
        )

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="Stock TS code")
        parser.add_argument("--freq", type=str, help="Frequency (e.g., daily, weekly)")
        parser.add_argument(
            "--dtype",
            type=str,
            default="trading",
            help="Data type (trading or fundamental)",
        )
        parser.add_argument("--batch", type=bool, help="Whether to run in batch mode")

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        dtype = options["dtype"]
        batch = options["batch"]

        api_base = settings.ETL_BASE_URL

        if batch:
            endpoints = []
            if dtype == "trading" or dtype is None:
                endpoints.append(
                    (
                        "trading",
                        f"{api_base}/stocks/trades/{freq}/all-not-pulled/?format=json",
                        save_trading_history_from_response,
                        f"{api_base}/stocks/trades/pull-status/update/{freq}/",
                    )
                )
            if dtype == "fundamental" or dtype is None:
                endpoints.append(
                    (
                        "fundamental",
                        f"{api_base}/stocks/fundamentals/{freq}/all-not-pulled/?format=json",
                        save_fundamental_data_from_response,
                        f"{api_base}/stocks/fundamentals/pull-status/update/{freq}/",
                    )
                )
            if dtype == "cost" or dtype is None:   
                endpoints.append(
                    (
                        "cost",
                        f"{api_base}/stocks/cost/{freq}/all-not-pulled/?format=json",
                        save_cost_data_from_response,
                        f"{api_base}/stocks/cost/pull-status/update/{freq}/",
                    )
                )
            if not endpoints:
                self.stderr.write(
                    self.stderr.write(
                        f"Unknown dtype '{dtype}'. Must be 'trading', 'fundamental', or omitted."
                    )
                )
                return

            for label, url, save_func, callback_url in endpoints:
                self.stdout.write(f"Batch fetching {label} data from {url}\n")
                try:
                    resp = requests.get(url, timeout=60)
                    resp.raise_for_status()
                    success_codes = save_func(resp, corp=None, freq=freq)
                    status = update_pull_status(callback_url, success_codes)
                    if status:
                        self.stdout.write(
                            f"Batch fetched {label} records from ETL API: {success_codes}\n"
                        )
                    else:
                        self.stderr.write(
                            f"Failed to update pull status for {label} data.\n"
                        )
                except requests.RequestException as e:
                    if self._is_no_unpulled_404(e, url):
                        self.stdout.write(
                            f"No unpulled {label} data from ETL, skip batch pull.\n"
                        )
                        continue
                    self.stderr.write(f"Failed to batch fetch {label} data: {e}\n")
        else:
            corporations = (
                Corporation.objects.filter(ts_code=ts_code)
                if ts_code
                else Corporation.objects.all()
            )

            if not corporations.exists():
                self.stderr.write("No Corporation(s) found for the given ts_code.\n")
                return

            def get_next_date(model, ts_code, freq, label):
                latest = (
                    model.objects.filter(ts_code=ts_code, freq=freq)
                    .order_by("-trade_date")
                    .first()
                )
                if latest and latest.trade_date:
                    next_date = (latest.trade_date + timedelta(days=1)).strftime(
                        "%Y-%m-%d"
                    )
                    self.stdout.write(
                        f"Auto-selected 'date_from' for {ts_code} ({label}): {next_date}\n"
                    )
                    return next_date
                self.stderr.write(
                    f"No {label} history found to determine 'date_from'. Need to initdata first.\n"
                )
                return None

            for corp in corporations:
                ts_code = corp.ts_code
                date_from_trade = get_next_date(
                    StockTradingHistory, ts_code, freq, "trading"
                )
                date_from_funda = get_next_date(
                    StockFundamentalHistory, ts_code, freq, "fundamental"
                )
                date_from_cost = get_next_date(StockCostHistory, ts_code, freq, "cost")
                if not date_from_trade or not date_from_funda:
                    continue

                endpoints = []
                if dtype == "trading" or dtype is None:
                    endpoints.append(
                        (
                            "trading",
                            f"{api_base}/stocks/{ts_code}/trades/{freq}/{date_from_trade}/?format=json",
                            save_trading_history_from_response,
                        )
                    )
                if dtype == "fundamental" or dtype is None:
                    endpoints.append(
                        (
                            "fundamental",
                            f"{api_base}/stocks/{ts_code}/fundamentals/{freq}/{date_from_funda}/?format=json",
                            save_fundamental_data_from_response,
                        )
                    )
                if dtype == "cost" or dtype is None:   
                    endpoints.append(
                        (
                            "cost",
                            f"{api_base}/stocks/{ts_code}/cost/{freq}/{date_from_cost}/?format=json",
                            save_cost_data_from_response,
                        )
                    )

                if not endpoints:
                    self.stderr.write(
                        f"Unknown dtype '{dtype}'. Must be 'trading', 'fundamental', or omitted.\n"
                    )
                    continue

                try:
                    for label, url, save_func in endpoints:
                        self.stdout.write(f"Fetching {label} data from {url}\n")
                        resp = requests.get(url, timeout=30)
                        resp.raise_for_status()
                        save_func(resp, corp)
                    self.stdout.write(
                        f"Fetched {', '.join([e[0] for e in endpoints])} records for {ts_code} from ETL API.\n"
                    )
                except requests.RequestException as e:
                    self.stderr.write(f"Failed to fetch data for {ts_code}: {e}\n")
