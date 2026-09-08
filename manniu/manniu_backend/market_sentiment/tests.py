from datetime import date

from django.test import SimpleTestCase

from .services.engine import _level, _sigmoid_score, _standardize


class SentimentMathTests(SimpleTestCase):
    def test_market_score_requires_history_before_standardization(self):
        self.assertIsNone(_standardize(1.0, [0.5]))
        self.assertIsNotNone(_standardize(1.0, [0.5, 0.7, 0.9]))

    def test_sigmoid_and_levels_are_bounded(self):
        self.assertGreater(_sigmoid_score(-3), 0)
        self.assertLess(_sigmoid_score(3), 100)
        self.assertEqual(_level(None), '')
        self.assertEqual(_level(20), 'LOW')
        self.assertEqual(_level(50), 'MEDIUM')
        self.assertEqual(_level(80), 'HIGH')