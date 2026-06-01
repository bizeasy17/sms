import csv
import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from users.models import User, UserWatchlist
import pandas as pd
from users.models import Corporation


class Command(BaseCommand):
    help = "Import user watchlist data from a CSV file"

    def add_arguments(self, parser):
        parser.add_argument("--filename", type=str, help="Path to the CSV file")

    def handle(self, *args, **options):
        filename = options["filename"]
        try:
            filepath = os.path.join(settings.STATIC_ROOT, filename)
            df = pd.read_csv(filepath, encoding="utf-8")
            admin_user = User.get_admin_user()
            ts_codes = df["ts_code"].unique()
            corp_map = {
                corp.ts_code: corp
                for corp in Corporation.objects.filter(ts_code__in=ts_codes)
            }
            watchlists = []
            for _, row in df.iterrows():
                corp = corp_map.get(row["ts_code"])
                if not corp:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Corporation not found for ts_code: {row['ts_code']}"
                        )
                    )
                    continue
                watchlists.append(
                    UserWatchlist(
                        user=admin_user,
                        ts_code=row["ts_code"],
                        name=corp.name,
                        corporation=corp,
                        is_enabled=not row["removed"],
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Prepared watchlist entry for ts_code: {row['ts_code']}"
                    )
                )
            UserWatchlist.objects.bulk_create(watchlists, ignore_conflicts=True)
            self.stdout.write(
                self.style.SUCCESS("Successfully imported watchlist data")
            )
        except Exception as e:
            raise CommandError(f"Error importing data: {e}")
