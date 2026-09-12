from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Q

from financials.models import FinancialDisclosureRecord
from financials.services.normalization import compute_row_signature, normalize_value


class DisclosureEventDetector:
    """
    Detects disclosure events from FinancialDisclosureRecord to drive targeted statement/event fetching.
    """

    @classmethod
    def detect_events_for_records(
        cls,
        raw_disclosure_records: list[dict[str, Any]],
    ) -> set[tuple[str, str]]:
        """
        Given the raw records retrieved from disclosure_date, extract unique (ts_code, period).
        """
        events: set[tuple[str, str]] = set()
        for r in raw_disclosure_records:
            ts_code = str(r.get('ts_code') or '').strip().upper()
            end_date = str(r.get('end_date') or '').strip()
            if ts_code and end_date:
                events.add((ts_code, end_date))
        return events

    @classmethod
    def filter_new_or_changed_records(
        cls,
        raw_disclosure_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return only disclosure payloads not already persisted for the same signature."""
        candidates: list[tuple[dict[str, Any], str, str]] = []
        for record in raw_disclosure_records:
            ts_code = str(normalize_value(record.get('ts_code')) or '').upper()
            if ts_code:
                candidates.append((record, ts_code, compute_row_signature(record)))

        if not candidates:
            return []

        existing = set(
            FinancialDisclosureRecord.objects.filter(
                ts_code__in={ts_code for _, ts_code, _ in candidates},
                row_signature__in={signature for _, _, signature in candidates},
            ).values_list('ts_code', 'row_signature')
        )
        return [
            record
            for record, ts_code, signature in candidates
            if (ts_code, signature) not in existing
        ]

    @classmethod
    def get_events_from_db(
        cls,
        target_period: str | None = None,
        start_ann_date: date | None = None,
        end_ann_date: date | None = None,
        ts_codes: list[str] | None = None,
    ) -> set[tuple[str, str]]:
        """
        Query FinancialDisclosureRecord within criteria to find affected (ts_code, period).
        """
        qs = FinancialDisclosureRecord.objects.all()
        if target_period:
            qs = qs.filter(Q(period=target_period) | Q(end_date=target_period))
        if start_ann_date:
            qs = qs.filter(ann_date__gte=start_ann_date)
        if end_ann_date:
            qs = qs.filter(ann_date__lte=end_ann_date)
        if ts_codes:
            qs = qs.filter(ts_code__in=ts_codes)

        events: set[tuple[str, str]] = set()
        for rec in qs.values('ts_code', 'end_date', 'period'):
            code = rec['ts_code']
            period = rec['period'] or (rec['end_date'].strftime('%Y%m%d') if rec['end_date'] else '')
            if code and period:
                events.add((code, period))
        return events

    @classmethod
    def get_actual_date_events(
        cls,
        actual_date: date,
        ts_codes: list[str] | None = None,
    ) -> set[tuple[str, str]]:
        """Return report targets whose confirmed disclosure date is the run date."""
        qs = FinancialDisclosureRecord.objects.filter(actual_date=actual_date)
        if ts_codes:
            qs = qs.filter(ts_code__in=ts_codes)

        events: set[tuple[str, str]] = set()
        for rec in qs.values('ts_code', 'end_date', 'period'):
            code = rec['ts_code']
            period = rec['period'] or (rec['end_date'].strftime('%Y%m%d') if rec['end_date'] else '')
            if code and period:
                events.add((code, period))
        return events

    @classmethod
    def detect_actual_date_events_from_records(
        cls,
        records: list[dict[str, Any]],
        actual_date: date,
        ts_codes: list[str] | None = None,
    ) -> set[tuple[str, str]]:
        """Extract due report targets from the current disclosure response."""
        allowed_codes = {code.upper() for code in ts_codes} if ts_codes else None
        events: set[tuple[str, str]] = set()
        for record in records:
            code = str(normalize_value(record.get('ts_code')) or '').upper()
            row_actual_date = record.get('actual_date')
            if normalize_value(row_actual_date) != actual_date and str(row_actual_date or '') != actual_date.strftime('%Y%m%d'):
                continue
            if not code or (allowed_codes is not None and code not in allowed_codes):
                continue
            end_date = normalize_value(record.get('end_date'))
            period = str(normalize_value(record.get('period')) or end_date or '')
            if code and period:
                events.add((code, period))
        return events
