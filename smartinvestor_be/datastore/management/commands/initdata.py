from django.conf import settings
from django.core.management.base import BaseCommand
import requests

from datastore.utils.remote_utils import (
    save_cost_data_from_response,
    save_trading_history_from_response,
    save_fundamental_data_from_response,
)
from datastore.models import Corporation
from datetime import datetime

# BASE_ETL_URL = "http://127.0.0.1:8000/api/"


class Command(BaseCommand):
    help = "Fetch stock and fundamental data from ETL database via API endpoint"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="Stock TS code")
        parser.add_argument("--resume", type=str, help="Resume date (YYYYMMDD)")
        parser.add_argument(
            "--freq", type=str, default="D", help="Data frequency (e.g., daily, weekly)"
        )

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        resume = options["resume"]
        freq = options["freq"]

        def fetch_and_save(
            corporations, url_template, save_func, data_type, inited_field
        ):
            for corp in corporations:
                if hasattr(settings, "INIT_DATA_LIMIT") and settings.INIT_DATA_LIMIT:
                    date_from = datetime.today().strftime("%Y-%m-%d")
                else:
                    date_from = corp.list_date
                api_url = url_template.format(
                    ts_code=corp.ts_code, freq=freq, data_from=date_from
                )
                try:
                    response = requests.get(api_url, timeout=30)
                    response.raise_for_status()
                    print(f"Fetched {data_type} data from {api_url}")
                    save_func(response, corp, freq)
                    setattr(corp, inited_field, True)
                    corp.save(update_fields=[inited_field])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Fetched {data_type} records from ETL API. for {corp.ts_code}"
                        )
                    )
                except requests.RequestException as e:
                    self.stderr.write(
                        self.style.ERROR(f"Failed to fetch {data_type} data: {e}")
                    )
                    continue
                except Exception as e:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Failed to save {data_type} data: {e} for {corp.ts_code}"
                        )
                    )
                    continue

        def get_corporations(ts_code, inited_field, resume):
            qs = Corporation.objects.filter(**{inited_field: False}).order_by("ts_code")
            if ts_code:
                qs = qs.filter(ts_code=ts_code)
            corporations = list(qs)
            if resume:
                try:
                    idx = [c.ts_code for c in corporations].index(resume)
                    corporations = corporations[idx:]
                except ValueError:
                    pass
            return corporations

        # Trading history
        freq_field_map = {
            "D": "trading_inited",
            "W": "weekly_trading_inited",
            "M": "monthly_trading_inited",
        }
        inited_field = freq_field_map.get(freq, "trading_inited")
        trading_corporations = get_corporations(ts_code, inited_field, resume)
        if not trading_corporations:
            self.stdout.write(
                self.style.WARNING("No corporations to process for trading. Exiting.")
            )

        fetch_and_save(
            trading_corporations,
            f"{settings.ETL_BASE_URL}"
            + "/stocks/{ts_code}/trades/{freq}/{data_from}/limit/"
            + f"{settings.INIT_DATA_LIMIT}/?format=json",
            save_trading_history_from_response,
            "trading history",
            inited_field,
        )

        freq_field_map = {
            "D": "funda_inited",
            "W": "weekly_funda_inited",
            "M": "monthly_funda_inited",
        }
        inited_field = freq_field_map.get(freq, "funda_inited")
        # Fundamental data
        fundamental_corporations = get_corporations(ts_code, inited_field, resume)
        if not fundamental_corporations:
            self.stdout.write(
                self.style.WARNING("No corporations to process for fundamentals. Exiting.")
            )
        fetch_and_save(
            fundamental_corporations,
            f"{settings.ETL_BASE_URL}"
            + "/stocks/{ts_code}/fundamentals/{freq}/{data_from}/limit/"
            + f"{settings.INIT_DATA_LIMIT}/?format=json",
            save_fundamental_data_from_response,
            "fundamental",
            inited_field,
        )
        
        freq_field_map = {
            "D": "cost_inited",
            "W": "weekly_cost_inited",
            "M": "monthly_cost_inited",
        }
        inited_field = freq_field_map.get(freq, "cost_inited")
        # 成本数据
        cost_corporations = get_corporations(ts_code, inited_field, resume)
        if not cost_corporations:
            self.stdout.write(
                self.style.WARNING("No corporations to process for costs. Exiting.")
            )
        fetch_and_save(
            cost_corporations,
            f"{settings.ETL_BASE_URL}"
            + "/stocks/{ts_code}/cost/{freq}/{data_from}/limit/"
            + f"{settings.INIT_DATA_LIMIT}/?format=json",
            save_cost_data_from_response,
            "cost",
            inited_field,
        )
