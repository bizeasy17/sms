import os, datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from prediction.models import StockValuationSnapshotLatest

TS='002236.SZ'
for d in [datetime.date(2026,5,28), datetime.date(2026,5,29)]:
    rows = list(
        StockValuationSnapshotLatest.objects.filter(
            ts_code=TS, market='CN', profit_report_type='Q1', latest_trade_date__lte=d
        ).values('valuation_variant','latest_trade_date','compare_group','match_score','valuation_method')
    )
    variants = {}
    for r in rows:
        v = r['valuation_variant'] or 'default'
        x = variants.setdefault(v, {'latest_trade_date': r.get('latest_trade_date'), 'compare_group': r.get('compare_group'), 'match_score_max': None, 'method_count':0})
        x['method_count'] += 1
        ms = r.get('match_score')
        if ms is not None:
            ms = float(ms)
            if x['match_score_max'] is None or ms > x['match_score_max']:
                x['match_score_max'] = ms
    print(f'\nASOF={d} variant_count={len(variants)}')
    for v,meta in sorted(variants.items()):
        print(v, meta)
