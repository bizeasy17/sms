from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pandas as pd
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from .models import (
    City,
    IndexDailyFundamentalHistory,
    IndexDailyFundamentalLatest,
    IngestionWatermark,
    MarketBarDailyHistory,
    MarketBarLatest,
    ProvinceRegionMapping,
    Security,
    StockCostDistributionHistory,
    StockCostDistributionLatest,
    StockDailyFundamentalHistory,
    StockDailyFundamentalLatest,
)
from .services.sync import SyncValidationError, _optional_trade_date, build_sync_plan, execute_sync
from .services.regime import classify_market_regime, classify_security_regime, next_regime_state


class MarketDataSchemaTests(SimpleTestCase):
    def test_security_code_rejects_values_longer_than_sixteen_characters(self):
        security = Security(ts_code='X' * 17, asset_type=Security.AssetType.STOCK)

        with self.assertRaises(ValidationError):
            security.full_clean()

    def test_city_is_unique_within_its_province(self):
        constraint = City._meta.constraints[0]

        self.assertEqual(constraint.fields, ('province', 'name'))

    def test_region_mapping_is_versioned_by_effective_date(self):
        constraint = ProvinceRegionMapping._meta.constraints[0]

        self.assertEqual(constraint.fields, ('province', 'mapping_version', 'effective_from'))

    def test_daily_history_uses_date_bound_security_index_and_unique_key(self):
        constraint = MarketBarDailyHistory._meta.constraints[0]
        index_fields = [index.fields for index in MarketBarDailyHistory._meta.indexes]

        self.assertEqual(constraint.fields, ('security', 'trade_date'))
        self.assertIn(['security', '-trade_date'], index_fields)

    def test_latest_bar_has_one_row_per_security_and_frequency(self):
        constraint = MarketBarLatest._meta.constraints[0]

        self.assertEqual(constraint.fields, ('security', 'frequency'))
        self.assertEqual(MarketBarLatest._meta.get_field('trade_date').get_default(), None)

    def test_stock_fundamental_history_and_latest_use_approved_keys(self):
        constraint = StockDailyFundamentalHistory._meta.constraints[0]

        self.assertEqual(constraint.fields, ('security', 'trade_date'))
        self.assertTrue(StockDailyFundamentalLatest._meta.get_field('security').unique)

    def test_stock_fundamental_preserves_tushare_raw_units_and_precision(self):
        self.assertEqual(StockDailyFundamentalHistory._meta.get_field('total_share').max_digits, 22)
        self.assertEqual(StockDailyFundamentalHistory._meta.get_field('total_mv').max_digits, 24)
        self.assertEqual(StockDailyFundamentalHistory._meta.get_field('pe_ttm').decimal_places, 6)

    def test_cost_history_and_latest_use_approved_keys(self):
        constraint = StockCostDistributionHistory._meta.constraints[0]

        self.assertEqual(constraint.fields, ('security', 'trade_date'))
        self.assertTrue(StockCostDistributionLatest._meta.get_field('security').unique)
        self.assertEqual(StockCostDistributionHistory._meta.get_field('winner_rate').max_digits, 12)

    def test_index_fundamental_history_and_latest_include_all_metrics(self):
        constraint = IndexDailyFundamentalHistory._meta.constraints[0]
        fields = {field.name for field in IndexDailyFundamentalHistory._meta.fields}

        self.assertEqual(constraint.fields, ('security', 'trade_date'))
        self.assertTrue(IndexDailyFundamentalLatest._meta.get_field('security').unique)
        self.assertTrue(
            {'pe', 'pe_ttm', 'pb', 'turnover_rate', 'turnover_rate_f', 'total_mv', 'float_mv'}
            <= fields
        )


class MarketRegimeClassifierTests(SimpleTestCase):
    def test_market_classifier_requires_eighty_positive_closes(self):
        result = classify_market_regime(
            range(1, 80),
            asof_trade_date=date(2026, 9, 8),
            source_trade_date=date(2026, 9, 8),
        )

        self.assertEqual(result.status, 'INSUFFICIENT_DATA')
        self.assertEqual(result.regime, 'BALANCE')

    def test_security_classifier_and_two_day_confirmation(self):
        result = classify_security_regime(
            range(1, 81),
            asof_trade_date=date(2026, 9, 8),
            source_trade_date=date(2026, 9, 8),
            ts_code='000001.SZ',
        )

        self.assertEqual(result.regime, 'GROWTH')
        self.assertEqual(next_regime_state('GROWTH', '', 0, 'DEFENSIVE', 2), ('GROWTH', 'DEFENSIVE', 1, False))
        self.assertEqual(next_regime_state('GROWTH', 'DEFENSIVE', 1, 'DEFENSIVE', 2), ('DEFENSIVE', '', 0, True))


