from django.test import SimpleTestCase
from unittest.mock import patch

from valuation_api.management.commands.estmktv import Command


class EstmktvCommandRefactorTests(SimpleTestCase):
    def test_resolve_runtime_options_defaults(self):
        resolved = Command._resolve_runtime_options({})

        self.assertEqual(resolved["market"], "CN")
        self.assertFalse(resolved["show_source"])
        self.assertFalse(resolved["show_sw_levels"])
        self.assertFalse(resolved["show_citic_levels"])
        self.assertFalse(resolved["show_match_keywords"])
        self.assertFalse(resolved["show_profit_source"])
        self.assertTrue(resolved["strict_express_match"])
        self.assertEqual(resolved["express_max_age_days"], 180)
        self.assertIsNone(resolved["scarcity_profile"])

    def test_resolve_runtime_options_overrides(self):
        options = {
            "market": " us ",
            "show_source": True,
            "show_sw_levels": True,
            "show_citic_levels": True,
            "show_match_keywords": True,
            "show_profit_source": True,
            "no_strict_express_match": True,
            "express_max_age_days": 45,
            "scarcity_profile": "auto",
        }

        resolved = Command._resolve_runtime_options(options)

        self.assertEqual(resolved["market"], "US")
        self.assertTrue(resolved["show_source"])
        self.assertTrue(resolved["show_sw_levels"])
        self.assertTrue(resolved["show_citic_levels"])
        self.assertTrue(resolved["show_match_keywords"])
        self.assertTrue(resolved["show_profit_source"])
        self.assertFalse(resolved["strict_express_match"])
        self.assertEqual(resolved["express_max_age_days"], 45)
        self.assertEqual(resolved["scarcity_profile"], "auto")

    def test_resolve_requested_scenario_model_priority(self):
        options = {
            "scenario_model": "ddm",
            "est_method": "PB",
        }

        self.assertEqual(
            Command._resolve_requested_scenario_model(options, default_scenario_model="fcff_dcf"),
            "pb",
        )

        self.assertEqual(
            Command._resolve_requested_scenario_model({"scenario_model": "PEG"}, default_scenario_model="fcff_dcf"),
            "peg",
        )

        self.assertEqual(
            Command._resolve_requested_scenario_model({}, default_scenario_model="fcff_dcf"),
            "fcff_dcf",
        )

    def test_handle_business_match_mode_delegates_to_service(self):
        command = Command()
        options = {"market": "CN"}

        with patch("valuation_api.management.commands.estmktv.handle_business_match_mode") as mocked:
            mocked.return_value = None
            command._handle_business_match_mode(
                ts_code="600036.SH",
                trade_date="2026-03-25",
                freq="D",
                scenario_model="fcff_dcf",
                options=options,
            )

            mocked.assert_called_once_with(
                command=command,
                ts_code="600036.SH",
                trade_date="2026-03-25",
                freq="D",
                scenario_model="fcff_dcf",
                options=options,
            )
