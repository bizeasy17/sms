from django.test import SimpleTestCase
from unittest.mock import patch

from financial_screening.services import (
    ScreenRequest,
    _growth_pct,
    _previous_quarter_report_type,
    _standalone,
    screen_financial_performance,
)


class FinancialMetricCalculationTests(SimpleTestCase):
    def test_growth_uses_absolute_prior_base_and_marks_turnaround(self):
        value, turnaround = _growth_pct(20, -10)
        self.assertEqual(value, 300.0)
        self.assertTrue(turnaround)

    def test_growth_returns_none_for_zero_or_missing_base(self):
        self.assertEqual(_growth_pct(10, 0), (None, False))
        self.assertEqual(_growth_pct(10, None), (None, False))

    def test_h1_standalone_value_subtracts_q1(self):
        self.assertEqual(_standalone(150, 50, "H1"), 100)

    def test_q1_standalone_value_is_not_subtracted(self):
        self.assertEqual(_standalone(50, 10, "Q1"), 50)

    def test_h1_qoq_compares_h1_second_quarter_with_q1(self):
        self.assertEqual(_previous_quarter_report_type("H1"), "Q1")
        self.assertEqual(_standalone(50, 900, _previous_quarter_report_type("H1")), 50)

    @patch("financial_screening.services._fetch_rows", return_value={})
    def test_screen_returns_empty_when_candidates_have_no_current_report(self, _fetch_rows):
        request = ScreenRequest(
            candidate_codes=["600975.SH"],
            fiscal_year=2026,
            report_type="H1",
            filters={"require_all_metrics": True},
            sort_by="predictive_signal_score",
            sort_order="desc",
        )

        self.assertEqual(screen_financial_performance(request), [])