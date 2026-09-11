from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from market_data.models import Security

from traditional_valuation.models import (
    TraditionalValuationSnapshot,
    TraditionalValuationSnapshotLatest,
    TraditionalValuationVariantSummaryLatest,
)


MAX_HISTORY_DAYS = 366
MAX_HISTORY_ROWS = 2000
VALID_REPORT_TYPES = {'Q1', 'H1', 'Q3', 'FY'}
VALID_PROFIT_BUCKETS = {'formal', 'blended'}


class TraditionalValuationRequestError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _date(value):
    return value.isoformat() if value else None


def _number(value):
    return float(value) if value is not None else None


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _validate_report_type(value):
    if value is not None and value not in VALID_REPORT_TYPES:
        raise TraditionalValuationRequestError('UNSUPPORTED_REPORT_TYPE', 'report_type 不受支持')
    return value


def _validate_profit_bucket(value):
    if value is not None and value not in VALID_PROFIT_BUCKETS:
        raise TraditionalValuationRequestError('INVALID_REQUEST', 'profit_bucket 仅支持 formal 或 blended')
    return value


def _query_filters(*, report_type=None, financial_end_date=None, profit_bucket=None, variant=None, style_profile=None):
    filters = {}
    if report_type:
        filters['report_type'] = report_type
    if financial_end_date:
        filters['financial_end_date'] = financial_end_date
    if profit_bucket:
        filters['profit_bucket'] = profit_bucket
    if variant:
        filters['valuation_variant'] = variant
    if style_profile:
        filters['style_profile'] = style_profile
    return filters


def _method_rows(snapshot, *, include_diagnostics):
    methods = snapshot.methods or {}
    skipped = (snapshot.summary or {}).get('skipped_methods') or {}
    rows = []
    for method_name, payload in methods.items():
        row = {'valuation_method': method_name, **_json_value(payload or {})}
        if not include_diagnostics:
            row.pop('input_field_names', None)
            row.pop('source_record_ids', None)
            row.pop('parameter_keys', None)
        rows.append(row)
    for method_name, reason in skipped.items():
        if not any(row['valuation_method'] == method_name for row in rows):
            rows.append({
                'valuation_method': method_name,
                'available': False,
                'skip_reason': reason,
            })
    return rows


def _summary(snapshot):
    summary = dict(snapshot.summary or {})
    summary.setdefault('composite_valuation_price_raw', _number(snapshot.composite_valuation_price_raw))
    summary.setdefault('composite_valuation_price_optimized', _number(snapshot.composite_valuation_price_optimized))
    summary.setdefault('conservative_valuation_price_raw', _number(snapshot.conservative_valuation_price_raw))
    summary.setdefault('conservative_valuation_price_optimized', _number(snapshot.conservative_valuation_price_optimized))
    return _json_value(summary)


def _risk(risk):
    if risk is None:
        return None
    return {
        'risk_engine_version': risk.risk_engine_version,
        'risk_score': _number(risk.risk_score),
        'risk_level': risk.risk_level,
        'confidence': _number(risk.confidence),
        'factors': _json_value(risk.factors or {}),
        'adjustment': _json_value(risk.adjustment or {}),
    }


def _variant_payload(row, *, include_diagnostics):
    payload = {
        'valuation_variant': row.valuation_variant,
        'compare_group': row.compare_group,
        'industry_level': row.industry_level,
        'industry_code': row.industry_code,
        'industry_name': row.industry_name,
        'match_rank': row.match_rank,
        'match_score': _number(row.match_score),
        'composite_valuation_price': _number(row.composite_valuation_price),
        'conservative_valuation_price': _number(row.conservative_valuation_price),
        'method_coverage': row.method_coverage,
        'is_active_variant': row.is_active_variant,
    }
    provenance = _json_value(row.provenance or {})
    if include_diagnostics:
        payload['provenance'] = provenance
        payload['summary'] = provenance.get('buy_candidate_summary') or {}
    else:
        candidate = provenance.get('buy_candidate_summary') or {}
        payload['summary'] = {
            key: candidate.get(key)
            for key in (
                'undervalue_score', 'buy_candidate', 'buy_candidate_reason',
                'buy_candidate_rule_version', 'valuation_valid_methods',
                'valuation_under_methods', 'valuation_core_methods',
            )
            if key in candidate
        }
    return payload


