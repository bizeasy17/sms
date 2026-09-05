from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from stockdata.models import Corporation, CorporationBasic
from utils.data_utils import fetch_and_store_corp_basic, fetch_and_store_corporations

class Command(BaseCommand):
    help = 'Custom setup command for stockdata app'

    def handle(self, *args, **options):
        try:
            fetch_and_store_corporations()
            if not Corporation.objects.exists():
                raise CommandError("Corporation initialization returned no records.")
            fetch_and_store_corp_basic()
            if not CorporationBasic.objects.exists():
                raise CommandError("Corporation basic initialization returned no records.")
            self.stdout.write(self.style.SUCCESS('Corporations fetched and stored successfully.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error during setup: {e}'))
            raise CommandError(f'ETL setup failed: {e}') from e