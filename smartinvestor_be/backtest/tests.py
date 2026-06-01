import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from backtest.models import TraditionalBacktestRun


class TraditionalBacktestApiTests(TestCase):
    def setUp(self):
        self.base_dir = Path(settings.BASE_DIR) / "output" / "backtests" / "traditional_value_exit"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.sample_path = self.base_dir / "traditional_value_exit_2024-01-01_2025-12-31.json"
        self.sample_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "strategy": "traditional_value_exit_account",
                    },
                    "strategy": {
                        "mode": "account",
                        "max_holding_days": 17,
                        "starting_capital": 300000,
                        "buy_weight_ladder": [0.2, 0.15, 0.1],
                    },
                    "combined": {
                        "trade_count": 8,
                        "avg_return_pct": 6.2,
                        "win_rate_pct": 62.5,
                    },
                    "by_year": {
                        "2024": {"trade_count": 4},
                        "2025": {"trade_count": 4},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.run = TraditionalBacktestRun.objects.create(
            run_key="traditional_value_exit_2024-01-01_2025-12-31",
            batch_key="traditional_value_exit",
            strategy_name="traditional_value_exit",
            status="success",
            scope="ALL",
            market="CN",
            summary_json={
                "trade_count": 8,
                "avg_return_pct": 6.2,
                "win_rate_pct": 62.5,
            },
            params_json={
                "mode": "account",
                "starting_capital": 300000,
            },
            result_json={
                "combined": {
                    "trade_count": 8,
                }
            },
            result_file="output/backtests/traditional_value_exit/traditional_value_exit_2024-01-01_2025-12-31.json",
        )

    def tearDown(self):
        if self.sample_path.exists():
            self.sample_path.unlink()

    def test_list_traditional_backtest_runs(self):
        response = self.client.get("/api/backtest/traditional/runs/?limit=10")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(isinstance(body.get("data"), list))
        self.assertGreaterEqual(len(body.get("data", [])), 1)
        first_row = body.get("data", [])[0]
        self.assertEqual(first_row.get("params", {}).get("max_holding_days"), 17)
        self.assertEqual(first_row.get("params", {}).get("buy_weight_ladder"), [0.2, 0.15, 0.1])

    def test_get_traditional_backtest_run_detail(self):
        run_id = self.run.id

        detail_resp = self.client.get(f"/api/backtest/traditional/runs/{run_id}/")
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertTrue(detail.get("ok"))
        self.assertIn("result", detail)
        self.assertEqual(detail.get("run_id"), run_id)
        self.assertEqual(detail.get("params", {}).get("max_holding_days"), 17)
        self.assertEqual(detail.get("params", {}).get("starting_capital"), 300000)
        self.assertEqual(detail.get("params", {}).get("buy_weight_ladder"), [0.2, 0.15, 0.1])

    def test_list_traditional_templates(self):
        response = self.client.get("/api/backtest/traditional/templates/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(isinstance(body.get("data"), list))
        self.assertGreaterEqual(len(body.get("data", [])), 1)

    @patch("backtest.views._SCAN_EXECUTOR.submit")
    def test_submit_traditional_scan_task(self, mock_submit):
        response = self.client.post(
            "/api/backtest/traditional/scan/submit/",
            data={
                "template_id": "baseline",
                "base_params": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                },
                "scan_grid": {
                    "min_score": [88, 90],
                },
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("ok"))
        self.assertIn("task_id", body)
        self.assertEqual(body.get("total_jobs"), 2)
        self.assertTrue(mock_submit.called)
