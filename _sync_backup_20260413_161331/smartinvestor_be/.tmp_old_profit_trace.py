import os, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()
from prediction.utils.prediction_util import get_stock_valuation_snapshot
s = get_stock_valuation_snapshot('688002.SH', trade_date='2026-03-20')
keys = ['trade_date','end_date','close_price','total_share','market_cap','netprofit','revenue','equity_book_value','profit_data_source','express_end_date','express_ann_date','express_apply_reason','express_block_reason','peg_growth_yoy_pct']
print(json.dumps({k:s.get(k) for k in keys}, ensure_ascii=False, indent=2, default=str))
