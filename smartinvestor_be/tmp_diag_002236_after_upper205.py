import os
import datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from datastore.models import StockTradingHistory
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate, _parse_date_like, _filter_core_method_prices, BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER

TS = "002236.SZ"
Q1_END = datetime.date(2026, 3, 31)

def filter_to_end_date(method_map, end_date):
    out = {}
    for method, payload in (method_map or {}).items():
        p_end = _parse_date_like((payload or {}).get("profit_report_end_date") or (payload or {}).get("report_end_date"))
        if p_end == end_date:
            out[method] = payload
    return out

print("upper_multiplier:", BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER)
for day in ("2026-05-06", "2026-04-30"):
    px = (
        StockTradingHistory.objects.filter(ts_code=TS, freq="D", trade_date=day)
        .values_list("close", flat=True)
        .first()
    )
    raw_map = _build_latest_snapshot_method_map(
        ts_codes=[TS],
        market="CN",
        pick_strategy="latest_trade_then_updated",
        max_trade_date=day,
    ).get(TS, {}) or {}
    strict_map = filter_to_end_date(raw_map, Q1_END)
    valid_core = {m: strict_map[m]["valuation_price"] for m in ("pe", "pb", "ps") if m in strict_map and strict_map[m].get("valuation_price") is not None}
    filtered, excluded = _filter_core_method_prices(valid_core, float(px))
    summary = _summarize_buy_candidate(px, strict_map, 0.1)
    print(f"\n=== {day} ===")
    print("close:", px)
    print("filtered_core:", filtered)
    print("excluded_core:", excluded)
    print("buy_candidate:", summary.get("buy_candidate"))
    print("score:", summary.get("undervalue_score"))
    print("reason:", summary.get("buy_candidate_reason"))
