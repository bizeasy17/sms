from datetime import date, timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase

from .constants import INDEX_BY_KEY, STYLE_WEIGHTS
from .normalization import common_date_values, normalize_series
from .quantile import summarize_series
from .services import IndexService
from .valuation import calculate_method


class IndexCalculationTests(SimpleTestCase):
	def test_style_weights_cover_universe(self):
		for weights in STYLE_WEIGHTS.values():
			self.assertEqual(set(weights), set(INDEX_BY_KEY))
			self.assertEqual(sum(weights.values()), 1)

	def test_common_dates_do_not_treat_missing_index_as_zero(self):
		first = date(2026, 1, 1)
		series = {key: {first: 1.0, first + timedelta(days=1): 2.0} for key in INDEX_BY_KEY}
		del series['cyb'][first + timedelta(days=1)]

		result = common_date_values(series, INDEX_BY_KEY)

		self.assertEqual(list(result), [first])

	def test_quantile_uses_linear_interpolation(self):
		first = date(2026, 1, 1)
		result = summarize_series({first: 1, first + timedelta(days=1): 3}, min_samples=1)

		self.assertEqual(result['p50'], 2.0)
		self.assertEqual(result['status'], 'VALID')

	def test_simple_method_uses_current_price_and_current_metric_separately(self):
		result = calculate_method('pe', 100, 20, 10, 20, min_samples=20)

		self.assertEqual(result['implied'], 50.0)
		self.assertEqual(result['status'], 'OVERVALUED')


class FakeIndexRepository:
	def __init__(self, with_latest_bar=True):
		self.security = SimpleNamespace(ts_code='000001.SH')
		self.with_latest_bar = with_latest_bar
		first = date(2026, 1, 1)
		self.rows = [
			{
				'trade_date': first + timedelta(days=offset),
				'pe': 10 + offset,
				'pe_ttm': 11 + offset,
				'pb': 1 + offset / 10,
			}
			for offset in range(20)
		]

	def resolve_security(self, _index_code):
		return self.security, '000001.SH'

	def index_fundamentals(self, _security, start_date=None, end_date=None):
		return self.rows

	def latest_fundamental(self, _security):
		row = self.rows[-1]
		return SimpleNamespace(**row)

	def latest_bar(self, _security):
		if not self.with_latest_bar:
			return None
		return SimpleNamespace(trade_date=self.rows[-1]['trade_date'], close=100)

	def index_bars(self, _security, start_date=None, end_date=None):
		return [{'trade_date': row['trade_date'], 'close': 100 + index} for index, row in enumerate(self.rows)]


class IndexServiceTests(SimpleTestCase):
	def test_composite_quantile_accepts_close_metric(self):
		result = IndexService(FakeIndexRepository()).composite_quantile(metric='CLOSE', min_samples=1)

		self.assertEqual(result.data['summary']['current'], 119.0)
		self.assertEqual(result.data['close'], 119.0)

	def test_composite_quantile_returns_weighted_close_on_latest_common_date(self):
		result = IndexService(FakeIndexRepository()).composite_quantile(min_samples=1)

		self.assertEqual(result.data['close'], 119.0)

	def test_composite_quantile_reports_missing_index(self):
		repository = FakeIndexRepository()
		service = IndexService(repository)
		original = repository.resolve_security

		def missing_cyb(index_code):
			if index_code == 'cyb':
				return None, '399006.SZ'
			return original(index_code)

		repository.resolve_security = missing_cyb
		result = service.composite_quantile(min_samples=1)

		self.assertEqual(result.status, 'NO_DATA')
		self.assertIn('cyb', result.coverage.missing_indices)

	def test_simple_valuation_falls_back_to_historical_close(self):
		result = IndexService(FakeIndexRepository(with_latest_bar=False)).simple_valuation('000001.SH', min_samples=1)

		self.assertEqual(result.data['current_index_price'], 119.0)
		self.assertEqual(result.status, 'VALID')
