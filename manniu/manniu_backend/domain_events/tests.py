from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from domain_events.services.security_events import (
    SecurityEventsDependencyError,
    list_security_events,
)


class SecurityEventsServiceTests(SimpleTestCase):
    def _security(self, ts_code, name='Test security', security_id=1):
        return SimpleNamespace(ts_code=ts_code, name=name, id=security_id)

    def _financial(self, ts_code, event_date, key):
        return {
            'security': self._security(ts_code),
            'security_id': 1,
            'source_event_key': key,
            'source_version': 'revision-1',
            'event_type': 'FINANCIAL_DISCLOSED',
            'scope_key': f'SECURITY:{ts_code}:2026-06-30',
            'asof_date': event_date,
            'payload': {'financial_end_date': '2026-06-30'},
        }

    def _regime(self, ts_code, event_date, key):
        return {
            'security': self._security(ts_code),
            'security_id': 1,
            'source_event_key': key,
            'source_version': 'stock_rule_v1',
            'event_type': 'SECURITY_STYLE_CHANGED',
            'scope_key': f'SECURITY:{ts_code}',
            'source_trade_date': event_date,
            'payload': {'old_regime': 'BALANCE', 'new_regime': 'GROWTH'},
        }

    @patch('domain_events.services.security_events.list_regime_events')
    @patch('domain_events.services.security_events.DisclosureEventDetector.list_disclosure_events')
    def test_merges_sources_with_stable_date_descending_order(self, disclosures, regimes):
        disclosures.return_value = [
            self._financial('000002.SZ', date(2026, 9, 10), 'financial-2'),
            self._financial('000001.SZ', date(2026, 9, 10), 'financial-1'),
        ]
        regimes.return_value = [self._regime('000001.SZ', date(2026, 9, 9), 'regime-1')]

        result = list_security_events(asof_date=date(2026, 9, 10), page_size=10)

        self.assertEqual([item.source_event_key for item in result.items], ['financial-1', 'financial-2', 'regime-1'])
        self.assertEqual(result.data_status, 'COMPLETE')
        self.assertEqual(result.total, 3)

    @patch('domain_events.services.security_events.list_regime_events', return_value=[])
    @patch('domain_events.services.security_events.DisclosureEventDetector.list_disclosure_events')
    def test_applies_asof_and_date_filters(self, disclosures, _regimes):
        disclosures.return_value = [
            self._financial('000001.SZ', date(2026, 9, 9), 'before'),
            self._financial('000001.SZ', date(2026, 9, 11), 'after'),
        ]

        result = list_security_events(
            ts_codes=['000001.SZ'],
            start_date=date(2026, 9, 8),
            end_date=date(2026, 9, 10),
            asof_date=date(2026, 9, 10),
            page_size=10,
        )

        self.assertEqual([item.source_event_key for item in result.items], ['before'])

    @patch('domain_events.services.security_events.list_regime_events', side_effect=RuntimeError('market data down'))
    @patch('domain_events.services.security_events.DisclosureEventDetector.list_disclosure_events')
    def test_single_source_failure_returns_partial_success(self, disclosures, _regimes):
        disclosures.return_value = [self._financial('000001.SZ', date(2026, 9, 9), 'financial-1')]

        result = list_security_events(ts_codes=['000001.SZ'], page_size=10)

        self.assertEqual(result.data_status, 'PARTIAL_SUCCESS')
        self.assertEqual(result.warnings, ('MARKET_DATA_UNAVAILABLE',))
        self.assertEqual(len(result.items), 1)

    @patch('domain_events.services.security_events.DisclosureEventDetector.list_disclosure_events', side_effect=RuntimeError('financials down'))
    def test_single_selected_source_failure_is_dependency_error(self, _disclosures):
        with self.assertRaises(SecurityEventsDependencyError) as context:
            list_security_events(event_types=['FINANCIAL_DISCLOSED'])
        self.assertEqual(context.exception.source_system, 'financials')
