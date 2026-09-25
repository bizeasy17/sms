from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from market_data.models import MarketBarDailyHistory
from market_sentiment.services.engine import ENGINE_VERSION, STOCK_ENGINE_VERSION, SentimentEngine


class Command(BaseCommand):
    help = 'Calculate and persist daily market and stock sentiment snapshots.'

    def add_arguments(self, parser):
        parser.add_argument('--scope', choices=['MARKET', 'STOCK'], default='MARKET')
        parser.add_argument('--trade-date', help='Completed trade date YYYYMMDD')
        parser.add_argument('--latest', action='store_true')
        parser.add_argument('--start-date', help='Replay start date YYYYMMDD')
        parser.add_argument('--end-date', help='Replay end date YYYYMMDD')
        parser.add_argument('--ts-codes', default='')
        parser.add_argument('--engine-version')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if not options['engine_version']:
            options['engine_version'] = STOCK_ENGINE_VERSION if options['scope'] == 'STOCK' else ENGINE_VERSION
        dates = self._resolve_dates(options)
        codes = [code.strip().upper() for code in options['ts_codes'].split(',') if code.strip()]
        if options['scope'] == 'MARKET' and codes:
            raise CommandError('--ts-codes is valid only with --scope STOCK')
        engine = SentimentEngine(engine_version=options['engine_version'])
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'Dry run valid: scope={options["scope"]} dates={dates[0]}..{dates[-1]} '
                f'codes={len(codes)} engine={options["engine_version"]}'
            ))
            return
        completed = 0
        persisted_stocks = 0
        if options['scope'] == 'MARKET':
            self.stdout.write(
                f'Market sentiment daily backfill started: dates={dates[0]}..{dates[-1]} total={len(dates)}'
            )
            for index, trade_date in enumerate(dates, start=1):
                self.stdout.write(
                    f'Market sentiment calculating: {index}/{len(dates)} date={trade_date}'
                )
                market = engine.calculate_market(trade_date)
                engine.persist(market, [])
                completed += 1
                self.stdout.write(
                    f'Market sentiment date completed: {index}/{len(dates)} date={market["trade_date"]}'
                )
        else:
            if options['engine_version'] == ENGINE_VERSION:
                for trade_date in dates:
                    stocks = engine.calculate_stocks(trade_date, ts_codes=codes or None)
                    engine.persist(None, stocks)
                    persisted_stocks += len(stocks)
                    self.stdout.write(
                        f'Stock sentiment date completed: date={trade_date} stocks={len(stocks)}'
                    )
                    completed += 1
            else:
                stocks_by_date = engine.calculate_stocks_v2(dates, ts_codes=codes or None)
                for trade_date in dates:
                    stocks = stocks_by_date.get(trade_date, [])
                    if not stocks:
                        self.stdout.write(self.style.WARNING(
                            f'Stock sentiment date skipped: date={trade_date} reason=no_stock_rows'
                        ))
                        continue
                    engine.persist(None, stocks)
                    persisted_stocks += len(stocks)
                    completed += 1
                    self.stdout.write(
                        f'Stock sentiment date completed: date={trade_date} stocks={len(stocks)}'
                    )
        if completed == 0:
            raise CommandError('No sentiment snapshots were calculated for the requested dates.')
        suffix = f' stocks={persisted_stocks}' if options['scope'] == 'STOCK' else ''
        self.stdout.write(self.style.SUCCESS(
            f'Sentiment refresh completed: scope={options["scope"]} dates={completed}{suffix} engine={options["engine_version"]}'
        ))

    def _resolve_dates(self, options):
        if options['latest'] and any(options.get(name) for name in ('trade_date', 'start_date', 'end_date')):
            raise CommandError('--latest cannot be combined with date arguments')
        if options['latest']:
            if options['scope'] == 'STOCK':
                latest = MarketBarDailyHistory.objects.filter(
                    trade_date__lte=date.today(),
                ).order_by('-trade_date').values_list('trade_date', flat=True).first()
                if latest is None:
                    raise CommandError('No daily market bars are available.')
                return [latest]
            return [date.today()]
        if options['trade_date']:
            return [self._parse_date(options['trade_date'])]
        if bool(options['start_date']) != bool(options['end_date']):
            raise CommandError('--start-date and --end-date must be provided together')
        if options['start_date'] and options['end_date']:
            start = self._parse_date(options['start_date'])
            end = self._parse_date(options['end_date'])
            if start > end:
                raise CommandError('--start-date cannot be after --end-date')
            return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
        return [date.today()]

    @staticmethod
    def _parse_date(value):
        text = str(value).replace('-', '')
        if len(text) != 8 or not text.isdigit():
            raise CommandError(f'Invalid date: {value}')
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError as exc:
            raise CommandError(f'Invalid date: {value}') from exc