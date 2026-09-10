from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from api_gateway.services.market_data import (
    MarketDataRequestError,
    normalize_ts_code,
    parse_history_range,
)
from market_data.models import MarketBarDailyHistory, Security, StockDailyFundamentalHistory
from manniu_auth.models import AuthRole, AuthScope, RoleScope, UserRole


class MarketDataGatewayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='gateway-user', password='Valid-password-123')
        role = AuthRole.objects.create(code='gateway-reader', name='Gateway reader')
        read_scope = AuthScope.objects.create(code='market_analysis:read', name='Market read')
        history_scope = AuthScope.objects.create(code='market_analysis:history', name='Market history')
        RoleScope.objects.create(role=role, scope=read_scope)
        RoleScope.objects.create(role=role, scope=history_scope)
        UserRole.objects.create(user=cls.user, role=role)
        cls.security = Security.objects.create(
            ts_code='000001.SZ', asset_type=Security.AssetType.STOCK,
            symbol='000001', name='Ping An Bank', market='主板', exchange='SZSE', list_status='L',
        )
        for offset in range(2):
            trade_date = date(2026, 9, 8 + offset)
            MarketBarDailyHistory.objects.create(
                security=cls.security, trade_date=trade_date,
                open=Decimal('10.0'), high=Decimal('10.5'), low=Decimal('9.8'),
                close=Decimal('10.2'), pre_close=Decimal('10.0'), change=Decimal('0.2'),
                pct_change=Decimal('2.0'), volume=100, amount=Decimal('1000'),
                close_qfq=Decimal('10.2'), close_hfq=Decimal('10.2'),
            )
            StockDailyFundamentalHistory.objects.create(
                security=cls.security, trade_date=trade_date,
                close=Decimal('10.2'), pe=Decimal('5.1'), pb=Decimal('0.8'),
                total_share=Decimal('100'), total_mv=Decimal('1000'),
            )

    def setUp(self):
        self.secret_patcher = patch(
            'manniu_auth.services.token_service._secret', return_value=b'test-secret'
        )
        self.secret_patcher.start()
        self.addCleanup(self.secret_patcher.stop)
        response = self.client.post(
            '/api/v1/auth/login',
            data={'username': 'gateway-user', 'password': 'Valid-password-123'},
            content_type='application/json',
        )
        self.token = response.json()['data']['access_token']
        self.headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def test_security_list_accepts_canonical_code_query(self):
        response = self.client.get('/api/v1/market-analysis/securities?q=Ping', **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'][0]['ts_code'], '000001.SZ')

    def test_public_api_catalog_requires_read_scope(self):
        unauthorized = self.client.get('/api/v1/public-api/catalog')
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.json()['error']['code'], 'AUTHENTICATION_REQUIRED')

        response = self.client.get('/api/v1/public-api/catalog', **self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['groups'][0]['key'], 'market_data')
        endpoints = payload['data']['groups'][0]['endpoints']
        self.assertEqual(len(endpoints), 6)
        self.assertTrue(all(endpoint['visibility'] == 'public' for endpoint in endpoints))
        self.assertTrue(all(endpoint['access_mode'] == 'authenticated' for endpoint in endpoints))
        self.assertFalse(any('required_scopes' in endpoint for endpoint in endpoints))
        self.assertIn('ts_code', next(endpoint for endpoint in endpoints if endpoint['id'].endswith('.detail'))['parameters'][0]['name'])

    def test_bars_and_fundamentals_are_bounded_and_serialized(self):
        bars = self.client.get(
            '/api/v1/market-analysis/securities/000001/bars',
            {'start_date': '2026-09-08', 'end_date': '2026-09-09', 'adjust': 'raw'},
            **self.headers,
        )
        self.assertEqual(bars.status_code, 200)
        self.assertEqual(bars.json()['data'][0]['close'], 10.2)
        fundamentals = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/fundamentals',
            {'start_date': '2026-09-08', 'end_date': '2026-09-09'},
            **self.headers,
        )
        self.assertEqual(fundamentals.status_code, 200)
        self.assertEqual(fundamentals.json()['data'][0]['units']['share'], '10k_shares')

    def test_history_range_rejects_unbounded_request(self):
        response = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/bars',
            {'start_date': '2020-01-01', 'end_date': '2026-09-09'},
            **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'RANGE_TOO_LARGE')

    def test_code_and_history_range_validation(self):
        self.assertEqual(normalize_ts_code('000001'), '000001.SZ')
        self.assertEqual(
            parse_history_range({'start_date': '2026-09-01', 'end_date': '2026-09-10'}),
            (date(2026, 9, 1), date(2026, 9, 10)),
        )
        with self.assertRaises(MarketDataRequestError):
            parse_history_range({'start_date': '2025-01-01', 'end_date': '2026-09-10'})