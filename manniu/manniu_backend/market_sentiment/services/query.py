from __future__ import annotations

from django.db.models import F

from api_gateway.services.market_data import Page, normalize_ts_code
from market_data.models import Security

from market_sentiment.models import MarketSentimentSnapshot, StockSentimentSnapshot
from market_sentiment.services.engine import ENGINE_VERSION


class SentimentQueryError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _number(value):
    return float(value) if value is not None else None


def _datetime(value):
    return value.isoformat() if value is not None else None


def _snapshot_payload(snapshot, *, stock=False):
    payload = {
        'scope': 'STOCK' if stock else snapshot.scope_type,
        'scope_code': snapshot.security.ts_code if stock else snapshot.scope_code,
        'trade_date': snapshot.trade_date.isoformat(),
        'score': _number(snapshot.score),
        'level': snapshot.level,
        'status': snapshot.status,
        'raw_score': _number(snapshot.raw_score),
        'standardized_score': _number(snapshot.standardized_score),
        'momentum': _number(snapshot.momentum),
        'activity': _number(snapshot.activity),
        'fear': _number(snapshot.fear),
        'coverage': _number(snapshot.coverage),
        'sample_count': snapshot.valid_count,
        'universe_count': snapshot.universe_count,
        'engine_version': snapshot.engine_version,
        'calculated_at': _datetime(snapshot.calculated_at),
        'source_trade_date': snapshot.source_trade_date.isoformat() if snapshot.source_trade_date else None,
        'metadata': snapshot.metadata or {},
    }
    if stock:
        payload.update({
            'ts_code': snapshot.security.ts_code,
            'normalization_mode': snapshot.normalization_mode,
            'peer_type': snapshot.peer_type,
            'peer_code': snapshot.peer_code,
            'peer_name': snapshot.peer_name,
            'valid_peer_count': snapshot.peer_count,
            'stock_history_count': (snapshot.metadata or {}).get('valid_history', 0),
        })
    return payload


def _engine_filter(queryset, engine_version):
    version = engine_version or ENGINE_VERSION
    return queryset.filter(engine_version=version), version


def _require_engine(queryset, model, engine_version):
    queryset, version = _engine_filter(queryset, engine_version)
    if not model.objects.filter(engine_version=version).exists():
        raise SentimentQueryError(
            'VERSION_CONFLICT',
            '指定的情绪 engine_version 不存在',
            details={'engine_version': version},
        )
    return queryset, version


def get_market_snapshot(*, asof_date, engine_version=None):
    queryset, _ = _require_engine(
        MarketSentimentSnapshot.objects.filter(
            market='CN', scope_type='MARKET', scope_code='ALL_A', trade_date__lte=asof_date,
        ),
        MarketSentimentSnapshot,
        engine_version,
    )
    snapshot = queryset.order_by('-trade_date').first()
    if snapshot is None:
        raise SentimentQueryError('RESULT_NOT_FOUND', '指定日期没有市场情绪快照')
    return _snapshot_payload(snapshot)


def get_market_history(*, start_date, end_date, page, page_size, engine_version=None):
    queryset, _ = _require_engine(
        MarketSentimentSnapshot.objects.filter(
            market='CN', scope_type='MARKET', scope_code='ALL_A',
            trade_date__range=(start_date, end_date),
        ).order_by('-trade_date'),
        MarketSentimentSnapshot,
        engine_version,
    )
    total = queryset.count()
    if total > 2000:
        raise SentimentQueryError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = queryset[(page - 1) * page_size:page * page_size]
    return Page([_snapshot_payload(row) for row in rows], page, page_size, total)


def _get_security(ts_code):
    canonical = normalize_ts_code(ts_code)
    try:
        return Security.objects.get(ts_code=canonical)
    except Security.DoesNotExist as error:
        raise SentimentQueryError('SECURITY_NOT_FOUND', '证券不存在') from error


def get_stock_snapshot(*, ts_code, asof_date, engine_version=None):
    security = _get_security(ts_code)
    queryset, _ = _require_engine(
        StockSentimentSnapshot.objects.filter(security=security, trade_date__lte=asof_date),
        StockSentimentSnapshot,
        engine_version,
    )
    snapshot = queryset.select_related('security').order_by('-trade_date').first()
    if snapshot is None:
        raise SentimentQueryError('RESULT_NOT_FOUND', '指定日期没有个股情绪快照')
    return _snapshot_payload(snapshot, stock=True)


def get_stock_history(*, ts_code, start_date, end_date, page, page_size, engine_version=None):
    security = _get_security(ts_code)
    queryset, _ = _require_engine(
        StockSentimentSnapshot.objects.filter(
            security=security, trade_date__range=(start_date, end_date),
        ).select_related('security').order_by('-trade_date'),
        StockSentimentSnapshot,
        engine_version,
    )
    total = queryset.count()
    if total > 2000:
        raise SentimentQueryError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = queryset[(page - 1) * page_size:page * page_size]
    return Page([_snapshot_payload(row, stock=True) for row in rows], page, page_size, total)


def get_stock_ranking(*, asof_date, page, page_size, engine_version=None, status=None):
    filters = {'trade_date': asof_date}
    if status:
        filters['status'] = status
    queryset, _ = _require_engine(
        StockSentimentSnapshot.objects.filter(**filters).select_related('security').order_by(
            F('score').desc(nulls_last=True), 'security__ts_code'
        ),
        StockSentimentSnapshot,
        engine_version,
    )
    total = queryset.count()
    rows = queryset[(page - 1) * page_size:page * page_size]
    return Page([_snapshot_payload(row, stock=True) for row in rows], page, page_size, total)
