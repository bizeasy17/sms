from django.test import SimpleTestCase

from .services.buy_candidate_summary import summarize_buy_candidate


class BuyCandidateSummaryTests(SimpleTestCase):
	def test_returns_unavailable_without_valid_methods(self):
		summary = summarize_buy_candidate(10, {"pe": {"valuation_price": None}})

		self.assertFalse(summary["buy_candidate"])
		self.assertEqual(summary["buy_candidate_reason"], "no_valid_valuation_methods")
		self.assertEqual(summary["valuation_valid_methods"], [])

	def test_requires_two_core_methods(self):
		summary = summarize_buy_candidate(
			10,
			{
				"pe": {"valuation_price": 14},
				"ddm": {"valuation_price": 15},
			},
		)

		self.assertFalse(summary["buy_candidate"])
		self.assertEqual(summary["valuation_core_methods"], ["pe"])

	def test_marks_discounted_core_consensus_as_buy_candidate(self):
		summary = summarize_buy_candidate(
			10,
			{
				"pe": {"valuation_price": 14},
				"pb": {"valuation_price": 13},
				"ps": {"valuation_price": 12},
			},
		)

		self.assertTrue(summary["buy_candidate"])
		self.assertEqual(summary["valuation_core_methods"], ["pe", "pb", "ps"])
		self.assertEqual(summary["valuation_under_methods"], ["pb", "pe", "ps"])
