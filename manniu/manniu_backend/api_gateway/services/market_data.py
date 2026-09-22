from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import pypinyin

from market_data.models import (
    MarketBarDailyHistory,
    Security,
    SWIndustryDailyHistory,
    StockDailyFundamentalHistory,
)
from market_data.services.industry import IndustryMappingError, resolve_sw_industry_mapping


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_HISTORY_DAYS = 366
MAX_HISTORY_ROWS = 2000
DEFAULT_EVIDENCE_DAYS = 60
MAX_EVIDENCE_DAYS = 200
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


def _normalized_search_text(value):
    return ''.join(char for char in str(value or '').strip().lower() if char.isalnum())


@lru_cache(maxsize=8192)
def _security_search_keys(name):
    syllables = pypinyin.pinyin(name or '', style=pypinyin.NORMAL)
    full_pinyin = ''.join(item[0] for item in syllables if item)
    initials = ''.join(item[0][0] for item in syllables if item and item[0])
    return (
        _normalized_search_text(name),
        _normalized_search_text(full_pinyin),
        _normalized_search_text(initials),
    )


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
        normalized_query = _normalized_search_text(query)
        securities = list(queryset)
        securities = [
            security for security in securities
            if query.lower() in (security.name or '').lower()
            or query.lower() in security.ts_code.lower()
            or any(normalized_query in key for key in _security_search_keys(security.name))
        ]
        total = len(securities)
        items = securities[(page - 1) * page_size:page * page_size]
        return Page([security_payload(item) for item in items], page, page_size, total)
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


def _trend(current, previous, *, tolerance=0.001):
    if current is None or previous is None:
        return None
    delta = float(current) - float(previous)
    if abs(delta) <= abs(float(current)) * tolerance:
        return 'FLAT'
    return 'UP' if delta > 0 else 'DOWN'


def _atr_values(rows, period=14):
    true_ranges = []
    previous_close = None
    for row in rows:
        if row.high is None or row.low is None:
            previous_close = row.close
            continue
        candidates = [float(row.high) - float(row.low)]
        if previous_close is not None:
            candidates.extend((
                abs(float(row.high) - float(previous_close)),
                abs(float(row.low) - float(previous_close)),
            ))
        true_ranges.append((row.trade_date, max(candidates)))
        previous_close = row.close
    atr_values = []
    for index in range(period - 1, len(true_ranges)):
        window = true_ranges[index - period + 1:index + 1]
        atr_values.append((window[-1][0], sum(item[1] for item in window) / period))
    return atr_values


def _industry_security_for_identity(identity):
    industry_code = str(identity.get('index_code') or identity.get('industry_code') or '').strip().upper()
    if not industry_code:
        return None
    exact = Security.objects.filter(ts_code=industry_code, asset_type=Security.AssetType.INDEX).first()
    if exact is not None:
        return exact
    root = industry_code.split('.')[0]
    return Security.objects.filter(
        ts_code__startswith=f'{root}.', asset_type=Security.AssetType.INDEX, market='SW',
    ).first()


def _industry_closes(security, rows):
    if security is None:
        return {}
    return dict(SWIndustryDailyHistory.objects.filter(
        security=security,
        trade_date__in=[row.trade_date for row in rows],
        close__isnull=False,
    ).values_list('trade_date', 'close'))


