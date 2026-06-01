import os, datetime
from collections import OrderedDict
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from datastore.models import StockTradingHistory
from prediction.models import StockValuationSnapshotLatest
from api.views import (
    _normalize_valuation_profit_report_type,
    _summarize_buy_candidate,
    _normalize_valuation_method_name,
    _normalize_valuation_variant,
)

TS = "002236.SZ"
ASOF = datetime.date(2026, 5, 26)
REPORT_DAY = datetime.date(2025, 4, 21)
rt = _normalize_valuation_profit_report_type("Q1")

# asof-constrained Q1 rows (this is the path that fell back to 2025-04-21)
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
        selected[key] = r

variants = []
for v,_m in selected.keys():
    if v not in variants:
        variants.append(v)
active_variant = variants[0] if variants else 'default'

method_map = {}
for (v,m), r in selected.items():
    if v != active_variant:
        continue
    vp = r.get('valuation_price')
    if vp is None:
        continue
    method_map[m] = {'valuation_price': float(vp)}

# price on report day (2025-04-21)
row_report = StockTradingHistory.objects.filter(ts_code=TS, freq='D', trade_date=REPORT_DAY).values('close_qfq','close').first()
px_report = float((row_report or {}).get('close_qfq') or (row_report or {}).get('close')) if row_report else None

# price on asof day (for reference)
row_asof = StockTradingHistory.objects.filter(ts_code=TS, freq='D', trade_date=ASOF).values('close_qfq','close').first()
px_asof = float((row_asof or {}).get('close_qfq') or (row_asof or {}).get('close')) if row_asof else None

summary_report = _summarize_buy_candidate(px_report, method_map, 0.1) if px_report else {}
summary_asof = _summarize_buy_candidate(px_asof, method_map, 0.1) if px_asof else {}

print(f"TS={TS} active_variant={active_variant}")
print("method_count", len(method_map))
print("snapshot_trade_dates", sorted({str(r.get('latest_trade_date')) for (_k,r) in selected.items() if _k[0]==active_variant}))
print("report_end_dates", sorted({str(r.get('profit_report_end_date')) for (_k,r) in selected.items() if _k[0]==active_variant}))
print("---")
print(f"price@2025-04-21={px_report}")
print("score@2025-04-21", summary_report.get('undervalue_score'))
print("buy@2025-04-21", summary_report.get('buy_candidate'))
print("reason@2025-04-21", summary_report.get('buy_candidate_reason'))
print("---")
print(f"price@2026-05-26={px_asof}")
print("score@2026-05-26", summary_asof.get('undervalue_score'))
print("buy@2026-05-26", summary_asof.get('buy_candidate'))
