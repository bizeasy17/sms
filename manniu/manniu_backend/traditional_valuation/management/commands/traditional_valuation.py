from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from market_data.models import Security
from market_data.services.business_match import build_business_industry_match
from traditional_valuation.models import (
    TraditionalValuationEventState,
    TraditionalValuationRun,
    TraditionalValuationSnapshot,
)
from traditional_valuation.services.config import ValuationTemplateLoader
from traditional_valuation.services.event_service import TraditionalValuationEventService
from traditional_valuation.services.valuation_engine import TraditionalValuationEngine


class Command(BaseCommand):
    help = 'Run traditional SW-industry valuation operations.'

    def add_arguments(self, parser):
        parser.add_argument('subcommand', choices=['validate', 'backfill', 'refresh-business-matches', 'detect-events', 'consume-events', 'refresh', 'status'])
        parser.add_argument('--ts-codes', default='')
        parser.add_argument('--scope', choices=['all', 'ts-code', '60', '00', '30', '68'], default='all')
        parser.add_argument('--asof-date', default='')
        parser.add_argument('--start-date', default='')
        parser.add_argument('--end-date', default='')
        parser.add_argument('--history-years', type=int, default=None)
        parser.add_argument('--report-type', default='FY', choices=['Q1', 'H1', 'Q3', 'FY'])
        parser.add_argument('--report-types', default='')
        parser.add_argument('--profit-bucket', default='formal', choices=['formal', 'blended', 'both'])
        parser.add_argument('--business-match-topn', type=int, default=3)
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--retry-failed', action='store_true')
        parser.add_argument('--historical-disclosures', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        command = options['subcommand']
        if command == 'validate':
            self._validate()
        elif command == 'status':
            self._status()
        elif command == 'detect-events':
            self._detect(options)
        elif command == 'consume-events':
            self._consume(options)
        elif command == 'refresh-business-matches':
            self._refresh_business_matches(options)
        elif command == 'refresh':
            self._detect(options)
            self._consume(options)
        else:
            self._backfill(options)

    def _validate(self):
        loader = ValuationTemplateLoader()
        data = loader.load()
        if not data['sw_defaults'] and not data['defaults']:
            raise CommandError(f'No valuation templates found under {loader.root}')
        required = {
            'traditional_valuation_snapshot',
            'traditional_valuation_snapshot_latest',
            'traditional_valuation_risk_snapshot',
            'traditional_valuation_event_state',
            'traditional_valuation_run',
        }
        missing = sorted(required - set(connection.introspection.table_names()))
        if missing:
            raise CommandError(f'Missing traditional valuation tables: {", ".join(missing)}')
        self.stdout.write(self.style.SUCCESS(json.dumps({
            'template_root': str(loader.root),
            'template_version': data['template_version'],
            'source_hash': data['source_hash'],
            'mapping_version': data['mapping_version'],
        }, sort_keys=True)))

    def _status(self):
        self.stdout.write(json.dumps({
            'snapshots': TraditionalValuationSnapshot.objects.count(),
            'events': {status: TraditionalValuationEventState.objects.filter(status=status).count() for status in TraditionalValuationEventState.Status.values},
            'runs': {status: TraditionalValuationRun.objects.filter(status=status).count() for status in TraditionalValuationRun.Status.values},
        }, sort_keys=True))

    def _date(self, value):
        if not value:
            return date.today()
        try:
            return date.fromisoformat(value.replace('/', '-'))
        except ValueError as exc:
            raise CommandError(f'Invalid --asof-date: {value}') from exc

    def _detect(self, options):
        if options['dry_run']:
            self.stdout.write('Dry run valid: event detection writes no rows.')
            return
        summary = TraditionalValuationEventService.import_upstream_events(
            self._date(options['asof_date']), options['limit']
        )
        self.stdout.write(self.style.SUCCESS(f'Valuation events imported: {json.dumps(summary, sort_keys=True)}'))

    def _securities(self, options):
        codes = [code.strip().upper() for code in options['ts_codes'].split(',') if code.strip()]
        queryset = Security.objects.filter(asset_type=Security.AssetType.STOCK)
        if options['scope'] == 'ts-code' and not codes:
            raise CommandError('--scope ts-code requires --ts-codes')
        if codes:
            queryset = queryset.filter(ts_code__in=codes)
            found = set(queryset.values_list('ts_code', flat=True))
            missing = sorted(set(codes) - found)
            if missing:
                raise CommandError(f'Unknown stock ts_codes: {", ".join(missing)}')
        elif options['scope'] != 'all':
            queryset = queryset.filter(ts_code__startswith=options['scope'])
        if options['limit'] > 0:
            queryset = queryset[:options['limit']]
        return queryset

    def _report_types(self, options):
        values = [value.strip().upper() for value in options['report_types'].split(',') if value.strip()]
        if not values:
            values = [options['report_type']]
        invalid = sorted(set(values) - {'Q1', 'H1', 'Q3', 'FY'})
        if invalid:
            raise CommandError(f'Invalid report types: {", ".join(invalid)}')
        return values

    def _backfill(self, options):
        securities = self._securities(options)
        if options['dry_run']:
            self.stdout.write(f'Dry run valid: securities={securities.count()}')
            return
        self._validate()
        start_date, end_date = self._backfill_range(options)
        report_types = self._report_types(options)
        run = TraditionalValuationRun.objects.create(run_key=uuid4().hex[:32], command='backfill', status=TraditionalValuationRun.Status.RUNNING, started_at=timezone.now())
        try:
            options['_refresh_run_key'] = run.run_key
            ts_codes = list(securities.values_list('ts_code', flat=True))
            imported = TraditionalValuationEventService.import_historical_disclosure_events(
                start_date,
                end_date,
                report_types=report_types,
                ts_codes=ts_codes,
                limit=options['limit'],
            )
            reset_count = 0
            if options['historical_disclosures'] and imported['source_event_keys']:
                reset_count = TraditionalValuationEventState.objects.filter(
                    source_event_key__in=imported['source_event_keys'],
                ).exclude(
                    status=TraditionalValuationEventState.Status.PENDING,
                ).update(
                    status=TraditionalValuationEventState.Status.PENDING,
                    next_retry_at=None,
                    claimed_at=None,
                    completed_at=None,
                    last_error_code='',
                    last_error_message='',
                )
            self.stdout.write(self.style.SUCCESS(
                'Historical disclosure events: '
                f"scanned={imported['scanned']} created={imported['created']} "
                f"existing={imported['existing']} reset_existing={reset_count}"
            ))
            consumed = {'completed': 0, 'failed': 0}
            while True:
                batch = self._consume(options, source_event_keys=imported['source_event_keys'])
                consumed['completed'] += batch['completed']
                consumed['failed'] += batch['failed']
                if batch['completed'] == 0:
                    break
            imported_summary = {
                key: value for key, value in imported.items() if key != 'source_event_keys'
            }
            imported_summary['reset_existing'] = reset_count
            run.status = TraditionalValuationRun.Status.SUCCEEDED if not consumed['failed'] else TraditionalValuationRun.Status.FAILED
            run.completed_count = consumed['completed']
            run.failed_count = consumed['failed']
            run.summary = {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'report_types': report_types,
                'scope': options['scope'],
                'historical_disclosures': imported_summary,
                'consumed': consumed,
            }
            run.finished_at = timezone.now()
            run.save()
        except Exception as exc:
            run.status = TraditionalValuationRun.Status.FAILED
            run.error_message = str(exc)[:2000]
            run.finished_at = timezone.now()
            run.save()
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'Backfill completed: completed={consumed["completed"]} failed={consumed["failed"]}'
        ))

    def _backfill_range(self, options):
        if options['asof_date']:
            raise CommandError('Historical disclosure backfill uses --start-date/--end-date, not --asof-date')
        end_date = self._date(options['end_date']) if options['end_date'] else date.today()
        if options['start_date']:
            start_date = self._date(options['start_date'])
        else:
            years = 5 if options['history_years'] is None else options['history_years']
            if years <= 0:
                raise CommandError('--history-years must be positive')
            start_date = end_date.replace(year=end_date.year - years)
        if start_date > end_date:
            raise CommandError('--start-date must not be after --end-date')
        return start_date, end_date

    def _refresh_business_matches(self, options):
        if options['business_match_topn'] < 0:
            raise CommandError('--business-match-topn must be zero or positive')
        if options['dry_run']:
            self.stdout.write(
                f'Dry run valid: securities={self._securities(options).count()} '
                f'level=L2 topn={options["business_match_topn"]}'
            )
            return

        asof_date = self._date(options['asof_date'])
        counts = {
            'processed': 0,
            'valid': 0,
            'no_profile': 0,
            'mapping_unavailable': 0,
            'rules_version_unavailable': 0,
            'failed': 0,
            'matched_candidates': 0,
        }
        failures = []
        for security in self._securities(options).iterator(chunk_size=100):
            counts['processed'] += 1
            try:
                result = build_business_industry_match(
                    security=security,
                    asof_date=asof_date,
                    level='L2',
                    top_n=options['business_match_topn'],
                )
                status = str(result.get('status') or '').lower()
                if status == 'valid':
                    counts['valid'] += 1
                elif status in counts:
                    counts[status] += 1
                else:
                    counts['failed'] += 1
                counts['matched_candidates'] += len(result.get('matches') or [])
            except Exception as exc:
                counts['failed'] += 1
                if len(failures) < 20:
                    failures.append({'ts_code': security.ts_code, 'error': str(exc)[:500]})

        summary = {
            'asof_date': asof_date.isoformat(),
            'level': 'L2',
            'requested_top_n': options['business_match_topn'],
            **counts,
            'failures': failures,
        }
        if counts['failed']:
            self.stdout.write(self.style.ERROR(json.dumps(summary, ensure_ascii=False, sort_keys=True)))
            raise CommandError(
                f'Business match refresh failed: processed={counts["processed"]} '
                f'failed={counts["failed"]}'
            )
        self.stdout.write(self.style.SUCCESS(json.dumps(summary, ensure_ascii=False, sort_keys=True)))

    def _consume(self, options, source_event_keys=None):
        limit = options['limit'] if options['limit'] > 0 else 500
        if options['dry_run']:
            self.stdout.write('Dry run valid: event consumption writes no rows.')
            return {'completed': 0, 'failed': 0}
        events = TraditionalValuationEventService.claim_pending(
            limit, options['retry_failed'], source_event_keys=source_event_keys
        )
        engine = TraditionalValuationEngine()
        completed = failed = 0
        buckets = ['formal', 'blended'] if options['profit_bucket'] == 'both' else [options['profit_bucket']]
        for event in events:
            try:
                if event.security is None and event.event_type == TraditionalValuationEventService.MARKET_STYLE_CHANGED:
                    securities = Security.objects.filter(asset_type=Security.AssetType.STOCK).order_by('id')[:options['limit']]
                    for security in securities:
                        report_type = event.payload.get('report_type') or options['report_type']
                        result = engine.calculate(security, event.asof_date or self._date(options['asof_date']), report_type, profit_bucket='formal', trigger_type=event.event_type)
                        engine.persist(result, report_type, profit_bucket='formal', refresh_run_key=options.get('_refresh_run_key'))
                    event.status = TraditionalValuationEventState.Status.SUCCEEDED
                    event.completed_at = timezone.now()
                    event.save(update_fields=['status', 'completed_at', 'updated_at'])
                    completed += len(securities)
                    continue
                if event.security is None:
                    raise ValueError('Event requires a security scope')
                with transaction.atomic():
                    report_type = event.payload.get('report_type') or options['report_type']
                    financial_end_date = event.payload.get('financial_end_date')
                    for bucket in buckets:
                        result = engine.calculate(
                            event.security,
                            event.asof_date or self._date(options['asof_date']),
                            report_type,
                            financial_end_date=date.fromisoformat(financial_end_date) if financial_end_date else None,
                            profit_bucket=bucket,
                            trigger_type=event.event_type,
                            business_match_topn=options['business_match_topn'],
                        )
                        engine.persist(result, report_type, profit_bucket=bucket, refresh_run_key=options.get('_refresh_run_key'))
                    event.status = TraditionalValuationEventState.Status.SUCCEEDED
                    event.completed_at = timezone.now()
                    event.save(update_fields=['status', 'completed_at', 'updated_at'])
                completed += 1
            except Exception as exc:
                event.status = TraditionalValuationEventState.Status.FAILED
                event.attempt_count += 1
                event.last_error_code = 'VALUATION_FAILED'
                event.last_error_message = str(exc)[:2000]
                event.save(update_fields=['status', 'attempt_count', 'last_error_code', 'last_error_message', 'updated_at'])
                failed += 1
        if failed:
            raise CommandError(f'Event consumption failed: completed={completed} failed={failed}')
        summary = {'completed': completed, 'failed': failed}
        self.stdout.write(self.style.SUCCESS(f'Event consumption completed: {json.dumps(summary, sort_keys=True)}'))
        return summary