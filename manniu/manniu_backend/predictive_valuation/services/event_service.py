from __future__ import annotations

import hashlib
from datetime import date

from django.db import transaction

from financials.services.event_detector import DisclosureEventDetector
from market_data.services.regime import list_regime_events
from predictive_valuation.models import PredictiveValuationEventState


class PredictiveValuationEventService:
    """Create idempotent predictive events from shared, already-public financial data."""

    DISCLOSURE_EVENT = 'FINANCIAL_DISCLOSED'
    MARKET_REGIME_EVENT = 'MARKET_STYLE_CHANGED'
    SECURITY_REGIME_EVENT = 'SECURITY_STYLE_CHANGED'

    @classmethod
    def import_upstream_events(cls, as_of_date: date | None = None, limit: int = 500) -> dict[str, int]:
        """Copy committed market-data and financial events into local state."""
        source_events = list_regime_events(asof_date=as_of_date, limit=limit)
        source_events.extend(DisclosureEventDetector.list_disclosure_events(asof_date=as_of_date, limit=limit))
        created = existing = 0
        with transaction.atomic():
            for source_event in source_events[:limit]:
                source_system = source_event['source_system']
                source_event_key = source_event['source_event_key']
                local_key = hashlib.sha256(f'{source_system}:{source_event_key}'.encode('utf-8')).hexdigest()
                event, was_created = PredictiveValuationEventState.objects.get_or_create(
                    event_key=local_key,
                    defaults={
                        'security': source_event.get('security'),
                        'event_type': source_event['event_type'],
                        'source_system': source_system,
                        'source_event_key': source_event_key,
                        'source_version': str(source_event.get('source_version') or ''),
                        'scope_key': str(source_event.get('scope_key') or ''),
                        'asof_date': source_event.get('asof_date') or source_event.get('source_trade_date'),
                        'payload': source_event.get('payload') or {},
                    },
                )
                if was_created:
                    created += 1
                else:
                    existing += 1
                    if event.status == PredictiveValuationEventState.Status.FAILED:
                        event.status = PredictiveValuationEventState.Status.PENDING
                        event.save(update_fields=['status', 'updated_at'])
        return {'scanned': len(source_events[:limit]), 'created': created, 'existing': existing}
