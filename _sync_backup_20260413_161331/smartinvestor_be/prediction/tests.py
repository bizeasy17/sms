import tempfile
from datetime import date, timedelta

import pandas as pd
from django.test import TestCase, override_settings

from prediction.management.commands.estmktv import Command


class EstMktvAutoRiskEngineTests(TestCase):
	def test_derive_auto_risk_indicators_from_df(self):
		start_day = date(2026, 1, 1)
		rows = []
		close_val = 100.0
		for idx in range(160):
			if idx < 120:
				ret = 0.002 if idx % 2 == 0 else -0.0015
			else:
				ret = -0.015 if idx % 3 == 0 else 0.008
			close_val = close_val * (1.0 + ret)
			rows.append(
				{
					"trade_date": start_day + timedelta(days=idx),
					"close_qfq": round(close_val, 4),
					"close": round(close_val, 4),
					"pct_change_qfq": round(ret * 100.0, 4),
					"pct_change": round(ret * 100.0, 4),
				}
			)

		indicators = Command._derive_auto_risk_indicators_from_df(
			trading_df=pd.DataFrame(rows),
			run_day=start_day + timedelta(days=160),
		)

		self.assertIn("vol_z", indicators)
		self.assertIn("risk_disp", indicators)
		self.assertIn("data_gap", indicators)
		self.assertIn("dd_z", indicators)
		for key in ["vol_z", "risk_disp", "data_gap", "dd_z"]:
			value = indicators.get(key)
			self.assertIsNotNone(value, msg=f"{key} should be computed")
			self.assertGreaterEqual(value, 0.0)
			self.assertLessEqual(value, 1.0)

	def test_auto_state_confirmation_and_cooldown(self):
		cfg = {
			"risk_weights": {"vol_z": 0.25, "risk_disp": 0.25, "data_gap": 0.25, "dd_z": 0.25},
			"thresholds": {"conservative_min": 0.6, "balanced_min": 0.3},
			"hysteresis": {"up_shift": 0.0, "down_shift": 0.0},
			"confirmation_days": 3,
			"cooldown_days": 5,
			"missing_policy": {"min_available_indicators": 4, "fallback_profile": "balanced"},
			"circuit_breaker": {
				"enabled": False,
				"extreme_risk_min": 0.95,
				"force_profile": "conservative",
				"force_days": 2,
				"extreme_flags": ["extreme_market"],
			},
			"legacy_signal_weights": {"score": 1.0, "confidence": 1.0},
			"fallback_profile": "balanced",
		}
		low_risk = {"enabled": True, "vol_z": 0.1, "risk_disp": 0.1, "data_gap": 0.1, "dd_z": 0.1}
		high_risk = {"enabled": True, "vol_z": 0.9, "risk_disp": 0.8, "data_gap": 0.7, "dd_z": 0.9}

		with tempfile.TemporaryDirectory() as tmp_dir:
			with override_settings(BASE_DIR=tmp_dir):
				p1, r1 = Command._resolve_auto_scarcity_profile(
					scarcity_kwargs=low_risk,
					auto_profile_cfg=cfg,
					tscode="000001.SZ",
					market="CN",
					run_date="2026-03-01",
				)
				self.assertEqual(p1, "aggressive")
				self.assertIn("cold_start", r1)

				p2, r2 = Command._resolve_auto_scarcity_profile(
					scarcity_kwargs=high_risk,
					auto_profile_cfg=cfg,
					tscode="000001.SZ",
					market="CN",
					run_date="2026-03-02",
				)
				self.assertEqual(p2, "aggressive")
				self.assertIn("pending_confirm", r2)

				p3, r3 = Command._resolve_auto_scarcity_profile(
					scarcity_kwargs=high_risk,
					auto_profile_cfg=cfg,
					tscode="000001.SZ",
					market="CN",
					run_date="2026-03-03",
				)
				self.assertEqual(p3, "aggressive")
				self.assertIn("pending_confirm", r3)

				p4, r4 = Command._resolve_auto_scarcity_profile(
					scarcity_kwargs=high_risk,
					auto_profile_cfg=cfg,
					tscode="000001.SZ",
					market="CN",
					run_date="2026-03-04",
				)
				self.assertEqual(p4, "conservative")
				self.assertIn("confirmed_switch", r4)

				p5, r5 = Command._resolve_auto_scarcity_profile(
					scarcity_kwargs=low_risk,
					auto_profile_cfg=cfg,
					tscode="000001.SZ",
					market="CN",
					run_date="2026-03-05",
				)
				self.assertEqual(p5, "conservative")
				self.assertIn("cooldown_hold", r5)

	def test_auto_state_circuit_breaker_window(self):
		cfg = {
			"risk_weights": {"vol_z": 0.25, "risk_disp": 0.25, "data_gap": 0.25, "dd_z": 0.25},
			"thresholds": {"conservative_min": 0.6, "balanced_min": 0.3},
			"hysteresis": {"up_shift": 0.0, "down_shift": 0.0},
			"confirmation_days": 3,
			"cooldown_days": 5,
			"missing_policy": {"min_available_indicators": 4, "fallback_profile": "balanced"},
			"circuit_breaker": {
				"enabled": True,
				"extreme_risk_min": 0.9,
				"force_profile": "conservative",
				"force_days": 2,
				"extreme_flags": ["extreme_market"],
			},
			"legacy_signal_weights": {"score": 1.0, "confidence": 1.0},
			"fallback_profile": "balanced",
		}
		extreme_risk = {"enabled": True, "vol_z": 0.95, "risk_disp": 0.95, "data_gap": 0.95, "dd_z": 0.95}
		low_risk = {"enabled": True, "vol_z": 0.1, "risk_disp": 0.1, "data_gap": 0.1, "dd_z": 0.1}

		with tempfile.TemporaryDirectory() as tmp_dir:
			with override_settings(BASE_DIR=tmp_dir):
				p1, r1 = Command._resolve_auto_scarcity_profile(
					scarcity_kwargs=extreme_risk,
					auto_profile_cfg=cfg,
					tscode="000002.SZ",
					market="CN",
					run_date="2026-03-10",
				)
				self.assertEqual(p1, "conservative")
				self.assertIn("circuit_breaker_triggered", r1)

				p2, r2 = Command._resolve_auto_scarcity_profile(
					scarcity_kwargs=low_risk,
					auto_profile_cfg=cfg,
					tscode="000002.SZ",
					market="CN",
					run_date="2026-03-11",
				)
				self.assertEqual(p2, "conservative")
				self.assertIn("circuit_breaker_window", r2)
