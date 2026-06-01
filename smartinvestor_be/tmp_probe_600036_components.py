import os, datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()
from datastore.models import StockTradingHistory
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate
import valuation.services.valuation_summary as vs

ts='600036.SH'; d=datetime.date(2026,5,14)
row=StockTradingHistory.objects.filter(ts_code=ts,freq='D',trade_date=d).values('close').first()
px=float(row['close'])
mm=_build_latest_snapshot_method_map(ts_codes=[ts], market='CN', pick_strategy='latest_trade_then_updated', max_trade_date=d).get(ts,{}) or {}
valid={m:float((p or {}).get('valuation_price')) for m,p in mm.items() if (p or {}).get('valuation_price') not in (None,0)}
f,e=vs._filter_core_method_prices(valid,px)
w=vs._compute_core_method_soft_weights(valid,px)
eff=vs._build_effective_core_methods(valid,f,w)
print('px',px)
print('filtered',f)
print('excluded',e)
print('weights',w)
print('eff',eff)
core_prices=[eff[m] for m in vs.BUY_CANDIDATE_CORE_METHODS if m in eff]
raw=[valid[m] for m in vs.BUY_CANDIDATE_CORE_METHODS if m in valid]
print('core_prices',core_prices,'raw',raw)
print('conservative from new',min(core_prices or raw))
print('new',_summarize_buy_candidate(px,mm,0.1)['buy_candidate_reason'])
