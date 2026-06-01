import os, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()
from prediction.utils.prediction_util import get_stock_valuation_snapshot
s = get_stock_valuation_snapshot('688002.SH', trade_date='2026-03-20')
keys = ['trade_date','close_price','total_share','market_cap','pe_ttm','pb','ps_ttm','netprofit','revenue','equity_book_value']
print(json.dumps({k:s.get(k) for k in keys}, ensure_ascii=False, indent=2, default=str))
