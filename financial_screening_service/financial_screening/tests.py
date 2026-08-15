from django.test import SimpleTestCase

from financial_screening.services import _growth_pct, _previous_quarter_report_type, _standalone


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