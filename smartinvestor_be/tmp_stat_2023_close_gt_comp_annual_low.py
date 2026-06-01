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

trading_base = StockTradingHistory.objects.filter(
    freq=freq,
    trade_date__gte=start,
    trade_date__lte=end,
)

price_map = {}
annual_low_map = {}
trade_qs = trading_base.values('ts_code', 'trade_date', 'low_qfq', 'low', 'close_qfq', 'close')
for r in trade_qs.iterator(chunk_size=5000):
    ts = r.get('ts_code')
    d = to_date_str(r.get('trade_date'))
    if not ts or not d:
        continue
    close = r.get('close_qfq') if r.get('close_qfq') is not None else r.get('close')
    low = r.get('low_qfq') if r.get('low_qfq') is not None else r.get('low')
    if close is not None:
        try:
            close = float(close)
        except Exception:
            close = None
    if low is not None:
        try:
            low = float(low)
        except Exception:
            low = None
    if close is not None:
        price_map[(ts, d)] = {'close': close, 'low': low}
    if low is not None:
        prev = annual_low_map.get(ts)
        if prev is None or low < prev:
            annual_low_map[ts] = low

candidate_by_ts = defaultdict(list)
for (ts, d), rows in rows_by_tsdate.items():
    if (ts, d) not in price_map:
        continue
    close = price_map[(ts, d)]['close']
    if close is None:
        continue
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
    cons = payload.get('conservative_valuation_price')
    if comp is None or cons is None:
        continue
    try:
        comp = float(comp)
        cons = float(cons)
    except Exception:
        continue
    if comp <= 0 or cons <= 0:
        continue
    if close > comp:
        candidate_by_ts[ts].append({
            'trade_date': d,
            'close': close,
            'composite': comp,
            'conservative': cons,
        })

candidate_tsdate_count = sum(len(v) for v in candidate_by_ts.values())
candidate_ts_count = len(candidate_by_ts)

final_rows = []
for ts, cand_list in candidate_by_ts.items():
    annual_min_low = annual_low_map.get(ts)
    if annual_min_low is None:
        continue
    conservative_ref = min(item['conservative'] for item in cand_list if item.get('conservative') is not None)
    if annual_min_low >= conservative_ref:
        continue
    close_values = [item['close'] for item in cand_list]
    comp_values = [item['composite'] for item in cand_list]
    hit_days = len(cand_list)
    first_hit = min(item['trade_date'] for item in cand_list)
    last_hit = max(item['trade_date'] for item in cand_list)
    final_rows.append({
        'ts_code': ts,
        'hit_days': hit_days,
        'first_hit': first_hit,
        'last_hit': last_hit,
        'annual_min_low': annual_min_low,
        'min_conservative_ref': conservative_ref,
        'min_composite': min(comp_values),
        'max_close': max(close_values),
        'max_composite': max(comp_values),
    })

annual_low_pass_ts_count = len(final_rows)
final_hit_ts_count = len(final_rows)

out_dir = os.path.join('output', 'local_valuation_checks')
os.makedirs(out_dir, exist_ok=True)
out_csv = os.path.join(out_dir, 'valuation_2023_close_gt_comp_annual_low_stats.csv')

sorted_rows = sorted(final_rows, key=lambda x: (-x['hit_days'], x['ts_code']))
with open(out_csv, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(['ts_code', 'hit_days', 'first_hit', 'last_hit', 'annual_min_low', 'min_conservative_ref', 'min_composite', 'max_close', 'max_composite'])
    for r in sorted_rows:
        writer.writerow([
            r['ts_code'],
            r['hit_days'],
            r['first_hit'],
            r['last_hit'],
            f"{r['annual_min_low']:.6f}" if r['annual_min_low'] is not None else '',
            f"{r['min_conservative_ref']:.6f}" if r['min_conservative_ref'] is not None else '',
            f"{r['min_composite']:.6f}" if r['min_composite'] is not None else '',
            f"{r['max_close']:.6f}" if r['max_close'] is not None else '',
            f"{r['max_composite']:.6f}" if r['max_composite'] is not None else '',
        ])

print(f"total_history_ts={total_history_ts}")
print(f"candidate_ts_count={candidate_ts_count}")
print(f"candidate_tsdate_count={candidate_tsdate_count}")
print(f"annual_low_pass_ts_count={annual_low_pass_ts_count}")
print(f"final_hit_ts_count={final_hit_ts_count}")
print(f"csv_path={out_csv}")
