import csv
from datetime import date, datetime
from collections import defaultdict
from pathlib import Path

from datastore.models import StockTradingHistory
from prediction.models import StockValuationSnapshotHistory

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


price_map = {}
trading_qs = (
    StockTradingHistory.objects
    .filter(freq='D', trade_date__year=2023)
    .values('ts_code', 'trade_date', 'low_qfq', 'high_qfq', 'close_qfq', 'low', 'high', 'close')
)
for r in trading_qs.iterator(chunk_size=5000):
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
        'low_price': float(low),
        'high_price': float(high),
        'close_price': float(close),
    }

latest_by_key = {}
val_qs = (
    StockValuationSnapshotHistory.objects
    .filter(trade_date__year=2023, market='CN', valuation_price__isnull=False)
    .order_by('ts_code', 'trade_date', 'valuation_method', '-archived_at', '-id')
    .values('id', 'ts_code', 'trade_date', 'valuation_method', 'valuation_price', 'archived_at')
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

rows_by_day = defaultdict(list)
for (ts, d, _m), r in latest_by_key.items():
    rows_by_day[(ts, d)].append(r)

agg = defaultdict(lambda: {
    'hit_days': 0,
    'over_days': 0,
    'first_hit': None,
    'last_hit': None,
    'min_low': None,
    'max_high': None,
    'min_cons': None,
    'max_comp': None,
})

total_hits = 0
total_over = 0

for (ts, d), rows in rows_by_day.items():
    if len(rows) < 2:
        continue
    p = price_map.get((ts, d))
    if not p:
        continue
    try:
        payload = _build_valuation_summary_payload(
            p['close_price'],
            rows,
            band_pct=0.1,
            price_key='valuation_price',
            ts_code=ts,
            freq='D',
        )
    except Exception:
        continue

    conservative = payload.get('conservative_valuation_price') if isinstance(payload, dict) else None
    composite = payload.get('composite_valuation_price') if isinstance(payload, dict) else None
    if conservative is None or composite is None:
        continue
    try:
        conservative = float(conservative)
        composite = float(composite)
    except Exception:
        continue
    if conservative <= 0 or composite <= 0:
        continue

    low_p = p['low_price']
    high_p = p['high_price']
    cond_a = low_p < conservative
    cond_b_near = high_p >= composite * 0.98
    cond_b_over = high_p >= composite

    if cond_a and cond_b_near:
        s = agg[ts]
        s['hit_days'] += 1
        total_hits += 1
        if cond_b_over:
            s['over_days'] += 1
            total_over += 1
        if s['first_hit'] is None or d < s['first_hit']:
            s['first_hit'] = d
        if s['last_hit'] is None or d > s['last_hit']:
            s['last_hit'] = d
        s['min_low'] = low_p if s['min_low'] is None else min(s['min_low'], low_p)
        s['max_high'] = high_p if s['max_high'] is None else max(s['max_high'], high_p)
        s['min_cons'] = conservative if s['min_cons'] is None else min(s['min_cons'], conservative)
        s['max_comp'] = composite if s['max_comp'] is None else max(s['max_comp'], composite)

out_dir = Path('output/local_valuation_checks')
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / 'valuation_2023_low_cons_high_comp_stats.csv'

records = []
for ts, s in agg.items():
    records.append({
        'ts_code': ts,
        'hit_days': s['hit_days'],
        'over_days': s['over_days'],
        'first_hit': s['first_hit'] or '',
        'last_hit': s['last_hit'] or '',
        'min_low': f"{s['min_low']:.6f}" if s['min_low'] is not None else '',
        'max_high': f"{s['max_high']:.6f}" if s['max_high'] is not None else '',
        'min_cons': f"{s['min_cons']:.6f}" if s['min_cons'] is not None else '',
        'max_comp': f"{s['max_comp']:.6f}" if s['max_comp'] is not None else '',
    })

records.sort(key=lambda x: (-x['hit_days'], -x['over_days'], x['ts_code']))

with out_path.open('w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(
        f,
        fieldnames=['ts_code', 'hit_days', 'over_days', 'first_hit', 'last_hit', 'min_low', 'max_high', 'min_cons', 'max_comp'],
    )
    writer.writeheader()
    writer.writerows(records)

print(f"total stocks: {len(records)}")
print(f"total hit records: {total_hits}")
print(f"total over records: {total_over}")
print(f"output path: {out_path.as_posix()}")
