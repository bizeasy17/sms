from __future__ import annotations

import hashlib
from datetime import date

from django.db import transaction

from financials.models import FinancialDisclosureRecord
from predictive_valuation.models import PredictiveValuationEventState


class PredictiveValuationEventService:
    """Create idempotent predictive events from shared, already-public financial data."""

    DISCLOSURE_EVENT = 'FINANCIAL_DISCLOSED'

    @classmethod
    def detect_financial_disclosures(cls, as_of_date: date | None = None) -> dict[str, int]:
        query = FinancialDisclosureRecord.objects.select_related('security').order_by('id')
        scanned_count = 0
        created_count = 0
        existing_count = 0
        skipped_not_public_count = 0
        with transaction.atomic():
            for disclosure in query.iterator(chunk_size=500):
                scanned_count += 1
                effective_date = disclosure.actual_date or disclosure.ann_date
                if not disclosure.end_date or not effective_date:
                    skipped_not_public_count += 1
                    continue
                if as_of_date is not None and effective_date > as_of_date:
                    skipped_not_public_count += 1
                    continue
                event_key = cls._event_key(disclosure.id, effective_date)
                _, created = PredictiveValuationEventState.objects.get_or_create(
                    event_key=event_key,
                    defaults={
                        'security': disclosure.security,
                        'event_type': cls.DISCLOSURE_EVENT,
                        'asof_date': effective_date,
                        'payload': {
                            'disclosure_id': disclosure.id,
                            'financial_end_date': disclosure.end_date.isoformat(),
                            'ann_date': disclosure.ann_date.isoformat() if disclosure.ann_date else None,
                            'actual_date': disclosure.actual_date.isoformat() if disclosure.actual_date else None,
                            'effective_date': effective_date.isoformat(),
                        },
                    },
                )
                if created:
                    created_count += 1
                else:
                    existing_count += 1
        return {
            'scanned': scanned_count,
            'created': created_count,
            'existing': existing_count,
            'skipped_not_public': skipped_not_public_count,
        }

    @staticmethod
    def _event_key(disclosure_id: int, effective_date: date) -> str:
        raw = f'financial-disclosed:{disclosure_id}:{effective_date.isoformat()}'
        return hashlib.sha256(raw.encode('ascii')).hexdigest()