from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from django.db import transaction

from market_data.models import IndustryRegimeRuleVersion, RegimeEvent, SWIndustryMappingVersion, Security


VALID_INDUSTRY_REGIMES = {'high_growth', 'balanced', 'stable_value', 'cyclical_resource'}


class IndustryMappingError(ValueError):
    pass


@dataclass(frozen=True)
class IndustryRegimeResult:
    selected_regime: str
    regime_confidence: float
    regime_source: str
    industry_code: str
    index_code: str
    sw_level: str
    sw_name: str
    mapping_version: str
    rules_version: str
    source_hash: str
    regime_reasons: tuple[str, ...]
    fallback_reason: str
    status: str


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), default=str)


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()


def _code(value: Any) -> str:
    text = str(value or '').strip().upper()
    return ''.join(character for character in text.split('.')[0] if character.isdigit())


def _read_json(path: str) -> dict[str, Any]:
    try:
        content = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndustryMappingError(f'Unable to read JSON artifact: {path}') from exc
    if not isinstance(content, dict):
        raise IndustryMappingError('Industry artifact root must be a JSON object')
    return content


def _mapping_membership(mapping: dict[str, Any]) -> dict[str, Any]:
    return mapping.get('ts_code_to_levels') or mapping.get('membership') or {}


def _validate_mapping(mapping: dict[str, Any]) -> None:
    if not mapping.get('version'):
        raise IndustryMappingError('SW mapping requires version')
    if not isinstance(mapping.get('levels', {}), dict):
        raise IndustryMappingError('SW mapping requires levels object')
    if not isinstance(_mapping_membership(mapping), dict):
        raise IndustryMappingError('SW mapping membership must be an object')


def _security_membership_coverage(mapping: dict[str, Any]) -> dict[str, Any]:
    member_codes = {str(code).upper() for code in _mapping_membership(mapping)}
    if not member_codes:
        return {'membership_count': 0, 'known_security_count': 0, 'unknown_security_count': 0, 'unknown_security_preview': []}
    known_codes = set(Security.objects.filter(ts_code__in=member_codes).values_list('ts_code', flat=True))
    missing_codes = sorted(member_codes.difference(known_codes))
    return {
        'membership_count': len(member_codes),
        'known_security_count': len(known_codes),
        'unknown_security_count': len(missing_codes),
        'unknown_security_preview': missing_codes[:10],
    }


def _validate_rules(rules: dict[str, Any]) -> None:
    if not rules.get('version'):
        raise IndustryMappingError('Industry regime rules require version')
    fallback = rules.get('fallback_regime', 'balanced')
    if fallback not in VALID_INDUSTRY_REGIMES:
        raise IndustryMappingError('Industry regime fallback_regime is invalid')
    exact = rules.get('exact') or rules.get('code_regimes') or {}
    if not isinstance(exact, dict) or any(regime not in VALID_INDUSTRY_REGIMES for regime in exact.values()):
        raise IndustryMappingError('Industry regime exact rules are invalid')


