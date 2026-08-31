import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Max, Min

from datastore.models import Corporation, StockTradingHistory
from market_sentiment.models import MarketSentimentFactor, MarketSentimentSnapshot
from market_sentiment.services.daily_engine import ENGINE_VERSION, SCORE_WINDOW, STOCK_ENGINE_VERSION, Z_WINDOW, calculate_all_stock_snapshots_latest, calculate_snapshots


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
        parser.add_argument('--all-stocks', action='store_true')
        parser.add_argument('--missing-history-groups', action='store_true', help='计算四类历史不足或滞后股票的最新可用情绪。')
        parser.add_argument('--resume', help='批量股票模式从该 ts_code（含）继续。')
        parser.add_argument('--limit', type=int, help='批量股票模式最多处理的股票数。')
        parser.add_argument('--engine-version')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *_args, **options):
        if options['all_stocks'] and options['scope'] != 'STOCK':
            raise CommandError('--all-stocks 必须与 --scope STOCK 一起使用。')
        if options['missing_history_groups'] and options['scope'] != 'STOCK':
            raise CommandError('--missing-history-groups 必须与 --scope STOCK 一起使用。')
        if options['missing_history_groups'] and options['all_stocks']:
            raise CommandError('--missing-history-groups 不能与 --all-stocks 同时使用。')
        if options['missing_history_groups'] and (options['trade_date'] or options['start_date'] or options['end_date'] or options['latest']):
            raise CommandError('--missing-history-groups 自动选择每只股票的最后交易日，不能指定日期参数。')
        if options['limit'] is not None and options['limit'] <= 0:
            raise CommandError('--limit 必须大于 0。')
        if not options['engine_version']:
            options['engine_version'] = STOCK_ENGINE_VERSION if options['scope'] == 'STOCK' else ENGINE_VERSION

        if options['missing_history_groups']:
            scope_targets = self._missing_history_targets(options)
            if not scope_targets:
                raise CommandError('没有符合四类历史条件的股票。')
            end_date = None
        else:
            scope_targets = None
        requested_date = options['trade_date'] or options['end_date']
        if not options['missing_history_groups'] and options['latest'] and requested_date:
            raise CommandError('--latest 不能与 --trade-date 或 --end-date 同时使用。')
        if not options['missing_history_groups'] and options['latest']:
            end_date = StockTradingHistory.objects.filter(freq='D').order_by('-trade_date').values_list('trade_date', flat=True).first()
            if end_date is None:
                raise CommandError('没有可用的日线行情。')
        elif not options['missing_history_groups']:
            end_date = self._date(requested_date, 'trade-date/end-date')
        if options['all_stocks'] and options['latest']:
            self._refresh_all_stocks_latest(end_date, options)
            return
        if scope_targets is None:
            scope_targets = [(scope_code, end_date, None) for scope_code in self._scope_codes(options)]
        total_computed = 0
        total_written = 0
        total_scopes = len(scope_targets)
        for scope_index, (scope_code, target_end_date, selection_group) in enumerate(scope_targets, start=1):
            calculation_start_date = (
                self._date(options['start_date'], 'start-date')
                if options['start_date']
                else target_end_date - datetime.timedelta(days=(SCORE_WINDOW + Z_WINDOW + 30) * 2)
            )
            results = calculate_snapshots(start_date=calculation_start_date, end_date=target_end_date, scope_type=options['scope'], scope_code=scope_code)
            target_results = results if options['start_date'] else [item for item in results if item['trade_date'] == target_end_date]
            if not target_results:
                self.stdout.write(self.style.WARNING(f'[{scope_index}/{total_scopes}] skipped scope={options["scope"]}:{scope_code} reason=no_trading_history'))
                self.stdout.flush()
                continue
            if selection_group:
                for item in target_results:
                    item['metadata']['selection_group'] = selection_group
            written = self._persist_results(target_results, scope_code, options)
            scored = sum(item.get('sentiment_score') is not None for item in target_results)
            warming = sum(item.get('status') == 'WARMING_UP' for item in target_results)
            insufficient = sum(item.get('status') == 'INSUFFICIENT_DATA' for item in target_results)
            latest = target_results[-1]
            total_computed += len(target_results)
            total_written += written
            self.stdout.write(
                f'[{scope_index}/{total_scopes}] completed scope={options["scope"]}:{scope_code} '
                f'computed={len(target_results)} scored={scored} warming={warming} '
                f'insufficient={insufficient} written={written} '
                f'latest_date={latest["trade_date"]} latest_score={latest.get("sentiment_score")}'
            )
            self.stdout.flush()
        if total_computed == 0:
            raise CommandError('指定范围内没有可计算的日线行情。')
        self.stdout.write(self.style.SUCCESS(f'total_computed={total_computed} total_written={total_written} scopes={len(scope_targets)}'))

    def _refresh_all_stocks_latest(self, end_date, options):
        calculation_start_date = end_date - datetime.timedelta(days=(SCORE_WINDOW + Z_WINDOW + 30) * 2)
        results = calculate_all_stock_snapshots_latest(
            start_date=calculation_start_date,
            end_date=end_date,
        )
        if options['resume']:
            resume = options['resume'].strip().upper()
            results = [item for item in results if item['scope_code'] >= resume]
        if options['limit']:
            results = results[:options['limit']]
        if not results:
            raise CommandError('最新交易日没有可计算的个股情绪。')
        written = 0 if options['dry_run'] else self._persist_batch_results(results, options)
        scored = sum(item.get('sentiment_score') is not None for item in results)
        warming = sum(item.get('status') == 'WARMING_UP' for item in results)
        insufficient = sum(item.get('status') == 'INSUFFICIENT_DATA' for item in results)
        self.stdout.write(self.style.SUCCESS(
            f'total_computed={len(results)} scored={scored} warming={warming} '
            f'insufficient={insufficient} total_written={written} latest_date={end_date}'
        ))

    @staticmethod
    @transaction.atomic
    def _persist_batch_results(results, options):
        key_fields = ['market', 'scope_type', 'scope_code', 'trade_date', 'engine_version']
        update_fields = [
            'sentiment_score', 'sentiment_level', 'raw_score', 'standardized_score',
            'momentum_score', 'activity_score', 'fear_score', 'universe_size',
            'valid_sample_size', 'coverage', 'status', 'metadata', 'updated_at',
        ]
        snapshots = []
        for item in results:
            values = {key: value for key, value in item.items() if key not in ('scope_code', 'trade_date')}
            snapshots.append(MarketSentimentSnapshot(
                market=options['market'],
                scope_type='STOCK',
                scope_code=item['scope_code'],
                trade_date=item['trade_date'],
                engine_version=options['engine_version'],
                **values,
            ))
        MarketSentimentSnapshot.objects.bulk_create(
            snapshots,
            batch_size=500,
            update_conflicts=True,
            update_fields=update_fields,
            unique_fields=key_fields,
        )
        persisted = {
            snapshot.scope_code: snapshot
            for snapshot in MarketSentimentSnapshot.objects.filter(
                market=options['market'],
                scope_type='STOCK',
                trade_date=results[0]['trade_date'],
                engine_version=options['engine_version'],
                scope_code__in=[item['scope_code'] for item in results],
            )
        }
        MarketSentimentFactor.objects.filter(snapshot__in=persisted.values()).delete()
        factors = []
        for item in results:
            snapshot = persisted[item['scope_code']]
            for order, (code, value) in enumerate((
                ('momentum', item.get('momentum_score')),
                ('activity', item.get('activity_score')),
                ('fear', item.get('fear_score')),
                ('raw_score', item.get('raw_score')),
            ), 1):
                factors.append(MarketSentimentFactor(
                    snapshot=snapshot,
                    dimension='COMPOSITE',
                    factor_code=code,
                    factor_name=code,
                    normalized_value=value,
                    contribution=value,
                    available=value is not None,
                    sort_order=order,
                    payload=item.get('metadata', {}),
                ))
        MarketSentimentFactor.objects.bulk_create(factors, batch_size=1000)
        return len(persisted)

    def _missing_history_targets(self, options):
        market_dates = list(
            StockTradingHistory.objects.filter(freq='D')
            .values_list('trade_date', flat=True).distinct().order_by('-trade_date')[:SCORE_WINDOW]
        )
        if len(market_dates) < SCORE_WINDOW:
            raise CommandError(f'市场交易日不足 {SCORE_WINDOW} 日，无法分类。')
        latest_date = market_dates[0]
        cutoff_date = market_dates[-1]
        history = {
            row['ts_code']: row
            for row in StockTradingHistory.objects.filter(freq='D').values('ts_code').annotate(
                days=Count('trade_date', distinct=True), first=Min('trade_date'), last=Max('trade_date')
            )
        }
        groups = {'NO_HISTORY': [], 'RECENT_SHORT': [], 'OLD_SHORT': [], 'STALE': []}
        corporations = Corporation.objects.filter(asset='E', list_status='L').values('ts_code', 'list_date')
        for corporation in corporations:
            ts_code = corporation['ts_code']
            stock_history = history.get(ts_code)
            if stock_history is None:
                groups['NO_HISTORY'].append((ts_code, None, 'NO_HISTORY'))
            elif stock_history['days'] < SCORE_WINDOW and corporation['list_date'] and corporation['list_date'] > cutoff_date:
                groups['RECENT_SHORT'].append((ts_code, stock_history['last'], 'RECENT_SHORT'))
            elif stock_history['days'] < SCORE_WINDOW:
                groups['OLD_SHORT'].append((ts_code, stock_history['last'], 'OLD_SHORT'))
            elif stock_history['last'] < latest_date:
                groups['STALE'].append((ts_code, stock_history['last'], 'STALE'))
        self.stdout.write(
            'selection_counts '
            + ' '.join(f'{name.lower()}={len(rows)}' for name, rows in groups.items())
            + f' latest={latest_date} cutoff={cutoff_date}'
        )
        targets = []
        for group_name in ('RECENT_SHORT', 'OLD_SHORT', 'STALE'):
            targets.extend(sorted(groups[group_name], key=lambda target: target[0]))
        for ts_code, _target_date, _group in groups['NO_HISTORY']:
            self.stdout.write(self.style.WARNING(f'skipped scope=STOCK:{ts_code} reason=no_trading_history'))
        if options['resume']:
            resume = options['resume'].strip().upper()
            targets = [target for target in targets if target[0] >= resume]
        if options['limit']:
            targets = targets[:options['limit']]
        return targets

    @staticmethod
    def _scope_codes(options):
        if not options['all_stocks']:
            return [options['scope_code']]
        queryset = Corporation.objects.filter(asset='E', list_status='L').order_by('ts_code').values_list('ts_code', flat=True)
        if options['resume']:
            queryset = queryset.filter(ts_code__gte=options['resume'].strip().upper())
        if options['limit']:
            queryset = queryset[:options['limit']]
        return list(queryset)

    def _persist_results(self, results, scope_code, options):
        written = 0
        for item in results:
            defaults = {key: value for key, value in item.items() if key != 'trade_date'}
            defaults['engine_version'] = options['engine_version']
            if options['dry_run']:
                if not options['all_stocks']:
                    self.stdout.write(f"{item['trade_date']} {item['status']} score={item.get('sentiment_score')}")
                continue
            snapshot, _ = MarketSentimentSnapshot.objects.update_or_create(market=options['market'], scope_type=options['scope'], scope_code=scope_code, trade_date=item['trade_date'], engine_version=options['engine_version'], defaults=defaults)
            MarketSentimentFactor.objects.filter(snapshot=snapshot).delete()
            for order, (code, value) in enumerate((('momentum', item.get('momentum_score')), ('activity', item.get('activity_score')), ('fear', item.get('fear_score')), ('raw_score', item.get('raw_score'))), 1):
                MarketSentimentFactor.objects.create(snapshot=snapshot, dimension='COMPOSITE', factor_code=code, factor_name=code, normalized_value=value, contribution=value, available=value is not None, sort_order=order, payload=item.get('metadata', {}))
            written += 1
        return written

    @staticmethod
    def _date(value, option_name):
        if not value:
            raise CommandError(f'必须提供 --{option_name}。')
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except ValueError as exc:
            raise CommandError(f'--{option_name} 必须为 YYYY-MM-DD。') from exc
