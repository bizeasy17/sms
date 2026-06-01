import os
import datetime
import pandas as pd
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate
from valuation.services.valuation_summary import summarize_buy_candidate

ts='600036.SH'
d=datetime.date(2026,5,14)
mm=_build_latest_snapshot_method_map(ts_codes=[ts], market='CN', pick_strategy='latest_trade_then_updated', max_trade_date=d).get(ts,{}) or {}
px=36.84
s=_summarize_buy_candidate(px, mm, 0.1)
print('buy',s.get('buy_candidate'),'score',s.get('undervalue_score'))
print(s.get('buy_candidate_reason'))
print('methods:',sorted((k,round((v or {}).get('valuation_price',0),4)) for k,v in mm.items() if (v or {}).get('valuation_price')))