def _snapshot_payload(snapshot, *, include_methods, include_risk, include_variants, include_diagnostics, variant_rows=None):
    summary = _summary(snapshot)
    payload = {
        'snapshot_id': snapshot.id,
        'ts_code': snapshot.security.ts_code,
        'asof_date': _date(snapshot.asof_date),
        'source_trade_date': _date(snapshot.source_trade_date),
        'report_type': snapshot.report_type,
        'financial_end_date': _date(snapshot.financial_end_date),
        'financial_ann_date': _date(snapshot.financial_ann_date),
        'profit_bucket': snapshot.profit_bucket,
        'valuation_variant': snapshot.valuation_variant,
        'style_profile': snapshot.style_profile,
        'parameter_version': snapshot.parameter_version,
        'engine_version': snapshot.valuation_engine_version,
        'current_price': _number(snapshot.current_price),
        'summary': summary,
        'source_data_status': summary.get('source_data_status', 'COMPLETE'),
        'freshness': summary.get('freshness', {}),
        'degraded_reasons': summary.get('degraded_reasons', []),
        'active_variant': summary.get('active_variant', snapshot.valuation_variant),
    }
    if include_methods:
        payload['methods'] = _method_rows(snapshot, include_diagnostics=include_diagnostics)
    if include_risk:
        payload['risk'] = _risk(getattr(snapshot, 'risk_snapshot', None))
    if include_variants:
        payload['variants'] = [
            _variant_payload(row, include_diagnostics=include_diagnostics)
            for row in (variant_rows or [])
        ]
    if include_diagnostics:
        payload['provenance'] = _json_value(snapshot.provenance or {})
        payload['parameter_source_hash'] = snapshot.parameter_source_hash
    return payload


def _validate_asof(asof_date):
    if asof_date and asof_date > date.today():
        raise TraditionalValuationRequestError('INVALID_DATE', 'asof_date 不能晚于当前日期')


def _get_security(ts_code):
    try:
        return Security.objects.get(ts_code=ts_code)
    except Security.DoesNotExist as exc:
        raise TraditionalValuationRequestError('SECURITY_NOT_FOUND', '证券不存在') from exc


def _base_queryset(security, *, asof_date=None, report_type=None, profit_bucket=None, variant=None, style_profile=None):
    filters = _query_filters(
        report_type=report_type,
        profit_bucket=profit_bucket,
        variant=variant,
        style_profile=style_profile,
    )
    queryset = TraditionalValuationSnapshot.objects.select_related('security', 'risk_snapshot').filter(
        security=security, **filters,
    )
    if asof_date:
        queryset = queryset.filter(asof_date__lte=asof_date)
    return queryset


def get_current(*, ts_code, asof_date=None, report_type=None, financial_end_date=None, profit_bucket='formal', variant=None, style_profile='baseline', include_methods=False, include_risk=True, include_variants=False, include_diagnostics=False):
    report_type = _validate_report_type(report_type)
    profit_bucket = _validate_profit_bucket(profit_bucket)
    _validate_asof(asof_date)
    security = _get_security(ts_code)
    filters = _query_filters(
        report_type=report_type,
        profit_bucket=profit_bucket,
        variant=variant,
        style_profile=style_profile,
    )
    queryset = TraditionalValuationSnapshotLatest.objects.select_related(
        'snapshot', 'risk_snapshot', 'security',
    ).filter(security=security, **filters)
    if financial_end_date:
        queryset = queryset.filter(snapshot__financial_end_date=financial_end_date)
    if asof_date:
        queryset = queryset.filter(asof_date__lte=asof_date)
    latest = queryset.order_by('-asof_date', '-updated_at').first()
    if latest is None:
        raise TraditionalValuationRequestError(
            'RESULT_NOT_FOUND', '指定条件下没有已发布的传统估值结果',
            details={'ts_code': security.ts_code, **filters},
        )
    snapshot = latest.snapshot
    variant_rows = []
    if include_variants:
        variant_rows = list(TraditionalValuationVariantSummaryLatest.objects.filter(
            security=security,
            report_type=snapshot.report_type,
            profit_bucket=snapshot.profit_bucket,
            style_profile=snapshot.style_profile,
            snapshot=snapshot,
        ).order_by('match_rank', 'valuation_variant'))
    payload = _snapshot_payload(
        snapshot,
        include_methods=include_methods,
        include_risk=include_risk,
        include_variants=include_variants,
        include_diagnostics=include_diagnostics,
        variant_rows=variant_rows,
    )
    payload['active_variant'] = latest.valuation_variant if latest.valuation_variant else payload['active_variant']
    return payload


