import datetime

from django.core.management.base import BaseCommand, CommandError

from datastore.models import StockTradingHistory
from market_sentiment.models import MarketSentimentFactor, MarketSentimentSnapshot
from market_sentiment.services.daily_engine import ENGINE_VERSION, SCORE_WINDOW, Z_WINDOW, calculate_snapshots


class Command(BaseCommand):
    help = '计算并持久化日线市场或个股情绪指数。'

    def add_arguments(self, parser):
        parser.add_argument('--trade-date')
        parser.add_argument('--start-date')
        parser.add_argument('--end-date')
        parser.add_argument('--latest', action='store_true')
        parser.add_argument('--market', default='CN')
        parser.add_argument('--scope', choices=['MARKET', 'STOCK'], default='MARKET')
        parser.add_argument('--scope-code', default='ALL_A')
        parser.add_argument('--engine-version', default=ENGINE_VERSION)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *_args, **options):
        requested_date = options['trade_date'] or options['end_date']
        if options['latest'] and requested_date:
            raise CommandError('--latest 不能与 --trade-date 或 --end-date 同时使用。')
        if options['latest']:
            end_date = StockTradingHistory.objects.filter(freq='D').order_by('-trade_date').values_list('trade_date', flat=True).first()
            if end_date is None:
                raise CommandError('没有可用的日线行情。')
        else:
            end_date = self._date(requested_date, 'trade-date/end-date')
        start_date = self._date(options['start_date'], 'start-date') if options['start_date'] else end_date - datetime.timedelta(days=(SCORE_WINDOW + Z_WINDOW + 30) * 2)
        results = calculate_snapshots(start_date=start_date, end_date=end_date, scope_type=options['scope'], scope_code=options['scope_code'])
        target_results = [item for item in results if options['start_date'] or item['trade_date'] == end_date]
        if not target_results:
            raise CommandError('指定范围内没有可计算的日线行情。')
        written = 0
        for item in target_results:
            defaults = {key: value for key, value in item.items() if key != 'trade_date'}
            defaults['engine_version'] = options['engine_version']
            if options['dry_run']:
                self.stdout.write(f"{item['trade_date']} {item['status']} score={item.get('sentiment_score')}")
                continue
            snapshot, _ = MarketSentimentSnapshot.objects.update_or_create(market=options['market'], scope_type=options['scope'], scope_code=options['scope_code'], trade_date=item['trade_date'], engine_version=options['engine_version'], defaults=defaults)
            MarketSentimentFactor.objects.filter(snapshot=snapshot).delete()
            for order, (code, value) in enumerate((('momentum', item.get('momentum_score')), ('activity', item.get('activity_score')), ('fear', item.get('fear_score')), ('raw_score', item.get('raw_score'))), 1):
                MarketSentimentFactor.objects.create(snapshot=snapshot, dimension='COMPOSITE', factor_code=code, factor_name=code, normalized_value=value, contribution=value, available=value is not None, sort_order=order, payload=item.get('metadata', {}))
            written += 1
        self.stdout.write(self.style.SUCCESS(f'computed={len(target_results)} written={written} scope={options["scope"]}:{options["scope_code"]}'))

    @staticmethod
    def _date(value, option_name):
        if not value:
            raise CommandError(f'必须提供 --{option_name}。')
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except ValueError as exc:
            raise CommandError(f'--{option_name} 必须为 YYYY-MM-DD。') from exc
