import os, datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from django.test.client import RequestFactory
from prediction.models import StockValuationSnapshotLatest
from prediction.management.commands.prefillvaluationsnapshot import _build_refresh_summary_by_variant, _normalize_valuation_variant, _normalize_method_name
from prediction.management.commands.backtestmarketstyleadjustment import _pick_active_variant
from api.views import get_stock_valuation_methods
from datastore.models import StockTradingHistory

TS='002236.SZ'
for d in [datetime.date(2026,5,28), datetime.date(2026,5,29)]:
    trade = StockTradingHistory.objects.filter(ts_code=TS,freq='D',trade_date=d).values('close_qfq','close').first()
    px = float((trade or {}).get('close_qfq') or (trade or {}).get('close'))

    rows = list(StockValuationSnapshotLatest.objects.filter(ts_code=TS, market='CN', profit_report_type='Q1', latest_trade_date__lte=d).values(
        'valuation_variant','valuation_method','valuation_price','match_score','compare_group','latest_trade_date','profit_report_end_date'
    ))
    dedup = {}
    for r in rows:
        k = (_normalize_valuation_variant(r.get('valuation_variant'), fallback='default'), _normalize_method_name(r.get('valuation_method')))
        if not k[1] or k in dedup:
            continue
        dedup[k] = {
            'valuation_variant': k[0],
            'valuation_method': k[1],
            'valuation_price': r.get('valuation_price'),
            'match_score': r.get('match_score'),
            'compare_group': r.get('compare_group'),
            'latest_trade_date': r.get('latest_trade_date'),
            'profit_report_end_date': r.get('profit_report_end_date'),
        }
    summary_by_variant, variant_meta = _build_refresh_summary_by_variant(list(dedup.values()), px, 0.1)
    active_refresh = _pick_active_variant(summary_by_variant, variant_meta, current_price=px)
    s_refresh = summary_by_variant.get(active_refresh) or {}

    rf = RequestFactory()
    req = rf.get('/api/stock/valuation/methods/', {'freq':'D','earnings_report_type':'Q1','valuation_band_pct':'0.1'})
    resp = get_stock_valuation_methods(req, TS)
    p = resp.data if hasattr(resp,'data') else {}
    s_front = (p.get('summary') or {})

    print(f"{d} px={px}")
    print(' refresh_active', active_refresh, 'score', s_refresh.get('undervalue_score'), 'buy', s_refresh.get('buy_candidate'))
    print(' frontend_active', p.get('active_valuation_variant'), 'score', s_front.get('undervalue_score'), 'buy', s_front.get('buy_candidate'))
