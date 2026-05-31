import pandas as pd
from django.test import SimpleTestCase, override_settings
from unittest.mock import patch

from valuation.services.snapshot_provider import fetch_local_financial_frames, record_for_end_date


class SnapshotProviderFallbackTests(SimpleTestCase):
    def _patch_empty_fundamental_manager(self):
        manager_patch = patch("valuation.services.snapshot_provider.StockFundamentalHistory.objects")
        mocked_manager = manager_patch.start()
        self.addCleanup(manager_patch.stop)

        mocked_qs = mocked_manager.filter.return_value
        mocked_qs.filter.return_value = mocked_qs
        mocked_qs.order_by.return_value = mocked_qs
        mocked_qs.values.return_value = mocked_qs
        mocked_qs.first.return_value = None

    def _fake_query(self, sql, params, db_alias=None):
        sql_text = " ".join(str(sql).split())
        if "earnings_fin_dividend" in sql_text:
            return pd.DataFrame()
        return pd.DataFrame(columns=["ts_code", "end_date", "ann_date"])

    @override_settings(VALUATION_REMOTE_DIVIDEND_FALLBACK=True)
    def test_fetch_local_financial_frames_fallback_to_remote_dividend_when_local_empty(self):
        self._patch_empty_fundamental_manager()

        class FakePro:
            def dividend(self, ts_code=None):
                return pd.DataFrame([{"ts_code": ts_code, "end_date": "20241231", "ann_date": "20250418"}])

        frames = fetch_local_financial_frames(
            "300627.SZ",
            query_local_financial_df_func=self._fake_query,
            pro=FakePro(),
        )

        self.assertEqual(frames.get("__fetch_source__"), "local")
        self.assertEqual(frames.get("__remote_fallback_frames__"), ["dividend"])
        dividend_df = frames.get("dividend")
        self.assertIsNotNone(dividend_df)
        self.assertEqual(len(dividend_df.index), 1)

    @override_settings(VALUATION_REMOTE_DIVIDEND_FALLBACK=False)
    def test_fetch_local_financial_frames_respects_disable_remote_dividend_fallback(self):
        self._patch_empty_fundamental_manager()

        class FakePro:
            def dividend(self, ts_code=None):
                return pd.DataFrame([{"ts_code": ts_code}])

        frames = fetch_local_financial_frames(
            "300627.SZ",
            query_local_financial_df_func=self._fake_query,
            pro=FakePro(),
        )

        self.assertEqual(frames.get("__remote_fallback_frames__"), [])
        self.assertTrue(frames.get("dividend").empty)

    def test_fetch_local_financial_frames_augments_forced_report_from_feature_panel(self):
        self._patch_empty_fundamental_manager()

        def fake_query(sql, params, db_alias=None):
            sql_text = " ".join(str(sql).split())
            if "earnings_financial_feature_panel" in sql_text:
                return pd.DataFrame(
                    [
                        {
                            "ts_code": "300502.SZ",
                            "report_type": "FY",
                            "end_date": "20251231",
                            "ann_date": "20260130",
                            "revenue": 10.0,
                            "total_revenue": 10.0,
                            "operate_profit": 3.0,
                            "total_profit": 3.2,
                            "n_income": 2.8,
                            "n_income_attr_p": 2.6,
                            "basic_eps": 0.5,
                            "diluted_eps": 0.5,
                            "roe": 12.0,
                            "roe_dt": 11.5,
                            "roa": 8.0,
                            "q_dt_roe": 3.0,
                            "tr_yoy": 30.0,
                            "netprofit_yoy": 40.0,
                            "grossprofit_margin": 35.0,
                            "netprofit_margin": 20.0,
                            "debt_to_assets": 25.0,
                            "current_ratio": 1.8,
                            "quick_ratio": 1.5,
                            "cash_ratio": 0.9,
                            "assets_turn": 0.7,
                            "ocf_to_or": 0.8,
                            "total_assets": 50.0,
                            "total_liab": 12.0,
                            "total_hldr_eqy_exc_min_int": 38.0,
                            "money_cap": 6.0,
                            "accounts_receiv": 4.0,
                            "inventories": 1.0,
                            "st_borr": 0.5,
                            "lt_borr": 1.5,
                            "n_cashflow_act": 4.2,
                            "n_cashflow_inv_act": -1.0,
                            "n_cash_flows_fnc_act": -0.6,
                            "n_incr_cash_cash_equ": 2.6,
                        }
                    ]
                )
            if "earnings_fin_dividend" in sql_text:
                return pd.DataFrame()
            return pd.DataFrame(columns=["ts_code", "end_date", "ann_date"])

        frames = fetch_local_financial_frames(
            "300502.SZ",
            forced_report_end_date="20251231",
            query_local_financial_df_func=fake_query,
        )

        self.assertEqual(record_for_end_date(frames.get("income"), "20251231").get("ann_date"), "20260130")
        self.assertEqual(record_for_end_date(frames.get("fina_indicator"), "20251231").get("report_type"), "FY")


class SnapshotProviderRecordSelectionTests(SimpleTestCase):
    def test_record_for_end_date_prefers_valid_ann_date(self):
        df = pd.DataFrame(
            [
                {"end_date": "20251231", "ann_date": "20150203", "marker": "stale"},
                {"end_date": "20251231", "ann_date": "20260320", "marker": "valid"},
            ]
        )

        selected = record_for_end_date(df, "20251231")
        self.assertEqual(selected.get("marker"), "valid")

    def test_record_for_end_date_falls_back_when_all_ann_missing(self):
        df = pd.DataFrame(
            [
                {"end_date": "20251231", "ann_date": None, "marker": "row1"},
                {"end_date": "20251231", "ann_date": None, "marker": "row2"},
            ]
        )

        selected = record_for_end_date(df, "20251231")
        self.assertIn(selected.get("marker"), {"row1", "row2"})