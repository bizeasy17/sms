import os, datetime
from collections import OrderedDict
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from django.test.client import RequestFactory
from datastore.models import StockTradingHistory
from prediction.models import StockValuationSnapshotLatest
from api.views import (
    _normalize_valuation_profit_report_type,
    _summarize_buy_candidate,
    _normalize_valuation_method_name,
    _normalize_valuation_variant,
    get_stock_valuation_methods,
)

TS="002236.SZ"
ASOF=datetime.date(2026,5,26)
rt=_normalize_valuation_profit_report_type("Q1")

trade = StockTradingHistory.objects.filter(ts_code=TS, freq='D', trade_date=ASOF).values('close_qfq','close').first()
px = float((trade or {}).get('close_qfq') or (trade or {}).get('close'))

# A) asof snapshot path (latest table constrained <= ASOF)
rows_asof = list(
    StockValuationSnapshotLatest.objects.filter(
        ts_code=TS, market='CN', profit_report_type=rt, latest_trade_date__lte=ASOF
    ).order_by('valuation_variant','valuation_method','-updated_at').values(
        'valuation_variant','valuation_method','latest_trade_date','valuation_price','profit_report_end_date'
    )
)
selected = OrderedDict()
for r in rows_asof:
    key = (_normalize_valuation_variant(r.get('valuation_variant'), fallback='default'), _normalize_valuation_method_name(r.get('valuation_method')))
    if key[1] and key not in selected:
        selected[key]=r

# pick first available variant from selected set (matches current constrained reality: default only)
variants = []
for v,_m in selected.keys():
    if v not in variants:
        variants.append(v)
active_variant = variants[0] if variants else 'default'
method_map_a = {}
for (v,m),r in selected.items():
    if v!=active_variant:
        continue
    vp = r.get('valuation_price')
    if vp is None:
        continue
    method_map_a[m] = {'valuation_price': float(vp)}
summary_a = _summarize_buy_candidate(px, method_map_a, 0.1)

# B) frontend detail API path (real request style)
rf = RequestFactory()
req = rf.get('/api/stock/valuation/methods/', {'freq':'D', 'earnings_report_type':'Q1', 'valuation_band_pct':'0.1'})
resp = get_stock_valuation_methods(req, TS)
payload = resp.data if hasattr(resp, 'data') else {}
summary_b = (payload or {}).get('summary') or {}
active_variant_b = (payload or {}).get('active_valuation_variant')

# capture trade_date footprint for active variant rows
rows_b = (payload or {}).get('data') or []
trade_dates_b = sorted({str(r.get('latest_trade_date')) for r in rows_b if r.get('latest_trade_date')})
report_end_dates_b = sorted({str(r.get('profit_report_end_date')) for r in rows_b if r.get('profit_report_end_date')})

print(f"TS={TS} ASOF={ASOF} Q1 current_price={px}")
print('--- A) ASOF constrained snapshot path ---')
print('active_variant', active_variant)
print('row_count', len(method_map_a))
print('snapshot_trade_dates', sorted({str(v.get('latest_trade_date')) for v in method_map_a.values() if v.get('latest_trade_date')}))
# method_map_a doesn't store trade date, print from selected
print('selected_trade_dates', sorted({str(r.get('latest_trade_date')) for (_k,r) in selected.items() if _k[0]==active_variant and r.get('latest_trade_date')}))
print('selected_report_end_dates', sorted({str(r.get('profit_report_end_date')) for (_k,r) in selected.items() if _k[0]==active_variant and r.get('profit_report_end_date')}))
print('undervalue_score', summary_a.get('undervalue_score'))
print('buy_candidate', summary_a.get('buy_candidate'))

print('\n--- B) Frontend detail API realtime path ---')
print('active_variant', active_variant_b)
print('row_count', len(rows_b))
print('row_trade_dates', trade_dates_b)
print('row_report_end_dates', report_end_dates_b)
print('undervalue_score', summary_b.get('undervalue_score'))
print('buy_candidate', summary_b.get('buy_candidate'))

same = (summary_a.get('undervalue_score') == summary_b.get('undervalue_score')) and (bool(summary_a.get('buy_candidate')) == bool(summary_b.get('buy_candidate')))
print('\nconsistent?', same)
