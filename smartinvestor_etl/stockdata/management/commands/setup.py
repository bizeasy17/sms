from django.core.management.base import BaseCommand
from utils.data_utils import fetch_and_store_corporations

class Command(BaseCommand):
    help = 'Custom setup command for stockdata app'

    def handle(self, *args, **options):
        try:
            fetch_and_store_corporations()
            self.stdout.write(self.style.SUCCESS('Corporations fetched and stored successfully.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error during setup: {e}'))
        self.stdout.write(self.style.SUCCESS('Setup command executed successfully.'))