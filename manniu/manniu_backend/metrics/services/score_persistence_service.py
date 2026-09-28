from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from market_data.models import Security
from metrics.models import MetricsScoreDimension, MetricsScoreSnapshot


SCORE_TYPES = tuple(choice for choice, _ in MetricsScoreSnapshot.ScoreType.choices)


def _parse_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])


def _decimal(value: Any, *, nullable: bool = True) -> Decimal | None:
    if value is None and nullable:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        if nullable:
            return None
        raise ValueError(f'invalid decimal value: {value!r}') from exc
    if not number.is_finite():
        if nullable:
            return None
        raise ValueError(f'invalid decimal value: {value!r}')
    return number


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(
        value,
        cls=DjangoJSONEncoder,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        allow_nan=False,
    ))


def _score_status(score_type: str, result: dict[str, Any]) -> str:
    if score_type == MetricsScoreSnapshot.ScoreType.MODEL_TOPN_6D:
        if result.get('model_degraded'):
            return MetricsScoreSnapshot.Status.DEGRADED
        topn_status = result.get('score_status')
        return {
            'COMPLETE': MetricsScoreSnapshot.Status.VALID,
            'AVAILABLE': MetricsScoreSnapshot.Status.VALID,
            'PARTIAL': MetricsScoreSnapshot.Status.PARTIAL,
            'NOT_AVAILABLE': MetricsScoreSnapshot.Status.INSUFFICIENT_DATA,
        }.get(topn_status, MetricsScoreSnapshot.Status.INSUFFICIENT_DATA)
    status = result.get('status')
    allowed = {choice for choice, _ in MetricsScoreSnapshot.Status.choices}
    return status if status in allowed else MetricsScoreSnapshot.Status.VALID


