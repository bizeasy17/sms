from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import pandas as pd
from django.db import transaction
from django.utils import timezone

from market_data.models import (
    CITICIndustryDimension,
    CITICIndustryMappingRun,
    CITICSecurityIndustryMembership,
    Security,
)


FIELDS = 'ts_code,l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,is_new,in_date,out_date'


def _hash_rows(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=True, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _as_date(value: Any) -> date | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    text = str(value).strip().replace('-', '')
    if len(text) != 8 or not text.isdigit():
        return None
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _clean(value: Any) -> str:
    return str(value or '').strip()


def _mapping_version(source_trade_date: date, source_hash: str) -> str:
    return f'citic-{source_trade_date:%Y%m%d}-{source_hash[:16]}'


def sync_citic_memberships(*, pro, source_trade_date: date, ts_codes: tuple[str, ...] = ()) -> int:
    frame = pro.ci_index_member(is_new='Y', fields=FIELDS)
    if frame is None or frame.empty:
        raise ValueError('ci_index_member returned no active rows; active CITIC mapping was preserved')
    rows = frame.to_dict(orient='records')
    allowed = {code.upper() for code in ts_codes}
    if allowed:
        rows = [row for row in rows if _clean(row.get('ts_code')).upper() in allowed]
    normalized = []
    for row in rows:
        ts_code = _clean(row.get('ts_code')).upper()
        if not ts_code:
            continue
        levels = []
        for level in ('L1', 'L2', 'L3'):
            code = _clean(row.get(f'{level.lower()}_code'))
            name = _clean(row.get(f'{level.lower()}_name'))
            if code and name:
                levels.append({'level': level, 'code': code, 'name': name})
        if ts_code and levels:
            normalized.append({
                'ts_code': ts_code,
                'levels': levels,
                'in_date': _as_date(row.get('in_date')),
                'out_date': _as_date(row.get('out_date')),
            })
    if not normalized:
        raise ValueError('ci_index_member contained no valid stock memberships')
    normalized.sort(key=lambda item: (item['ts_code'], json.dumps(item['levels'], sort_keys=True)))
    source_hash = _hash_rows(normalized)
    mapping_version = _mapping_version(source_trade_date, source_hash)
    securities = {
        code: security for code, security in Security.objects.filter(
            asset_type=Security.AssetType.STOCK,
            ts_code__in={item['ts_code'] for item in normalized},
        ).in_bulk(field_name='ts_code').items()
    }
    valid = [item for item in normalized if item['ts_code'] in securities]
    run = CITICIndustryMappingRun.objects.create(
        mapping_version=mapping_version,
        source_trade_date=source_trade_date,
        source_hash=source_hash,
        source_count=len(normalized),
    )
    try:
        with transaction.atomic():
            dimensions = {}
            for item in valid:
                for entry in item['levels']:
                    parent = ''
                    if entry['level'] == 'L2':
                        parent = next((x['code'] for x in item['levels'] if x['level'] == 'L1'), '')
                    elif entry['level'] == 'L3':
                        parent = next((x['code'] for x in item['levels'] if x['level'] == 'L2'), '')
                    key = (entry['level'], entry['code'])
                    dimensions[key] = {
                        'market': 'CN', 'level': entry['level'], 'code': entry['code'],
                        'name': entry['name'], 'parent_code': parent,
                        'mapping_version': mapping_version, 'source_trade_date': source_trade_date,
                        'source_hash': source_hash, 'is_active': True,
                    }
            dimension_rows = {
                key: CITICIndustryDimension.objects.get_or_create(
                    market=payload['market'], level=payload['level'], code=payload['code'],
                    mapping_version=payload['mapping_version'], defaults=payload,
                )[0]
                for key, payload in dimensions.items()
            }
            memberships = []
            for item in valid:
                for entry in item['levels']:
                    membership, _ = CITICSecurityIndustryMembership.objects.get_or_create(
                        security=securities[item['ts_code']],
                        industry=dimension_rows[(entry['level'], entry['code'])],
                        mapping_version=mapping_version,
                        in_date=item['in_date'],
                        defaults={
                            'level': entry['level'], 'out_date': item['out_date'],
                            'is_current': True, 'source_trade_date': source_trade_date,
                        },
                    )
                    memberships.append(membership)
            run.dimension_count = len(dimension_rows)
            run.membership_count = len(memberships)
            run.rejected_count = len(normalized) - len(valid)
            run.status = CITICIndustryMappingRun.Status.SUCCEEDED
            run.finished_at = timezone.now()
            run.save(update_fields=['dimension_count', 'membership_count', 'rejected_count', 'status', 'finished_at'])
        return len(memberships)
    except Exception as exc:
        run.status = CITICIndustryMappingRun.Status.FAILED
        run.error_message = str(exc)[:2000]
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error_message', 'finished_at'])
        raise


def get_citic_memberships(*, security: Security | int | str, asof_date: date | None = None, level: str | None = None, mapping_version: str | None = None):
    query = CITICSecurityIndustryMembership.objects.select_related('industry', 'security')
    if isinstance(security, Security):
        query = query.filter(security=security)
    elif isinstance(security, int):
        query = query.filter(security_id=security)
    else:
        query = query.filter(security__ts_code=str(security).upper())
    if level:
        query = query.filter(level=level.upper())
    if mapping_version:
        query = query.filter(mapping_version=mapping_version)
    else:
        query = query.filter(is_current=True)
    rows = []
    for row in query.order_by('level', 'industry__code'):
        if asof_date and row.in_date and row.in_date > asof_date:
            continue
        if asof_date and row.out_date and row.out_date < asof_date:
            continue
        rows.append({
            'level': row.level, 'code': row.industry.code, 'name': row.industry.name,
            'parent_code': row.industry.parent_code, 'mapping_version': row.mapping_version,
            'in_date': row.in_date, 'out_date': row.out_date,
        })
    return rows
