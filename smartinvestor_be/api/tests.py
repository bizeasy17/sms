import json
import datetime
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pandas as pd

from django.core.cache import cache
from django.test import TestCase, override_settings

from api.views import (
    _build_corporate_action_impact_payload,
    _build_valuation_summary_payload,
    _compute_predictive_pick_score,
    _enrich_rows_with_share_basis,
    _fetch_earnings_signal_batch,
    _resolve_valuation_report_end_date_from_feature_panel,
)
from valuation.services.valuation_engine import estimate_all_supported_methods


class EarningsSignalApiTests(TestCase):
    def setUp(self):
        self.url = "/api/earnings/signal/600519.SH/"
        self.cache_key = "earnings_signal:600519.SH:ALL"
        cache.delete(self.cache_key)

    def _build_urlopen_response(self, payload_dict):
        mocked = MagicMock()
        mocked.__enter__.return_value.read.return_value = json.dumps(payload_dict).encode("utf-8")
        return mocked

    @patch("api.views.urllib_request.urlopen")
    def test_get_earnings_signal_success(self, mocked_urlopen):
        mocked_urlopen.return_value = self._build_urlopen_response(
            {
                "ok": True,
                "result": {
                    "ts_code": "600519.SH",
                    "trade_date": "2026-03-28",
                    "model_version": "earnings_q1_v1_2_0",
                    "be_payload": {
                        "signal_score": 67.4,
                        "target_return_pct": 12.5,
                        "target_price": 1888.66,
                        "target_market_cap": 23770000.12,
                        "action": "BUY",
                        "risk_level": "MEDIUM",
                    },
                    "valuation_mapping": {
                        "stance": "BUY",
                        "confidence": "MEDIUM",
                        "prob_component": 42.7,
                        "earnings_component": 24.7,
                    },
                },
            }
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(body.get("code"), 0)
        self.assertEqual(body.get("message"), "ok")

        data = body.get("data") or {}
        self.assertEqual(data.get("ts_code"), "600519.SH")
        self.assertEqual(data.get("action"), "BUY")
        self.assertEqual(data.get("risk_level"), "MEDIUM")
        self.assertEqual(data.get("signal_score"), 67.4)
        self.assertEqual(data.get("target_return_pct"), 12.5)
        self.assertEqual(data.get("target_price"), 1888.66)
        self.assertEqual(data.get("target_market_cap"), 23770000.12)
        self.assertEqual(data.get("model_version"), "earnings_q1_v1_2_0")
        self.assertEqual(data.get("asof_date"), "2026-03-28")

    @patch("api.views.urllib_request.urlopen", side_effect=URLError("timeout"))
    def test_get_earnings_signal_degrade_default(self, _mocked_urlopen):
        cache.delete(self.cache_key)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(body.get("code"), 0)
        self.assertEqual((body.get("degrade") or {}).get("enabled"), True)
        self.assertEqual((body.get("degrade") or {}).get("reason"), "upstream_error_default")

    @patch("api.views.urllib_request.urlopen", side_effect=URLError("timeout"))
    def test_get_earnings_signal_degrade_with_cache(self, _mocked_urlopen):
        cache.set(
            self.cache_key,
            {
                "ts_code": "600519.SH",
                "signal_score": 55.5,
                "action": "HOLD",
                "risk_level": "MEDIUM",
                "model_version": "cached_v1",
                "asof_date": "2026-03-27",
                "explain": {
                    "stance": "HOLD",
                    "confidence": "LOW",
                    "prob_component": None,
                    "earnings_component": None,
                },
            },
            timeout=60,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(body.get("code"), 0)
        self.assertEqual((body.get("degrade") or {}).get("enabled"), True)
        self.assertEqual((body.get("degrade") or {}).get("reason"), "upstream_error_cache_hit")
        self.assertEqual((body.get("data") or {}).get("model_version"), "cached_v1")


class TraditionalValuationAnchorTests(TestCase):
    @patch("valuation.services.valuation_engine._build_scarcity_overlay_row", return_value=None)
    @patch("valuation.services.valuation_engine.estimate_by_ddm", side_effect=ValueError("skip_ddm"))
    @patch("valuation.services.valuation_engine.estimate_by_fcff_dcf", side_effect=ValueError("skip_dcf"))
    @patch("valuation.services.valuation_engine._build_sw_history_component_rows", return_value=[])
    @patch("valuation.services.valuation_engine.estimate_by_sw_history")
    def test_estimate_all_supported_methods_prefers_sw_history_targets_when_enabled(
        self,
        mocked_sw_history,
        _mocked_components,
        _mocked_dcf,
        _mocked_ddm,
        _mocked_scarcity,
    ):
        snapshot = {
            "trade_date": "20260422",
            "close_price": 2.0,
            "market_cap": 20.0,
            "total_share": 10.0,
            "netprofit": 10.0,
            "equity_book_value": 10.0,
            "revenue": 10.0,
            "pe_ttm": 2.0,
            "pb": 2.0,
            "ps_ttm": 2.0,
            "peg_growth_yoy_pct": None,
        }
        mocked_sw_history.return_value = {
            "method": "sw_history",
            "ts_code": "688080.SH",
            "implied_price": 7.0,
            "equity_value": 70.0,
            "history_targets": {"pe": 4.0, "pb": 5.0, "ps": 6.0},
        }

        valuations = estimate_all_supported_methods(
            ts_code="688080.SH",
            trade_date="2026-04-22",
            snapshot=snapshot,
            prefer_sw_history_targets=True,
        )

        pe_row = valuations.loc[valuations["method"] == "pe"].iloc[0]
        pb_row = valuations.loc[valuations["method"] == "pb"].iloc[0]
        ps_row = valuations.loc[valuations["method"] == "ps"].iloc[0]

        self.assertEqual(pe_row["applied_multiple"], 4.0)
        self.assertEqual(pb_row["applied_multiple"], 5.0)
        self.assertEqual(ps_row["applied_multiple"], 6.0)
        self.assertEqual(pe_row["implied_price"], 4.0)
        self.assertEqual(pb_row["implied_price"], 5.0)
        self.assertEqual(ps_row["implied_price"], 6.0)

    @patch("valuation.services.valuation_engine._build_scarcity_overlay_row", return_value=None)
    @patch("valuation.services.valuation_engine.estimate_by_ddm", side_effect=ValueError("skip_ddm"))
    @patch("valuation.services.valuation_engine.estimate_by_fcff_dcf", side_effect=ValueError("skip_dcf"))
    @patch("valuation.services.valuation_engine._build_sw_history_component_rows", return_value=[])
    @patch("valuation.services.valuation_engine.estimate_by_sw_history")
    def test_estimate_all_supported_methods_keeps_snapshot_targets_by_default(
        self,
        mocked_sw_history,
        _mocked_components,
        _mocked_dcf,
        _mocked_ddm,
        _mocked_scarcity,
    ):
        snapshot = {
            "trade_date": "20260422",
            "close_price": 2.0,
            "market_cap": 20.0,
            "total_share": 10.0,
            "netprofit": 10.0,
            "equity_book_value": 10.0,
            "revenue": 10.0,
            "pe_ttm": 2.0,
            "pb": 2.0,
            "ps_ttm": 2.0,
            "peg_growth_yoy_pct": None,
        }
        mocked_sw_history.return_value = {
            "method": "sw_history",
            "ts_code": "688080.SH",
            "implied_price": 7.0,
            "equity_value": 70.0,
            "history_targets": {"pe": 4.0, "pb": 5.0, "ps": 6.0},
        }

        valuations = estimate_all_supported_methods(
            ts_code="688080.SH",
            trade_date="2026-04-22",
            snapshot=snapshot,
        )

        pe_row = valuations.loc[valuations["method"] == "pe"].iloc[0]
        pb_row = valuations.loc[valuations["method"] == "pb"].iloc[0]
        ps_row = valuations.loc[valuations["method"] == "ps"].iloc[0]

        self.assertEqual(pe_row["applied_multiple"], 2.0)
        self.assertEqual(pb_row["applied_multiple"], 2.0)
        self.assertEqual(ps_row["applied_multiple"], 2.0)


class EarningsSignalBatchTests(TestCase):
    def setUp(self):
        cache.clear()

    def _build_batch_urlopen_response(self, payload_dict):
        mocked = MagicMock()
        mocked.__enter__.return_value.read.return_value = json.dumps(payload_dict).encode("utf-8")
        return mocked

    @patch("api.views.urllib_request.urlopen")
    def test_fetch_earnings_signal_batch_uses_cache(self, mocked_urlopen):
        cache.set(
            "earnings_signal:600519.SH:ALL",
            {
                "ts_code": "600519.SH",
                "signal_score": 61.5,
                "action": "BUY",
                "risk_level": "MEDIUM",
                "report_type": "Q1",
            },
            timeout=120,
        )

        mocked_urlopen.return_value = self._build_batch_urlopen_response(
            {
                "ok": True,
                "results": {
                    "000001.SZ": {
                        "ts_code": "000001.SZ",
                        "trade_date": "2026-04-05",
                        "financial_report_type": "Q1",
                        "feature_data_source": "quarterly",
                        "financial_fiscal_year": 2026,
                        "be_payload": {
                            "signal_score": 55.0,
                            "target_return_pct": 9.0,
                            "target_price": 15.2,
                            "target_market_cap": 250000000000.0,
                            "action": "HOLD",
                            "risk_level": "MEDIUM",
                        },
                        "valuation_mapping": {
                            "stance": "HOLD",
                            "confidence": "MEDIUM",
                            "prob_component": 30.0,
                            "earnings_component": 25.0,
                        },
                    }
                },
            }
        )

        result = _fetch_earnings_signal_batch(["600519.SH", "000001.SZ"], report_type="ALL")
        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertIn("600519.SH", result)
        self.assertIn("000001.SZ", result)
        self.assertEqual((result.get("600519.SH") or {}).get("signal_score"), 61.5)
        self.assertEqual((result.get("000001.SZ") or {}).get("signal_score"), 55.0)

        cached_000001 = cache.get("earnings_signal:000001.SZ:ALL") or {}
        self.assertEqual(cached_000001.get("signal_score"), 55.0)

    @patch("api.views.urllib_request.urlopen")
    def test_fetch_earnings_signal_batch_batch_cache_hit_stats(self, mocked_urlopen):
        mocked_urlopen.return_value = self._build_batch_urlopen_response(
            {
                "ok": True,
                "results": {
                    "000001.SZ": {
                        "ts_code": "000001.SZ",
                        "trade_date": "2026-04-05",
                        "financial_report_type": "Q1",
                        "feature_data_source": "quarterly",
                        "financial_fiscal_year": 2026,
                        "be_payload": {
                            "signal_score": 55.0,
                            "target_return_pct": 9.0,
                            "action": "HOLD",
                            "risk_level": "MEDIUM",
                        },
                        "valuation_mapping": {
                            "stance": "HOLD",
                            "confidence": "MEDIUM",
                        },
                    }
                },
            }
        )

        _fetch_earnings_signal_batch(["000001.SZ"], report_type="ALL")
        self.assertEqual(mocked_urlopen.call_count, 1)

        result, stats = _fetch_earnings_signal_batch(
            ["000001.SZ"],
            report_type="ALL",
            return_stats=True,
        )

        self.assertIn("000001.SZ", result)
        self.assertEqual(stats.get("batch_cache_hit"), True)
        self.assertEqual(stats.get("per_code_cache_hit"), 1)
        self.assertEqual(stats.get("upstream_request_count"), 0)
        self.assertEqual(mocked_urlopen.call_count, 1)

    @override_settings(EARNINGS_SIGNAL_BATCH_CHUNK_SIZE=1, EARNINGS_SERVICE_RETRY_COUNT=0)
    @patch("api.views.urllib_request.urlopen")
    def test_fetch_earnings_signal_batch_chunk_partial_failure_stats(self, mocked_urlopen):
        def _side_effect(req, timeout):
            payload = json.loads(req.data.decode("utf-8"))
            ts_code = (payload.get("ts_codes") or [""])[0]
            if ts_code == "600519.SH":
                return self._build_batch_urlopen_response(
                    {
                        "ok": True,
                        "results": {
                            "600519.SH": {
                                "ts_code": "600519.SH",
                                "trade_date": "2026-04-05",
                                "financial_report_type": "Q1",
                                "feature_data_source": "quarterly",
                                "financial_fiscal_year": 2026,
                                "be_payload": {
                                    "signal_score": 66.0,
                                    "target_return_pct": 11.0,
                                    "action": "BUY",
                                    "risk_level": "LOW",
                                },
                                "valuation_mapping": {
                                    "stance": "BUY",
                                    "confidence": "HIGH",
                                },
                            }
                        },
                    }
                )
            raise URLError("simulated timeout")

        mocked_urlopen.side_effect = _side_effect

        result, stats = _fetch_earnings_signal_batch(
            ["600519.SH", "000001.SZ"],
            report_type="ALL",
            return_stats=True,
        )

        self.assertEqual((result.get("600519.SH") or {}).get("signal_score"), 66.0)
        self.assertIsNone((result.get("000001.SZ") or {}).get("signal_score"))
        self.assertEqual((result.get("000001.SZ") or {}).get("action"), "HOLD")
        self.assertEqual(stats.get("total_chunks"), 2)
        self.assertEqual(stats.get("successful_chunks"), 1)
        self.assertEqual(stats.get("failed_chunks"), 1)
        self.assertEqual(stats.get("failed_code_count"), 1)


class ValuationReportPeriodResolveTests(TestCase):
    @patch("api.views.query_local_financial_df")
    def test_resolve_annual_report_end_date_from_feature_panel(self, mocked_query):
        mocked_query.return_value = pd.DataFrame(
            [{"end_date": "20251231", "ann_date": "20260130"}]
        )

        resolved = _resolve_valuation_report_end_date_from_feature_panel(
            ts_code="300502.SZ",
            report_type="ANNUAL",
            asof_date=datetime.date(2026, 4, 16),
        )

        self.assertEqual(resolved, datetime.date(2025, 12, 31))
        sql = mocked_query.call_args.args[0]
        params = mocked_query.call_args.args[1]
        self.assertIn("report_type = %s", sql)
        self.assertEqual(params[:2], ["300502.SZ", "FY"])


class PredictivePickScoreTests(TestCase):
    def test_compute_predictive_pick_score_prefers_buy_low_risk_fusion(self):
        score = _compute_predictive_pick_score(
            {
                "signal_score": 60,
                "action": "BUY",
                "risk_level": "LOW",
                "target_return_pct": 20,
                "valuation_status": "under",
                "buy_candidate": True,
                "earnings_report_type": "FUSION",
            }
        )
        self.assertEqual(score, 97.0)

    def test_compute_predictive_pick_score_penalizes_sell_high_risk_overvalued(self):
        score = _compute_predictive_pick_score(
            {
                "signal_score": 45,
                "action": "SELL",
                "risk_level": "HIGH",
                "target_return_pct": -30,
                "valuation_status": "over",
                "buy_candidate": False,
                "earnings_report_type": "Q1",
            }
        )
        self.assertEqual(score, 9.0)


class ValuationNormalizationTests(TestCase):
    @patch("api.views.query_local_financial_df")
    def test_build_corporate_action_impact_payload_detects_dividend_dilution(self, mocked_query):
        mocked_query.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "300627.SZ",
                    "end_date": "20241231",
                    "ann_date": "20250418",
                    "record_date": "20250619",
                    "ex_date": "20250620",
                    "pay_date": "20250620",
                    "stk_div": 0.4,
                    "stk_bo_rate": 0.4,
                    "stk_co_rate": 0.0,
                    "cash_div_tax": 0.5,
                    "div_proc": "实施",
                }
            ]
        )

        payload = _build_corporate_action_impact_payload(
            ts_code="300627.SZ",
            current_trade_date=datetime.date(2026, 4, 10),
            current_total_share_shares=78_000_000,
            row={
                "latest_trade_date": datetime.date(2025, 4, 25),
                "valuation_price": 40.0,
                "valuation_market_cap": 2_160_000_000.0,
            },
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("impact_type"), "share_dilution_from_dividend")
        self.assertTrue(payload.get("impact_detected"))
        self.assertGreater(payload.get("share_change_ratio_pct") or 0.0, 10.0)
        self.assertEqual((payload.get("latest_dividend_event") or {}).get("ex_date"), datetime.date(2025, 6, 20))

    @patch("api.views._build_corporate_action_impact_payload")
    def test_enrich_rows_with_share_basis_adds_normalized_price(self, mocked_impact):
        mocked_impact.return_value = {"impact_detected": True}
        rows = [
            {
                "valuation_method": "sw_history",
                "valuation_price": 44.0,
                "valuation_market_cap": 2_200_000_000.0,
                "latest_trade_date": datetime.date(2025, 4, 25),
            }
        ]

        enriched = _enrich_rows_with_share_basis(
            ts_code="300627.SZ",
            current_trade_date=datetime.date(2026, 4, 10),
            current_total_share_shares=78_000_000,
            current_price=35.0,
            band_pct=0.1,
            rows=rows,
        )

        self.assertEqual(len(enriched), 1)
        row = enriched[0]
        self.assertEqual(row.get("valuation_price_normalized_to_latest_share"), round(2_200_000_000.0 / 78_000_000, 4))
        self.assertIn("valuation_status_normalized_to_latest_share", row)
        self.assertIn("valuation_gap_pct_normalized_to_latest_share", row)
        self.assertEqual((row.get("corporate_action_impact") or {}).get("impact_detected"), True)

    def test_build_valuation_summary_payload_can_use_normalized_price_key(self):
        rows = [
            {"valuation_method": "pe", "valuation_price": 12.0, "valuation_price_normalized_to_latest_share": 10.0},
            {"valuation_method": "pb", "valuation_price": 15.0, "valuation_price_normalized_to_latest_share": 11.0},
            {"valuation_method": "ps", "valuation_price": 14.0, "valuation_price_normalized_to_latest_share": 9.0},
        ]

        summary_raw = _build_valuation_summary_payload(10.0, rows, 0.1)
        summary_norm = _build_valuation_summary_payload(10.0, rows, 0.1, price_key="valuation_price_normalized_to_latest_share")

        self.assertIsNotNone(summary_raw.get("composite_valuation_price"))
        self.assertIsNotNone(summary_norm.get("composite_valuation_price"))
        self.assertNotEqual(summary_raw.get("composite_valuation_price"), summary_norm.get("composite_valuation_price"))
