from django.conf import settings
from django.apps import apps
from django.test import SimpleTestCase


DOMAIN_APPS = (
	'traditional_valuation',
	'predictive_valuation',
	'stock_selection',
	'backtest_engine',
	'financials',
	'market_data',
	'indices',
)


class DatabaseConfigurationTests(SimpleTestCase):
	def test_uses_postgresql(self):
		self.assertEqual(settings.DATABASES['default']['ENGINE'], 'django.db.backends.postgresql')


class DomainApplicationRegistrationTests(SimpleTestCase):
	def test_domain_apps_are_registered_with_matching_names(self):
		for app_name in DOMAIN_APPS:
			with self.subTest(app_name=app_name):
				self.assertIn(app_name, settings.INSTALLED_APPS)
				self.assertEqual(apps.get_app_config(app_name).name, app_name)
