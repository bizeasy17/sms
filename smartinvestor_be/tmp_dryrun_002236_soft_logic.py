import os
import datetime
from statistics import median

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from datastore.models import StockTradingHistory
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate, _classify_valuation
from valuation.services.valuation_summary import (
    BUY_CANDIDATE_CORE_METHODS,
    BUY_CANDIDATE_SUPPORT_METHODS,
    BUY_CANDIDATE_OPTIONAL_METHODS,
    BUY_CANDIDATE_MIN_CORE_METHOD_COUNT,
    BUY_CANDIDATE_MIN_CORE_UNDER_COUNT,
    BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT,
    BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT,
    BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT,
    BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER,
    BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER,
)

TS = "002236.SZ"
BAND = 0.1
START = datetime.date.today() - datetime.timedelta(days=30)
END = datetime.date.today()


def to_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def soft_weight(price, current_price):
    if not current_price or not price:
        return 0.0
    lower = current_price * BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER
    upper = current_price * BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER
    if lower <= price <= upper:
        return 1.0
    # Soft decay instead of hard exclusion.
    # Over upper: decay by relative overflow; under lower: decay by relative underflow.
    if price > upper:
        overflow = (price - upper) / max(upper, 1e-9)
        return max(0.25, 1.0 - min(0.75, overflow))
    underflow = (lower - price) / max(lower, 1e-9)
    return max(0.25, 1.0 - min(0.75, underflow))


def weighted_avg(values, weights):
    if not values:
        return None
    s_w = sum(weights)
    if s_w <= 0:
        return None
    return sum(v * w for v, w in zip(values, weights)) / s_w


def summarize_soft(current_price, method_map, band_pct=0.1):
    if current_price in (None, 0) or not method_map:
        return {
            "composite_valuation_price": None,
            "conservative_valuation_price": None,
            "undervalue_score": None,
            "buy_candidate": False,
            "valuation_core_methods": [],
            "valuation_under_methods": [],
        }

    current_price = float(current_price)
    valid_methods = {}
    for method, payload in (method_map or {}).items():
        p = to_float((payload or {}).get("valuation_price"))
        if p is not None and p > 0:
            valid_methods[method] = p

    core_prices = [valid_methods[m] for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods]
    support_prices = [valid_methods[m] for m in BUY_CANDIDATE_SUPPORT_METHODS if m in valid_methods]
    optional_prices = [valid_methods[m] for m in BUY_CANDIDATE_OPTIONAL_METHODS if m in valid_methods]
    if not core_prices and not support_prices and not optional_prices:
        return {
            "composite_valuation_price": None,
            "conservative_valuation_price": None,
            "undervalue_score": None,
            "buy_candidate": False,
            "valuation_core_methods": [],
            "valuation_under_methods": [],
        }

    core_weights = [soft_weight(p, current_price) for p in core_prices]
    core_ref = weighted_avg(core_prices, core_weights) if core_prices else None

    candidate_prices = []
    if core_prices:
        candidate_prices.extend(core_prices)
    else:
        candidate_prices.extend(support_prices + optional_prices)

    # Composite uses soft-weighted core center when available, avoiding sudden method drop.
    if core_ref is not None:
        composite = core_ref
    else:
        composite = float(median(candidate_prices))

    conservative = min(core_prices or candidate_prices)

    under_methods = [m for m, p in valid_methods.items() if current_price <= p * (1 - band_pct)]
    core_under = [m for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods and current_price <= valid_methods[m] * (1 - band_pct)]

    composite_gap = (composite - current_price) / current_price
    conservative_gap = (conservative - current_price) / current_price

    score = 0
    valid_cnt = len(valid_methods)
    core_cnt = len(core_prices)
    core_under_cnt = len(core_under)
    under_cnt = len(under_methods)

    if valid_cnt >= 4:
        score += 20
    elif valid_cnt >= 3:
        score += 15
    elif valid_cnt >= 2:
        score += 8

    if core_cnt >= 3:
        score += 25
    elif core_cnt >= 2:
        score += 18
    elif core_cnt == 1:
        score += 8

    if core_under_cnt >= 3:
        score += 30
    elif core_under_cnt >= 2:
        score += 24
    elif core_under_cnt == 1:
        score += 16

    if under_cnt >= 4:
        score += 10
    elif under_cnt >= 3:
        score += 7
    elif under_cnt >= 2:
        score += 4

    if composite_gap >= 0.3:
        score += 15
    elif composite_gap >= 0.15:
        score += 10
    elif composite_gap >= band_pct:
        score += 5

    if conservative_gap >= 0.15:
        score += 10
    elif conservative_gap >= 0.08:
        score += 6
    elif conservative_gap >= 0.03:
        score += 3

    buy_candidate = (
        core_cnt >= BUY_CANDIDATE_MIN_CORE_METHOD_COUNT
        and core_under_cnt >= BUY_CANDIDATE_MIN_CORE_UNDER_COUNT
        and under_cnt >= BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT
        and composite_gap >= BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT
        and conservative_gap >= BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT
    )

    return {
        "composite_valuation_price": round(composite, 4),
        "conservative_valuation_price": round(conservative, 4),
        "undervalue_score": min(score, 100),
        "buy_candidate": bool(buy_candidate),
        "valuation_core_methods": [m for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods],
        "valuation_under_methods": sorted(under_methods),
    }

rows = list(
    StockTradingHistory.objects
    .filter(ts_code=TS, freq="D", trade_date__gte=START, trade_date__lte=END)
    .order_by("trade_date")
    .values("trade_date", "close")
)

print(f"TS={TS} rows={len(rows)} range=[{START},{END}]")
print("date\tclose\told_score\told_buy\tnew_score\tnew_buy\told_status\tnew_status")
for r in rows:
    d = r["trade_date"]
    px = to_float(r.get("close"))
    mm = _build_latest_snapshot_method_map(
        ts_codes=[TS],
        market="CN",
        pick_strategy="latest_trade_then_updated",
        max_trade_date=d,
    ).get(TS, {}) or {}

    old_s = _summarize_buy_candidate(px, mm, BAND)
    new_s = summarize_soft(px, mm, BAND)

    old_status, _ = _classify_valuation(px, old_s.get("composite_valuation_price"), BAND)
    new_status, _ = _classify_valuation(px, new_s.get("composite_valuation_price"), BAND)

    print(
        f"{d}\t{px:.2f}\t{old_s.get('undervalue_score')}\t{old_s.get('buy_candidate')}"
        f"\t{new_s.get('undervalue_score')}\t{new_s.get('buy_candidate')}\t{old_status}\t{new_status}"
    )
