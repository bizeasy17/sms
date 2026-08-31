import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from datastore.models import StockTradingHistory
from market_sentiment.models import MarketSentimentFactor, MarketSentimentSnapshot
from market_sentiment.services.index_engine import ENGINE_VERSION, INDEX_WEIGHTS, calculate_index_composite_snapshots
from market_sentiment.services.daily_engine import SCORE_WINDOW, Z_WINDOW


class Command(BaseCommand):
    help = '从本地 index_daily/index_dailybasic 计算并持久化综合指数情绪。'

    def add_arguments(self, parser):
        parser.add_argument('--start-date', default='2007-01-15')
        parser.add_argument('--end-date')
        parser.add_argument('--latest', action='store_true')
        parser.add_argument('--market', default='CN')
        parser.add_argument('--scope-code', default='BROAD_COMPOSITE')
        parser.add_argument('--engine-version', default=ENGINE_VERSION)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *_args, **options):
        if options['latest'] and options['end_date']:
            raise CommandError('--latest 不能与 --end-date 同时使用。')
        if options['latest']:
            end_date = StockTradingHistory.objects.filter(
                ts_code__in=INDEX_WEIGHTS, freq='D'
            ).aggregate(latest=Max('trade_date'))['latest']
            if end_date is None:
                raise CommandError('没有可用的指数日线行情。')
            start_date = end_date - datetime.timedelta(days=(SCORE_WINDOW + Z_WINDOW + 30) * 2)
        else:
            start_date = self._date(options['start_date'], 'start-date')
            end_date = self._date(options['end_date'], 'end-date') if options['end_date'] else datetime.date.today()
        if start_date > end_date:
            raise CommandError('--start-date 不能晚于 --end-date。')

        results = calculate_index_composite_snapshots(start_date=start_date, end_date=end_date)
        if options['latest']:
            results = [item for item in results if item['trade_date'] == end_date]
        if not results:
            raise CommandError('本地指数表中没有可计算的数据。')
        scored = sum(item.get('sentiment_score') is not None for item in results)
        insufficient = sum(item.get('status') == 'INSUFFICIENT_DATA' for item in results)
        warming = sum(item.get('status') == 'WARMING_UP' for item in results)
        written = 0
        if not options['dry_run']:
            for item in results:
                defaults = {key: value for key, value in item.items() if key != 'trade_date'}
                defaults['engine_version'] = options['engine_version']
                snapshot, _ = MarketSentimentSnapshot.objects.update_or_create(
                    market=options['market'],
                    scope_type='INDEX',
                    scope_code=options['scope_code'],
                    trade_date=item['trade_date'],
                    engine_version=options['engine_version'],
                    defaults=defaults,
                )
                MarketSentimentFactor.objects.filter(snapshot=snapshot).delete()
                for order, (code, value) in enumerate((
                    ('momentum', item.get('momentum_score')),
                    ('activity', item.get('activity_score')),
                    ('fear', item.get('fear_score')),
                    ('raw_score', item.get('raw_score')),
                ), 1):
                    MarketSentimentFactor.objects.create(
                        snapshot=snapshot,
                        dimension='COMPOSITE',
                        factor_code=code,
                        factor_name=code,
                        normalized_value=value,
                        contribution=value,
                        available=value is not None,
                        sort_order=order,
                        payload=item.get('metadata', {}),
                    )
                written += 1
        latest = results[-1]
        self.stdout.write(self.style.SUCCESS(
            f'computed={len(results)} scored={scored} warming={warming} insufficient={insufficient} '
            f'written={written} first={results[0]["trade_date"]} latest={latest["trade_date"]} '
            f'latest_score={latest.get("sentiment_score")} engine={options["engine_version"]}'
        ))

    @staticmethod
    def _date(value, option_name):
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except ValueError as exc:
            raise CommandError(f'--{option_name} 必须为 YYYY-MM-DD。') from exc