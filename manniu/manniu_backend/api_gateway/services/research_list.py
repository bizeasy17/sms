from __future__ import annotations

from datetime import date
from decimal import Decimal

from market_data.models import MarketBarDailyHistory, MarketBarLatest, SWIndustryMappingVersion, Security
from personal_user.models import HoldingPosition, UserSecurityListItem
from predictive_valuation.models import PredictiveValuationCurrent
from traditional_valuation.models import (
    TraditionalValuationSnapshotLatest,
    TraditionalValuationVariantSummaryLatest,
)

from .market_data import MarketDataRequestError, Page, _normalized_search_text, _security_search_keys


POOL_VALUES = {'holding', 'watchlist', 'observe', 'market'}
MARKET_VALUES = {'all', 'sh-main', 'sz-main', 'cyb', 'star'}


def _number(value):
    return float(value) if isinstance(value, Decimal) else value


def _date(value):
    return value.isoformat() if value else None


def _canonical_industry_code(value):
    return str(value or '').strip().upper().split('.')[0]


def _active_mapping():
    return SWIndustryMappingVersion.objects.filter(
        market='CN', is_active=True,
    ).order_by('-published_at').first()


def _industry_identity(mapping, security):
    if mapping is None:
        return {}
    membership = (mapping.artifact or {}).get('ts_code_to_levels') or (mapping.artifact or {}).get('membership') or {}
    identity = membership.get(security.ts_code.upper()) or {}
    for key in ('l3_code', 'l2_code', 'l1_code'):
        code = identity.get(key)
        if code:
            level = key[:2].upper()
            entries = (mapping.artifact or {}).get('levels', {}).get(level, {})
            for entry_key, entry in entries.items():
                entry = entry or {}
                candidates = {str(entry_key).upper(), str(entry.get('index_code') or '').upper(), str(entry.get('industry_code') or '').upper()}
                if str(code).upper() in candidates:
                    return {
                        'level': entry.get('sw_level') or level,
                        'code': entry.get('industry_code') or entry.get('index_code') or code,
                        'name': entry.get('industry_name') or entry.get('name') or '',
                    }
    return {}


def _industry_codes(mapping, requested):
    code = _canonical_industry_code(requested)
    if not code:
        return None
    if mapping is None:
        raise MarketDataRequestError('UPSTREAM_DEPENDENCY_UNAVAILABLE', 'SW 行业映射暂不可用')
    levels = (mapping.artifact or {}).get('levels', {})
    matched = set()
    for entries in levels.values():
        for entry_key, entry in (entries or {}).items():
            entry = entry or {}
            if code in {
                _canonical_industry_code(entry_key),
                _canonical_industry_code(entry.get('index_code')),
                _canonical_industry_code(entry.get('industry_code')),
            }:
                matched.add(code)
                break
    if not matched:
        raise MarketDataRequestError('INVALID_REQUEST', 'industry 不是有效的 SW 行业代码')
    membership = (mapping.artifact or {}).get('ts_code_to_levels') or (mapping.artifact or {}).get('membership') or {}
    return {
        ts_code for ts_code, identity in membership.items()
        if any(_canonical_industry_code(identity.get(key)) == code for key in ('l3_code', 'l2_code', 'l1_code'))
    }


def _market_match(ts_code, market):
    if market == 'all':
        return True
    code, _, exchange = ts_code.upper().partition('.')
    if market == 'sh-main':
        return exchange == 'SH' and not code.startswith('688')
    if market == 'sz-main':
        return exchange == 'SZ' and not code.startswith(('300', '301'))
    if market == 'cyb':
        return exchange == 'SZ' and code.startswith(('300', '301'))
    return exchange == 'SH' and code.startswith('688')


def _user_security_ids(user, pool):
    if pool == 'watchlist':
        return set(UserSecurityListItem.objects.filter(
            user=user, list_type=UserSecurityListItem.ListType.WATCHLIST,
        ).values_list('security_id', flat=True))
    if pool == 'observe':
        return set(UserSecurityListItem.objects.filter(
            user=user, list_type=UserSecurityListItem.ListType.OBSERVATION,
        ).values_list('security_id', flat=True))
    return set(HoldingPosition.objects.filter(
        user=user, portfolio__archived_at__isnull=True,
    ).values_list('security_id', flat=True))


