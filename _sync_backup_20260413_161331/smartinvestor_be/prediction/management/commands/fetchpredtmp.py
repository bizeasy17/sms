from django.core.management.base import BaseCommand
import requests

from datastore.models import Corporation
import json
from datetime import datetime
from prediction.models import StockPrediction


class Command(BaseCommand):
    help = "Custom management command for prediction (template)"

    def add_arguments(self, parser):
        # Add command line arguments here if needed
        parser.add_argument("--tscode", type=str, help="Stock TS code")
        parser.add_argument("--freq", type=str, help="Frequency")
        parser.add_argument("--resume", type=str, help="Resume ts code")

    def handle(self, *args, **options):

        ts_code = options["tscode"]
        resume = options["resume"]
        freq = options["freq"]
        period = 30
        volatility = "STDOPT"

        api_url = "http://127.0.0.1:8000/api/predict/{ts_code}" + f"/{freq}/{volatility}/{period}/XGB/?format=json"

        def get_corporations(ts_code, resume):
            qs = Corporation.objects.filter(ts_code=ts_code).order_by("ts_code")
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

        def parse_prediction_json(json_str):
            """
            Parses the prediction JSON string returned from the server.

            Args:
                json_str (str): JSON string to parse.

            Returns:
                list[dict]: List of parsed prediction records with formatted dates.
            """
            try:
                records = json.loads(json_str)
                for record in records:
                    # Convert trade_date to datetime object if needed
                    if "trade_date" in record:
                        try:
                            record["trade_date"] = datetime.strptime(
                                record["trade_date"], "%Y-%m-%dT%H:%M:%S.%f"
                            )
                        except ValueError:
                            # Fallback if microseconds are missing
                            record["trade_date"] = datetime.strptime(
                                record["trade_date"], "%Y-%m-%dT%H:%M:%S"
                            )
                return records
            except (json.JSONDecodeError, TypeError):
                return []

        # Trading history
        corps = get_corporations(ts_code, resume)
        # Add your prediction logic here, using the api_url and trading_corporations as needed
        for corp in corps:
            api_url = api_url.format(ts_code=corp.ts_code)

            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Process the prediction data as needed
                # records = parse_prediction_json(data)
                records = data
                for record in records:
                    record["freq"] = freq
                    record["volatility"] = volatility
                    record["applied_model"] = "XGB"
                    record["model_version"] = "1.1"
                    record["is_temp"] = True
                    if "row" in record:
                        del record["row"]
                for record in records:
                    StockPrediction.objects.update_or_create(
                        corporation=corp,
                        trade_date=record["trade_date"].split("T")[0],
                        confidence=0.6,
                        defaults={k: v for k, v in record.items() if k != "trade_date"},
                    )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error fetching prediction data for {corp.ts_code}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS("Prediction command executed successfully.")
        )
