from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from financials.models import FinancialDisclosureRecord
from traditional_valuation.models import TraditionalValuationEventState


class TraditionalValuationEventService:
    FINANCIAL_DISCLOSED = 'FINANCIAL_DISCLOSED'
    MARKET_STYLE_CHANGED = 'MARKET_STYLE_CHANGED'
    SECURITY_STYLE_CHANGED = 'SECURITY_STYLE_CHANGED'

    @staticmethod
    def _key(event_type, payload):
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(f'{event_type}:'.encode() + encoded).hexdigest()

    @classmethod
    def create_event(cls, event_type, payload, security=None, asof_date=None, source_version=''):
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
        if not created and event.status == TraditionalValuationEventState.Status.FAILED:
            event.status = TraditionalValuationEventState.Status.PENDING
            event.next_retry_at = None
            event.save(update_fields=['status', 'next_retry_at', 'updated_at'])
        return event, created

    @classmethod
    def detect_financial_disclosures(cls, asof_date=None, limit=0):
        asof_date = asof_date or date.today()
        rows = FinancialDisclosureRecord.objects.filter(ann_date__lte=asof_date).select_related('security').order_by('-ann_date', '-id')
        if limit > 0:
            rows = rows[:limit]
        created = 0
        for row in rows.iterator(chunk_size=200):
            payload = {
                'disclosure_id': row.pk,
                'financial_end_date': row.end_date.isoformat() if row.end_date else None,
                'ann_date': row.ann_date.isoformat() if row.ann_date else None,
                'report_type': _report_type(row.end_date),
            }
            _, was_created = cls.create_event(cls.FINANCIAL_DISCLOSED, payload, row.security, asof_date, str(row.pk))
            created += int(was_created)
        return created

    @classmethod
    def claim_pending(cls, limit=100, retry_failed=False):
        statuses = [TraditionalValuationEventState.Status.PENDING]
        if retry_failed:
            statuses.append(TraditionalValuationEventState.Status.FAILED)
        now = timezone.now()
        with transaction.atomic():
            events = list(
                TraditionalValuationEventState.objects.select_for_update()
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