def _traditional_rows(securities, asof_date):
    latest = TraditionalValuationSnapshotLatest.objects.select_related('snapshot').filter(
        security_id__in=[security.id for security in securities],
        profit_bucket='formal', style_profile='baseline',
    )
    if asof_date:
        latest = latest.filter(asof_date__lte=asof_date)
    latest_by_security = {}
    for row in latest.order_by('security_id', '-asof_date', '-updated_at'):
        latest_by_security.setdefault(row.security_id, row)
    summaries = TraditionalValuationVariantSummaryLatest.objects.filter(
        security_id__in=list(latest_by_security), profit_bucket='formal', style_profile='baseline',
        is_active_variant=True,
    )
    summary_by_security = {}
    for row in summaries.order_by('security_id', '-asof_date', '-updated_at'):
        summary_by_security.setdefault(row.security_id, row)
    result = {}
    for security in securities:
        latest_row = latest_by_security.get(security.id)
        summary = summary_by_security.get(security.id)
        if latest_row is None or summary is None:
            result[security.id] = {'status': 'NOT_AVAILABLE', 'action': None, 'undervalue_score': None, 'reason_code': 'RESULT_NOT_FOUND'}
            continue
        candidate = (summary.provenance or {}).get('buy_candidate_summary') or {}
        score = candidate.get('undervalue_score')
        result[security.id] = {
            'status': 'OK',
            'action': 'BUY' if candidate.get('buy_candidate') else 'HOLD',
            'undervalue_score': _number(score),
            'asof_date': _date(latest_row.asof_date),
            'source_trade_date': _date(latest_row.source_trade_date),
            'valuation_variant': summary.valuation_variant,
            'reason_code': None,
        }
    return result


def _predictive_rows(securities, asof_date):
    rows = PredictiveValuationCurrent.objects.select_related('snapshot').filter(
        security_id__in=[security.id for security in securities],
    )
    if asof_date:
        rows = rows.filter(asof_date__lte=asof_date)
    by_security = {}
    for row in rows.order_by('security_id', '-asof_date', '-updated_at'):
        by_security.setdefault(row.security_id, row)
    result = {}
    for security in securities:
        row = by_security.get(security.id)
        if row is None:
            result[security.id] = {'status': 'NOT_AVAILABLE', 'action': None, 'undervalue_score': None, 'reason_code': 'RESULT_NOT_FOUND'}
            continue
        score = _number(row.signal_score)
        result[security.id] = {
            'status': 'OK' if score is not None else 'NOT_AVAILABLE',
            'action': row.action,
            'undervalue_score': score,
            'asof_date': _date(row.asof_date),
            'source_market_date': _date(getattr(row.snapshot, 'source_market_date', None)),
            'report_type': row.report_type,
            'model_version': row.model_version,
            'reason_code': None if score is not None else 'PREDICTIVE_SIGNAL_SCORE_MISSING',
        }
    return result


def get_research_list(*, user, pool='market', market='all', industry=None, q='', asof_date=None, page=1, page_size=20):
    pool = str(pool or 'market').strip().lower()
    market = str(market or 'all').strip().lower()
    if pool not in POOL_VALUES:
        raise MarketDataRequestError('INVALID_REQUEST', 'pool 不受支持')
    if market not in MARKET_VALUES:
        raise MarketDataRequestError('INVALID_REQUEST', 'market 不受支持')
    if page < 1 or page_size < 1 or page_size > 200:
        raise MarketDataRequestError('INVALID_REQUEST', 'page 或 page_size 超出允许范围')
    if asof_date and asof_date > date.today():
        raise MarketDataRequestError('INVALID_DATE', 'asof_date 不能晚于当前日期')
    mapping = _active_mapping()
    industry_codes = _industry_codes(mapping, industry) if industry else None
    queryset = Security.objects.filter(asset_type=Security.AssetType.STOCK).select_related('industry').order_by('ts_code')
    if industry_codes is not None:
        queryset = queryset.filter(ts_code__in=industry_codes)
    if pool != 'market':
        if user is None:
            raise MarketDataRequestError('FORBIDDEN', '用户股票池需要登录用户上下文')
        queryset = queryset.filter(pk__in=_user_security_ids(user, pool))
    securities = [security for security in queryset if _market_match(security.ts_code, market)]
    query = str(q or '').strip()
    if query:
        normalized = _normalized_search_text(query)
        securities = [
            security for security in securities
            if query.lower() in (security.name or '').lower()
            or query.lower() in security.ts_code.lower()
            or any(normalized in key for key in _security_search_keys(security.name))
        ]
    total = len(securities)
    page_items = securities[(page - 1) * page_size:page * page_size]
    security_ids = [security.id for security in page_items]
    if asof_date:
        market_rows = MarketBarDailyHistory.objects.filter(
            security_id__in=security_ids, trade_date__lte=asof_date,
        ).order_by('security_id', '-trade_date')
    else:
        market_rows = MarketBarLatest.objects.filter(
            security_id__in=security_ids, frequency='D',
        )
    market_by_security = {}
    for row in market_rows:
        market_by_security.setdefault(row.security_id, row)
    traditional = _traditional_rows(page_items, asof_date)
    predictive = _predictive_rows(page_items, asof_date)
    data = []
    for security in page_items:
        bar = market_by_security.get(security.id)
        data.append({
            'ts_code': security.ts_code,
            'name': security.name,
            'sw_industry': _industry_identity(mapping, security),
            'market': {
                'trade_date': _date(bar.trade_date) if bar else None,
                'pct_change': _number(bar.pct_change) if bar else None,
                'unit': 'percent',
            },
            'traditional_valuation': traditional[security.id],
            'predictive_valuation': predictive[security.id],
        })
    return Page(data, page, page_size, total)