from django.core.management.base import BaseCommand, CommandError
from utils.data_utils import fetch_and_store_corporations
from stockdata.models import Corporation

class Command(BaseCommand):
    help = 'Custom setup command for stockdata app'

    def handle(self, *args, **options):
        try:
            fetch_and_store_corporations()
            if not Corporation.objects.exists():
                raise CommandError("Corporation initialization returned no records.")
            self.stdout.write(self.style.SUCCESS('Corporations fetched and stored successfully.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error during setup: {e}'))
            raise CommandError(f'Corporation initialization failed: {e}') from e