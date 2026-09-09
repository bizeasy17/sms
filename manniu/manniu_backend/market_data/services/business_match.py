from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction

from market_data.models import BusinessIndustryMatchSnapshot, CompanyProfile, SWIndustryMappingVersion, Security
from market_data.services.citic import get_citic_memberships


DEFAULT_FIELD_WEIGHTS = {'main_business': 3.0, 'business_scope': 2.0, 'introduction': 1.0}
DEFAULT_LEVEL_WEIGHTS = {'L1': 0.9, 'L2': 1.15, 'L3': 1.3}
DEFAULT_KEYWORDS = {
    '芯片': [('L2', '半导体', 3.2)], '集成电路': [('L2', '半导体', 3.2)],
    '晶圆': [('L2', '半导体', 3.0)], '光伏': [('L2', '光伏设备', 2.6)],
    '锂电': [('L2', '电池', 2.7)], '储能': [('L2', '电池', 2.5)],
    '医疗器械': [('L2', '医疗器械', 3.0)], '软件': [('L2', '软件开发', 1.8)],
    '云计算': [('L2', 'IT服务', 2.3)], '算力': [('L2', 'IT服务', 2.4)],
    '服务器': [('L2', '计算机设备', 2.1)], '白酒': [('L2', '白酒', 3.0)],
    '机器人': [('L2', '自动化设备', 2.3)], '军工': [('L1', '国防军工', 2.0)],
}


def _norm(value: Any) -> str:
    return re.sub(r'\s+', '', str(value or '').lower())


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str).encode()).hexdigest()


def _active_mapping():
    return SWIndustryMappingVersion.objects.filter(is_active=True, market='CN').order_by('-published_at').first()


def _load_rules():
    paths = (
        Path(settings.BASE_DIR) / 'static' / 'industry_config' / 'business_keyword_rules_CN.json',
        Path(settings.BASE_DIR) / 'traditional_valuation' / 'static' / 'valuation_config' / 'business_keyword_rules_CN.json',
    )
    for path in paths:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, json.JSONDecodeError):
                continue
    return {'version': 'builtin-business-rules-1', 'field_weights': DEFAULT_FIELD_WEIGHTS}


def _entries(mapping, level):
    return (mapping.artifact.get('levels') or {}).get(level, {})


def _industry_targets(mapping, level, name):
    for code, entry in _entries(mapping, level).items():
        if entry.get('industry_name') == name:
            return code, entry
    return None, None


def _score_profile(profile, mapping, citic_rows, level, rules):
    field_weights = dict(DEFAULT_FIELD_WEIGHTS)
    field_weights.update(rules.get('field_weights') or {})
    scores = {}
    evidence = {}
    levels = ['L1', 'L2', 'L3'] if level == 'ALL' else [level]
    for field, weight in field_weights.items():
        text = _norm(profile.get(field))
        if not text:
            continue
        for level_name in levels:
            for code, entry in _entries(mapping, level_name).items():
                name = _norm(entry.get('industry_name'))
                if len(name) < 2 or name not in text:
                    continue
                key = (level_name, code)
                hits = text.count(name)
                scores[key] = scores.get(key, 0.0) + float(weight) * DEFAULT_LEVEL_WEIGHTS.get(level_name, 1.0) * hits * (1 + len(name) / 8)
                evidence.setdefault(key, {})[name] = evidence.setdefault(key, {}).get(name, 0) + hits
        for keyword, targets in DEFAULT_KEYWORDS.items():
            hits = text.count(_norm(keyword))
            if not hits:
                continue
            for target_level, target_name, target_weight in targets:
                if target_level not in levels:
                    continue
                code, _ = _industry_targets(mapping, target_level, target_name)
                if not code:
                    continue
                key = (target_level, code)
                scores[key] = scores.get(key, 0.0) + float(weight) * target_weight * hits
                evidence.setdefault(key, {})[keyword] = evidence.setdefault(key, {}).get(keyword, 0) + hits
    citic_evidence = []
    for row in citic_rows:
        citic_name = _norm(row['name'])
        for target_level in levels:
            for code, entry in _entries(mapping, target_level).items():
                target_name = _norm(entry.get('industry_name'))
                similarity = 1.0 if citic_name == target_name else SequenceMatcher(None, citic_name, target_name).ratio()
                if similarity < 0.55:
                    continue
                key = (target_level, code)
                boost = DEFAULT_LEVEL_WEIGHTS.get(row['level'], 1.0) * similarity
                scores[key] = scores.get(key, 0.0) + boost
                evidence.setdefault(key, {})[f'citic:{row["name"]}'] = 1
                citic_evidence.append({'citic_level': row['level'], 'citic_name': row['name'], 'target_level': target_level, 'target_code': code, 'target_name': entry.get('industry_name'), 'similarity': round(similarity, 4), 'boost': round(boost, 4)})
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    return ranked, evidence, citic_evidence


@transaction.atomic
def build_business_industry_match(*, security: Security | int | str, asof_date, level='L2', top_n=3, mapping_version=None, rules_version=None):
    if not isinstance(security, Security):
        security = Security.objects.get(pk=security) if isinstance(security, int) else Security.objects.get(ts_code=str(security).upper())
    profile = CompanyProfile.objects.filter(security=security).first()
    if not profile or not any((profile.main_business, profile.business_scope, getattr(profile, 'introduction', ''))):
        return {'status': 'NO_PROFILE', 'matches': [], 'requested_top_n': max(0, top_n)}
    mapping = SWIndustryMappingVersion.objects.filter(mapping_version=mapping_version, is_active=True).first() if mapping_version else _active_mapping()
    if mapping is None:
        return {'status': 'MAPPING_UNAVAILABLE', 'matches': [], 'requested_top_n': max(0, top_n)}
    rules = _load_rules()
    if rules_version and str(rules.get('version') or '') != rules_version:
        return {'status': 'RULES_VERSION_UNAVAILABLE', 'matches': [], 'requested_top_n': max(0, top_n)}
    profile_payload = {'main_business': profile.main_business, 'business_scope': profile.business_scope, 'introduction': getattr(profile, 'introduction', '')}
    profile_hash = _hash_payload(profile_payload)
    citic_rows = get_citic_memberships(security=security, asof_date=asof_date, level=None)
    ranked, evidence, citic_evidence = _score_profile(profile_payload, mapping, citic_rows, level.upper(), rules)
    requested = max(0, int(top_n or 0))
    matches = []
    for rank, ((level_name, code), score) in enumerate(ranked[:requested], start=1):
        entry = _entries(mapping, level_name).get(code, {})
        matches.append({'rank': rank, 'score': round(score, 4), 'industry_level': level_name, 'industry_code': code, 'industry_name': entry.get('industry_name'), 'matched_keywords': sorted(evidence.get((level_name, code), {})), 'evidence': {'citic': [item for item in citic_evidence if item['target_level'] == level_name and item['target_code'] == code]}})
    payload = {'status': 'VALID', 'matches': matches, 'requested_top_n': requested, 'returned_count': len(matches), 'profile_hash': profile_hash, 'profile_source': 'market_data', 'mapping_version': mapping.mapping_version, 'rules_version': str(rules.get('version') or 'builtin-business-rules-1')}
    BusinessIndustryMatchSnapshot.objects.update_or_create(security=security, asof_date=asof_date, level=level.upper(), requested_top_n=requested, profile_hash=profile_hash, mapping_version=mapping.mapping_version, rules_version=payload['rules_version'], defaults={'returned_count': len(matches), 'profile_source': 'market_data', 'profile_updated_at': profile.source_updated_at, 'status': 'VALID', 'matches': matches})
    return payload
