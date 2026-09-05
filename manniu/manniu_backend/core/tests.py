from django.conf import settings
from django.test import SimpleTestCase


class DatabaseConfigurationTests(SimpleTestCase):
	def test_uses_postgresql(self):
		self.assertEqual(settings.DATABASES['default']['ENGINE'], 'django.db.backends.postgresql')