def prepare_score_snapshot(
    result: dict[str, Any],
    score_type: str,
    asof_date: date | datetime | str,
    *,
    market_asof_date: date | datetime | str | None = None,
    security: Security | None = None,
) -> dict[str, Any]:
    if score_type not in SCORE_TYPES:
        raise ValueError(f'unsupported score_type: {score_type}')
    ts_code = str(result.get('ts_code') or '').strip().upper()
    if not ts_code:
        raise ValueError('score result is missing ts_code')
    if security is None:
        security_manager = getattr(Security, 'objects')
        try:
            security = security_manager.get(ts_code=ts_code, asset_type=Security.AssetType.STOCK)
        except ObjectDoesNotExist as exc:
            raise LookupError(f'security not found: {ts_code}') from exc
    if security.ts_code != ts_code:
        raise ValueError('score result ts_code does not match security')

    score = _decimal(result.get('score', result.get('total_score')))
    if score is not None and not Decimal('0') <= score <= Decimal('100'):
        raise ValueError('score must be between 0 and 100')

    source_periods = result.get('source_periods')
    if not isinstance(source_periods, dict):
        source_periods = {
            'financial_end_date': result.get('financial_end_date') or result.get('snapshot_asof_date'),
            'market_asof_date': market_asof_date,
        }
    dimensions = result.get('dimensions') or result.get('dimension_scores') or []
    if not isinstance(dimensions, list):
        raise ValueError('score result dimensions must be a list')
    dimension_rows = []
    seen_keys = set()
    for dimension in dimensions:
        key = str(dimension.get('key') or '').strip()
        if not key or key in seen_keys:
            raise ValueError('score result contains a missing or duplicate dimension key')
        seen_keys.add(key)
        weight = _decimal(dimension.get('weight'), nullable=False)
        dimension_score = _decimal(dimension.get('score'))
        if dimension_score is not None and not Decimal('0') <= dimension_score <= Decimal('100'):
            raise ValueError(f'dimension score out of range: {key}')
        evidence = {
            name: value for name, value in dimension.items()
            if name not in {'key', 'name', 'weight', 'score', 'status', 'available_weight'}
        }
        dimension_rows.append({
            'dimension_key': key,
            'dimension_name': str(dimension.get('name') or ''),
            'weight': weight,
            'score': dimension_score,
            'status': str(dimension.get('status') or ('VALID' if dimension_score is not None else 'NOT_AVAILABLE')),
            'available_weight': _decimal(
                dimension.get('available_weight', dimension.get('factor_weight_coverage', dimension.get('feature_coverage')))
            ),
            'evidence': _json_safe(evidence),
        })

    asof = _parse_date(asof_date)
    market_asof = _parse_date(market_asof_date)
    financial_end = _parse_date(
        result.get('financial_end_date')
        or result.get('snapshot_asof_date')
        or result.get('latest_financial_end_date')
    )
    status = _score_status(score_type, result)
    warnings = result.get('warnings') or []
    if result.get('model_degraded') and result.get('model_degrade_reason'):
        warnings = [*warnings, f"model_degraded: {result['model_degrade_reason']}"]
    defaults = {
        'asof_date': asof,
        'financial_end_date': financial_end,
        'market_asof_date': market_asof,
        'report_type': str(result.get('report_type') or result.get('resolved_report_type') or ''),
        'score': score,
        'label': str(result.get('label') or result.get('score_grade') or ''),
        'score_status': status,
        'coverage': _decimal(result.get('coverage', result.get('feature_weight_coverage'))),
        'calculation_version': str(result.get('calculation_version') or ''),
        'scoring_version': str(result.get('scoring_version') or ''),
        'profile_version': str(result.get('profile_version') or ''),
        'peer_mapping_version': str(result.get('peer_mapping_version') or ''),
        'model_version': str(result.get('model_version') or ''),
        'feature_set_version': str(result.get('feature_set_version') or ''),
        'mapping_version': str(result.get('mapping_version') or result.get('feature_dimension_mapping', {}).get('mapping_version') or ''),
        'normalization_version': str(result.get('normalization_version') or ''),
        'dimension_weight_version': str(result.get('dimension_weight_version') or ''),
        'score_topn': result.get('score_topn'),
        'store_topn': result.get('store_topn'),
        'model_scope': str(result.get('model_scope') or ''),
        'model_degraded': bool(result.get('model_degraded')),
        'model_degrade_reason': str(result.get('model_degrade_reason') or '')[:512],
        'source_periods': _json_safe(source_periods),
        'warnings': _json_safe(warnings),
    }
    fingerprint_payload = {
        'security_id': security.pk,
        'score_type': score_type,
        'asof_date': asof,
        'market_asof_date': market_asof,
        'defaults': defaults,
        'dimensions': dimension_rows,
    }
    fingerprint_text = json.dumps(
        fingerprint_payload,
        cls=DjangoJSONEncoder,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        allow_nan=False,
    )
    fingerprint = hashlib.sha256(fingerprint_text.encode('utf-8')).hexdigest()
    return {
        'security': security,
        'score_type': score_type,
        'input_fingerprint': fingerprint,
        'defaults': defaults,
        'dimensions': dimension_rows,
    }


def persist_prepared_score_snapshot(prepared: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    snapshot_manager = getattr(MetricsScoreSnapshot, 'objects')
    lookup = {
        'security': prepared['security'],
        'score_type': prepared['score_type'],
        'input_fingerprint': prepared['input_fingerprint'],
    }
    if dry_run:
        exists = snapshot_manager.filter(**lookup).exists()
        return {'snapshot': None, 'created': False, 'already_exists': exists, 'fingerprint': prepared['input_fingerprint']}

    with transaction.atomic():
        snapshot, created = snapshot_manager.get_or_create(
            **lookup,
            defaults=prepared['defaults'],
        )
        if created:
            getattr(MetricsScoreDimension, 'objects').bulk_create([
                MetricsScoreDimension(snapshot=snapshot, **dimension)
                for dimension in prepared['dimensions']
            ])
    return {
        'snapshot': snapshot,
        'created': created,
        'already_exists': not created,
        'fingerprint': prepared['input_fingerprint'],
    }


def persist_score_result(
    result: dict[str, Any],
    score_type: str,
    asof_date: date | datetime | str,
    *,
    market_asof_date: date | datetime | str | None = None,
    security: Security | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    prepared = prepare_score_snapshot(
        result,
        score_type,
        asof_date,
        market_asof_date=market_asof_date,
        security=security,
    )
    return persist_prepared_score_snapshot(prepared, dry_run=dry_run)