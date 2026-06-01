import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartinvestor_be.settings')
import django
django.setup()

from rest_framework.test import APIRequestFactory
from api.views import (
    get_industry_universe_types,
    get_industry_universe_list,
    get_industry_universe_history,
    get_industry_universe_constituents,
)

factory = APIRequestFactory()

req = factory.get('/api/industry-universe/types/')
resp = get_industry_universe_types(req)
print('types status', resp.status_code, 'count', len((resp.data or {}).get('data') or []))

req = factory.get('/api/industry-universe/list/', {'industry_type': 'sw'})
resp = get_industry_universe_list(req)
rows = (resp.data or {}).get('data') or []
print('list sw status', resp.status_code, 'count', len(rows))
first_sw = rows[0]['industry_key'] if rows else ''
print('first_sw', first_sw)

if first_sw:
    req = factory.get('/api/industry-universe/history/', {'industry_type': 'sw', 'industry_key': first_sw, 'metric': 'pe', 'period': '1Y'})
    resp = get_industry_universe_history(req)
    print('history sw status', resp.status_code, 'rows', len((resp.data or {}).get('data') or []))

    req = factory.get('/api/industry-universe/constituents/', {'industry_type': 'sw', 'industry_key': first_sw, 'from_index': 0, 'to_index': 10})
    resp = get_industry_universe_constituents(req)
    print('constituents sw status', resp.status_code, 'rows', len((resp.data or {}).get('data') or []))

req = factory.get('/api/industry-universe/list/', {'industry_type': 'valuation_variant'})
resp = get_industry_universe_list(req)
rows = (resp.data or {}).get('data') or []
print('list variant status', resp.status_code, 'count', len(rows))
first_variant = rows[0]['industry_key'] if rows else ''
print('first_variant', first_variant)

if first_variant:
    req = factory.get('/api/industry-universe/history/', {'industry_type': 'valuation_variant', 'industry_key': first_variant, 'metric': 'pe', 'period': '1Y'})
    resp = get_industry_universe_history(req)
    print('history variant status', resp.status_code, 'rows', len((resp.data or {}).get('data') or []))

