import os, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "valuation_service.settings")
import django
django.setup()
from valuation_api.live_valuation import get_local_valuation_snapshot
s = get_local_valuation_snapshot('688002.SH', trade_date='2026-03-20', freq='D')
keys = ['trade_date','close_price','total_share','market_cap','pe_ttm','pb','ps_ttm','netprofit','revenue','equity_book_value','fcff_per_share']
print(json.dumps({k:s.get(k) for k in keys}, ensure_ascii=False, indent=2, default=str))
