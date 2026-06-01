import os
import datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from prediction.models import StockValuationSnapshot, StockValuationSnapshotLatest
from api.views import _resolve_valuation_report_end_date, _normalize_valuation_profit_report_type

TS = "002236.SZ"
asof = datetime.date(2026, 5, 28)
rt = _normalize_valuation_profit_report_type("Q1")
end_date = _resolve_valuation_report_end_date(rt, explicit_value=None, fiscal_year_value=None)

print(f"ts={TS} asof={asof} report_type={rt} resolved_end_date={end_date}")

qs = StockValuationSnapshot.objects.filter(ts_code=TS, market="CN", profit_report_type=rt)
if end_date is not None:
    qs = qs.filter(profit_report_end_date=end_date)

rows = list(
    qs.order_by("valuation_variant", "valuation_method", "-trade_date", "-updated_at")
      .values("valuation_variant","valuation_method","trade_date","updated_at","valuation_price","profit_report_end_date","profit_report_type")[:80]
)
print(f"snapshot_rows_count={len(rows)}")
for r in rows[:20]:
    print(r)

# emulate per method/variant first-row selection used by get_stock_valuation_methods
selected = {}
for r in rows:
    key=(r["valuation_variant"], r["valuation_method"])
    if key not in selected:
        selected[key]=r
print(f"selected_method_variant_count={len(selected)}")
for k,v in sorted(selected.items())[:20]:
    print(k, v["trade_date"], v["profit_report_end_date"], v["valuation_price"])

# latest table check
latest_rows = list(
    StockValuationSnapshotLatest.objects.filter(ts_code=TS, market="CN", profit_report_type=rt)
    .order_by("valuation_variant","valuation_method","-updated_at")
    .values("valuation_variant","valuation_method","latest_trade_date","valuation_price","profit_report_end_date","profit_report_type")[:30]
)
print(f"snapshot_latest_q1_rows={len(latest_rows)}")
for r in latest_rows[:20]:
    print(r)

# restrict latest <= asof (list path behavior)
latest_asof = list(
    StockValuationSnapshotLatest.objects.filter(ts_code=TS, market="CN", profit_report_type=rt, latest_trade_date__lte=asof)
    .order_by("valuation_variant","valuation_method","-updated_at")
    .values("valuation_variant","valuation_method","latest_trade_date","valuation_price","profit_report_end_date","profit_report_type")[:30]
)
print(f"snapshot_latest_q1_rows_asof={len(latest_asof)}")
for r in latest_asof[:20]:
    print(r)
