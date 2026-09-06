from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .models import City, MarketBarDailyHistory, MarketBarLatest, ProvinceRegionMapping, Security


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
