from __future__ import annotations

from dataclasses import dataclass

from market_data.models import SWIndustryDailyHistory, Security
from market_data.services.industry import (
    IndustryMappingError,
    _code,
    _identity_from_code,
    _mapping_row,
)


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_HISTORY_ROWS = 2000
VALID_LEVELS = {'L1', 'L2', 'L3'}


class SWIndustryRequestError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class SWIndustryPage:
    items: list[dict]
    page: int
    page_size: int
    total: int

    @property
    def has_next(self):
        return self.page * self.page_size < self.total


def _parse_pagination(page, page_size):
    try:
        page = int(page or 1)
        page_size = int(page_size or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError) as exc:
        raise SWIndustryRequestError('INVALID_REQUEST', 'page 和 page_size 必须为整数') from exc
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise SWIndustryRequestError('INVALID_REQUEST', f'page 必须大于等于 1，page_size 范围为 1-{MAX_PAGE_SIZE}')
    return page, page_size


def _entries(mapping):
    for level, entries in (mapping.get('levels') or {}).items():
        normalized_level = str(level).upper()
        if normalized_level not in VALID_LEVELS or not isinstance(entries, dict):
            continue
        for key, entry in entries.items():
            if isinstance(entry, dict):
                yield normalized_level, str(key), entry


def _industry_payload(*, level, key, entry, mapping_version, source_hash, constituent_count=None):
    index_code = str(entry.get('index_code') or key).strip().upper()
    industry_code = str(entry.get('industry_code') or key).strip().upper()
    payload = {
        'industry_code': industry_code,
        'index_code': index_code,
        'name': str(entry.get('name') or entry.get('industry_name') or '').strip(),
        'level': str(entry.get('sw_level') or level).upper(),
        'parent_code': entry.get('parent_code') or entry.get('parent_index_code'),
        'mapping_version': mapping_version,
        'source_hash': source_hash,
    }
    if constituent_count is not None:
        payload['constituent_count'] = constituent_count
    return payload


def list_sw_industries(*, level=None, query='', page=1, page_size=DEFAULT_PAGE_SIZE):
    page, page_size = _parse_pagination(page, page_size)
    normalized_level = str(level or '').strip().upper()
    if normalized_level and normalized_level not in VALID_LEVELS:
        raise SWIndustryRequestError('INVALID_REQUEST', 'level 仅支持 L1、L2、L3')
    try:
        mapping_row = _mapping_row(None)
    except IndustryMappingError as exc:
        raise SWIndustryRequestError('CONFIGURATION_UNAVAILABLE', str(exc)) from exc
    text = str(query or '').strip().lower()
    items = []
    for entry_level, key, entry in _entries(mapping_row.artifact):
        payload = _industry_payload(
            level=entry_level,
            key=key,
            entry=entry,
            mapping_version=mapping_row.mapping_version,
            source_hash=mapping_row.source_hash,
        )
        if normalized_level and payload['level'] != normalized_level:
            continue
        if text and text not in ' '.join((payload['industry_code'], payload['index_code'], payload['name'])).lower():
            continue
        items.append(payload)
    items.sort(key=lambda item: (item['level'], item['industry_code'], item['name']))
    total = len(items)
    start = (page - 1) * page_size
    return SWIndustryPage(items[start:start + page_size], page, page_size, total)


def get_sw_industry(*, industry_code):
    try:
        mapping_row = _mapping_row(None)
    except IndustryMappingError as exc:
        raise SWIndustryRequestError('CONFIGURATION_UNAVAILABLE', str(exc)) from exc
    identity = _identity_from_code(mapping_row.artifact, industry_code)
    if not identity:
        raise SWIndustryRequestError('RESULT_NOT_FOUND', 'SW 行业不存在')
    index_code = str(identity.get('index_code') or identity.get('industry_code') or '').upper()
    target_codes = {
        _code(index_code),
        _code(identity.get('industry_code')),
    }
    membership = mapping_row.artifact.get('ts_code_to_levels') or mapping_row.artifact.get('membership') or {}
    constituent_count = sum(
        1 for value in membership.values()
        if isinstance(value, dict) and any(
            _code(value.get(f'l{level}_code')) in target_codes for level in (1, 2, 3)
        )
    )
    return _industry_payload(
        level=identity.get('sw_level', ''),
        key=industry_code,
        entry=identity,
        mapping_version=mapping_row.mapping_version,
        source_hash=mapping_row.source_hash,
        constituent_count=constituent_count,
    )


def get_sw_industry_bars(*, industry_code, start_date, end_date, page=1, page_size=DEFAULT_PAGE_SIZE):
    industry = get_sw_industry(industry_code=industry_code)
    page, page_size = _parse_pagination(page, page_size)
    root = _code(industry['index_code'] or industry['industry_code'])
    security = Security.objects.filter(
        asset_type=Security.AssetType.INDEX,
        ts_code__startswith=f'{root}.',
        market='SW',
    ).first()
    if security is None:
        raise SWIndustryRequestError('RESULT_NOT_FOUND', 'SW 行业日线不存在')
    queryset = SWIndustryDailyHistory.objects.filter(
        security=security,
        trade_date__range=(start_date, end_date),
    ).order_by('-trade_date')
    total = queryset.count()
    if total > MAX_HISTORY_ROWS:
        raise SWIndustryRequestError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = list(queryset[(page - 1) * page_size:page * page_size])
    items = [{
        'industry_code': industry['industry_code'],
        'index_code': security.ts_code,
        'name': row.name or industry['name'],
        'trade_date': row.trade_date.isoformat(),
        'open': float(row.open) if row.open is not None else None,
        'high': float(row.high) if row.high is not None else None,
        'low': float(row.low) if row.low is not None else None,
        'close': float(row.close) if row.close is not None else None,
        'pre_close': float(row.pre_close) if row.pre_close is not None else None,
        'change': float(row.change) if row.change is not None else None,
        'pct_change': float(row.pct_change) if row.pct_change is not None else None,
        'vol': float(row.vol) if row.vol is not None else None,
        'amount': float(row.amount) if row.amount is not None else None,
    } for row in rows]
    return SWIndustryPage(items, page, page_size, total)