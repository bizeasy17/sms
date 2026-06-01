import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartinvestor_be.settings')
import django
django.setup()

from rest_framework.test import APIRequestFactory
from api.views import get_industry_universe_list

factory = APIRequestFactory()
req = factory.get('/api/industry-universe/list/', {'industry_type': 'sw'})
resp = get_industry_universe_list(req)
print('status', resp.status_code)
print(resp.data)