@transaction.atomic
def publish_industry_mapping(*, mapping: dict[str, Any], rules: dict[str, Any], source_trade_date: date | None = None) -> tuple[SWIndustryMappingVersion, IndustryRegimeRuleVersion]:
    _validate_mapping(mapping)
    _validate_rules(rules)
    membership_coverage = _security_membership_coverage(mapping)
    mapping_version = str(mapping['version']).strip()
    rules_version = str(rules['version']).strip()
    mapping_hash = _hash(mapping)
    rules_hash = _hash(rules)
    market = str(mapping.get('market') or 'CN').upper()
    taxonomy = str(mapping.get('src') or mapping.get('taxonomy') or 'SW2021').upper()
    mapping_row, _ = SWIndustryMappingVersion.objects.get_or_create(
        market=market,
        taxonomy=taxonomy,
        mapping_version=mapping_version,
        defaults={
            'source_hash': mapping_hash,
            'source_trade_date': source_trade_date,
            'source_metadata': {'updated_at': mapping.get('updated_at'), 'src': mapping.get('src')},
            'validation_summary': membership_coverage,
            'artifact': mapping,
        },
    )
    if mapping_row.source_hash != mapping_hash:
        raise IndustryMappingError('Mapping version already exists with different content')
    if rules.get('mapping_version') and str(rules['mapping_version']) != mapping_version:
        raise IndustryMappingError('Rules mapping_version does not match mapping artifact')
    rule_row, _ = IndustryRegimeRuleVersion.objects.get_or_create(
        mapping_version=mapping_row,
        rules_version=rules_version,
        defaults={
            'rules_hash': rules_hash,
            'fallback_regime': rules.get('fallback_regime', 'balanced'),
            'rules': rules,
            'validation_summary': {'exact_rule_count': len(rules.get('exact', rules.get('code_regimes', {})))},
        },
    )
    if rule_row.rules_hash != rules_hash:
        raise IndustryMappingError('Rules version already exists with different content')
    SWIndustryMappingVersion.objects.filter(market=market, taxonomy=taxonomy, is_active=True).exclude(pk=mapping_row.pk).update(is_active=False)
    IndustryRegimeRuleVersion.objects.filter(mapping_version__market=market, mapping_version__taxonomy=taxonomy, is_active=True).exclude(pk=rule_row.pk).update(is_active=False)
    if not mapping_row.is_active:
        mapping_row.is_active = True
        mapping_row.save(update_fields=['is_active'])
    if not rule_row.is_active:
        rule_row.is_active = True
        rule_row.save(update_fields=['is_active'])
    source_date = source_trade_date or date.today()
    event_key = hashlib.sha256(f'{market}|{taxonomy}|{mapping_version}|{rules_version}'.encode('utf-8')).hexdigest()
    RegimeEvent.objects.get_or_create(
        event_type='INDUSTRY_MAPPING_CHANGED',
        event_key=event_key,
        defaults={'source_trade_date': source_date, 'payload': {'mapping_version': mapping_version, 'rules_version': rules_version, 'source_hash': mapping_hash}},
    )
    return mapping_row, rule_row


def publish_industry_mapping_files(*, mapping_file: str, rules_file: str, source_trade_date: date | None = None) -> tuple[SWIndustryMappingVersion, IndustryRegimeRuleVersion]:
    return publish_industry_mapping(mapping=_read_json(mapping_file), rules=_read_json(rules_file), source_trade_date=source_trade_date)


def _mapping_row(mapping_version: str | None) -> SWIndustryMappingVersion:
    query = SWIndustryMappingVersion.objects.filter(mapping_version=mapping_version) if mapping_version else SWIndustryMappingVersion.objects.filter(is_active=True)
    row = query.order_by('-published_at').first()
    if row is None:
        raise IndustryMappingError('CONFIGURATION_UNAVAILABLE: no SW mapping version is active')
    return row


def _rule_row(mapping: SWIndustryMappingVersion, rules_version: str | None) -> IndustryRegimeRuleVersion:
    query = mapping.regime_rule_versions.filter(rules_version=rules_version) if rules_version else mapping.regime_rule_versions.filter(is_active=True)
    row = query.order_by('-published_at').first()
    if row is None:
        raise IndustryMappingError('CONFIGURATION_UNAVAILABLE: no industry regime rules are active')
    return row


def _identity_from_security(mapping: dict[str, Any], security: Security) -> dict[str, Any]:
    membership = _mapping_membership(mapping).get(security.ts_code.upper(), {})
    for key, level in (('l3_code', 'L3'), ('l2_code', 'L2'), ('l1_code', 'L1')):
        identity = _identity_from_code(mapping, str(membership.get(key) or ''))
        if identity:
            return {**identity, **membership, 'sw_level': level}
    return membership


def _identity_from_code(mapping: dict[str, Any], requested_code: str) -> dict[str, Any]:
    code = _code(requested_code)
    for level, entries in mapping.get('levels', {}).items():
        for key, entry in (entries or {}).items():
            entry = entry or {}
            if code in {_code(key), _code(entry.get('index_code')), _code(entry.get('industry_code'))}:
                return {**entry, 'sw_level': entry.get('sw_level') or level}
    return {}