def get_market_evidence(*, ts_code, days=DEFAULT_EVIDENCE_DAYS):
    try:
        days = int(days)
    except (TypeError, ValueError) as exc:
        raise MarketDataRequestError('INVALID_REQUEST', 'days 必须为整数') from exc
    if days < 1 or days > MAX_EVIDENCE_DAYS:
        raise MarketDataRequestError('INVALID_REQUEST', f'days 范围为 1-{MAX_EVIDENCE_DAYS}')

    security = get_security(ts_code=ts_code)
    if security.asset_type != Security.AssetType.STOCK:
        raise MarketDataRequestError('UNSUPPORTED_REQUEST', '市场证据仅支持股票')

    calculation_rows = list(MarketBarDailyHistory.objects.filter(
        security=security, close__isnull=False,
    ).order_by('-trade_date')[:max(days, 205)])
    if not calculation_rows:
        raise MarketDataRequestError('INSUFFICIENT_DATA', '股票日线数据不足')
    calculation_rows.reverse()
    rows = calculation_rows[-days:]
    warnings = []

    industry_security = None
    industry_identity = {}
    try:
        industry_identity = resolve_sw_industry_mapping(security=security)
        industry_security = _industry_security_for_identity(industry_identity)
    except IndustryMappingError:
        warnings.append('SW_INDUSTRY_MAPPING_UNAVAILABLE')
    industry_closes = _industry_closes(industry_security, rows)
    if not industry_closes:
        parent_index_code = industry_identity.get('parent_index_code') or industry_identity.get('parent_code')
        parent_identity = resolve_sw_industry_mapping(index_code=parent_index_code) if parent_index_code else {}
        parent_security = _industry_security_for_identity(parent_identity)
        parent_closes = _industry_closes(parent_security, rows)
        if parent_closes:
            warnings.append('SW_INDUSTRY_L3_DATA_UNAVAILABLE_FALLBACK_L2')
            industry_identity = parent_identity
            industry_security = parent_security
            industry_closes = parent_closes
        else:
            warnings.append('SW_INDUSTRY_DATA_UNAVAILABLE')

    industry_name = (
        str(industry_identity.get('industry_name') or industry_identity.get('name') or '').strip()
        or (industry_security.name.strip() if industry_security and industry_security.name else None)
    )

    atr_values = [item for item in _atr_values(calculation_rows) if item[0] >= rows[0].trade_date]
    current_atr = atr_values[-1][1] if atr_values else None
    atr_percentile = None
    if current_atr is not None:
        atr_percentile = sum(value <= current_atr for _, value in atr_values) / len(atr_values) * 100
    closes = [float(row.close) for row in calculation_rows if row.close is not None]
    ma25 = sum(closes[-25:]) / 25 if len(closes) >= 25 else None
    ma25_previous = sum(closes[-30:-5]) / 25 if len(closes) >= 30 else None
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    ma200_previous = sum(closes[-205:-5]) / 200 if len(closes) >= 205 else None
    current_price = closes[-1]
    first_price = float(rows[0].close) if rows[0].close is not None else None
    last_industry_close = industry_closes.get(rows[-1].trade_date)
    first_industry_close = industry_closes.get(rows[0].trade_date)
    relative_strength = None
    if first_price and first_industry_close and last_industry_close is not None:
        relative_strength = (current_price / first_price - 1) - (float(last_industry_close) / float(first_industry_close) - 1)

    return {
        'security': {'ts_code': security.ts_code, 'name': security.name},
        'industry': {
            'index_code': industry_identity.get('index_code'),
            'industry_code': industry_identity.get('industry_code'),
            'name': industry_name,
        },
        'history': [
            {
                'trade_date': _date(row.trade_date),
                'open': _number(row.open),
                'high': _number(row.high),
                'low': _number(row.low),
                'close': _number(row.close),
                'industry_close': _number(industry_closes.get(row.trade_date)),
            }
            for row in rows
        ],
        'summary': {
            'atr_14': current_atr,
            'atr_14_percentile_60d': atr_percentile,
            'ma25': ma25,
            'ma25_trend': _trend(ma25, ma25_previous),
            'ma200': ma200,
            'ma200_trend': _trend(ma200, ma200_previous),
            'current_price': current_price,
            'price_to_ma25': current_price / ma25 if ma25 else None,
            'relative_strength_vs_industry': relative_strength,
        },
        'requested_days': days,
        'returned_days': len(rows),
        'warnings': warnings,
    }


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