from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from uuid import uuid4

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from market_data.models import Security
from market_data.models import MarketBarDailyHistory
from predictive_valuation.models import (
    PredictiveFinancialFeatureLatest,
    PredictiveFinancialFeaturePanel,
    PredictiveValuationEventState,
    PredictiveValuationRun,
    PredictiveValuationSnapshot,
)
from predictive_valuation.services.artifact_registry import ArtifactValidationError, PredictiveArtifactRegistry
from predictive_valuation.services.event_service import PredictiveValuationEventService
from predictive_valuation.services.financial_feature_builder import PredictiveFinancialFeatureBuilder
from predictive_valuation.services.inference_service import PredictiveInferenceService


class Command(BaseCommand):
    help = 'Operate predictive valuation feature construction and model-serving validation.'

    def add_arguments(self, parser):
        parser.add_argument('subcommand', choices=['validate', 'build-features', 'backfill', 'backfill-features', 'backfill-valuations', 'detect-events', 'consume-events', 'refresh', 'status'])
        parser.add_argument('--ts-codes', default='', help='Comma-separated stock ts_codes')
        parser.add_argument('--asof-date', default='', help='Maximum public date in YYYYMMDD format')
        parser.add_argument('--scope', choices=['all', 'ts-code'], default='all')
        parser.add_argument('--start-date', default='', help='Financial period start date YYYYMMDD')
        parser.add_argument('--end-date', default='', help='Financial period end date YYYYMMDD')
        parser.add_argument('--history-years', type=int, default=None, help='Backfill years, default 5')
        parser.add_argument('--report-types', default='', help='Comma-separated Q1,H1,Q3,FY values')
        parser.add_argument('--horizon', default='1M')
        parser.add_argument('--anchor-mode', default='latest', help='Snapshot anchor mode, default latest')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--retry-failed', action='store_true')
        parser.add_argument('--all', action='store_true', help='Build features for all stock securities')
        parser.add_argument('--dry-run', action='store_true', help='Validate the requested feature scope without writes')

    def handle(self, *args, **options):
        subcommand = options['subcommand']
        if subcommand == 'validate':
            self._validate()
            return
        if subcommand == 'status':
            self._status()
            return
        if subcommand == 'detect-events':
            self._detect_events(options)
            return
        if subcommand == 'backfill-features':
            self._backfill_features(options)
            return
        if subcommand == 'backfill':
            self._backfill_features(options)
            self._backfill_valuations(options)
            return
        if subcommand == 'backfill-valuations':
            self._backfill_valuations(options)
            return
        if subcommand == 'consume-events':
            self._consume_events(options)
            return
        if subcommand == 'refresh':
            self._detect_events(options)
            self._consume_events(options)
            return
        self._build_features(options)

    def _validate(self) -> None:
        config_path = self._resolve_base_path(settings.PREDICTIVE_VALUATION_CONFIG)
        if not config_path.is_file():
            raise CommandError(f'Predictive valuation config not found: {config_path}')
        try:
            config = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
        except yaml.YAMLError as exc:
            raise CommandError(f'Invalid predictive valuation config: {exc}') from exc
        if not isinstance(config, dict) or not str(config.get('feature_contract_version') or '').strip():
            raise CommandError('Predictive valuation config requires feature_contract_version')

        table_names = set(connection.introspection.table_names())
        required_tables = {
            'predictive_valuation_financial_feature_panel',
            'predictive_valuation_financial_feature_latest',
            'predictive_valuation_snapshot',
            'predictive_valuation_current',
            'predictive_valuation_event_state',
            'predictive_valuation_run',
        }
        missing_tables = sorted(required_tables - table_names)
        if missing_tables:
            raise CommandError(f'Missing predictive valuation tables: {", ".join(missing_tables)}')

        model_root = self._resolve_base_path(settings.PREDICTIVE_VALUATION_MODEL_ROOT)
        risk_root = self._resolve_base_path(settings.PREDICTIVE_VALUATION_RISK_DATA_ROOT)
        if not model_root.is_dir():
            raise CommandError(f'Predictive valuation model root not found: {model_root}')
        if not risk_root.is_dir():
            raise CommandError(f'Predictive valuation risk-data root not found: {risk_root}')
        serving_pointer = model_root / str(config.get('model', {}).get('serving_pointer') or 'serving.yaml')
        if not serving_pointer.is_file():
            raise CommandError(f'Predictive valuation serving pointer not found: {serving_pointer}')
        try:
            report_types = tuple(str(report_type).strip().upper() for report_type in config.get('model', {}).get('report_types', []))
            if not report_types:
                raise CommandError('Predictive valuation config requires model.report_types')
            artifacts = PredictiveArtifactRegistry(model_root).validate_production_models(report_types)
        except ArtifactValidationError as exc:
            raise CommandError(f'Invalid predictive valuation serving artifact: {exc}') from exc
        model_versions = ','.join(f'{artifact.report_type}:{artifact.model_version}' for artifact in artifacts)
        version_warnings = [
            f'{artifact.report_type}:{artifact.required_sklearn_version}->{artifact.installed_sklearn_version}'
            for artifact in artifacts
            if artifact.required_sklearn_version and artifact.required_sklearn_version != artifact.installed_sklearn_version
        ]
        if version_warnings:
            self.stderr.write(self.style.WARNING(
                f'scikit-learn compatibility warning: {", ".join(version_warnings)}'
            ))
        self.stdout.write(self.style.SUCCESS(
            f'Validation passed: config={config_path} model_root={model_root} '
            f'risk_root={risk_root} serving_pointer={serving_pointer} '
            f'models={model_versions}'
        ))

    def _build_features(self, options: dict) -> None:
        if options['all'] and options['ts_codes']:
            raise CommandError('--all and --ts-codes are mutually exclusive')
        codes = [code.strip().upper() for code in options['ts_codes'].split(',') if code.strip()]
        if not options['all'] and not codes:
            raise CommandError('build-features requires --ts-codes or --all')
        as_of_date = self._parse_date(options['asof_date'])
        securities = Security.objects.filter(asset_type=Security.AssetType.STOCK)
        if codes:
            securities = securities.filter(ts_code__in=codes)
            found_codes = set(securities.values_list('ts_code', flat=True))
            missing_codes = sorted(set(codes) - found_codes)
            if missing_codes:
                raise CommandError(f'Unknown stock ts_codes: {", ".join(missing_codes)}')
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'Dry run valid: securities={securities.count()} as_of_date={as_of_date}'))
            return

        rebuilt_rows = 0
        security_count = 0
        for security in securities.iterator(chunk_size=200):
            rebuilt_rows += PredictiveFinancialFeatureBuilder.rebuild_for_security(security, as_of_date=as_of_date)
            security_count += 1
        self.stdout.write(self.style.SUCCESS(
            f'Feature build completed: securities={security_count} panel_rows={rebuilt_rows} as_of_date={as_of_date}'
        ))

    def _status(self) -> None:
        self.stdout.write(json.dumps({
            'feature_panel_rows': PredictiveFinancialFeaturePanel.objects.count(),
            'feature_latest_rows': PredictiveFinancialFeatureLatest.objects.count(),
            'snapshot_rows': PredictiveValuationSnapshot.objects.count(),
            'event_counts': {
                status: PredictiveValuationEventState.objects.filter(status=status).count()
                for status in PredictiveValuationEventState.Status.values
            },
            'run_counts': {
                status: PredictiveValuationRun.objects.filter(status=status).count()
                for status in PredictiveValuationRun.Status.values
            },
        }, sort_keys=True))

    def _detect_events(self, options: dict) -> None:
        as_of_date = self._parse_date(options['asof_date'])
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'Dry run valid: as_of_date={as_of_date}'))
            return
        financial = PredictiveValuationEventService.detect_financial_disclosures(as_of_date=as_of_date)
        regimes = PredictiveValuationEventService.detect_regime_changes(limit=options['limit'])
        self.stdout.write(self.style.SUCCESS(f'Predictive valuation events: {json.dumps({"financial": financial, "regimes": regimes}, sort_keys=True)}'))

    def _backfill_features(self, options: dict) -> None:
        start_date, end_date = self._backfill_range(options)
        securities = self._securities(options)
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'Dry run valid: command=backfill-features securities={securities.count()} start={start_date} end={end_date}'))
            return
        run = self._start_run('backfill-features', options, start_date, end_date)
        count = 0
        try:
            for security in securities.iterator(chunk_size=200):
                count += PredictiveFinancialFeatureBuilder.rebuild_for_security(
                    security,
                    start_date=start_date,
                    end_date=end_date,
                    update_latest=False,
                )
            self._finish_run(run, PredictiveValuationRun.Status.SUCCEEDED, {'feature_panel_rows': count})
        except Exception as exc:
            self._finish_run(run, PredictiveValuationRun.Status.FAILED, {'feature_panel_rows': count}, str(exc))
            raise CommandError(f'Feature backfill failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'Feature backfill completed: run_key={run.run_key} panel_rows={count}'))

    def _backfill_valuations(self, options: dict) -> None:
        self._validate()
        start_date, end_date = self._backfill_range(options)
        report_types = self._report_types(options)
        anchor_mode = str(options.get('anchor_mode') or 'latest').strip()
        if not anchor_mode or len(anchor_mode) > 16:
            raise CommandError('--anchor-mode must be 1-16 characters')
        requested_fusion = 'FUSION' in report_types
        panel_report_types = ('Q1', 'H1', 'Q3', 'FY') if requested_fusion else report_types
        panels = PredictiveFinancialFeaturePanel.objects.filter(end_date__range=(start_date, end_date), report_type__in=panel_report_types).select_related('security').order_by('security_id', 'end_date', 'report_type')
        codes = self._codes(options)
        if codes:
            panels = panels.filter(security__ts_code__in=codes)
        if options['limit'] > 0:
            panels = panels[:options['limit']]
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'Dry run valid: command=backfill-valuations panels={panels.count()} start={start_date} end={end_date} report_types={",".join(report_types)}'))
            return
        run = self._start_run('backfill-valuations', options, start_date, end_date)
        service = PredictiveInferenceService()
        ok_count = 0
        fail_count = 0
        try:
            if requested_fusion:
                grouped = {}
                for panel in panels.iterator(chunk_size=100):
                    grouped.setdefault((panel.security_id, panel.fiscal_year), []).append(panel)
                work_items = grouped.values()
            else:
                work_items = ([panel] for panel in panels.iterator(chunk_size=100))
            for item in work_items:
                try:
                    if requested_fusion:
                        service.predict_fusion(item, horizon=options['horizon'], trigger_type='HISTORICAL_BACKFILL', batch_key=run.run_key, refresh_reason='historical_backfill', run_key=run.run_key, is_backfill=True, anchor_mode=anchor_mode)
                    else:
                        service.predict_panel(item[0], horizon=options['horizon'], trigger_type='HISTORICAL_BACKFILL', batch_key=run.run_key, refresh_reason='historical_backfill', run_key=run.run_key, is_backfill=True, anchor_mode=anchor_mode)
                    ok_count += 1
                except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    fail_count += 1
                    panel = item[0]
                    self.stderr.write(
                        self.style.WARNING(
                            f'Valuation prediction failed: ts_code={panel.security.ts_code} '
                            f'report_type={"FUSION" if requested_fusion else panel.report_type} asof_date={panel.source_as_of_date} '
                            f'error={str(exc)[:2000]}'
                        )
                    )
            summary = {
                'processed_panels': ok_count + fail_count,
                'ok': ok_count,
                'fail': fail_count,
            }
            if fail_count > 0 and ok_count == 0:
                error = f'Valuation backfill finished with all predictions failed (ok={ok_count}, fail={fail_count})'
                self._finish_run(run, PredictiveValuationRun.Status.FAILED, summary, error)
                raise CommandError(error)
            self._finish_run(run, PredictiveValuationRun.Status.SUCCEEDED, summary)
        except CommandError:
            raise
        except Exception as exc:
            summary = {'processed_panels': ok_count + fail_count, 'ok': ok_count, 'fail': fail_count}
            self._finish_run(run, PredictiveValuationRun.Status.FAILED, summary, str(exc))
            raise CommandError(f'Valuation backfill failed: {exc}') from exc
        self.stdout.write(
            self.style.SUCCESS(
                f'Valuation backfill completed: run_key={run.run_key} '
                f'snapshots={ok_count} failed={fail_count}'
            )
        )

    def _consume_events(self, options: dict) -> None:
        statuses = [PredictiveValuationEventState.Status.PENDING]
        if options['retry_failed']:
            statuses.append(PredictiveValuationEventState.Status.FAILED)
        events = PredictiveValuationEventState.objects.filter(status__in=statuses).order_by('created_at')
        if options['limit'] <= 0:
            raise CommandError('consume-events requires --limit to bound event fan-out')
        events = events[:options['limit']]
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'Dry run valid: command=consume-events events={events.count()}'))
            return
        self._validate()
        service = PredictiveInferenceService()
        completed = failed = 0
        for event in events:
            event.status = PredictiveValuationEventState.Status.RUNNING
            event.claimed_at = timezone.now()
            event.save(update_fields=['status', 'claimed_at', 'updated_at'])
            try:
                completed += self._consume_event(event, service, options['horizon'], options['limit'])
                event.status = PredictiveValuationEventState.Status.SUCCEEDED
                event.completed_at = timezone.now()
                event.last_error = ''
            except Exception as exc:
                failed += 1
                event.status = PredictiveValuationEventState.Status.FAILED
                event.retry_count += 1
                event.last_error = str(exc)[:2000]
            event.save()
        if failed:
            raise CommandError(f'Event consumption failed: completed={completed} failed={failed}')
        self.stdout.write(self.style.SUCCESS(f'Event consumption completed: snapshots={completed}'))

    def _consume_event(self, event, service: PredictiveInferenceService, horizon: str, limit: int) -> int:
        if event.event_type == PredictiveValuationEventService.DISCLOSURE_EVENT:
            end_date = date.fromisoformat(event.payload['financial_end_date'])
            PredictiveFinancialFeatureBuilder.rebuild_for_security(event.security)
            panel = PredictiveFinancialFeaturePanel.objects.filter(security=event.security, end_date=end_date).order_by('-source_as_of_date').first()
            if panel is None:
                return 0
            service.predict_panel(panel, horizon=horizon, trigger_type=event.event_type, refresh_reason=event.event_type)
            return 1
        if event.event_type == PredictiveValuationEventService.SECURITY_REGIME_EVENT:
            panel = PredictiveFinancialFeaturePanel.objects.filter(security=event.security).order_by('-source_as_of_date').first()
            if panel is None:
                return 0
            service.predict_panel(panel, horizon=horizon, trigger_type=event.event_type, refresh_reason=event.event_type)
            return 1
        if event.event_type == PredictiveValuationEventService.MARKET_REGIME_EVENT:
            panels = PredictiveFinancialFeaturePanel.objects.filter(report_type__in=self._report_types({'report_types': ''})).order_by('security_id', '-source_as_of_date').distinct('security_id')[:limit]
            for panel in panels:
                service.predict_panel(panel, horizon=horizon, trigger_type=event.event_type, refresh_reason=event.event_type)
            return len(panels)
        raise ValueError(f'Unsupported predictive event type: {event.event_type}')

    def _securities(self, options: dict):
        codes = self._codes(options)
        if options['scope'] == 'ts-code' and not codes:
            raise CommandError('--scope ts-code requires --ts-codes')
        securities = Security.objects.filter(asset_type=Security.AssetType.STOCK)
        if codes:
            securities = securities.filter(ts_code__in=codes)
        if options['limit'] > 0:
            securities = securities[:options['limit']]
        return securities

    @staticmethod
    def _codes(options: dict) -> list[str]:
        return [code.strip().upper() for code in str(options.get('ts_codes') or '').split(',') if code.strip()]

    def _report_types(self, options: dict) -> tuple[str, ...]:
        configured = yaml.safe_load(self._resolve_base_path(settings.PREDICTIVE_VALUATION_CONFIG).read_text(encoding='utf-8')) or {}
        allowed = tuple(str(value).upper() for value in configured.get('model', {}).get('report_types', []))
        requested = tuple(value.strip().upper() for value in str(options.get('report_types') or '').split(',') if value.strip()) or allowed
        if not requested or any(value not in allowed and value != 'FUSION' for value in requested):
            raise CommandError(f'--report-types must be a subset of {",".join(allowed)} plus FUSION')
        return requested

    def _backfill_range(self, options: dict) -> tuple[date, date]:
        if options['start_date'] and options['history_years'] is not None:
            raise CommandError('--start-date and --history-years are mutually exclusive')
        end_date = self._parse_date(options['end_date']) or MarketBarDailyHistory.objects.order_by('-trade_date').values_list('trade_date', flat=True).first()
        if end_date is None:
            raise CommandError('No completed market trading date is available for the default backfill end date')
        years = 5 if options['history_years'] is None else options['history_years']
        if years <= 0:
            raise CommandError('--history-years must be positive')
        start_date = self._parse_date(options['start_date']) or end_date.replace(year=end_date.year - years)
        if start_date > end_date:
            raise CommandError('--start-date must not be after --end-date')
        return start_date, end_date

    @staticmethod
    def _start_run(command: str, options: dict, start_date: date, end_date: date) -> PredictiveValuationRun:
        return PredictiveValuationRun.objects.create(run_key=uuid4().hex[:32], command=command, status=PredictiveValuationRun.Status.RUNNING, params={'start_date': start_date.isoformat(), 'end_date': end_date.isoformat(), 'options': {key: str(value) for key, value in options.items()}}, started_at=timezone.now())

    @staticmethod
    def _finish_run(run: PredictiveValuationRun, status: str, summary: dict, error: str = '') -> None:
        run.status, run.summary, run.error_message, run.finished_at = status, summary, error[:2000], timezone.now()
        run.save(update_fields=['status', 'summary', 'error_message', 'finished_at', 'updated_at'])

    @staticmethod
    def _resolve_base_path(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else settings.BASE_DIR / path

    @staticmethod
    def _parse_date(value: str) -> date | None:
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(f'{raw[:4]}-{raw[4:6]}-{raw[6:8]}')
        except (TypeError, ValueError) as exc:
            raise CommandError('--asof-date must be YYYYMMDD') from exc