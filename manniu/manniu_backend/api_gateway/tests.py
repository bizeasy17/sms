from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from api_gateway.services.market_data import (
    MarketDataRequestError,
    normalize_ts_code,
    parse_history_range,
)
from market_data.models import MarketBarDailyHistory, Security, StockDailyFundamentalHistory
from financials.models import (
    FinancialDisclosureRecord,
    FinancialExpressRecord,
    FinancialForecastRecord,
    FinancialIncomeRecord,
    FinancialMainBusinessRecord,
)
from manniu_auth.models import AuthRole, AuthScope, RoleScope, UserRole
from traditional_valuation.models import (
    TraditionalValuationRiskSnapshot,
    TraditionalValuationSnapshot,
    TraditionalValuationSnapshotLatest,
    TraditionalValuationVariantSummaryLatest,
)
from market_sentiment.models import MarketSentimentSnapshot, StockSentimentSnapshot
from predictive_valuation.models import PredictiveValuationCurrent, PredictiveValuationSnapshot


class MarketDataGatewayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='gateway-user', password='Valid-password-123')
        role = AuthRole.objects.create(code='gateway-reader', name='Gateway reader')
        read_scope = AuthScope.objects.create(code='market_analysis:read', name='Market read')
        history_scope = AuthScope.objects.create(code='market_analysis:history', name='Market history')
        sentiment_scope = AuthScope.objects.create(code='market_sentiment:read', name='Sentiment read')
        sentiment_history_scope = AuthScope.objects.create(
            code='market_sentiment:history_read', name='Sentiment history',
        )
        predictive_scope = AuthScope.objects.create(
            code='predictive_valuation:read', name='Predictive valuation read',
        )
        predictive_history_scope = AuthScope.objects.create(
            code='predictive_valuation:history_read', name='Predictive valuation history',
        )
        predictive_operator_scope = AuthScope.objects.create(
            code='predictive_valuation:operator_read', name='Predictive valuation operator read',
        )
        RoleScope.objects.create(role=role, scope=read_scope)
        RoleScope.objects.create(role=role, scope=history_scope)
        RoleScope.objects.create(role=role, scope=sentiment_scope)
        RoleScope.objects.create(role=role, scope=sentiment_history_scope)
        RoleScope.objects.create(role=role, scope=predictive_scope)
        RoleScope.objects.create(role=role, scope=predictive_history_scope)
        RoleScope.objects.create(role=role, scope=predictive_operator_scope)
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
        FinancialIncomeRecord.objects.create(
            security=cls.security, ts_code='000001.SZ', ann_date=date(2026, 8, 30),
            end_date=date(2026, 6, 30), period='20260630', row_signature='income-current',
            revenue=Decimal('1000.0'), basic_eps=Decimal('0.50'),
        )
        FinancialIncomeRecord.objects.create(
            security=cls.security, ts_code='000001.SZ', ann_date=date(2026, 9, 5),
            end_date=date(2026, 6, 30), period='20260630', row_signature='income-future',
            revenue=Decimal('2000.0'), basic_eps=Decimal('0.80'),
        )
        FinancialDisclosureRecord.objects.create(
            security=cls.security, ts_code='000001.SZ', ann_date=date(2026, 8, 30),
            actual_date=date(2026, 8, 30), end_date=date(2026, 6, 30), period='20260630',
            row_signature='disclosure-current',
        )
        snapshot = TraditionalValuationSnapshot.objects.create(
            security=cls.security,
            asof_date=date(2026, 9, 9),
            source_trade_date=date(2026, 9, 8),
            report_type='H1',
            financial_end_date=date(2026, 6, 30),
            financial_ann_date=date(2026, 8, 30),
            profit_bucket='formal',
            valuation_variant='sw_l3_baseline',
            style_profile='baseline',
            parameter_version='sw-test-1',
            valuation_engine_version='test-1',
            current_price=Decimal('10.2'),
            composite_valuation_price_raw=Decimal('14.0'),
            composite_valuation_price_optimized=Decimal('13.5'),
            conservative_valuation_price_raw=Decimal('12.0'),
            conservative_valuation_price_optimized=Decimal('11.4'),
            methods={'pe': {'valuation_price': 14.0}},
            summary={
                'buy_candidate': True,
                'source_data_status': 'COMPLETE',
                'skipped_methods': {'ddm': 'dividend_unavailable'},
            },
            provenance={'mapping_version': 'mapping-test-1'},
        )
        risk = TraditionalValuationRiskSnapshot.objects.create(
            snapshot=snapshot, risk_engine_version='test-risk-1',
            risk_score=Decimal('20.0'), risk_level='LOW', confidence=Decimal('0.9'),
        )
        TraditionalValuationSnapshotLatest.objects.create(
            security=cls.security, report_type='H1', profit_bucket='formal',
            valuation_variant='sw_l3_baseline', style_profile='baseline',
            snapshot=snapshot, asof_date=snapshot.asof_date,
            source_trade_date=snapshot.source_trade_date,
            composite_valuation_price=Decimal('13.5'),
            conservative_valuation_price=Decimal('11.4'),
            risk_snapshot=risk, parameter_version='sw-test-1',
            valuation_engine_version='test-1',
        )
        TraditionalValuationVariantSummaryLatest.objects.create(
            security=cls.security, report_type='H1', profit_bucket='formal',
            valuation_variant='sw_l3_baseline', style_profile='baseline',
            snapshot=snapshot, asof_date=snapshot.asof_date,
            compare_group='sw_l3_baseline', industry_level='L3',
            industry_code='801783.SI', industry_name='测试行业',
            composite_valuation_price=Decimal('13.5'),
            conservative_valuation_price=Decimal('11.4'), method_coverage=1,
            is_active_variant=True,
            provenance={'buy_candidate_summary': {'buy_candidate': True}},
        )
        MarketSentimentSnapshot.objects.create(
            market='CN', scope_type='MARKET', scope_code='ALL_A',
            trade_date=date(2026, 9, 9), score=None, level='', status='WARMING_UP',
            raw_score=Decimal('0.25'), standardized_score=None,
            momentum=Decimal('0.10'), activity=Decimal('0.20'), fear=Decimal('-0.05'),
            universe_count=1, valid_count=1, coverage=Decimal('1.0'),
            engine_version='sentiment_v1', source_trade_date=date(2026, 9, 9),
            metadata={'factor_count': 1},
        )
        StockSentimentSnapshot.objects.create(
            security=cls.security, trade_date=date(2026, 9, 9),
            score=Decimal('72.5'), level='HIGH', status='VALID',
            raw_score=Decimal('72.5'), standardized_score=Decimal('1.2'),
            momentum=Decimal('0.8'), activity=Decimal('0.6'), fear=Decimal('-0.2'),
            universe_count=1, valid_count=1, coverage=Decimal('1.0'),
            engine_version='sentiment_v1', source_trade_date=date(2026, 9, 9),
            peer_type='industry', peer_code='industry-1', peer_name='测试行业',
            peer_count=10, normalization_mode='same_day_peer_percentile',
            metadata={'valid_history': 20},
        )
        predictive_snapshot = PredictiveValuationSnapshot.objects.create(
            security=cls.security, asof_date=date(2026, 9, 9), report_type='H1',
            model_version='pv-test-1', feature_contract_version='features-v1',
            source_market_date=date(2026, 9, 8), financial_end_date=date(2026, 6, 30),
            financial_ann_date=date(2026, 8, 30), financial_source_as_of_date=date(2026, 8, 30),
            financial_report_type='H1', financial_fiscal_year=2026, feature_data_source='live_db',
            signal_score=Decimal('72.5'), up_probability=Decimal('0.80000000'),
            target_return_pct=Decimal('12.5'), target_return_low_pct=Decimal('5.0'),
            target_return_high_pct=Decimal('20.0'), target_price=Decimal('11.475'),
            target_price_low=Decimal('10.71'), target_price_high=Decimal('12.24'),
            target_market_cap=Decimal('1125'), risk_level='MEDIUM', action='BUY',
            anchor_mode='live_latest', refresh_reason='MANUAL_REFRESH',
            explain={'confidence': 0.8},
            raw_result={'live_feature_compliant': True, 'adjusted_return': {'center': 0.125}},
            predictive_tiered_template={'balanced': {'target_price': 11.475}},
        )
        PredictiveValuationCurrent.objects.create(
            security=cls.security, report_type='H1', snapshot=predictive_snapshot,
            model_version='pv-test-1', feature_contract_version='features-v1',
            asof_date=predictive_snapshot.asof_date, signal_score=Decimal('72.5'),
            up_probability=Decimal('0.80000000'), target_return_pct=Decimal('12.5'),
            target_return_low_pct=Decimal('5.0'), target_return_high_pct=Decimal('20.0'),
            target_price=Decimal('11.475'), target_price_low=Decimal('10.71'),
            target_price_high=Decimal('12.24'), target_market_cap=Decimal('1125'),
            risk_level='MEDIUM', action='BUY', feature_data_source='live_db',
            refresh_reason='MANUAL_REFRESH', explain={'confidence': 0.8},
            raw_result={'live_feature_compliant': True},
            predictive_tiered_template={'balanced': {'target_price': 11.475}},
            market_regime='BALANCE', security_regime='GROWTH',
        )
        fusion_snapshot = PredictiveValuationSnapshot.objects.create(
            security=cls.security, asof_date=date(2026, 9, 9), report_type='FUSION',
            model_version='fusion', feature_contract_version='features-v1',
            source_market_date=date(2026, 9, 8), financial_end_date=date(2026, 6, 30),
            feature_data_source='live_db', signal_score=Decimal('70'),
            target_return_pct=Decimal('10'), target_return_low_pct=Decimal('4'),
            target_return_high_pct=Decimal('16'), target_price=Decimal('11'),
            target_price_low=Decimal('10.4'), target_price_high=Decimal('11.6'),
            target_market_cap=Decimal('1100'), risk_level='MEDIUM', action='BUY',
            raw_result={'fusion': {'components': {'Q1': {'status': 'FAILED'}, 'H1': {'status': 'SUCCEEDED'}}},
                        'live_feature_compliant': True},
        )
        PredictiveValuationCurrent.objects.create(
            security=cls.security, report_type='FUSION', snapshot=fusion_snapshot,
            model_version='fusion', feature_contract_version='features-v1',
            asof_date=fusion_snapshot.asof_date, signal_score=Decimal('70'),
            target_return_pct=Decimal('10'), target_return_low_pct=Decimal('4'),
            target_return_high_pct=Decimal('16'), target_price=Decimal('11'),
            target_price_low=Decimal('10.4'), target_price_high=Decimal('11.6'),
            target_market_cap=Decimal('1100'), risk_level='MEDIUM', action='BUY',
            feature_data_source='live_db', raw_result={'live_feature_compliant': True},
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

    def test_sentiment_market_and_stock_snapshot_routes(self):
        market = self.client.get(
            '/api/v1/market-analysis/sentiment/market',
            {'asof_date': '2026-09-10'}, **self.headers,
        )
        self.assertEqual(market.status_code, 200)
        self.assertEqual(market.json()['data']['status'], 'WARMING_UP')
        self.assertEqual(market.json()['meta']['source_trade_date'], '2026-09-09')

        stock = self.client.get(
            '/api/v1/market-analysis/sentiment/stocks/000001',
            {'asof_date': '2026-09-10'}, **self.headers,
        )
        self.assertEqual(stock.status_code, 200)
        self.assertEqual(stock.json()['data']['ts_code'], '000001.SZ')
        self.assertEqual(stock.json()['data']['stock_history_count'], 20)

    def test_sentiment_history_and_ranking_are_bounded(self):
        history = self.client.get(
            '/api/v1/market-analysis/sentiment/market/history',
            {'start_date': '2026-09-01', 'end_date': '2026-09-10', 'page_size': 10},
            **self.headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()['meta']['total'], 1)

        ranking = self.client.get(
            '/api/v1/market-analysis/sentiment/stocks/ranking',
            {'asof_date': '2026-09-09'}, **self.headers,
        )
        self.assertEqual(ranking.status_code, 200)
        self.assertEqual(ranking.json()['data'][0]['score'], 72.5)

        invalid_range = self.client.get(
            '/api/v1/market-analysis/sentiment/market/history',
            {'start_date': '2024-01-01', 'end_date': '2026-09-10'}, **self.headers,
        )
        self.assertEqual(invalid_range.status_code, 400)
        self.assertEqual(invalid_range.json()['error']['code'], 'RANGE_TOO_LARGE')

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

    def test_financials_asof_route_and_history_scope(self):
        current = self.client.get(
            '/api/v1/market-analysis/securities/000001/financials',
            {'dataset': 'income'}, **self.headers,
        )
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()['data'][0]['revenue'], 2000.0)

        historical = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/financials',
            {'dataset': 'income', 'asof_date': '2026-09-01'}, **self.headers,
        )
        self.assertEqual(historical.status_code, 200)
        self.assertEqual(historical.json()['data'][0]['revenue'], 1000.0)

    def test_financials_and_disclosures_require_valid_request(self):
        missing_dataset = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/financials', **self.headers,
        )
        self.assertEqual(missing_dataset.status_code, 400)
        self.assertEqual(missing_dataset.json()['error']['code'], 'INVALID_REQUEST')

        disclosures = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/disclosures', **self.headers,
        )
        self.assertEqual(disclosures.status_code, 200)
        self.assertEqual(disclosures.json()['data'][0]['effective_date'], '2026-08-30')

    def test_financials_end_date_matches_report_period(self):
        FinancialExpressRecord.objects.create(
            security=self.security, ts_code='000001.SZ', ann_date=date(2022, 1, 14),
            end_date=date(2021, 12, 31), period='20211231', row_signature='express-period',
        )
        FinancialForecastRecord.objects.create(
            security=self.security, ts_code='000001.SZ', ann_date=date(2026, 1, 31),
            end_date=date(2025, 12, 31), period='20251231', row_signature='forecast-old',
        )
        FinancialForecastRecord.objects.create(
            security=self.security, ts_code='000001.SZ', ann_date=date(2026, 7, 31),
            end_date=date(2026, 6, 30), period='20260630', row_signature='forecast-period',
        )
        FinancialMainBusinessRecord.objects.create(
            security=self.security, ts_code='000001.SZ', ann_date=None,
            end_date=date(2026, 6, 30), period='20260630', row_signature='main-business-period',
            bz_item='主营业务',
        )

        express = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/financials',
            {'dataset': 'express', 'asof_date': '2026-09-10',
             'start_date': '2021-01-01', 'end_date': '2021-12-31'}, **self.headers,
        )
        forecast = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/financials',
            {'dataset': 'forecast', 'asof_date': '2026-09-10',
             'start_date': '2026-01-01', 'end_date': '2026-06-30'}, **self.headers,
        )
        main_business = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/financials',
            {'dataset': 'main_business', 'asof_date': '2026-09-10',
             'start_date': '2026-01-01', 'end_date': '2026-06-30'}, **self.headers,
        )

        self.assertEqual(express.status_code, 200)
        self.assertEqual(express.json()['meta']['total'], 1)
        self.assertEqual(express.json()['data'][0]['end_date'], '2021-12-31')
        self.assertEqual(forecast.status_code, 200)
        self.assertEqual(forecast.json()['meta']['total'], 1)
        self.assertEqual(forecast.json()['data'][0]['end_date'], '2026-06-30')
        self.assertEqual(main_business.status_code, 200)
        self.assertEqual(main_business.json()['meta']['total'], 1)
        self.assertEqual(main_business.json()['data'][0]['end_date'], '2026-06-30')

    def test_traditional_valuation_current_history_and_compare(self):
        current = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/traditional',
            {'asof_date': '2026-09-10', 'report_type': 'H1'}, **self.headers,
        )
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()['data']['valuation_variant'], 'sw_l3_baseline')
        self.assertEqual(current.json()['data']['summary']['buy_candidate'], True)

        history = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/traditional/history',
            {'start_date': '2026-09-01', 'end_date': '2026-09-10', 'report_type': 'H1'}, **self.headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()['meta']['total'], 1)

        compare = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/traditional/compare',
            {'asof_date': '2026-09-10', 'report_type': 'H1'}, **self.headers,
        )
        self.assertEqual(compare.status_code, 200)
        self.assertEqual(compare.json()['data']['active_variant'], 'sw_l3_baseline')

    def test_traditional_valuation_diagnostics_require_scope(self):
        response = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/traditional',
            {'include_methods': 'true'}, **self.headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error']['code'], 'SCOPE_REQUIRED')

    def test_traditional_valuation_history_is_bounded(self):
        response = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/traditional/history',
            {'start_date': '2024-01-01', 'end_date': '2026-09-10'}, **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'RANGE_TOO_LARGE')

    def test_predictive_valuation_current_history_fusion_and_status(self):
        current = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/predictive',
            {'report_type': 'H1'}, **self.headers,
        )
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()['data']['model_version'], 'pv-test-1')
        self.assertEqual(current.json()['data']['source_market_date'], '2026-09-08')
        self.assertEqual(current.json()['data']['target_return']['center'], 12.5)
        self.assertEqual(current.json()['meta']['source_trade_date'], '2026-09-08')

        history = self.client.get(
            '/api/v1/market-analysis/securities/000001/valuations/predictive/history',
            {'start_date': '2026-09-01', 'end_date': '2026-09-10', 'report_type': 'H1'},
            **self.headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()['meta']['total'], 1)

        fusion = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/predictive/fusion',
            **self.headers,
        )
        self.assertEqual(fusion.status_code, 200)
        self.assertEqual(fusion.json()['data']['report_type'], 'FUSION')
        self.assertEqual(fusion.json()['data']['data_status'], 'PARTIAL_SUCCESS')
        self.assertIn('components', fusion.json()['data']['raw_result']['fusion'])

        status = self.client.get(
            '/api/v1/market-analysis/valuations/predictive/status', **self.headers,
        )
        self.assertEqual(status.status_code, 200)
        self.assertIn('H1', status.json()['data']['models'])

    def test_predictive_valuation_validates_scope_and_version(self):
        response = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/predictive',
            {'serving_slot': 'candidate'}, **self.headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'VERSION_CONFLICT')

        history = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/predictive/history',
            {'start_date': '2024-01-01', 'end_date': '2026-09-10'}, **self.headers,
        )
        self.assertEqual(history.status_code, 400)
        self.assertEqual(history.json()['error']['code'], 'RANGE_TOO_LARGE')

        unknown = self.client.get(
            '/api/v1/market-analysis/securities/000001.SZ/valuations/predictive',
            {'unexpected': 'value'}, **self.headers,
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.json()['error']['code'], 'INVALID_REQUEST')

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

    @patch('api_gateway.views.index_catalog', return_value=(
        [{'index_key': 'hs300', 'ts_code': '399300.SZ', 'data_status': 'VALID'}],
        'COMPLETE',
    ))
    def test_indices_catalog_route(self, catalog_mock):
        response = self.client.get(
            '/api/v1/market-analysis/indices/catalog',
            {'index_keys': 'hs300'},
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'][0]['index_key'], 'hs300')
        catalog_mock.assert_called_once_with(['hs300'])

    def test_index_valuation_rejects_unknown_metric(self):
        response = self.client.get(
            '/api/v1/market-analysis/indices/hs300/valuation',
            {'metric': 'PS'},
            **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'INVALID_METRIC')

    @patch('api_gateway.views.index_valuation_result', return_value=(
        {'index_key': 'hs300', 'metric': 'PE', 'method': {'status': 'VALID'}},
        'VALID',
        [],
        SimpleNamespace(end_date=date(2026, 9, 9)),
    ))
    def test_index_valuation_route_forwards_typed_request(self, valuation_mock):
        response = self.client.get(
            '/api/v1/market-analysis/indices/hs300/valuation',
            {'metric': 'PE', 'window': '1Y', 'band_pct': '0.15'},
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['meta']['data_status'], 'COMPLETE')
        valuation_mock.assert_called_once_with(
            index_key='hs300', metric='PE', window='1Y', start_date=None,
            end_date=None, band_pct=0.15,
        )

    def test_index_health_returns_explicit_unavailable(self):
        response = self.client.get(
            '/api/v1/market-analysis/indices/health',
            **self.headers,
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'UPSTREAM_DEPENDENCY_UNAVAILABLE')