class MarketDataSyncPlanTests(SimpleTestCase):
    def test_optional_source_date_converts_nan_to_null(self):
        self.assertIsNone(_optional_trade_date(float('nan')))
        self.assertEqual(_optional_trade_date('20260905'), date(2026, 9, 5))

    def test_first_backfill_defaults_to_five_years(self):
        plan = build_sync_plan({'dataset': 'stock-bars', 'mode': 'backfill'}, today=date(2026, 9, 6))

        self.assertEqual(plan.start_date, date(2021, 9, 6))
        self.assertEqual(plan.end_date, date(2026, 9, 6))

    def test_conflicting_backfill_dates_are_rejected(self):
        with self.assertRaises(SyncValidationError):
            build_sync_plan({
                'dataset': 'stock-bars',
                'mode': 'backfill',
                'start_date': '20210101',
                'history_years': 2,
            })

    def test_daily_mode_rejects_history_years(self):
        with self.assertRaises(SyncValidationError):
            build_sync_plan({'dataset': 'stock-bars', 'mode': 'daily', 'history_years': 5})

    def test_unimplemented_resample_is_rejected(self):
        with self.assertRaises(SyncValidationError):
            build_sync_plan({'dataset': 'resample', 'mode': 'backfill'})

    def test_invalid_pagination_is_rejected(self):
        with self.assertRaises(SyncValidationError):
            build_sync_plan({'dataset': 'stock-bars', 'mode': 'backfill', 'page_size': 0})

    def test_unimplemented_resume_is_rejected(self):
        with self.assertRaises(SyncValidationError):
            build_sync_plan({'dataset': 'stock-bars', 'mode': 'backfill', 'resume_run': 1})

    def test_by_date_strategy_validation(self):
        plan = build_sync_plan({'dataset': 'stock-bars', 'mode': 'daily', 'strategy': 'by-date'}, today=date(2026, 9, 6))
        self.assertEqual(plan.strategy, 'by-date')
        self.assertEqual(plan.start_date, date(2026, 9, 3))

        with self.assertRaises(SyncValidationError):
            build_sync_plan({'dataset': 'security-master', 'mode': 'backfill', 'strategy': 'by-date'})


