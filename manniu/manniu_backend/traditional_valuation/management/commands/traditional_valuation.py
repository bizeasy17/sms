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
        parser.add_argument('--asof-date', default='')
        parser.add_argument('--report-type', default='FY', choices=['Q1', 'H1', 'Q3', 'FY'])
        parser.add_argument('--profit-bucket', default='formal', choices=['formal', 'blended', 'both'])
        parser.add_argument('--business-match-topn', type=int, default=3)
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--retry-failed', action='store_true')
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
        count = TraditionalValuationEventService.detect_financial_disclosures(self._date(options['asof_date']), options['limit'])
        self.stdout.write(self.style.SUCCESS(f'Financial valuation events created: {count}'))

    def _securities(self, options):
        codes = [code.strip().upper() for code in options['ts_codes'].split(',') if code.strip()]
        queryset = Security.objects.filter(asset_type=Security.AssetType.STOCK)
        if codes:
            queryset = queryset.filter(ts_code__in=codes)
            found = set(queryset.values_list('ts_code', flat=True))
            missing = sorted(set(codes) - found)
            if missing:
                raise CommandError(f'Unknown stock ts_codes: {", ".join(missing)}')
        return queryset

    def _backfill(self, options):
        securities = self._securities(options)
        if options['dry_run']:
            self.stdout.write(f'Dry run valid: securities={securities.count()}')
            return
        self._validate()
        asof_date = self._date(options['asof_date'])
        run = TraditionalValuationRun.objects.create(run_key=uuid4().hex[:32], command='backfill', status=TraditionalValuationRun.Status.RUNNING, started_at=timezone.now())
        engine = TraditionalValuationEngine()
        completed = failed = 0
        buckets = ['formal', 'blended'] if options['profit_bucket'] == 'both' else [options['profit_bucket']]
        try:
            for security in securities.iterator(chunk_size=100):
                for bucket in buckets:
                    try:
                        result = engine.calculate(
                            security, asof_date, options['report_type'], profit_bucket=bucket,
                            trigger_type='BACKFILL', business_match_topn=options['business_match_topn'],
                        )
                        engine.persist(result, options['report_type'], profit_bucket=bucket)
                        completed += 1
                    except Exception:
                        failed += 1
            run.status = TraditionalValuationRun.Status.SUCCEEDED if not failed else TraditionalValuationRun.Status.FAILED
            run.completed_count = completed
            run.failed_count = failed
            run.summary = {'asof_date': asof_date.isoformat(), 'report_type': options['report_type']}
            run.finished_at = timezone.now()
            run.save()
        except Exception as exc:
            run.status = TraditionalValuationRun.Status.FAILED
            run.error_message = str(exc)[:2000]
            run.finished_at = timezone.now()
            run.save()
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'Backfill completed: completed={completed} failed={failed}'))

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

    def _consume(self, options):
        if options['limit'] <= 0:
            raise CommandError('--limit must be positive for consume-events')
        if options['dry_run']:
            self.stdout.write('Dry run valid: event consumption writes no rows.')
            return
        events = TraditionalValuationEventService.claim_pending(options['limit'], options['retry_failed'])
        engine = TraditionalValuationEngine()
        completed = failed = 0
        for event in events:
            try:
                if event.security is None:
                    raise ValueError('Market-scope event fan-out is not configured yet')
                report_type = event.payload.get('report_type') or options['report_type']
                bucket = options['profit_bucket'] if options['profit_bucket'] != 'both' else 'formal'
                result = engine.calculate(event.security, event.asof_date or self._date(options['asof_date']), report_type, profit_bucket=bucket, trigger_type=event.event_type)
                with transaction.atomic():
                    engine.persist(result, report_type, profit_bucket=bucket)
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
        self.stdout.write(self.style.SUCCESS(f'Event consumption completed: completed={completed}'))