import os
import datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from datastore.models import StockTradingHistory
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate
from valuation.services.valuation_summary import _filter_core_method_prices

TS = "002236.SZ"
end = datetime.date.today()
start = end - datetime.timedelta(days=14)

rows = list(
    StockTradingHistory.objects
    .filter(ts_code=TS, freq="D", trade_date__gte=start, trade_date__lte=end)
    .order_by("trade_date")
    .values("trade_date", "close")
)

print(f"trade rows={len(rows)} range=[{start},{end}]")
print("date\tclose\tscore\tbuy\tcomposite\tcore_methods\tcore_excluded")
for r in rows:
    d = r["trade_date"]
    px = float(r["close"]) if r.get("close") is not None else None
    mm = _build_latest_snapshot_method_map(
        ts_codes=[TS],
        market="CN",
        pick_strategy="latest_trade_then_updated",
        max_trade_date=d,
    ).get(TS, {}) or {}
    s = _summarize_buy_candidate(px, mm, 0.1)

    valid_core = {
        m: float((mm.get(m) or {}).get("valuation_price"))
        for m in ("pe", "pb", "ps")
        if (mm.get(m) or {}).get("valuation_price") not in (None, "")
    }
    filtered, excluded = _filter_core_method_prices(valid_core, px) if px else ({}, {})
    excluded_keys = ",".join(sorted(excluded.keys())) if excluded else "-"
    core_keys = ",".join(sorted(filtered.keys())) if filtered else "-"
    print(f"{d}\t{px:.2f}\t{s.get('undervalue_score')}\t{s.get('buy_candidate')}\t{s.get('composite_valuation_price')}\t{core_keys}\t{excluded_keys}")
