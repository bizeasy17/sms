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
DATES=[datetime.date(2026,5,28), datetime.date(2026,5,29)]
rt=_normalize_valuation_profit_report_type("Q1")

for ASOF in DATES:
    trade = StockTradingHistory.objects.filter(ts_code=TS, freq='D', trade_date=ASOF).values('close_qfq','close').first()
    px = float((trade or {}).get('close_qfq') or (trade or {}).get('close'))

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
    variants=[]
    for v,_ in selected.keys():
        if v not in variants:
            variants.append(v)
    active_a = variants[0] if variants else 'default'
    map_a={}
    for (v,m),r in selected.items():
        if v==active_a and r.get('valuation_price') is not None:
            map_a[m]={'valuation_price':float(r['valuation_price'])}
    summary_a=_summarize_buy_candidate(px,map_a,0.1)

    rf=RequestFactory()
    req=rf.get('/api/stock/valuation/methods/', {'freq':'D','earnings_report_type':'Q1','valuation_band_pct':'0.1'})
    resp=get_stock_valuation_methods(req,TS)
    p=resp.data if hasattr(resp,'data') else {}
    rows_b=(p.get('data') or [])
    map_b={}
    for r in rows_b:
        m=_normalize_valuation_method_name(r.get('valuation_method'))
        vp=r.get('valuation_price')
        if m and vp is not None:
            map_b[m]={'valuation_price':float(vp)}
    summary_b=_summarize_buy_candidate(px,map_b,0.1)

    print(f"{ASOF} px={px}")
    print(f"  refresh_like(active={active_a}) score={summary_a.get('undervalue_score')} buy={summary_a.get('buy_candidate')}")
    print(f"  frontend(active={p.get('active_valuation_variant')}) score={summary_b.get('undervalue_score')} buy={summary_b.get('buy_candidate')}")