def get_history(*, ts_code, start_date, end_date, report_type=None, profit_bucket=None, variant=None, style_profile=None, page=1, page_size=50, include_diagnostics=False):
    report_type = _validate_report_type(report_type)
    profit_bucket = _validate_profit_bucket(profit_bucket)
    _validate_asof(end_date)
    if start_date is None or end_date is None:
        raise TraditionalValuationRequestError('INVALID_DATE', 'start_date 和 end_date 均为必填项')
    if start_date > end_date:
        raise TraditionalValuationRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
    if end_date - start_date > timedelta(days=MAX_HISTORY_DAYS):
        raise TraditionalValuationRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')
    security = _get_security(ts_code)
    queryset = _base_queryset(
        security, report_type=report_type, profit_bucket=profit_bucket,
        variant=variant, style_profile=style_profile,
    ).filter(asof_date__range=(start_date, end_date)).order_by('-asof_date', '-id')
    total = queryset.count()
    if total > MAX_HISTORY_ROWS:
        raise TraditionalValuationRequestError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = list(queryset[(page - 1) * page_size:page * page_size])
    return {
        'items': [_snapshot_payload(row, include_methods=False, include_risk=True, include_variants=False, include_diagnostics=include_diagnostics) for row in rows],
        'page': page, 'page_size': page_size, 'total': total,
        'has_next': page * page_size < total,
        'asof_date': end_date,
    }


def get_compare(*, ts_code, asof_date=None, report_type=None, financial_end_date=None, profit_bucket='formal', variant=None, style_profile='baseline', limit=10, include_methods=False, include_diagnostics=False):
    report_type = _validate_report_type(report_type)
    profit_bucket = _validate_profit_bucket(profit_bucket)
    _validate_asof(asof_date)
    security = _get_security(ts_code)
    filters = {'security': security, 'profit_bucket': profit_bucket, 'style_profile': style_profile}
    if report_type:
        filters['report_type'] = report_type
    queryset = TraditionalValuationVariantSummaryLatest.objects.filter(
        **filters,
    ).select_related('snapshot').order_by('match_rank', 'valuation_variant')
    if financial_end_date:
        queryset = queryset.filter(snapshot__financial_end_date=financial_end_date)
    if asof_date:
        queryset = queryset.filter(asof_date__lte=asof_date)
    if variant:
        queryset = queryset.filter(valuation_variant=variant)
    rows = list(queryset[:limit])
    if not rows:
        raise TraditionalValuationRequestError('RESULT_NOT_FOUND', '指定条件下没有已发布的传统估值变体')
    snapshot = rows[0].snapshot
    payload = {
        'ts_code': security.ts_code,
        'asof_date': _date(snapshot.asof_date),
        'source_trade_date': _date(snapshot.source_trade_date),
        'report_type': snapshot.report_type,
        'financial_end_date': _date(snapshot.financial_end_date),
        'profit_bucket': snapshot.profit_bucket,
        'style_profile': snapshot.style_profile,
        'active_variant': next((row.valuation_variant for row in rows if row.is_active_variant), None),
        'variants': [_variant_payload(row, include_diagnostics=include_diagnostics) for row in rows],
    }
    if include_methods:
        payload['methods'] = _method_rows(snapshot, include_diagnostics=include_diagnostics)
    if include_diagnostics:
        payload['provenance'] = _json_value(snapshot.provenance or {})
    return payload
