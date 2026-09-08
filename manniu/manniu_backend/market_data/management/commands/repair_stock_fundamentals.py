from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from market_data.models import MarketBarDailyHistory, Security, StockDailyFundamentalHistory
from market_data.services.sync import build_sync_plan, execute_sync


class Command(BaseCommand):
    help = 'Check or backfill stock fundamental history gaps using stock bar coverage as the baseline.'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true', help='Backfill detected stocks; otherwise check only.')
        parser.add_argument('--start-date', default='')
        parser.add_argument('--end-date', default='')
        parser.add_argument('--history-years', type=int, default=5)
        parser.add_argument('--batch-size', type=int, default=50)
        parser.add_argument('--show-limit', type=int, default=30)

    def handle(self, *_args, **options):
        today = date.today()
        end_date = self._parse_date(options['end_date'], '--end-date') if options['end_date'] else today
        if options['start_date']:
            start_date = self._parse_date(options['start_date'], '--start-date')
        else:
            history_years = options['history_years']
            if history_years <= 0:
                raise CommandError('--history-years must be positive')
            try:
                start_date = end_date.replace(year=end_date.year - history_years)
            except ValueError:
                start_date = end_date.replace(year=end_date.year - history_years, month=2, day=28)
        if start_date > end_date:
            raise CommandError('--start-date must not be after --end-date')
        if options['batch_size'] <= 0:
            raise CommandError('--batch-size must be positive')

        missing_codes, bar_counts, fundamental_counts, stock_count = self._find_missing(start_date, end_date)
        self.stdout.write(f'Check window: {start_date} through {end_date}')
        self.stdout.write(f'Total stocks: {stock_count}')
        self.stdout.write(f'Stocks requiring fundamental backfill: {len(missing_codes)}')
        self.stdout.write(f'Stocks currently complete: {stock_count - len(missing_codes)}')

        show_limit = max(0, options['show_limit'])
        if show_limit:
            self.stdout.write('Sample gaps (ts_code, stock bars, fundamentals):')
            for security_id, ts_code in missing_codes[:show_limit]:
                self.stdout.write(
                    f'  {ts_code}: {bar_counts.get(security_id, 0)}, '
                    f'{fundamental_counts.get(security_id, 0)}'
                )

        if not options['execute'] or not missing_codes:
            return

        batch_size = options['batch_size']
        total = len(missing_codes)
        total_rows = 0
        for offset in range(0, total, batch_size):
            batch = missing_codes[offset:offset + batch_size]
            codes = ','.join(ts_code for _, ts_code in batch)
            self.stdout.write(
                f'Backfilling batch [{offset + 1} through {min(offset + batch_size, total)} / {total}]...'
            )
            plan = build_sync_plan({
                'dataset': 'stock-fundamentals',
                'mode': 'backfill',
                'scope': 'ts-code',
                'ts_codes': codes,
                'start_date': start_date.strftime('%Y%m%d'),
                'end_date': end_date.strftime('%Y%m%d'),
            })
            try:
                count = execute_sync(plan)
            except Exception as exc:
                raise CommandError(f'Batch starting at {offset + 1} failed: {exc}') from exc
            total_rows += count
            self.stdout.write(self.style.SUCCESS(f'Batch completed; upserted rows: {count}'))

        self.stdout.write(self.style.SUCCESS(f'Fundamental backfill completed; total upserted rows: {total_rows}'))

    @staticmethod
    def _parse_date(value, option_name):
        try:
            return date.fromisoformat(value) if '-' in value else date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        except (TypeError, ValueError) as exc:
            raise CommandError(f'{option_name} must use YYYYMMDD or YYYY-MM-DD') from exc

    @staticmethod
    def _find_missing(start_date, end_date):
        stocks = dict(
            Security.objects.filter(asset_type=Security.AssetType.STOCK).values_list('id', 'ts_code')
        )
        bar_counts = dict(
            MarketBarDailyHistory.objects.filter(
                security_id__in=stocks.keys(),
                trade_date__range=(start_date, end_date),
            )
            .values('security_id')
            .annotate(row_count=Count('id'))
            .values_list('security_id', 'row_count')
        )
        fundamental_counts = dict(
            StockDailyFundamentalHistory.objects.filter(
                security_id__in=stocks.keys(),
                trade_date__range=(start_date, end_date),
            )
            .values('security_id')
            .annotate(row_count=Count('id'))
            .values_list('security_id', 'row_count')
        )
        missing_codes = sorted(
            (
                (security_id, ts_code)
                for security_id, ts_code in stocks.items()
                if bar_counts.get(security_id, 0) > fundamental_counts.get(security_id, 0)
            ),
            key=lambda item: item[1],
        )
        return missing_codes, bar_counts, fundamental_counts, len(stocks)