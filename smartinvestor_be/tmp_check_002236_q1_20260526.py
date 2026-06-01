import os, datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from prediction.models import StockValuationSnapshot, StockValuationSnapshotLatest
from api.views import _normalize_valuation_profit_report_type

TS="002236.SZ"
ASOF=datetime.date(2026,5,26)
rt=_normalize_valuation_profit_report_type("Q1")

# Path A: asof constrained (list/batch path style)
rows_asof=list(
    StockValuationSnapshotLatest.objects.filter(
        ts_code=TS, market='CN', profit_report_type=rt, latest_trade_date__lte=ASOF
    ).order_by('valuation_variant','valuation_method','-updated_at').values(
        'valuation_variant','valuation_method','latest_trade_date','valuation_price','profit_report_end_date'
    )
)
selected_asof={}
for r in rows_asof:
    k=(r['valuation_variant'],r['valuation_method'])
    if k not in selected_asof:
        selected_asof[k]=r

# Path B: detail API Q1 branch (no asof constraint, just latest by method/variant)
rows_detail=list(
    StockValuationSnapshot.objects.filter(
        ts_code=TS, market='CN', profit_report_type=rt
    ).order_by('valuation_variant','valuation_method','-trade_date','-updated_at').values(
        'valuation_variant','valuation_method','trade_date','valuation_price','profit_report_end_date'
    )
)
selected_detail={}
for r in rows_detail:
    k=(r['valuation_variant'],r['valuation_method'])
    if k not in selected_detail:
        selected_detail[k]=r

print('ASOF PATH sample:')
for k,v in list(sorted(selected_asof.items()))[:8]:
    print(k, v['latest_trade_date'], v['profit_report_end_date'], v['valuation_price'])

print('\nDETAIL PATH sample:')
for k,v in list(sorted(selected_detail.items()))[:8]:
    print(k, v['trade_date'], v['profit_report_end_date'], v['valuation_price'])
