from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from market_sentiment.services.engine import SentimentEngine


class Command(BaseCommand):
    help = 'Calculate and persist daily market and stock sentiment snapshots.'

    def add_arguments(self, parser):
        parser.add_argument('--scope', choices=['MARKET', 'STOCK'], default='MARKET')
        parser.add_argument('--trade-date', help='Completed trade date YYYYMMDD')
        parser.add_argument('--latest', action='store_true')
        parser.add_argument('--start-date', help='Replay start date YYYYMMDD')
        parser.add_argument('--end-date', help='Replay end date YYYYMMDD')
        parser.add_argument('--ts-codes', default='')
        parser.add_argument('--engine-version', default='sentiment_v1')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dates = self._resolve_dates(options)
        codes = [code.strip().upper() for code in options['ts_codes'].split(',') if code.strip()]
        if options['scope'] == 'MARKET' and codes:
            raise CommandError('--ts-codes is valid only with --scope STOCK')
        engine = SentimentEngine(engine_version=options['engine_version'])
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'Dry run valid: scope={options["scope"]} dates={dates[0]}..{dates[-1]} codes={len(codes)}'
            ))
            return
        completed = 0
        for trade_date in dates:
            if options['scope'] == 'MARKET':
                market = engine.calculate_market(trade_date)
                engine.persist(market, [])
            else:
                market = engine.calculate_market(trade_date, ts_codes=codes or None)
                stocks = engine.calculate_stocks(trade_date, ts_codes=codes or None)
                engine.persist(market, stocks)
            completed += 1
        self.stdout.write(self.style.SUCCESS(
            f'Sentiment refresh completed: scope={options["scope"]} dates={completed} engine={options["engine_version"]}'
        ))

    def _resolve_dates(self, options):
        if options['latest'] and any(options.get(name) for name in ('trade_date', 'start_date', 'end_date')):
            raise CommandError('--latest cannot be combined with date arguments')
        if options['latest'] or options['trade_date']:
            value = options['trade_date'] or date.today().strftime('%Y%m%d')
            return [self._parse_date(value)]
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