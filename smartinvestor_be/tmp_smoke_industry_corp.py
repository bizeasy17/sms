import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartinvestor_be.settings')
import django
django.setup()

from rest_framework.test import APIRequestFactory
from api.views import get_industry_universe_list, get_industry_universe_history, get_industry_universe_constituents

factory = APIRequestFactory()
req = factory.get('/api/industry-universe/list/', {'industry_type': 'corp_industry'})
resp = get_industry_universe_list(req)
rows = (resp.data or {}).get('data') or []
print('corp list status', resp.status_code, 'count', len(rows))
first_key = rows[0]['industry_key'] if rows else ''
print('first corp key', first_key)
if first_key:
    req = factory.get('/api/industry-universe/history/', {'industry_type': 'corp_industry', 'industry_key': first_key, 'metric': 'pb', 'period': '1Y'})
    resp = get_industry_universe_history(req)
    print('corp history status', resp.status_code, 'rows', len((resp.data or {}).get('data') or []))
    req = factory.get('/api/industry-universe/constituents/', {'industry_type': 'corp_industry', 'industry_key': first_key, 'from_index': 0, 'to_index': 5})
    resp = get_industry_universe_constituents(req)
    print('corp constituents status', resp.status_code, 'rows', len((resp.data or {}).get('data') or []))
