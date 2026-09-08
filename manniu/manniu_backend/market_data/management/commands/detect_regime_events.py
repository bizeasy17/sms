from datetime import date

from django.core.management.base import BaseCommand, CommandError

from market_data.services.regime import RegimeService


class Command(BaseCommand):
    help = 'Detect and persist market/security regime snapshots and change events.'

    def add_arguments(self, parser):
        parser.add_argument('--asof-date', default='', help='As-of date YYYY-MM-DD; defaults to today')
        parser.add_argument('--scope', choices=['market', 'all'], default='all')
        parser.add_argument('--benchmark-ts-code', default='000001.SH')
        parser.add_argument('--confirm-days', type=int, default=2)
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **options):
        try:
            asof_date = date.fromisoformat(options['asof_date']) if options['asof_date'] else date.today()
        except ValueError as exc:
            raise CommandError('--asof-date must use YYYY-MM-DD') from exc
        if options['confirm_days'] < 1:
            raise CommandError('--confirm-days must be positive')
        result = RegimeService().detect(
            asof_date=asof_date,
            scope=options['scope'],
            benchmark_ts_code=options['benchmark_ts_code'],
            confirm_days=options['confirm_days'],
            limit=options['limit'],
        )
        self.stdout.write(self.style.SUCCESS(str(result)))