def _identity_parent(mapping: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    parent_code = identity.get('parent_index_code') or identity.get('parent_code')
    return _identity_from_code(mapping, str(parent_code or ''))


def _rule_value(rules: dict[str, Any], code: str) -> str | None:
    exact = rules.get('exact') or rules.get('code_regimes') or {}
    for raw_code, regime in exact.items():
        if _code(raw_code) == code and regime in VALID_INDUSTRY_REGIMES:
            return regime
    return None


def _keyword_rule_value(rules: dict[str, Any], industry_name: str) -> tuple[str, str] | None:
    name = industry_name.strip().lower()
    if not name:
        return None
    raw_rules = rules.get('keyword') or rules.get('keyword_regimes') or {}
    items = raw_rules.items() if isinstance(raw_rules, dict) else (
        (item.get('keyword'), item.get('regime')) for item in raw_rules if isinstance(item, dict)
    )
    for keyword, regime in items:
        if keyword and regime in VALID_INDUSTRY_REGIMES and str(keyword).lower() in name:
            return regime, str(keyword)
    return None


def resolve_sw_industry_mapping(*, security: Security | int | str | None = None, industry_code: str | None = None, index_code: str | None = None, mapping_version: str | None = None) -> dict[str, Any]:
    mapping_row = _mapping_row(mapping_version)
    resolved_security = None
    if security is not None:
        resolved_security = security if isinstance(security, Security) else Security.objects.get(ts_code=security) if isinstance(security, str) else Security.objects.get(pk=security)
    membership = _identity_from_security(mapping_row.artifact, resolved_security) if resolved_security else {}
    explicit = _identity_from_code(mapping_row.artifact, index_code or industry_code or '')
    membership_code = _code(membership.get('index_code') or membership.get('industry_code'))
    explicit_code = _code(explicit.get('index_code') or explicit.get('industry_code'))
    if resolved_security and explicit and membership_code != explicit_code:
        raise IndustryMappingError('Explicit SW identifier conflicts with security membership')
    return {**(explicit or membership), 'mapping_version': mapping_row.mapping_version, 'source_hash': mapping_row.source_hash}


def resolve_industry_regime(*, security: Security | int | str | None = None, industry_code: str | None = None, index_code: str | None = None, industry_name: str | None = None, mapping_version: str | None = None, rules_version: str | None = None) -> IndustryRegimeResult:
    mapping_row = _mapping_row(mapping_version)
    rule_row = _rule_row(mapping_row, rules_version)
    identity = resolve_sw_industry_mapping(
        security=security,
        industry_code=industry_code,
        index_code=index_code,
        mapping_version=mapping_row.mapping_version,
    )
    current_identity = identity
    visited_codes: set[str] = set()
    while current_identity:
        codes = [_code(current_identity.get('index_code')), _code(current_identity.get('industry_code'))]
        codes = [code for code in codes if code and code not in visited_codes]
        visited_codes.update(codes)
        for code in codes:
            regime = _rule_value(rule_row.rules, code)
            if regime:
                source = 'exact' if current_identity is identity else 'parent'
                return IndustryRegimeResult(regime, 1.0 if source == 'exact' else 0.8, source, str(identity.get('industry_code') or code), str(identity.get('index_code') or ''), str(identity.get('sw_level') or ''), str(identity.get('name') or identity.get('industry_name') or ''), mapping_row.mapping_version, rule_row.rules_version, mapping_row.source_hash, (f'{source}_code={code}',), '', 'VALID')
        parent = _identity_parent(mapping_row.artifact, current_identity)
        if not parent or _code(parent.get('index_code') or parent.get('industry_code')) in visited_codes:
            break
        current_identity = parent
    resolved_name = str(identity.get('name') or identity.get('industry_name') or industry_name or '')
    keyword_match = _keyword_rule_value(rule_row.rules, resolved_name)
    if keyword_match:
        regime, keyword = keyword_match
        return IndustryRegimeResult(regime, 0.6, 'keyword', str(identity.get('industry_code') or _code(industry_code)), str(identity.get('index_code') or _code(index_code)), str(identity.get('sw_level') or ''), resolved_name, mapping_row.mapping_version, rule_row.rules_version, mapping_row.source_hash, (f'keyword={keyword}',), '', 'VALID')
    fallback = rule_row.fallback_regime
    return IndustryRegimeResult(fallback, 0.0, 'fallback', str(identity.get('industry_code') or _code(industry_code)), str(identity.get('index_code') or _code(index_code)), str(identity.get('sw_level') or ''), resolved_name, mapping_row.mapping_version, rule_row.rules_version, mapping_row.source_hash, ('fallback_balanced',), 'no_matching_regime_rule', 'DEGRADED')


def build_sw_mapping_from_tushare(*, token: str, page_size: int = 2000, max_pages: int = 300) -> dict[str, Any]:
    if not token:
        raise IndustryMappingError('TUSHARE_TOKEN is required to generate SW mapping')
    if page_size < 1 or max_pages < 1:
        raise IndustryMappingError('page_size and max_pages must be positive')
    try:
        import pandas as pd
        import tushare as ts
    except ImportError as exc:
        raise IndustryMappingError('pandas and tushare are required to generate SW mapping') from exc
    ts.set_token(token)
    pro = ts.pro_api()
    levels: dict[str, dict[str, dict[str, Any]]] = {'L1': {}, 'L2': {}, 'L3': {}}
    industry_to_index: dict[str, dict[str, str]] = {'L1': {}, 'L2': {}, 'L3': {}}
    for level in levels:
        frame = pro.index_classify(src='SW2021', level=level)
        if frame is None or frame.empty:
            raise IndustryMappingError(f'No SW2021 {level} classifications returned')
        for row in frame.fillna('').to_dict(orient='records'):
            index_code = str(row.get('index_code') or '').upper()
            industry_code = str(row.get('industry_code') or '')
            if not index_code or not industry_code:
                continue
            levels[level][index_code] = {
                'index_code': index_code,
                'industry_code': industry_code,
                'industry_name': str(row.get('industry_name') or ''),
                'level': level,
                'parent_code': str(row.get('parent_code') or ''),
                'src': 'SW2021',
            }
            industry_to_index[level][industry_code] = index_code
    for level, parent_level in (('L2', 'L1'), ('L3', 'L2')):
        for entry in levels[level].values():
            entry['parent_index_code'] = industry_to_index[parent_level].get(entry['parent_code'], '')
    pages: list[Any] = []
    offset = 0
    seen_markers: set[tuple[Any, ...]] = set()
    for _ in range(max_pages):
        try:
            page = pro.index_member_all(limit=page_size, offset=offset)
        except TypeError:
            page = pro.index_member_all()
            pages = [page] if page is not None else []
            break
        if page is None or page.empty:
            break
        marker = (str(page.iloc[0].get('ts_code') or ''), str(page.iloc[0].get('in_date') or ''), str(page.iloc[0].get('l3_code') or ''))
        if marker in seen_markers:
            raise IndustryMappingError('Repeated index_member_all page detected')
        seen_markers.add(marker)
        pages.append(page)
        if len(page) < page_size:
            break
        offset += len(page)
    else:
        raise IndustryMappingError('index_member_all maximum page limit reached')
    if not pages:
        raise IndustryMappingError('No SW2021 membership records returned')
    members = pd.concat(pages, ignore_index=True).fillna('')
    membership: dict[str, dict[str, Any]] = {}
    level_members: dict[str, dict[str, set[str]]] = {'L1': {}, 'L2': {}, 'L3': {}}
    for row in members.to_dict(orient='records'):
        code = str(row.get('ts_code') or '').upper()
        if not code or str(row.get('out_date') or ''):
            continue
        item = {'name': str(row.get('name') or ''), 'l1_code': str(row.get('l1_code') or ''), 'l1_name': str(row.get('l1_name') or ''), 'l2_code': str(row.get('l2_code') or ''), 'l2_name': str(row.get('l2_name') or ''), 'l3_code': str(row.get('l3_code') or ''), 'l3_name': str(row.get('l3_name') or ''), 'in_date': str(row.get('in_date') or ''), 'out_date': None, 'source': 'SW2021'}
        membership[code] = item
        for level, field in (('L1', 'l1_code'), ('L2', 'l2_code'), ('L3', 'l3_code')):
            if item[field]:
                level_members[level].setdefault(item[field], set()).add(code)
    return {'version': f'SW2021-{datetime.now().strftime("%Y%m%d%H%M%S")}', 'market': 'CN', 'src': 'SW2021', 'updated_at': datetime.now().isoformat(timespec='seconds'), 'levels': levels, 'level_members': {level: {key: sorted(value) for key, value in values.items()} for level, values in level_members.items()}, 'ts_code_to_levels': membership}