from django.test import TestCase

from .services import build_valuation_risk_payload


class ValuationRiskScaffoldTests(TestCase):
    def test_build_payload_returns_ready_risk_structure(self):
        payload = build_valuation_risk_payload(
            ts_code='000001.SZ',
            market='CN',
            trade_date='2026-04-11',
            valuation_variant='default',
            profit_report_type='ANNUAL',
            profit_report_ann_date='2026-03-20',
            profit_data_source='fina_indicator_income',
            rows=[
                {'valuation_method': 'pe', 'valuation_price': 12.3},
                {'valuation_method': 'pb', 'valuation_price': 12.8},
                {'valuation_method': 'ps', 'valuation_price': 13.0},
                {'valuation_method': 'fcff_dcf', 'valuation_price': 12.5},
            ],
            summary={
                'composite_valuation_price': 12.65,
                'conservative_valuation_price': 12.3,
            },
            financial_profile={
                'debt_to_assets': 42.0,
                'ca_to_assets': 46.0,
                'gross_margin': 30.0,
                'netprofit_margin': 11.5,
                'roe': 16.0,
                'ar_to_assets': 12.0,
                'inventory_to_assets': 18.0,
                'goodwill_to_assets': 6.0,
            },
            base_band_pct=0.1,
        )

        self.assertEqual(payload['ts_code'], '000001.SZ')
        self.assertEqual(payload['market'], 'CN')
        self.assertEqual(payload['status'], 'READY')
        self.assertIn(payload['risk_level'], ['LOW', 'MEDIUM', 'HIGH'])
        self.assertGreaterEqual(payload['risk_score'], 0)
        self.assertLessEqual(payload['risk_score'], 100)
        self.assertEqual(len(payload['factors']), 15)
        self.assertIn('valuation_output', payload['dimensions'])
        self.assertIn('asset_quality', payload['dimensions'])
        self.assertIn('adjustment', payload)

    def test_business_match_and_express_source_raise_risk(self):
        payload = build_valuation_risk_payload(
            ts_code='000001.SZ',
            market='CN',
            trade_date='2026-04-11',
            valuation_variant='business_match|L2|801081.SI|半导体',
            profit_report_type='Q1',
            profit_report_ann_date='2025-08-01',
            profit_data_source='express_vip',
            rows=[
                {'valuation_method': 'pe', 'valuation_price': 10.0},
                {'valuation_method': 'pb', 'valuation_price': 16.0},
            ],
            summary={
                'composite_valuation_price': 13.0,
                'conservative_valuation_price': 10.0,
            },
            base_band_pct=0.1,
        )

        self.assertIn(payload['risk_level'], ['MEDIUM', 'HIGH'])
        self.assertGreaterEqual(payload['adjustment']['valuation_discount_pct'], 0.03)

    def test_incomplete_payload_increases_disclosure_risk(self):
        payload = build_valuation_risk_payload(
            ts_code='000002.SZ',
            market='CN',
            trade_date='2026-04-11',
            valuation_variant='default',
            profit_report_type='Q1',
            profit_report_end_date='2025-06-30',
            profit_report_ann_date=None,
            profit_data_source='',
            rows=[{'valuation_method': 'pe', 'valuation_price': 8.0}],
            summary={'composite_valuation_gap_pct': 42.0},
            base_band_pct=0.1,
        )

        self.assertGreaterEqual(payload['dimensions']['disclosure_quality'], 45)
        self.assertGreaterEqual(payload['dimensions']['valuation_output'], 48)

    def test_high_leverage_profile_triggers_asset_quality_risk(self):
        payload = build_valuation_risk_payload(
            ts_code='000003.SZ',
            market='CN',
            trade_date='2026-04-11',
            valuation_variant='default',
            profit_report_type='ANNUAL',
            profit_report_ann_date='2026-03-31',
            profit_data_source='fina_indicator_income',
            rows=[
                {'valuation_method': 'pe', 'valuation_price': 10.2},
                {'valuation_method': 'pb', 'valuation_price': 9.8},
                {'valuation_method': 'ps', 'valuation_price': 10.0},
            ],
            summary={'composite_valuation_gap_pct': 8.0},
            financial_profile={
                'debt_to_assets': 82.0,
                'ca_to_assets': 18.0,
                'gross_margin': 9.0,
                'netprofit_margin': 2.5,
                'roe': 3.2,
                'ar_to_assets': 38.0,
                'inventory_to_assets': 42.0,
                'goodwill_to_assets': 33.0,
            },
            base_band_pct=0.1,
        )

        self.assertGreaterEqual(payload['dimensions']['asset_quality'], 60)
        leverage_factor = [item for item in payload['factors'] if item.get('factor_code') == 'leverage_stress'][0]
        self.assertTrue(leverage_factor['is_triggered'])
        self.assertGreaterEqual(leverage_factor['factor_score'], 70)
        goodwill_factor = [item for item in payload['factors'] if item.get('factor_code') == 'goodwill_pressure'][0]
        self.assertTrue(goodwill_factor['is_triggered'])
        self.assertGreaterEqual(goodwill_factor['factor_score'], 70)

    def test_profitability_reason_highlights_actual_weak_metric_only(self):
        payload = build_valuation_risk_payload(
            ts_code='688002.SH',
            market='CN',
            trade_date='2025-04-25',
            valuation_variant='default',
            profit_report_type='Q1',
            profit_report_end_date='2025-03-31',
            profit_report_ann_date='2025-04-25',
            profit_data_source='fina_indicator_income',
            rows=[
                {'valuation_method': 'pe', 'valuation_price': 41.90},
                {'valuation_method': 'pb', 'valuation_price': 32.47},
                {'valuation_method': 'ps', 'valuation_price': 35.18},
                {'valuation_method': 'sw_history', 'valuation_price': 57.30},
                {'valuation_method': 'fcff_dcf', 'valuation_price': 6.24},
                {'valuation_method': 'peg', 'valuation_price': 17.29},
            ],
            summary={},
            financial_profile={
                'roe': 2.648,
                'netprofit_margin': 9.9791,
                'gross_margin': 45.9515,
            },
            base_band_pct=0.1,
        )

        profitability_factor = [item for item in payload['factors'] if item.get('factor_code') == 'profitability_quality'][0]
        self.assertTrue(profitability_factor['is_triggered'])
        self.assertIn('ROE 偏低', profitability_factor['reason'])
        self.assertNotIn('净利率偏低', profitability_factor['reason'])
        self.assertNotIn('毛利率偏低', profitability_factor['reason'])

    def test_gap_pressure_reason_reports_missing_summary_precisely(self):
        payload = build_valuation_risk_payload(
            ts_code='000004.SZ',
            market='CN',
            trade_date='2026-04-11',
            valuation_variant='default',
            profit_report_type='ANNUAL',
            profit_report_ann_date='2026-03-31',
            profit_data_source='fina_indicator_income',
            rows=[
                {'valuation_method': 'pe', 'valuation_price': 11.0},
                {'valuation_method': 'pb', 'valuation_price': 9.0},
                {'valuation_method': 'ps', 'valuation_price': 10.0},
            ],
            summary={},
            financial_profile={
                'debt_to_assets': 30.0,
                'ca_to_assets': 55.0,
                'gross_margin': 32.0,
                'netprofit_margin': 12.0,
                'roe': 14.0,
            },
            base_band_pct=0.1,
        )

        gap_factor = [item for item in payload['factors'] if item.get('factor_code') == 'gap_pressure'][0]
        self.assertTrue(gap_factor['is_triggered'])
        self.assertEqual(gap_factor['reason'], '缺少组合/保守估值偏离数据，当前按保守风险分处理。')

    def test_freshness_reason_handles_invalid_announcement_date(self):
        payload = build_valuation_risk_payload(
            ts_code='600050.SH',
            market='CN',
            trade_date='2026-03-27',
            valuation_variant='default',
            profit_report_type='ANNUAL',
            profit_report_end_date='2025-12-31',
            profit_report_ann_date='2024-03-05',
            profit_data_source='fina_indicator_income',
            rows=[
                {'valuation_method': 'pe', 'valuation_price': 6.2},
                {'valuation_method': 'pb', 'valuation_price': 5.9},
                {'valuation_method': 'ps', 'valuation_price': 6.0},
            ],
            summary={'composite_valuation_gap_pct': 8.0},
            base_band_pct=0.1,
        )

        freshness_factor = [item for item in payload['factors'] if item.get('factor_code') == 'report_freshness'][0]
        self.assertIn('公告日早于报告期末日', freshness_factor['reason'])
        self.assertIn('status=ann_before_report_end', freshness_factor['factor_value'])
