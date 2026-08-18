import datetime
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase

from earnings_forecast.management.commands.export_updated_financial_codes import (
	_collect_remote_dividend_codes,
)
from earnings_forecast.services.backtest import _simulate_year
from earnings_forecast.services.stock_regime import classify_stock_regime, next_regime_state


class StockRegimeTests(SimpleTestCase):
	def test_growth_regime_requires_strength_above_moving_averages(self):
		metrics = classify_stock_regime(range(1, 81))
		self.assertIsNotNone(metrics)
		self.assertEqual(metrics.regime, "GROWTH")

	def test_regime_switch_requires_two_confirmations(self):
		first = next_regime_state("GROWTH", "", 0, "DEFENSIVE", 2)
		self.assertEqual(first, ("GROWTH", "DEFENSIVE", 1, False))
		second = next_regime_state("GROWTH", "DEFENSIVE", 1, "DEFENSIVE", 2)
		self.assertEqual(second, ("DEFENSIVE", "", 0, True))

	def test_current_regime_resets_pending_switch(self):
		self.assertEqual(
			next_regime_state("BALANCE", "DEFENSIVE", 1, "BALANCE", 2),
			("BALANCE", "", 0, False),
		)


class ExportUpdatedFinancialCodesTests(SimpleTestCase):
	@patch("earnings_forecast.management.commands.export_updated_financial_codes.timezone.now")
	@patch("earnings_forecast.management.commands.export_updated_financial_codes.os.getenv")
	def test_collect_remote_dividend_codes_respects_scope_prefix(self, mocked_getenv, mocked_now):
		mocked_getenv.side_effect = lambda key: "dummy-token" if key in ("TUSHARE_TOKEN", "TUSHARE_PRO_TOKEN") else None
		mocked_now.return_value = datetime.datetime(2026, 4, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)

		class FakePro:
			def dividend(self, **kwargs):
				return pd.DataFrame(
					[
						{"ts_code": "300627.SZ"},
						{"ts_code": "600519.SH"},
					]
				)

		fake_ts = SimpleNamespace(
			set_token=lambda _token: None,
			pro_api=lambda: FakePro(),
		)

		with patch.dict(sys.modules, {"tushare": fake_ts}):
			codes = _collect_remote_dividend_codes(
				changed_since=datetime.datetime(2026, 4, 11, 0, 0, 0, tzinfo=datetime.timezone.utc),
				prefixes=["30"],
			)

		self.assertEqual(codes, {"300627.SZ"})


class PredictiveBacktestSellStrategyTests(SimpleTestCase):
	def _make_snapshot(self, *, ts_code="300627.SZ", asof_date=datetime.date(2024, 1, 2), score=95.0, risk_level="LOW"):
		return SimpleNamespace(
			ts_code=ts_code,
			asof_date=asof_date,
			report_type="Q3",
			action="BUY",
			risk_level=risk_level,
			signal_score=score,
			target_return_pct=20.0,
			target_price=12.0,
			target_market_cap=1200.0,
			model_version="test-model",
			financial_end_date="2023-09-30",
			financial_ann_date="2023-10-31",
			raw_result={
				"financial_end_date": "2023-09-30",
				"financial_ann_date": "2023-10-31",
				"pred_earnings_growth": 18.0,
				"quantitative_target": {
					"target_price_low": 10.0,
					"target_price": 12.0,
					"target_price_high": 12.5,
				},
			},
		)

	def test_simulate_year_exits_on_optimistic_price(self):
		snapshot = self._make_snapshot()
		market_dates = [
			datetime.date(2024, 1, 2),
			datetime.date(2024, 1, 3),
			datetime.date(2024, 1, 4),
		]
		price_map = {
			"300627.SZ": {
				datetime.date(2024, 1, 2): 9.5,
				datetime.date(2024, 1, 3): 11.0,
				datetime.date(2024, 1, 4): 12.6,
			}
		}
		_, _, _, trades = _simulate_year(
			year=2024,
			market_dates=market_dates,
			ts_codes=["300627.SZ"],
			by_date_code={(datetime.date(2024, 1, 2), "300627.SZ"): [snapshot]},
			price_map=price_map,
			min_score=90.0,
			max_risk="MEDIUM",
			stop_mode="none",
			single_stop_dd=0.1,
			sell_strategy="optimistic_price",
			take_profit_pct=0.0,
			stop_loss_pct=0.0,
			max_holding_days=0,
		)

		self.assertEqual(len(trades), 1)
		self.assertEqual(trades[0]["exit_reason"], "optimistic_price_hit")
		self.assertEqual(trades[0]["exit_date"], "2024-01-04")

	def test_simulate_year_exits_on_take_profit_pct(self):
		snapshot = self._make_snapshot()
		market_dates = [
			datetime.date(2024, 1, 2),
			datetime.date(2024, 1, 3),
			datetime.date(2024, 1, 4),
		]
		price_map = {
			"300627.SZ": {
				datetime.date(2024, 1, 2): 9.5,
				datetime.date(2024, 1, 3): 10.6,
				datetime.date(2024, 1, 4): 10.7,
			}
		}
		_, _, _, trades = _simulate_year(
			year=2024,
			market_dates=market_dates,
			ts_codes=["300627.SZ"],
			by_date_code={(datetime.date(2024, 1, 2), "300627.SZ"): [snapshot]},
			price_map=price_map,
			min_score=90.0,
			max_risk="MEDIUM",
			stop_mode="none",
			single_stop_dd=0.1,
			sell_strategy="take_profit_pct",
			take_profit_pct=0.1,
			stop_loss_pct=0.0,
			max_holding_days=0,
		)

		self.assertEqual(len(trades), 1)
		self.assertEqual(trades[0]["exit_reason"], "take_profit_pct_hit")
		self.assertEqual(trades[0]["exit_date"], "2024-01-03")

	def test_simulate_year_exits_on_stop_loss_pct(self):
		snapshot = self._make_snapshot()
		market_dates = [
			datetime.date(2024, 1, 2),
			datetime.date(2024, 1, 3),
			datetime.date(2024, 1, 4),
		]
		price_map = {
			"300627.SZ": {
				datetime.date(2024, 1, 2): 9.5,
				datetime.date(2024, 1, 3): 8.8,
				datetime.date(2024, 1, 4): 8.7,
			}
		}
		_, _, _, trades = _simulate_year(
			year=2024,
			market_dates=market_dates,
			ts_codes=["300627.SZ"],
			by_date_code={(datetime.date(2024, 1, 2), "300627.SZ"): [snapshot]},
			price_map=price_map,
			min_score=90.0,
			max_risk="MEDIUM",
			stop_mode="none",
			single_stop_dd=0.1,
			sell_strategy="optimistic_or_take_profit",
			take_profit_pct=0.0,
			stop_loss_pct=0.05,
			max_holding_days=0,
		)

		self.assertEqual(len(trades), 1)
		self.assertEqual(trades[0]["exit_reason"], "stop_loss_pct_hit")
		self.assertEqual(trades[0]["exit_date"], "2024-01-03")
