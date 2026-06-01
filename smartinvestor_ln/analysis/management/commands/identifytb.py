from django.core.management.base import BaseCommand, CommandError

from analysis.utils.analysis_utils import identify_stock_top_bottom

class Command(BaseCommand):
    help = 'Identify top and bottom assets based on time series analysis.'

    def add_arguments(self, parser):
        parser.add_argument('--tscode', type=str, help='Time series code')
        parser.add_argument('--freq', type=str, required=True, help='Frequency (e.g., daily, weekly)')
        parser.add_argument('--distance', type=int, default=20, help='Distance parameter for peak/trough detection')
        parser.add_argument('--resume', type=str, help='Resume from last run')

    def handle(self, *args, **options):
        ts_code = options['tscode']
        freq = options['freq']
        distance = options['distance']
        resume = options['resume']
        
        identify_stock_top_bottom(ts_code=ts_code, freq=freq, distance=distance, resume=resume)
        self.stdout.write(self.style.SUCCESS(
            f'Running identifytopbottom with ts_code={ts_code}, freq={freq}, resume from {resume}'
        ))

        # TODO: Implement your analysis logic here