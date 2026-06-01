from datetime import date, datetime
from collections import defaultdict
import csv
import os

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

total_history_ts = history_base.values('ts_code').distinct().count()

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

trading_base = StockTradingHistory.objects.filter(
    freq=freq,
    trade_date__gte=start,
    trade_date__lte=end,
)

price_map = {}
trade_qs = trading_base.values('ts_code', 'trade_date', 'close_qfq', 'close')
for r in trade_qs.iterator(chunk_size=5000):
    ts = r.get('ts_code')
    d = to_date_str(r.get('trade_date'))
    if not ts or not d:
        continue
    close = r.get('close_qfq') if r.get('close_qfq') is not None else r.get('close')
    if close is None:
        continue
    try:
        close = float(close)
    except Exception:
        continue
    price_map[(ts, d)] = {'close': close}

eligible_tsdate_with_price_keys = {k for k in eligible_tsdate_keys_ge2 if k in price_map}
eligible_ts_with_price_and_ge2_methods = len({k[0] for k in eligible_tsdate_with_price_keys})

hit_tsdate_count_close_gt_comp = 0
hit_stats_by_ts = defaultdict(lambda: {
    'hit_days': 0,
    'first_hit': None,
    'last_hit': None,
    'min_close': None,
    'max_close': None,
    'min_comp': None,
    'max_comp': None,
})

for ts, d in sorted(eligible_tsdate_with_price_keys):
    rows = rows_by_tsdate.get((ts, d), [])
    if len(rows) < 2:
        continue
    close = price_map[(ts, d)]['close']

    try:
        payload = _build_valuation_summary_payload(
            close,
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

    comp = payload.get('composite_valuation_price')
    if comp is None:
        continue
    try:
        comp = float(comp)
    except Exception:
        continue
    if comp <= 0:
        continue

    if close > comp:
        hit_tsdate_count_close_gt_comp += 1
        s = hit_stats_by_ts[ts]
        s['hit_days'] += 1
        if s['first_hit'] is None or d < s['first_hit']:
            s['first_hit'] = d
        if s['last_hit'] is None or d > s['last_hit']:
            s['last_hit'] = d
        s['min_close'] = close if s['min_close'] is None else min(s['min_close'], close)
        s['max_close'] = close if s['max_close'] is None else max(s['max_close'], close)
        s['min_comp'] = comp if s['min_comp'] is None else min(s['min_comp'], comp)
        s['max_comp'] = comp if s['max_comp'] is None else max(s['max_comp'], comp)

hit_ts_count_close_gt_comp = len(hit_stats_by_ts)

out_dir = os.path.join('output', 'local_valuation_checks')
os.makedirs(out_dir, exist_ok=True)
out_csv = os.path.join(out_dir, 'valuation_2023_close_gt_comp_stats.csv')

sorted_rows = sorted(
    (
        {
            'ts_code': ts,
            **stats,
        }
        for ts, stats in hit_stats_by_ts.items()
    ),
    key=lambda x: (-x['hit_days'], x['ts_code'])
)

with open(out_csv, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(['ts_code', 'hit_days', 'first_hit', 'last_hit', 'min_close', 'max_close', 'min_comp', 'max_comp'])
    for r in sorted_rows:
        writer.writerow([
            r['ts_code'],
            r['hit_days'],
            r['first_hit'],
            r['last_hit'],
            f"{r['min_close']:.6f}" if r['min_close'] is not None else '',
            f"{r['max_close']:.6f}" if r['max_close'] is not None else '',
            f"{r['min_comp']:.6f}" if r['min_comp'] is not None else '',
            f"{r['max_comp']:.6f}" if r['max_comp'] is not None else '',
        ])

print(f"total_history_ts={total_history_ts}")
print(f"eligible_ts_with_price_and_ge2_methods={eligible_ts_with_price_and_ge2_methods}")
print(f"hit_tsdate_count_close_gt_comp={hit_tsdate_count_close_gt_comp}")
print(f"hit_ts_count_close_gt_comp={hit_ts_count_close_gt_comp}")
print(f"csv_path={out_csv}")
