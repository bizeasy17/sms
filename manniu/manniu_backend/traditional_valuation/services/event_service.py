from __future__ import annotations

import hashlib
import json
from django.db import transaction
from django.utils import timezone

from financials.services.event_detector import DisclosureEventDetector
from market_data.services.regime import list_regime_events
from traditional_valuation.models import TraditionalValuationEventState


class TraditionalValuationEventService:
    FINANCIAL_DISCLOSED = 'FINANCIAL_DISCLOSED'
    MARKET_STYLE_CHANGED = 'MARKET_STYLE_CHANGED'
    SECURITY_STYLE_CHANGED = 'SECURITY_STYLE_CHANGED'

    @classmethod
    def import_upstream_events(cls, asof_date=None, limit=500):
        source_events = list_regime_events(asof_date=asof_date, limit=limit)
        source_events.extend(DisclosureEventDetector.list_disclosure_events(asof_date=asof_date, limit=limit))
        created = existing = 0
        for source_event in source_events[:limit]:
            source_system = source_event['source_system']
            source_event_key = source_event['source_event_key']
            _, was_created = cls.create_event(
                source_event['event_type'],
                source_event.get('payload') or {},
                security=source_event.get('security'),
                asof_date=source_event.get('asof_date') or source_event.get('source_trade_date'),
                source_version=str(source_event.get('source_version') or ''),
                source_system=source_system,
                source_event_key=source_event_key,
                scope_key=str(source_event.get('scope_key') or ''),
            )
            created += int(was_created)
            existing += int(not was_created)
        return {'scanned': len(source_events[:limit]), 'created': created, 'existing': existing}

    @classmethod
    def import_historical_disclosure_events(
        cls, start_date, end_date, report_types=None, ts_codes=None, limit=0
    ):
        source_events = DisclosureEventDetector.list_disclosure_events(
            start_date=start_date,
            end_date=end_date,
            actual_date_only=True,
            report_types=report_types,
            ts_codes=ts_codes,
            limit=limit,
        )
        created = existing = 0
        source_event_keys = []
        for source_event in source_events:
            _, was_created = cls.create_event(
                source_event['event_type'],
                source_event.get('payload') or {},
                security=source_event.get('security'),
                asof_date=source_event.get('asof_date'),
                source_version=str(source_event.get('source_version') or ''),
                source_system=source_event['source_system'],
                source_event_key=source_event['source_event_key'],
                scope_key=source_event.get('scope_key'),
            )
            source_event_keys.append(source_event['source_event_key'])
            created += int(was_created)
            existing += int(not was_created)
        return {
            'scanned': len(source_events),
            'created': created,
            'existing': existing,
            'source_event_keys': source_event_keys,
        }

    @staticmethod
    def _key(event_type, payload):
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(f'{event_type}:'.encode() + encoded).hexdigest()

    @classmethod
    def create_event(cls, event_type, payload, security=None, asof_date=None, source_version='', source_system=None, source_event_key=None, scope_key=None):
        event_key = cls._key(source_system or event_type, source_event_key or payload)
        event, created = TraditionalValuationEventState.objects.get_or_create(
            source_system=source_system,
            source_event_key=source_event_key,
            defaults={
                'event_type': event_type,
                'event_key': event_key,
                'scope_key': scope_key or (security.ts_code if security else 'MARKET'),
                'security': security,
                'source_version': source_version,
                'asof_date': asof_date,
                'payload': payload,
            },
        )
        if created:
            return event, True
        if event.status == TraditionalValuationEventState.Status.FAILED:
            event.status = TraditionalValuationEventState.Status.PENDING
            event.next_retry_at = None
            event.save(update_fields=['status', 'next_retry_at', 'updated_at'])
        return event, False

    @classmethod
    def _legacy_create_event(cls, event_type, payload, security=None, asof_date=None, source_version=''):
        event_key = cls._key(event_type, payload)
        event, created = TraditionalValuationEventState.objects.get_or_create(
            event_type=event_type,
            event_key=event_key,
            defaults={
                'security': security,
                'scope_key': security.ts_code if security else 'MARKET',
                'source_version': source_version,
                'asof_date': asof_date,
                'payload': payload,
            },
        )
        return event, created

    @classmethod
    def claim_pending(cls, limit=100, retry_failed=False, source_event_keys=None):
        statuses = [TraditionalValuationEventState.Status.PENDING]
        if retry_failed:
            statuses.append(TraditionalValuationEventState.Status.FAILED)
        now = timezone.now()
        with transaction.atomic():
            queryset = TraditionalValuationEventState.objects.select_for_update()
            if source_event_keys is not None:
                queryset = queryset.filter(source_event_key__in=source_event_keys)
            events = list(
                queryset
                .filter(status__in=statuses)
                .filter(next_retry_at__isnull=True)
                .order_by('created_at')[:limit]
            )
            for event in events:
                event.status = TraditionalValuationEventState.Status.CLAIMED
                event.claimed_at = now
                event.save(update_fields=['status', 'claimed_at', 'updated_at'])
            return events


def _report_type(end_date):
    if not end_date:
        return 'FY'
    return {'0331': 'Q1', '0630': 'H1', '0930': 'Q3', '1231': 'FY'}.get(end_date.strftime('%m%d'), 'FY')