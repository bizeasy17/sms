from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from market_data.models import (
    MarketBarDailyHistory,
    Security,
    StockDailyFundamentalHistory,
)


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_HISTORY_DAYS = 366
MAX_HISTORY_ROWS = 2000
VALID_ASSET_TYPES = {value for value, _ in Security.AssetType.choices}
VALID_BAR_ADJUSTMENTS = {'raw', 'qfq', 'hfq'}
VALID_FREQUENCIES = {'D'}


class MarketDataRequestError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class Page:
    items: list
    page: int
    page_size: int
    total: int

    @property
    def has_next(self):
        return self.page * self.page_size < self.total


def parse_date(value, field_name):
    if value in (None, ''):
        return None
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise MarketDataRequestError('INVALID_DATE', f'{field_name} 必须为 YYYY-MM-DD') from exc
    return parsed


def parse_pagination(params):
    try:
        page = int(params.get('page', 1))
        page_size = int(params.get('page_size', DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError) as exc:
        raise MarketDataRequestError('INVALID_REQUEST', 'page 和 page_size 必须为整数') from exc
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise MarketDataRequestError(
            'INVALID_REQUEST',
            f'page 必须大于等于 1，page_size 范围为 1-{MAX_PAGE_SIZE}',
        )
    return page, page_size


def parse_history_range(params):
    start_date = parse_date(params.get('start_date'), 'start_date')
    end_date = parse_date(params.get('end_date'), 'end_date')
    if start_date is None or end_date is None:
        raise MarketDataRequestError('INVALID_DATE', 'start_date 和 end_date 均为必填项')
    if start_date > end_date:
        raise MarketDataRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
    if end_date - start_date > timedelta(days=MAX_HISTORY_DAYS):
        raise MarketDataRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')
    return start_date, end_date


def normalize_ts_code(raw_code):
    code = str(raw_code or '').strip().upper()
    if not code or len(code) > 16:
        raise MarketDataRequestError('INVALID_SYMBOL', '交易代码格式无效')
    exact = Security.objects.filter(ts_code=code)
    if exact.exists():
        return code
    candidates = list(Security.objects.filter(ts_code__startswith=f'{code}.').values_list('ts_code', flat=True)[:2])
    if len(candidates) != 1:
        if not candidates:
            raise MarketDataRequestError('SECURITY_NOT_FOUND', '证券不存在')
        raise MarketDataRequestError('INVALID_SYMBOL', '交易代码无法唯一解析')
    return candidates[0]


def _number(value):
    return float(value) if value is not None else None


def _date(value):
    return value.isoformat() if value is not None else None


def _datetime(value):
    return value.isoformat() if value is not None else None


def security_payload(security, *, include_profile=False):
    payload = {
        'ts_code': security.ts_code,
        'asset_type': security.asset_type,
        'symbol': security.symbol,
        'name': security.name,
        'full_name': security.full_name,
        'market': security.market,
        'exchange': security.exchange,
        'list_status': security.list_status,
        'list_date': _date(security.list_date),
        'delist_date': _date(security.delist_date),
        'is_hs': security.is_hs,
        'industry': security.industry.name if security.industry_id else None,
        'area': security.area.name if security.area_id else None,
        'source_updated_at': _datetime(security.source_updated_at),
    }
    if include_profile:
        try:
            profile = security.company_profile
        except Security.company_profile.RelatedObjectDoesNotExist:
            profile = None
        payload['company_profile'] = None if profile is None else {
            'chairman': profile.chairman,
            'manager': profile.manager,
            'secretary': profile.secretary,
            'setup_date': _date(profile.setup_date),
            'province': profile.province_name,
            'city': profile.city_name,
            'exchange': profile.exchange,
            'website': profile.website,
            'employees': profile.employees,
            'main_business': profile.main_business,
            'business_scope': profile.business_scope,
            'source_updated_at': _datetime(profile.source_updated_at),
        }
    return payload


def list_securities(*, filters, page, page_size):
    queryset = Security.objects.select_related('industry', 'area').order_by('ts_code')
    asset_type = filters.get('asset_type')
    if asset_type:
        asset_type = str(asset_type).upper()
        if asset_type not in VALID_ASSET_TYPES:
            raise MarketDataRequestError('INVALID_REQUEST', 'asset_type 无效')
        queryset = queryset.filter(asset_type=asset_type)
    for field in ('market', 'industry', 'list_status'):
        value = str(filters.get(field, '')).strip()
        if value:
            queryset = queryset.filter(**({f'{field}__name' if field == 'industry' else field: value}))
    query = str(filters.get('q', '')).strip()
    if query:
        queryset = queryset.filter(name__icontains=query) | queryset.filter(ts_code__icontains=query)
    total = queryset.count()
    items = list(queryset[(page - 1) * page_size:page * page_size])
    return Page([security_payload(item) for item in items], page, page_size, total)


def get_security(*, ts_code):
    canonical = normalize_ts_code(ts_code)
    try:
        return Security.objects.select_related('industry', 'area', 'company_profile').get(ts_code=canonical)
    except Security.DoesNotExist as exc:
        raise MarketDataRequestError('SECURITY_NOT_FOUND', '证券不存在') from exc


def _bar_payload(row, adjust):
    suffix = '' if adjust == 'raw' else f'_{adjust}'
    return {
        'ts_code': row.security.ts_code,
        'trade_date': _date(row.trade_date),
        'frequency': 'D',
        'open': _number(getattr(row, f'open{suffix}')),
        'high': _number(getattr(row, f'high{suffix}')),
        'low': _number(getattr(row, f'low{suffix}')),
        'close': _number(getattr(row, f'close{suffix}')),
        'pre_close': _number(getattr(row, f'pre_close{suffix}')),
        'change': _number(getattr(row, f'change{suffix}')),
        'pct_change': _number(getattr(row, f'pct_change{suffix}')),
        'volume': row.volume,
        'amount': _number(row.amount),
        'adjust': adjust,
        'source_updated_at': _datetime(row.source_updated_at),
        'synced_at': _datetime(row.synced_at),
    }


def get_bars(*, ts_code, start_date, end_date, adjust, frequency, page, page_size):
    if adjust not in VALID_BAR_ADJUSTMENTS:
        raise MarketDataRequestError('INVALID_REQUEST', 'adjust 仅支持 raw、qfq、hfq')
    if frequency not in VALID_FREQUENCIES:
        raise MarketDataRequestError('UNSUPPORTED_FREQUENCY', '当前仅支持日线 frequency=D')
    security = get_security(ts_code=ts_code)
    queryset = MarketBarDailyHistory.objects.select_related('security').filter(
        security=security, trade_date__range=(start_date, end_date),
    ).order_by('-trade_date')
    total = queryset.count()
    if total > MAX_HISTORY_ROWS:
        raise MarketDataRequestError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = list(queryset[(page - 1) * page_size:page * page_size])
    if adjust != 'raw' and rows and all(getattr(row, f'close_{adjust}') is None for row in rows):
        raise MarketDataRequestError('INSUFFICIENT_DATA', f'{adjust} 调整数据不可用')
    return Page([_bar_payload(row, adjust) for row in rows], page, page_size, total)


def _fundamental_payload(row):
    fields = (
        'close', 'turnover_rate', 'turnover_rate_f', 'volume_ratio', 'pe', 'pe_ttm', 'pb',
        'ps', 'ps_ttm', 'dv_ratio', 'dv_ttm', 'total_share', 'float_share', 'free_share',
        'total_mv', 'circ_mv',
    )
    return {
        'ts_code': row.security.ts_code,
        'trade_date': _date(row.trade_date),
        **{field: _number(getattr(row, field)) for field in fields},
        'source_updated_at': _datetime(row.source_updated_at),
        'synced_at': _datetime(row.synced_at),
        'units': {'share': '10k_shares', 'market_cap': '10k_CNY', 'rates': 'percentage_points'},
    }


def get_fundamentals(*, ts_code, start_date, end_date, page, page_size):
    security = get_security(ts_code=ts_code)
    if security.asset_type != Security.AssetType.STOCK:
        raise MarketDataRequestError('UNSUPPORTED_REQUEST', '日基本面仅支持股票')
    queryset = StockDailyFundamentalHistory.objects.select_related('security').filter(
        security=security, trade_date__range=(start_date, end_date),
    ).order_by('-trade_date')
    total = queryset.count()
    if total > MAX_HISTORY_ROWS:
        raise MarketDataRequestError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = list(queryset[(page - 1) * page_size:page * page_size])
    return Page([_fundamental_payload(row) for row in rows], page, page_size, total)