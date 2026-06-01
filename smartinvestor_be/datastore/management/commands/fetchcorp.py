from django.core.management.base import BaseCommand
from utils.data_utils import fetch_and_store_corporations, fetch_and_store_corp_basic


class Command(BaseCommand):
    help = "Custom setup command for stockdata app"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="Stock code to fetch data for")
        parser.add_argument(
            "--resume", type=str, help="Resume fetching from this stock code"
        )

    def handle(self, *args, **options):
        try:
            # fetch_and_store_corporations()
            ts_code = options.get("tscode")
            resume = options.get("resume")

            fetch_and_store_corporations()
            fetch_and_store_corp_basic(ts_code=ts_code, resume=resume)
            self.stdout.write(
                self.style.SUCCESS("Corporations fetched and stored successfully.")
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error during setup: {e}"))
        self.stdout.write(self.style.SUCCESS("Setup command executed successfully."))
