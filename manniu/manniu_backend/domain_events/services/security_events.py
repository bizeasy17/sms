from __future__ import annotations

from datetime import date
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError

from financials.services.event_detector import DisclosureEventDetector
from market_data.services.regime import list_regime_events

from ..types import SecurityEvent, SecurityEventBatch

VALID_EVENT_TYPES: frozenset[str] = frozenset({
    'FINANCIAL_DISCLOSED',
    'SECURITY_STYLE_CHANGED',
})
MAX_PAGE_SIZE = 200
MAX_SOURCE_EVENTS = 2000


class SecurityEventsRequestError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class SecurityEventsDependencyError(RuntimeError):
    def __init__(self, source_system: str, error: Exception):
        super().__init__(f'{source_system} event service unavailable')
        self.source_system = source_system
        self.error = error


def _validate_request(*, event_types, page, page_size):
    selected = tuple(event_types or VALID_EVENT_TYPES)
    unsupported = sorted(set(selected) - VALID_EVENT_TYPES)
    if unsupported:
        raise SecurityEventsRequestError(
            'INVALID_EVENT_TYPE',
            'event_type 仅支持 FINANCIAL_DISCLOSED 或 SECURITY_STYLE_CHANGED',
            details={'unsupported': unsupported},
        )
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise SecurityEventsRequestError('INVALID_REQUEST', 'page 或 page_size 超出允许范围')
    return selected


def _security_fields(raw: dict[str, Any]):
    security = raw.get('security')
    return (
        getattr(security, 'ts_code', None) or '',
        getattr(security, 'id', raw.get('security_id')),
        getattr(security, 'name', None),
    )


def _financial_event(raw: dict[str, Any]) -> SecurityEvent | None:
    ts_code, security_id, security_name = _security_fields(raw)
    payload = dict(raw.get('payload') or {})
    event_value = raw.get('asof_date') or payload.get('effective_date')
    if not ts_code or not event_value:
        return None
    event_date = event_value if isinstance(event_value, date) else date.fromisoformat(str(event_value))
    return SecurityEvent(
        event_type='FINANCIAL_DISCLOSED',
        source_system='financials',
        source_event_key=str(raw.get('source_event_key') or ''),
        source_version=raw.get('source_version') or None,
        ts_code=ts_code,
        security_id=security_id,
        security_name=security_name,
        scope_key=str(raw.get('scope_key') or f'SECURITY:{ts_code}'),
        event_date=event_date,
        source_trade_date=None,
        payload=payload,
    )


def _regime_event(raw: dict[str, Any]) -> SecurityEvent | None:
    ts_code, security_id, security_name = _security_fields(raw)
    source_date = raw.get('source_trade_date')
    if not ts_code or not source_date:
        return None
    event_date = source_date if isinstance(source_date, date) else date.fromisoformat(str(source_date))
    return SecurityEvent(
        event_type='SECURITY_STYLE_CHANGED',
        source_system='market_data',
        source_event_key=str(raw.get('source_event_key') or ''),
        source_version=raw.get('source_version') or None,
        ts_code=ts_code,
        security_id=security_id,
        security_name=security_name,
        scope_key=str(raw.get('scope_key') or f'SECURITY:{ts_code}'),
        event_date=event_date,
        source_trade_date=event_date,
        payload=dict(raw.get('payload') or {}),
    )


def _in_range(event: SecurityEvent, *, ts_codes, start_date, end_date, asof_date):
    return (
        (not ts_codes or event.ts_code in ts_codes)
        and (start_date is None or event.event_date >= start_date)
        and (end_date is None or event.event_date <= end_date)
        and (asof_date is None or event.event_date <= asof_date)
    )


def list_security_events(
    *,
    ts_codes: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    asof_date: date | None = None,
    event_types: list[str] | None = None,
    page: int = 1,
    page_size: int = 50,
) -> SecurityEventBatch:
    selected = _validate_request(event_types=event_types, page=page, page_size=page_size)
    if start_date and end_date and start_date > end_date:
        raise SecurityEventsRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
    if start_date and asof_date and start_date > asof_date:
        raise SecurityEventsRequestError('INVALID_DATE', 'start_date 不能晚于 asof_date')
    normalized_codes = {str(code).strip().upper() for code in (ts_codes or []) if str(code).strip()}
    raw_events: list[SecurityEvent] = []
    warnings: list[str] = []
    source_failures = 0

    if 'FINANCIAL_DISCLOSED' in selected:
        try:
            source_rows = DisclosureEventDetector.list_disclosure_events(
                asof_date=asof_date,
                ts_codes=list(normalized_codes) or None,
                limit=MAX_SOURCE_EVENTS,
            )
            raw_events.extend(event for row in source_rows if (event := _financial_event(row)))
        except (AttributeError, DatabaseError, KeyError, ObjectDoesNotExist, RuntimeError, TypeError, ValueError) as error:
            source_failures += 1
            warnings.append('FINANCIALS_UNAVAILABLE')
            if len(selected) == 1:
                raise SecurityEventsDependencyError('financials', error) from error

    if 'SECURITY_STYLE_CHANGED' in selected:
        try:
            source_rows = list_regime_events(asof_date=asof_date, scope='security', limit=MAX_SOURCE_EVENTS)
            raw_events.extend(event for row in source_rows if (event := _regime_event(row)))
        except (AttributeError, DatabaseError, KeyError, ObjectDoesNotExist, RuntimeError, TypeError, ValueError) as error:
            source_failures += 1
            warnings.append('MARKET_DATA_UNAVAILABLE')
            if len(selected) == 1:
                raise SecurityEventsDependencyError('market_data', error) from error

    unique_events = {
        (event.source_system, event.source_event_key): event
        for event in raw_events
        if _in_range(event, ts_codes=normalized_codes, start_date=start_date, end_date=end_date, asof_date=asof_date)
        and event.source_event_key
    }
    ordered = sorted(
        unique_events.values(),
        key=lambda event: (-event.event_date.toordinal(), event.ts_code, event.event_type, event.source_event_key),
    )
    total = len(ordered)
    first = (page - 1) * page_size
    items = tuple(ordered[first:first + page_size])
    if source_failures == len(selected):
        raise SecurityEventsDependencyError('domain_events', RuntimeError('all event sources unavailable'))
    return SecurityEventBatch(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_next=first + page_size < total,
        asof_date=asof_date,
        data_status='PARTIAL_SUCCESS' if source_failures else ('NO_DATA' if not items else 'COMPLETE'),
        warnings=tuple(warnings),
    )
