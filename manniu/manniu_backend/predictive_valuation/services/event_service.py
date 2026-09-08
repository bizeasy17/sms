from __future__ import annotations

import hashlib
from datetime import date

from django.db import transaction

from financials.models import FinancialDisclosureRecord
from market_data.models import MarketBarDailyHistory, Security
from predictive_valuation.models import PredictiveValuationEventState, PredictiveValuationRegimeState


class PredictiveValuationEventService:
    """Create idempotent predictive events from shared, already-public financial data."""

    DISCLOSURE_EVENT = 'FINANCIAL_DISCLOSED'
    MARKET_REGIME_EVENT = 'MARKET_REGIME_CHANGED'
    SECURITY_REGIME_EVENT = 'SECURITY_REGIME_CHANGED'

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

    @classmethod
    def detect_regime_changes(cls, limit: int = 0) -> dict[str, int]:
        securities = Security.objects.filter(asset_type=Security.AssetType.STOCK).order_by('id')
        if limit > 0:
            securities = securities[:limit]
        scanned = created = 0
        benchmark = Security.objects.filter(ts_code='000001.SH').first()
        candidates = ([('MARKET:000001.SH', benchmark)] if benchmark else []) + [(f'SECURITY:{sec.ts_code}', sec) for sec in securities]
        with transaction.atomic():
            for scope_key, security in candidates:
                if security is None:
                    continue
                regime = cls._classify_regime(security)
                if regime is None:
                    continue
                scanned += 1
                label, asof_date, metrics = regime
                previous = PredictiveValuationRegimeState.objects.filter(scope_key=scope_key).first()
                if previous is not None and previous.regime != label:
                    event_type = cls.MARKET_REGIME_EVENT if scope_key.startswith('MARKET:') else cls.SECURITY_REGIME_EVENT
                    event_key = cls._regime_event_key(scope_key, label, asof_date)
                    _, was_created = PredictiveValuationEventState.objects.get_or_create(
                        event_key=event_key,
                        defaults={'security': None if scope_key.startswith('MARKET:') else security, 'event_type': event_type, 'asof_date': asof_date, 'payload': {'scope_key': scope_key, 'previous_regime': previous.regime, 'regime': label, 'metrics': metrics}},
                    )
                    created += int(was_created)
                PredictiveValuationRegimeState.objects.update_or_create(scope_key=scope_key, defaults={'regime': label, 'asof_date': asof_date, 'metrics': metrics})
        return {'scanned': scanned, 'created': created}

    @staticmethod
    def _classify_regime(security: Security) -> tuple[str, date, dict[str, float]] | None:
        closes = list(MarketBarDailyHistory.objects.filter(security=security).order_by('-trade_date').values_list('trade_date', 'close')[:60])
        if len(closes) < 60:
            return None
        closes.reverse()
        values = [float(close) if close is not None else None for _, close in closes]
        if any(value is None for value in values):
            return None
        ma20 = sum(values[-20:]) / 20
        ma60 = sum(values) / 60
        latest = values[-1]
        regime = 'BULL' if latest >= ma20 >= ma60 else ('BEAR' if latest <= ma20 <= ma60 else 'BALANCE')
        return regime, closes[-1][0], {'close': latest, 'ma20': ma20, 'ma60': ma60}

    @staticmethod
    def _event_key(disclosure_id: int, effective_date: date) -> str:
        raw = f'financial-disclosed:{disclosure_id}:{effective_date.isoformat()}'
        return hashlib.sha256(raw.encode('ascii')).hexdigest()

    @staticmethod
    def _regime_event_key(scope_key: str, regime: str, asof_date: date) -> str:
        raw = f'regime:{scope_key}:{regime}:{asof_date.isoformat()}'
        return hashlib.sha256(raw.encode('ascii')).hexdigest()