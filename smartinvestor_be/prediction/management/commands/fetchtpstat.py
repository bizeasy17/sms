import os
from django.core.management.base import BaseCommand
import pandas as pd
from django.conf import settings
from datastore.models import Corporation
from prediction.models import StockGainLossQuantile
from users.models import User

class Command(BaseCommand):
    help = 'Fetch TP stat data'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--filename',
            type=str,
            help='Source of the TP stat data',
            required=True
        )

    def handle(self, *args, **options):
        # Your logic to fetch TP stat goes here
        filename = options['filename']
        
        try:
            filepath = os.path.join(settings.STATIC_ROOT, filename)
            df = pd.read_csv(filepath, encoding="utf-8")
            df = df.drop_duplicates()
            ts_codes = df["ts_code"].unique()
            corp_map = {
                corp.ts_code: corp
                for corp in Corporation.objects.filter(ts_code__in=ts_codes)
            }
            quantilelists = []
            for _, row in df.iterrows():
                corp = corp_map.get(row["ts_code"])
                if not corp:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Corporation not found for ts_code: {row['ts_code']}"
                        )
                    )
                    continue
                # Convert row to dict, exclude 'ts_code', assign to defaults
                row_dict = row.to_dict()
                row_dict.pop("ts_code", None)
                quantilelists.append(
                    StockGainLossQuantile(
                        ts_code=row["ts_code"],
                        corporation=corp,
                        **row_dict
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Prepared top bottom entry for ts_code: {row['ts_code']} {row['freq']} {row['quantile']}"
                    )
                )
            StockGainLossQuantile.objects.bulk_create(quantilelists, ignore_conflicts=True)
            self.stdout.write(
                self.style.SUCCESS("Successfully imported top bottom data")
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
        self.stdout.write(self.style.SUCCESS('Successfully fetched TP stat data'))