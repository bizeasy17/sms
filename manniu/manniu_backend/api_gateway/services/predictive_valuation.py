from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from market_data.models import Security
from predictive_valuation.models import PredictiveValuationCurrent, PredictiveValuationSnapshot
from predictive_valuation.services.artifact_registry import (
    ArtifactValidationError,
    PredictiveArtifactRegistry,
)

from .market_data import MarketDataRequestError


VALID_REPORT_TYPES = {'Q1', 'H1', 'Q3', 'FY', 'FUSION', 'LATEST'}
QUARTER_REPORT_TYPES = ('Q1', 'H1', 'Q3', 'FY')
MAX_HISTORY_DAYS = 366
MAX_HISTORY_ROWS = 2000


class PredictiveValuationRequestError(MarketDataRequestError):
    pass


def _date(value):
    return value.isoformat() if value else None


def _value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value(item) for item in value]
    return value


def _validate_report_type(value, *, allow_latest=True):
    report_type = str(value or ('LATEST' if allow_latest else '')).strip().upper()
    allowed = VALID_REPORT_TYPES if allow_latest else VALID_REPORT_TYPES - {'LATEST'}
    if report_type not in allowed:
        raise PredictiveValuationRequestError(
            'UNSUPPORTED_REPORT_TYPE',
            'report_type 不受支持',
            details={'allowed': sorted(allowed)},
        )
    return report_type


def _validate_anchor_mode(value):
    if value in (None, ''):
        return None
    anchor_mode = str(value).strip().lower()
    if anchor_mode not in {'ann', 'live_latest'}:
        raise PredictiveValuationRequestError(
            'INVALID_REQUEST', 'anchor_mode 仅支持 ann 或 live_latest',
        )
    return anchor_mode


def _validate_model_selection(model_version=None, serving_slot=None):
    model_version = str(model_version or '').strip() or None
    serving_slot = str(serving_slot or '').strip().lower() or None
    if serving_slot and serving_slot != 'production':
        raise PredictiveValuationRequestError(
            'VERSION_CONFLICT',
            '当前只发布 production serving slot',
            details={'serving_slot': serving_slot, 'available_slots': ['production']},
        )
    return model_version, serving_slot


def _security(ts_code):
    try:
        return Security.objects.get(ts_code=ts_code)
    except Security.DoesNotExist as exc:
        raise PredictiveValuationRequestError('SECURITY_NOT_FOUND', '证券不存在') from exc


def _status(row):
    if row.last_error:
        return 'FAILED'
    snapshot = getattr(row, 'snapshot', None)
    current_raw_result = row.raw_result or {}
    snapshot_raw_result = getattr(snapshot, 'raw_result', None) or {}
    fusion = current_raw_result.get('fusion') or snapshot_raw_result.get('fusion') or {}
    components = fusion.get('components') or {}
    if any((component or {}).get('status') == 'FAILED' for component in components.values()):
        return 'PARTIAL_SUCCESS'
    if row.feature_data_source == 'dataset_fallback':
        return 'DATASET_FALLBACK'
    if row.feature_data_source in {'stale', 'STALE'}:
        return 'STALE'
    return 'COMPLETE'


def _payload(row, *, include_diagnostics=False):
    snapshot = getattr(row, 'snapshot', None)
    raw_result = dict((snapshot.raw_result if snapshot else row.raw_result) or {})
    explain = dict((snapshot.explain if snapshot else row.explain) or {})
    payload = {
        'ts_code': row.security.ts_code,
        'asof_date': _date(row.asof_date),
        'source_market_date': _date(getattr(snapshot, 'source_market_date', None)),
        'financial_end_date': _date(getattr(snapshot, 'financial_end_date', None)),
        'financial_ann_date': _date(getattr(snapshot, 'financial_ann_date', None)),
        'financial_source_as_of_date': _date(getattr(snapshot, 'financial_source_as_of_date', None)),
        'financial_report_type': getattr(snapshot, 'financial_report_type', '') or row.report_type,
        'financial_fiscal_year': getattr(snapshot, 'financial_fiscal_year', None),
        'report_type': row.report_type,
        'anchor_mode': getattr(snapshot, 'anchor_mode', '') or raw_result.get('anchor_mode'),
        'model_version': row.model_version,
        'feature_contract_version': row.feature_contract_version,
        'artifact_hash': getattr(snapshot, 'artifact_hash', '') or raw_result.get('artifact_hash'),
        'feature_data_source': row.feature_data_source,
        'live_feature_compliant': raw_result.get('live_feature_compliant'),
        'signal_score': row.signal_score,
        'up_probability': row.up_probability,
        'action': row.action,
        'risk_level': row.risk_level,
        'target_return_pct': row.target_return_pct,
        'target_return': {
            'low': row.target_return_low_pct,
            'center': row.target_return_pct,
            'high': row.target_return_high_pct,
        },
        'target_price': {
            'low': row.target_price_low,
            'center': row.target_price,
            'high': row.target_price_high,
        },
        'target_market_cap': row.target_market_cap,
        'market_regime': row.market_regime,
        'stock_regime': row.security_regime,
        'refresh_reason': row.refresh_reason,
        'refresh_detail': row.refresh_detail,
        'explain': explain,
        'predictive_tiered_template': row.predictive_tiered_template,
        'data_status': _status(row),
    }
    if include_diagnostics:
        payload['raw_result'] = raw_result
        payload['last_error'] = row.last_error
        payload['snapshot_source'] = getattr(snapshot, 'snapshot_source', '')
        payload['run_key'] = getattr(snapshot, 'run_key', '')
    return _value(payload)


