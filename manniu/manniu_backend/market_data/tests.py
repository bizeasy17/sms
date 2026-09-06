from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .models import (
	City,
	IndexDailyFundamentalHistory,
	IndexDailyFundamentalLatest,
	MarketBarDailyHistory,
	MarketBarLatest,
	ProvinceRegionMapping,
	Security,
	StockCostDistributionHistory,
	StockCostDistributionLatest,
	StockDailyFundamentalHistory,
	StockDailyFundamentalLatest,
)


class MarketDataSchemaTests(SimpleTestCase):
	def test_security_code_rejects_values_longer_than_sixteen_characters(self):
		security = Security(ts_code='X' * 17, asset_type=Security.AssetType.STOCK)

		with self.assertRaises(ValidationError):
			security.full_clean()

	def test_city_is_unique_within_its_province(self):
		constraint = City._meta.constraints[0]

		self.assertEqual(constraint.fields, ('province', 'name'))

	def test_region_mapping_is_versioned_by_effective_date(self):
		constraint = ProvinceRegionMapping._meta.constraints[0]

		self.assertEqual(constraint.fields, ('province', 'mapping_version', 'effective_from'))

	def test_daily_history_uses_date_bound_security_index_and_unique_key(self):
		constraint = MarketBarDailyHistory._meta.constraints[0]
		index_fields = [index.fields for index in MarketBarDailyHistory._meta.indexes]

		self.assertEqual(constraint.fields, ('security', 'trade_date'))
		self.assertIn(['security', '-trade_date'], index_fields)

	def test_latest_bar_has_one_row_per_security_and_frequency(self):
		constraint = MarketBarLatest._meta.constraints[0]

		self.assertEqual(constraint.fields, ('security', 'frequency'))
		self.assertEqual(MarketBarLatest._meta.get_field('trade_date').get_default(), None)

	def test_stock_fundamental_history_and_latest_use_approved_keys(self):
		constraint = StockDailyFundamentalHistory._meta.constraints[0]

		self.assertEqual(constraint.fields, ('security', 'trade_date'))
		self.assertTrue(StockDailyFundamentalLatest._meta.get_field('security').unique)

	def test_stock_fundamental_preserves_tushare_raw_units_and_precision(self):
		self.assertEqual(StockDailyFundamentalHistory._meta.get_field('total_share').max_digits, 22)
		self.assertEqual(StockDailyFundamentalHistory._meta.get_field('total_mv').max_digits, 24)
		self.assertEqual(StockDailyFundamentalHistory._meta.get_field('pe_ttm').decimal_places, 6)

	def test_cost_history_and_latest_use_approved_keys(self):
		constraint = StockCostDistributionHistory._meta.constraints[0]

		self.assertEqual(constraint.fields, ('security', 'trade_date'))
		self.assertTrue(StockCostDistributionLatest._meta.get_field('security').unique)
		self.assertEqual(StockCostDistributionHistory._meta.get_field('winner_rate').max_digits, 12)

	def test_index_fundamental_history_and_latest_include_all_metrics(self):
		constraint = IndexDailyFundamentalHistory._meta.constraints[0]
		fields = {field.name for field in IndexDailyFundamentalHistory._meta.fields}

		self.assertEqual(constraint.fields, ('security', 'trade_date'))
		self.assertTrue(IndexDailyFundamentalLatest._meta.get_field('security').unique)
		self.assertTrue(
			{'pe', 'pe_ttm', 'pb', 'turnover_rate', 'turnover_rate_f', 'total_mv', 'float_mv'}
			<= fields
		)
