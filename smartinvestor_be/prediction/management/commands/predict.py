import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prediction.utils.prediction_util import get_model_by_name, predict_stock_trend
from datastore.models import Corporation  # Adjust import path as needed


class Command(BaseCommand):
    help = "Predict stock using tscode, resume, and freq parameters"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="Stock code")
        parser.add_argument("--startwith", type=str, help="tscode to start with")
        parser.add_argument("--given_date", type=str, help="Given date")
        parser.add_argument("--model_name", type=str, help="Model name")
        parser.add_argument("--resume", type=str, help="Resume ts code")
        parser.add_argument("--freq", type=str, help="Frequency parameter")
        parser.add_argument("--v", type=str, help="Version parameter")
        parser.add_argument("--model_surfix", type=str, help="Model surfix parameter")

    def handle(self, *args, **options):
        tscode = options["tscode"]
        resume = options["resume"]
        freq = options["freq"]
        given_date = options["given_date"]
        model_name = options["model_name"] or "XGB"
        version = options["v"] or 1.1
        model_surfix = options["model_surfix"] or "model"
        start_with = options["startwith"]

        models = get_model_by_name(
            model_name=model_name,
            volatility="STDOPT",
            freq=freq,
            version=version,
            file_suffix=model_surfix,
        )

        def get_tscode_prefix(tscode):
            if tscode.startswith("688"):
                return "688"
            if tscode.startswith("3"):
                return "3"
            if tscode.startswith("60"):
                return "60"
            if tscode.startswith("0"):
                return "0"
            raise ValueError("Invalid ts code")

        try:
            if not freq:
                self.stdout.write(self.style.ERROR("Frequency (--freq) is required."))
                return

            def get_corporations(ts_code, start_with, resume):
                corporations = []
                qs = Corporation.objects.all().order_by("ts_code")
                if ts_code:
                    qs = qs.filter(ts_code=ts_code)
                
                if start_with:
                    qs = qs.filter(ts_code__startswith=start_with)
                    
                if resume:
                    try:
                        if not ts_code and resume:
                            qs = qs.filter(ts_code__gte=resume)
                    except ValueError:
                        pass
                corporations = list(qs)
                
                return corporations

            corporations = get_corporations(tscode, start_with, resume)
            project_root = (
                settings.BASE_DIR
                if hasattr(settings, "BASE_DIR")
                else os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
            for corp in corporations:
                self.stdout.write(f"Processing {corp.ts_code} - {corp.name}")
                try:
                    result = predict_stock_trend(
                        corp.ts_code,
                        corp=corp,
                        model=models.get(get_tscode_prefix(corp.ts_code)),
                        model_name=model_name,
                        given_date=given_date,
                        freq=freq,
                        version=version,
                        project_root=project_root,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"Prediction result: {result}")
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"Error predicting {corp.ts_code}: {e}")
                    )
                    continue
        except Exception as e:
            raise CommandError(f"Error during prediction: {e}")
