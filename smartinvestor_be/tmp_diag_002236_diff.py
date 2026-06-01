import os
import datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from datastore.models import StockTradingHistory
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate
from valuation.services.valuation_summary import BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER

TS = "002236.SZ"
for day in (datetime.date(2026,5,28), datetime.date(2026,5,29)):
    px = float(StockTradingHistory.objects.filter(ts_code=TS, freq='D', trade_date=day).values_list('close', flat=True).first())
    mm = _build_latest_snapshot_method_map(ts_codes=[TS], market='CN', pick_strategy='latest_trade_then_updated', max_trade_date=day).get(TS,{}) or {}
    core = {m: (mm.get(m) or {}).get('valuation_price') for m in ('pe','pb','ps')}
    s = _summarize_buy_candidate(px, mm, 0.1)
    print('\n===', day, '===')
    print('close=', px, 'upper_bound=', round(px*BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER,4))
    print('core_prices=', core)
    print('score=', s.get('undervalue_score'), 'buy=', s.get('buy_candidate'))
    print('reason=', s.get('buy_candidate_reason'))
