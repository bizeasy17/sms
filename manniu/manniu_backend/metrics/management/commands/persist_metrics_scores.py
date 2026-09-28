from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from market_data.models import Security
from metrics.services.growth_potential_service import compute_growth_potential_score
from metrics.services.health_scoring_service import compute_score
from metrics.services.model_topn_scoring import rebuild_score
from metrics.services.score_persistence_service import SCORE_TYPES, persist_score_result
from predictive_valuation.services.feature_provider import get_model_top_features


_REPORT_TYPES = {
    (3, 31): 'Q1',
    (6, 30): 'H1',
    (9, 30): 'Q3',
    (12, 31): 'FY',
}


class Command(BaseCommand):
    help = 'Compute and persist metrics score snapshots into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--asof-date', required=True, help='Information cutoff date (YYYY-MM-DD or YYYYMMDD)')
        parser.add_argument('--score-types', nargs='+', choices=SCORE_TYPES, required=True)
        parser.add_argument('--scope', choices=['ts-codes', 'all'], required=True)
        parser.add_argument('--ts-code', action='append', default=[], help='Repeatable stock code for ts-codes scope')
        parser.add_argument('--ts-codes-file', default='', help='Text file containing one or comma-separated ts_codes per line')
        parser.add_argument('--report-type', default='', help='TopN report type, for example H1 or FY')
        parser.add_argument('--model-version', default='', help='Optional TopN model version')
        parser.add_argument('--score-topn', type=int, default=20)
        parser.add_argument('--store-topn', type=int, default=50)
        parser.add_argument('--dry-run', action='store_true', help='Compute and check idempotency without writing snapshots')

    def handle(self, *args, **options):
        try:
            asof_date = self._parse_asof(options['asof_date'])
            score_types = list(dict.fromkeys(options['score_types']))
            codes = self._resolve_codes(options)
            self._validate_topn_options(options, score_types)
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        securities = {
            security.ts_code: security
            for security in Security.objects.filter(
                asset_type=Security.AssetType.STOCK,
                ts_code__in=codes,
            ).order_by('id')
        }
        counts = Counter()
        total = len(codes) * len(score_types)
        self.stdout.write(
            f'Starting metrics persistence: securities={len(codes)} score_types={len(score_types)} '
            f'asof_date={asof_date.isoformat()} dry_run={options["dry_run"]}'
        )

        for code in codes:
            security = securities.get(code)
            for score_type in score_types:
                if security is None:
                    counts['failed'] += 1
                    self.stderr.write(f'ERROR {code} {score_type}: security not found')
                    continue
                try:
                    result = self._compute_result(code, score_type, asof_date, options)
                    stored = persist_score_result(
                        result,
                        score_type,
                        asof_date,
                        market_asof_date=asof_date if score_type != 'COMPANY_GROWTH_POTENTIAL' else None,
                        security=security,
                        dry_run=options['dry_run'],
                    )
                    if options['dry_run']:
                        counts['already_exists' if stored['already_exists'] else 'would_create'] += 1
                    else:
                        counts['already_exists' if stored['already_exists'] else 'created'] += 1
                except (ValueError, LookupError, TypeError, KeyError, AttributeError, ImportError, RuntimeError, OSError, DatabaseError) as exc:
                    counts['failed'] += 1
                    self.stderr.write(f'ERROR {code} {score_type}: {type(exc).__name__}: {exc}')

        self.stdout.write(
            f'Metrics persistence summary: total={total} created={counts["created"]} '
            f'would_create={counts["would_create"]} already_exists={counts["already_exists"]} '
            f'failed={counts["failed"]}'
        )
        if counts['failed']:
            raise CommandError(f'{counts["failed"]} score snapshot operation(s) failed')

    def _resolve_codes(self, options) -> list[str]:
        if options['scope'] == 'all':
            if options['ts_code'] or options['ts_codes_file']:
                raise ValueError('--scope all cannot be combined with --ts-code or --ts-codes-file')
            return list(
                Security.objects.filter(asset_type=Security.AssetType.STOCK)
                .order_by('ts_code')
                .values_list('ts_code', flat=True)
            )

        codes = [str(code).strip().upper() for code in options['ts_code'] if str(code).strip()]
        file_name = str(options['ts_codes_file']).strip()
        if file_name:
            path = Path(file_name)
            if not path.is_absolute():
                path = settings.BASE_DIR / path
            with path.open('r', encoding='utf-8-sig') as source:
                for line in source:
                    codes.extend(part.strip().upper() for part in line.split(',') if part.strip())
        codes = list(dict.fromkeys(codes))
        if not codes:
            raise ValueError('--scope ts-codes requires --ts-code or --ts-codes-file')
        return codes

    @staticmethod
    def _parse_asof(value: str) -> date:
        text = str(value).strip()
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        return date.fromisoformat(text[:10])

    @staticmethod
    def _validate_topn_options(options, score_types):
        if not 6 <= options['score_topn'] <= 20:
            raise ValueError('--score-topn must be between 6 and 20')
        if not 20 <= options['store_topn'] <= 50:
            raise ValueError('--store-topn must be between 20 and 50')
        if 'MODEL_TOPN_6D' in score_types and options['report_type']:
            if options['report_type'].upper() not in {'Q1', 'H1', 'Q3', 'FY'}:
                raise ValueError('--report-type must be one of Q1, H1, Q3, FY')

    def _compute_result(self, ts_code, score_type, asof_date, options):
        asof_text = asof_date.isoformat()
        if score_type == 'FINANCIAL_HEALTH_6D':
            return compute_score(ts_code, asof_text)
        if score_type == 'COMPANY_GROWTH_POTENTIAL':
            return compute_growth_potential_score(ts_code, asof_date)
        return self._compute_topn_result(ts_code, asof_text, options)

    def _compute_topn_result(self, ts_code, asof_date, options):
        payload = compute_score(ts_code, asof_date, include_feature_values=True)
        feature_values = payload.pop('_feature_values', {})
        normalized_overrides = payload.pop('_normalization_overrides', {})
        snapshot_date = str(payload.get('snapshot_asof_date') or '')
        inferred_report_type = ''
        if len(snapshot_date) == 8 and snapshot_date.isdigit():
            report_date = datetime.strptime(snapshot_date, '%Y%m%d').date()
            inferred_report_type = _REPORT_TYPES.get((report_date.month, report_date.day), '')
        report_type = options['report_type'].upper() or inferred_report_type
        if not report_type:
            raise ValueError('unable to infer TopN report type; pass --report-type')

        try:
            top_payload = get_model_top_features(
                ts_code=ts_code,
                stock_type=payload.get('stock_type'),
                topn=options['store_topn'],
                model_version=options['model_version'] or None,
                report_type=report_type,
            )
            payload.update({
                'model_top_features': top_payload['top_features'],
                'model_version': top_payload.get('model_version', ''),
                'report_type': top_payload.get('report_type') or report_type,
                'model_scope': top_payload.get('model_scope', ''),
                'model_degraded': bool(top_payload.get('degraded')),
                'model_degrade_reason': top_payload.get('degrade_reason') or '',
                'score_topn': options['score_topn'],
                'store_topn': options['store_topn'],
            })
            payload.update(rebuild_score(
                payload,
                payload['model_top_features'],
                options['score_topn'],
                feature_values,
                normalized_overrides,
            ))
        except (ValueError, LookupError, TypeError, KeyError, AttributeError, ImportError, RuntimeError, OSError, DatabaseError) as exc:
            payload.update({
                'score_type': 'MODEL_TOPN_DIMENSION',
                'score_status': 'NOT_AVAILABLE',
                'total_score': None,
                'score_grade': 'N/A',
                'dimension_scores': [],
                'model_version': options['model_version'],
                'report_type': report_type,
                'model_degraded': True,
                'model_degrade_reason': str(exc),
                'score_topn': options['score_topn'],
                'store_topn': options['store_topn'],
            })
        return payload