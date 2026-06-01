from datetime import date, datetime
from collections import defaultdict

from prediction.models import StockValuationSnapshotHistory
from datastore.models import StockTradingHistory

try:
    from api.views import _build_valuation_summary_payload
except Exception:
    from api.views.valuation import _build_valuation_summary_payload


def to_date_str(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v)
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s

start = date(2023, 1, 1)
end = date(2023, 12, 31)
market = 'CN'
freq = 'D'

history_base = StockValuationSnapshotHistory.objects.filter(
    market=market,
    trade_date__gte=start,
    trade_date__lte=end,
    valuation_price__isnull=False,
)

total_history_rows = history_base.count()
total_history_ts = history_base.values('ts_code').distinct().count()
total_history_tsdate = history_base.values('ts_code', 'trade_date').distinct().count()
total_history_methods = history_base.values('valuation_method').distinct().count()

history_ts_set = set(history_base.values_list('ts_code', flat=True).distinct())

trading_base = StockTradingHistory.objects.filter(
    freq=freq,
    trade_date__gte=start,
    trade_date__lte=end,
)

trade_ts_set = set(trading_base.values_list('ts_code', flat=True).distinct())
total_trade_ts = len(trade_ts_set)
overlap_ts = len(history_ts_set & trade_ts_set)

latest_by_key = {}
val_qs = (
    history_base
    .order_by('ts_code', 'trade_date', 'valuation_method', '-archived_at', '-id')
    .values('id', 'ts_code', 'trade_date', 'valuation_method', 'archived_at', 'valuation_price')
)
for r in val_qs.iterator(chunk_size=5000):
    ts = r.get('ts_code')
    d = to_date_str(r.get('trade_date'))
    m = r.get('valuation_method')
    if not ts or not d or not m:
        continue
    k = (ts, d, m)
    if k not in latest_by_key:
        latest_by_key[k] = r

rows_by_tsdate = defaultdict(list)
for (ts, d, _m), r in latest_by_key.items():
    rows_by_tsdate[(ts, d)].append(r)

eligible_tsdate_keys_ge2 = {k for k, rows in rows_by_tsdate.items() if len(rows) >= 2}
eligible_tsdate_ge2_methods = len(eligible_tsdate_keys_ge2)
eligible_ts_ge2_methods_set = {k[0] for k in eligible_tsdate_keys_ge2}
eligible_ts_ge2_methods = len(eligible_ts_ge2_methods_set)

price_map = {}
trade_qs = trading_base.values('ts_code', 'trade_date', 'low_qfq', 'high_qfq', 'low', 'high', 'close_qfq', 'close')
for r in trade_qs.iterator(chunk_size=5000):
    ts = r.get('ts_code')
    d = to_date_str(r.get('trade_date'))
    if not ts or not d:
        continue
    low = r.get('low_qfq') if r.get('low_qfq') is not None else r.get('low')
    high = r.get('high_qfq') if r.get('high_qfq') is not None else r.get('high')
    close = r.get('close_qfq') if r.get('close_qfq') is not None else r.get('close')
    if low is None or high is None or close is None:
        continue
    price_map[(ts, d)] = {
        'low': float(low),
        'high': float(high),
        'close': float(close),
    }

eligible_tsdate_with_price_keys = {k for k in eligible_tsdate_keys_ge2 if k in price_map}
eligible_tsdate_with_price_and_ge2_methods = len(eligible_tsdate_with_price_keys)
eligible_ts_with_price_and_ge2_methods_set = {k[0] for k in eligible_tsdate_with_price_keys}
eligible_ts_with_price_and_ge2_methods = len(eligible_ts_with_price_and_ge2_methods_set)

hit_tsdate_count = 0
hit_ts_set = set()
for ts, d in eligible_tsdate_with_price_keys:
    rows = rows_by_tsdate.get((ts, d), [])
    if len(rows) < 2:
        continue
    p = price_map[(ts, d)]
    try:
        payload = _build_valuation_summary_payload(
            p['close'],
            rows,
            band_pct=0.1,
            price_key='valuation_price',
            ts_code=ts,
            freq='D',
        )
    except Exception:
        continue

    if not isinstance(payload, dict):
        continue
    conservative = payload.get('conservative_valuation_price')
    composite = payload.get('composite_valuation_price')
    if conservative is None or composite is None:
        continue
    try:
        conservative = float(conservative)
        composite = float(composite)
    except Exception:
        continue
    if conservative <= 0 or composite <= 0:
        continue

    cond_a = p['low'] < conservative
    cond_b_near = p['high'] >= composite * 0.98
    if cond_a and cond_b_near:
        hit_tsdate_count += 1
        hit_ts_set.add(ts)

hit_ts_count = len(hit_ts_set)

ts_with_history_but_no_trade = len(history_ts_set - trade_ts_set)
ts_with_trade_but_never_ge2_methods = len(trade_ts_set - eligible_ts_ge2_methods_set)
ts_with_ge2_methods_and_price_but_no_hit = len(eligible_ts_with_price_and_ge2_methods_set - hit_ts_set)

print(f"total_history_rows={total_history_rows}")
print(f"total_history_ts={total_history_ts}")
print(f"total_history_tsdate={total_history_tsdate}")
print(f"total_history_methods={total_history_methods}")
print(f"total_trade_ts={total_trade_ts}")
print(f"overlap_ts={overlap_ts}")
print(f"eligible_tsdate_ge2_methods={eligible_tsdate_ge2_methods}")
print(f"eligible_ts_ge2_methods={eligible_ts_ge2_methods}")
print(f"eligible_tsdate_with_price_and_ge2_methods={eligible_tsdate_with_price_and_ge2_methods}")
print(f"eligible_ts_with_price_and_ge2_methods={eligible_ts_with_price_and_ge2_methods}")
print(f"hit_tsdate_count={hit_tsdate_count}")
print(f"hit_ts_count={hit_ts_count}")
print(f"ts_with_history_but_no_trade={ts_with_history_but_no_trade}")
print(f"ts_with_trade_but_never_ge2_methods={ts_with_trade_but_never_ge2_methods}")
print(f"ts_with_ge2_methods_and_price_but_no_hit={ts_with_ge2_methods_and_price_but_no_hit}")
