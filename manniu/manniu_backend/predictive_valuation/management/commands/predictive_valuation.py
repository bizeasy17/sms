from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from market_data.models import Security
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


class Command(BaseCommand):
    help = 'Operate predictive valuation feature construction and model-serving validation.'

    def add_arguments(self, parser):
        parser.add_argument('subcommand', choices=['validate', 'build-features', 'detect-events', 'status'])
        parser.add_argument('--ts-codes', default='', help='Comma-separated stock ts_codes')
        parser.add_argument('--asof-date', default='', help='Maximum public date in YYYYMMDD format')
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
            artifact = PredictiveArtifactRegistry(model_root).load_production()
        except ArtifactValidationError as exc:
            raise CommandError(f'Invalid predictive valuation serving artifact: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(
            f'Validation passed: config={config_path} model_root={model_root} '
            f'risk_root={risk_root} serving_pointer={serving_pointer} '
            f'model_version={artifact.model_version} features={len(artifact.feature_columns)}'
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
        result = PredictiveValuationEventService.detect_financial_disclosures(as_of_date=as_of_date)
        self.stdout.write(self.style.SUCCESS(f'Financial disclosure events: {json.dumps(result, sort_keys=True)}'))

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