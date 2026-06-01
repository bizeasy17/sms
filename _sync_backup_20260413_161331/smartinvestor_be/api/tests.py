import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.core.cache import cache
from django.test import TestCase, override_settings

from api.views import _compute_predictive_pick_score, _fetch_earnings_signal_batch


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