def _current_queryset(security, *, asof_date=None, report_type=None, model_version=None):
    queryset = PredictiveValuationCurrent.objects.select_related('security', 'snapshot').filter(
        security=security,
    )
    if asof_date:
        queryset = queryset.filter(asof_date__lte=asof_date)
    if report_type and report_type not in {'LATEST'}:
        queryset = queryset.filter(report_type=report_type)
    if model_version:
        queryset = queryset.filter(model_version=model_version)
    return queryset


def get_current(*, ts_code, asof_date=None, report_type='LATEST', anchor_mode=None,
                model_version=None, serving_slot=None, include_diagnostics=False):
    report_type = _validate_report_type(report_type)
    anchor_mode = _validate_anchor_mode(anchor_mode)
    model_version, _ = _validate_model_selection(model_version, serving_slot)
    if asof_date and asof_date > date.today():
        raise PredictiveValuationRequestError('INVALID_DATE', 'asof_date 不能晚于当前日期')
    security = _security(ts_code)
    queryset = _current_queryset(
        security, asof_date=asof_date, report_type=report_type, model_version=model_version,
    )
    if anchor_mode:
        queryset = queryset.filter(snapshot__anchor_mode=anchor_mode)
    row = queryset.order_by('-asof_date', '-updated_at').first()
    if row is None:
        raise PredictiveValuationRequestError(
            'RESULT_NOT_FOUND', '指定条件下没有已发布的预测估值结果',
            details={'ts_code': security.ts_code, 'report_type': report_type},
        )
    return _payload(row, include_diagnostics=include_diagnostics)


def get_history(*, ts_code, start_date, end_date, report_type=None, page=1, page_size=50,
                include_diagnostics=False):
    report_type = _validate_report_type(report_type, allow_latest=False) if report_type else None
    if start_date is None or end_date is None:
        raise PredictiveValuationRequestError('INVALID_DATE', 'start_date 和 end_date 均为必填项')
    if start_date > end_date:
        raise PredictiveValuationRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
    if end_date > date.today():
        raise PredictiveValuationRequestError('INVALID_DATE', 'end_date 不能晚于当前日期')
    if end_date - start_date > timedelta(days=MAX_HISTORY_DAYS):
        raise PredictiveValuationRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')
    security = _security(ts_code)
    queryset = PredictiveValuationSnapshot.objects.select_related('security').filter(
        security=security, asof_date__range=(start_date, end_date),
    )
    if report_type:
        queryset = queryset.filter(report_type=report_type)
    total = queryset.count()
    if total > MAX_HISTORY_ROWS:
        raise PredictiveValuationRequestError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = list(queryset.order_by('-asof_date', '-id')[(page - 1) * page_size:page * page_size])
    return {
        'items': [_payload(row, include_diagnostics=include_diagnostics) for row in rows],
        'page': page,
        'page_size': page_size,
        'total': total,
        'has_next': page * page_size < total,
        'asof_date': end_date,
    }


def get_fusion(*, ts_code, asof_date=None, anchor_mode=None, model_version=None,
               include_diagnostics=False):
    return get_current(
        ts_code=ts_code, asof_date=asof_date, report_type='FUSION',
        anchor_mode=anchor_mode, model_version=model_version,
        include_diagnostics=include_diagnostics,
    )


def get_status(*, report_type=None, model_version=None, serving_slot=None):
    report_type = _validate_report_type(report_type, allow_latest=False) if report_type else None
    model_version, serving_slot = _validate_model_selection(model_version, serving_slot)
    report_types = (report_type,) if report_type else QUARTER_REPORT_TYPES
    models = {}
    for item in report_types:
        try:
            artifact = PredictiveArtifactRegistry().load_production(item)
            available = True
            configured_version = artifact.model_version
            error = None
        except (ArtifactValidationError, OSError, ImportError) as exc:
            available = False
            configured_version = None
            error = str(exc)
        queryset = PredictiveValuationCurrent.objects.filter(report_type=item)
        if model_version:
            queryset = queryset.filter(model_version=model_version)
        latest = queryset.order_by('-asof_date', '-updated_at').first()
        models[item] = {
            'artifact_available': available,
            'configured_model_version': configured_version,
            'requested_model_version': model_version,
            'latest_asof_date': _date(latest.asof_date) if latest else None,
            'latest_status': _status(latest) if latest else 'NOT_AVAILABLE',
            'error': error,
        }
    statuses = [item['latest_status'] for item in models.values()]
    data_status = 'COMPLETE' if any(status == 'COMPLETE' for status in statuses) else 'NOT_AVAILABLE'
    return {
        'serving_slot': serving_slot or 'production',
        'model_version': model_version,
        'models': models,
        'data_status': data_status,
    }