class MarketDataSyncExecutionTests(TestCase):
    @patch('market_data.services.sync._client')
    def test_stock_bar_sync_uses_stk_factor_and_persists_adjusted_prices(self, client):
        security = Security.objects.create(ts_code='000001.SZ', asset_type=Security.AssetType.STOCK)
        client.return_value.stk_factor.return_value = pd.DataFrame([{
            'ts_code': security.ts_code,
            'trade_date': '20260905',
            'open': 10.0, 'high': 11.0, 'low': 9.8, 'close': 10.5, 'pre_close': 10.0,
            'change': 0.5, 'pct_change': 5.0, 'vol': 123456, 'amount': 1234567.8, 'adj_factor': 2.5,
            'open_qfq': 8.0, 'high_qfq': 8.8, 'low_qfq': 7.84, 'close_qfq': 8.4, 'pre_close_qfq': 8.0,
            'open_hfq': 20.0, 'high_hfq': 22.0, 'low_hfq': 19.6, 'close_hfq': 21.0, 'pre_close_hfq': 20.0,
        }])
        plan = build_sync_plan({
            'dataset': 'stock-bars',
            'mode': 'backfill',
            'scope': 'ts-code',
            'ts_codes': security.ts_code,
            'start_date': '20260905',
            'end_date': '20260905',
        })

        self.assertEqual(execute_sync(plan), 1)
        client.return_value.stk_factor.assert_called_once()
        history = MarketBarDailyHistory.objects.get(security=security, trade_date=date(2026, 9, 5))
        latest = MarketBarLatest.objects.get(security=security, frequency=MarketBarLatest.Frequency.DAILY)
        self.assertEqual(history.close_qfq, Decimal('8.4'))
        self.assertEqual(history.close_hfq, Decimal('21.0'))
        self.assertEqual(history.adj_factor, Decimal('2.5'))
        self.assertEqual(history.change_qfq, Decimal('0.4'))
        self.assertEqual(history.pct_change_qfq, Decimal('5'))
        self.assertEqual(history.change_hfq, Decimal('1.0'))
        self.assertEqual(history.pct_change_hfq, Decimal('5'))
        self.assertEqual(latest.close_qfq, Decimal('8.4'))
        self.assertEqual(latest.close_hfq, Decimal('21.0'))

    @patch('market_data.services.sync._client')
    def test_stock_fundamental_sync_updates_history_latest_and_watermark(self, client):
        security = Security.objects.create(ts_code='000001.SZ', asset_type=Security.AssetType.STOCK)
        client.return_value.daily_basic.return_value = pd.DataFrame([{
            'ts_code': security.ts_code,
            'trade_date': '20260905',
            'close': 10.5,
            'pe': 8.3,
            'total_share': 1000.0,
            'total_mv': 10500.0,
        }])
        plan = build_sync_plan({
            'dataset': 'stock-fundamentals',
            'mode': 'backfill',
            'scope': 'ts-code',
            'ts_codes': security.ts_code,
            'start_date': '20260905',
            'end_date': '20260905',
        })

        self.assertEqual(execute_sync(plan), 1)
        self.assertTrue(StockDailyFundamentalHistory.objects.filter(security=security, trade_date=date(2026, 9, 5)).exists())
        self.assertEqual(StockDailyFundamentalLatest.objects.get(security=security).trade_date, date(2026, 9, 5))
        self.assertEqual(
            IngestionWatermark.objects.get(dataset='stock-fundamentals', scope_key=security.ts_code, frequency='D').last_complete_source_date,
            date(2026, 9, 5),
        )

    @patch('market_data.services.sync._client')
    def test_by_date_strategy_executes_bulk_upsert_for_stock_bars(self, client):
        sec1 = Security.objects.create(ts_code='000001.SZ', asset_type=Security.AssetType.STOCK)
        sec2 = Security.objects.create(ts_code='000002.SZ', asset_type=Security.AssetType.STOCK)
        client.return_value.stk_factor.return_value = pd.DataFrame([
            {
                'ts_code': '000001.SZ', 'trade_date': '20260905',
                'open': 10.0, 'high': 11.0, 'low': 9.8, 'close': 10.5, 'pre_close': 10.0,
                'change': 0.5, 'pct_change': 5.0, 'vol': 1000, 'amount': 10000.0, 'adj_factor': 1.0,
                'open_qfq': 10.0, 'high_qfq': 11.0, 'low_qfq': 9.8, 'close_qfq': 10.5, 'pre_close_qfq': 10.0,
                'open_hfq': 10.0, 'high_hfq': 11.0, 'low_hfq': 9.8, 'close_hfq': 10.5, 'pre_close_hfq': 10.0,
            },
            {
                'ts_code': '000002.SZ', 'trade_date': '20260905',
                'open': 20.0, 'high': 21.0, 'low': 19.8, 'close': 20.5, 'pre_close': 20.0,
                'change': 0.5, 'pct_change': 2.5, 'vol': 2000, 'amount': 40000.0, 'adj_factor': 1.0,
                'open_qfq': 20.0, 'high_qfq': 21.0, 'low_qfq': 19.8, 'close_qfq': 20.5, 'pre_close_qfq': 20.0,
                'open_hfq': 20.0, 'high_hfq': 21.0, 'low_hfq': 19.8, 'close_hfq': 20.5, 'pre_close_hfq': 20.0,
            },
        ])
        plan = build_sync_plan({
            'dataset': 'stock-bars',
            'mode': 'backfill',
            'strategy': 'by-date',
            'start_date': '20260905',
            'end_date': '20260905',
        })

        self.assertEqual(execute_sync(plan), 2)
        client.return_value.stk_factor.assert_called_once_with(trade_date='20260905')
        self.assertEqual(MarketBarDailyHistory.objects.filter(trade_date=date(2026, 9, 5)).count(), 2)
        self.assertEqual(MarketBarLatest.objects.filter(frequency=MarketBarLatest.Frequency.DAILY).count(), 2)
