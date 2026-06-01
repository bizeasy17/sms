import os
import datetime
import pandas as pd

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from datastore.models import StockTradingHistory
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate
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

BAND = 0.1
START = datetime.date.today() - datetime.timedelta(days=30)
END = datetime.date.today()

# pick 200 active symbols by latest available day volume
latest_day = StockTradingHistory.objects.filter(freq='D').order_by('-trade_date').values_list('trade_date', flat=True).first()
q = (
    StockTradingHistory.objects.filter(freq='D', trade_date=latest_day)
    .exclude(ts_code__isnull=True)
    .exclude(ts_code='')
    .order_by('-vol')
    .values_list('ts_code', flat=True)
)
ts_codes = []
seen = set()
for ts in q:
    if ts in seen:
        continue
    seen.add(ts)
    ts_codes.append(ts)
    if len(ts_codes) >= 200:
        break


def legacy_filter_core(valid_methods, current_price):
    filtered = {}
    lower = current_price * BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER
    upper = current_price * BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER
    for m in BUY_CANDIDATE_CORE_METHODS:
        p = valid_methods.get(m)
        if p is None:
            continue
        if lower <= p <= upper:
            filtered[m] = p
    if not filtered:
        return filtered
    prices = list(filtered.values())
    min_p, max_p = min(prices), max(prices)
    spread_max = 2.2
    if min_p > 0 and (max_p / min_p) > spread_max:
        far = max(filtered.items(), key=lambda kv: abs(kv[1] - current_price))[0]
        filtered.pop(far, None)
    return filtered


def legacy_summarize(current_price, method_map, band_pct):
    out = {"undervalue_score": None, "buy_candidate": False}
    if current_price in (None, 0) or not method_map:
        return out
    current_price = float(current_price)
    valid = {}
    for m, payload in (method_map or {}).items():
        p = (payload or {}).get("valuation_price")
        if p is None:
            continue
        p = float(p)
        if p > 0:
            valid[m] = p
    if not valid:
        return out

    raw_core = [valid[m] for m in BUY_CANDIDATE_CORE_METHODS if m in valid]
    filtered_core = legacy_filter_core(valid, current_price)
    core = [filtered_core[m] for m in BUY_CANDIDATE_CORE_METHODS if m in filtered_core]
    support = [valid[m] for m in BUY_CANDIDATE_SUPPORT_METHODS if m in valid]
    optional = [valid[m] for m in BUY_CANDIDATE_OPTIONAL_METHODS if m in valid and 0.5*current_price <= valid[m] <= 2.5*current_price]

    if len(core) >= BUY_CANDIDATE_MIN_CORE_METHOD_COUNT:
        candidates = list(core)
    elif raw_core:
        candidates = list(core or raw_core)
    else:
        candidates = core + support + optional
    if not candidates:
        return out

    composite = float(pd.Series(candidates, dtype="float64").median())
    conservative = min(core or raw_core or candidates)
    under = [m for m,p in valid.items() if current_price <= p*(1-band_pct)]
    core_under = [m for m in BUY_CANDIDATE_CORE_METHODS if m in filtered_core and current_price <= filtered_core[m]*(1-band_pct)]

    comp_gap = (composite-current_price)/current_price
    cons_gap = (conservative-current_price)/current_price
    valid_cnt, core_cnt, core_under_cnt, under_cnt = len(valid), len(core), len(core_under), len(under)

    score = 0
    if valid_cnt >= 4: score += 20
    elif valid_cnt >= 3: score += 15
    elif valid_cnt >= 2: score += 8
    if core_cnt >= 3: score += 25
    elif core_cnt >= 2: score += 18
    elif core_cnt == 1: score += 8
    if core_under_cnt >= 3: score += 30
    elif core_under_cnt >= 2: score += 24
    elif core_under_cnt == 1: score += 16
    if under_cnt >= 4: score += 10
    elif under_cnt >= 3: score += 7
    elif under_cnt >= 2: score += 4
    if comp_gap >= 0.3: score += 15
    elif comp_gap >= 0.15: score += 10
    elif comp_gap >= band_pct: score += 5
    if cons_gap >= 0.15: score += 10
    elif cons_gap >= 0.08: score += 6
    elif cons_gap >= 0.03: score += 3

    buy = (
        core_cnt >= BUY_CANDIDATE_MIN_CORE_METHOD_COUNT
        and core_under_cnt >= BUY_CANDIDATE_MIN_CORE_UNDER_COUNT
        and under_cnt >= BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT
        and comp_gap >= BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT
        and cons_gap >= BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT
    )
    out["undervalue_score"] = min(score, 100)
    out["buy_candidate"] = bool(buy)
    return out

stats = {
    'stocks': 0,
    'days': 0,
    'changed_days': 0,
    'flip_days': 0,
    'old_true_new_false': 0,
    'old_false_new_true': 0,
}

for ts in ts_codes:
    rows = list(
        StockTradingHistory.objects
        .filter(ts_code=ts, freq='D', trade_date__gte=START, trade_date__lte=END)
        .order_by('trade_date')
        .values('trade_date', 'close')
    )
    if not rows:
        continue
    stats['stocks'] += 1
    for r in rows:
        stats['days'] += 1
        d = r['trade_date']
        px = float(r['close']) if r.get('close') is not None else None
        mm = _build_latest_snapshot_method_map(
            ts_codes=[ts],
            market='CN',
            pick_strategy='latest_trade_then_updated',
            max_trade_date=d,
        ).get(ts, {}) or {}
        old = legacy_summarize(px, mm, BAND)
        new = _summarize_buy_candidate(px, mm, BAND)
        if old.get('undervalue_score') != new.get('undervalue_score'):
            stats['changed_days'] += 1
        if old.get('buy_candidate') != new.get('buy_candidate'):
            stats['flip_days'] += 1
            if old.get('buy_candidate') and not new.get('buy_candidate'):
                stats['old_true_new_false'] += 1
            elif (not old.get('buy_candidate')) and new.get('buy_candidate'):
                stats['old_false_new_true'] += 1

print(f"sample_stocks={stats['stocks']} latest_day={latest_day} range=[{START},{END}]")
print(
    f"days={stats['days']} changed_days={stats['changed_days']} "
    f"flip_days={stats['flip_days']} "
    f"old_true_new_false={stats['old_true_new_false']} "
    f"old_false_new_true={stats['old_false_new_true']}"
)
if stats['days']:
    flip_ratio = stats['flip_days'] / stats['days'] * 100
    print(f"flip_ratio_pct={flip_ratio:.2f}")
