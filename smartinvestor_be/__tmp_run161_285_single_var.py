import copy
from backtest.views import _resolve_run_payload, _build_buyable_universe_rows


def to_rows(x):
    if x is None:
        return []
    if isinstance(x, dict):
        return x.get('rows') or x.get('data') or x.get('items') or x.get('candidate_rows') or []
    try:
        return list(x)
    except Exception:
        return []


def ts_map(rows):
    out = {}
    for r in rows:
        if isinstance(r, dict):
            ts = r.get('ts_code')
            if ts:
                out[str(ts)] = r
    return out


def jaccard(a, b):
    u = a | b
    return (len(a & b) / float(len(u))) if u else 0.0


def num(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        try:
            s = str(v).replace(',', '').strip()
            return float(s) if s else None
        except Exception:
            return None


def median(vals):
    vals = sorted(vals)
    n = len(vals)
    if n == 0:
        return None
    m = n // 2
    if n % 2 == 1:
        return vals[m]
    return (vals[m-1] + vals[m]) / 2.0


def mean(vals):
    return (sum(vals) / len(vals)) if vals else None


def fmt(x):
    if x is None:
        return 'NA'
    if isinstance(x, float):
        return f'{x:.6f}'
    return str(x)


def pair_stats(name, rows_a, rows_b):
    ma = ts_map(rows_a)
    mb = ts_map(rows_b)
    sa = set(ma.keys())
    sb = set(mb.keys())
    inter = sorted(sa & sb)
    only_a = len(sa - sb)
    only_b = len(sb - sa)
    j = jaccard(sa, sb)

    d_max = []
    d_disc = []
    for ts in inter:
        ra = ma[ts]
        rb = mb[ts]
        a1 = num(ra.get('max_score'))
        b1 = num(rb.get('max_score'))
        if a1 is not None and b1 is not None:
            d_max.append(a1 - b1)

        a2 = num(ra.get('best_discount_pct'))
        b2 = num(rb.get('best_discount_pct'))
        if a2 is not None and b2 is not None:
            d_disc.append(a2 - b2)

    print(f'PAIR {name} intersection={len(inter)} onlyA={only_a} onlyB={only_b} jaccard={j:.6f}')
    print('PAIR_DIFF %s max_score_diff(mean,median,n)=(%s,%s,%s) best_discount_pct_diff(mean,median,n)=(%s,%s,%s)' % (
        name,
        fmt(mean(d_max)), fmt(median(d_max)), len(d_max),
        fmt(mean(d_disc)), fmt(median(d_disc)), len(d_disc)
    ))


def ensure_layer_set(payload, key, value):
    if isinstance(payload, dict):
        payload[key] = value
        for layer in ('params', 'strategy', 'payload'):
            v = payload.get(layer)
            if isinstance(v, dict):
                v[key] = value


def ensure_layer_del(payload, key):
    if isinstance(payload, dict):
        if key in payload:
            del payload[key]
        for layer in ('params', 'strategy', 'payload'):
            v = payload.get(layer)
            if isinstance(v, dict) and key in v:
                del v[key]


def flatten(obj, prefix=''):
    out = {}
    if isinstance(obj, dict):
        for k in sorted(obj.keys(), key=lambda x: str(x)):
            p = f'{prefix}.{k}' if prefix else str(k)
            v = obj.get(k)
            if isinstance(v, dict):
                out.update(flatten(v, p))
            elif isinstance(v, list):
                out[p] = f'<list len={len(v)}>'
            else:
                out[p] = v
    else:
        out[prefix or '<root>'] = obj
    return out


p161 = _resolve_run_payload(161)
p285 = _resolve_run_payload(285)

r161 = to_rows(_build_buyable_universe_rows(p161, max_rows=5000))
r285 = to_rows(_build_buyable_universe_rows(p285, max_rows=5000))

s161 = set(ts_map(r161).keys())
s285 = set(ts_map(r285).keys())

p161_legacy = copy.deepcopy(p161)
ensure_layer_set(p161_legacy, 'risk_alignment_mode', 'legacy')
r161_legacy = to_rows(_build_buyable_universe_rows(p161_legacy, max_rows=5000))
s161_legacy = set(ts_map(r161_legacy).keys())

p285_noalign = copy.deepcopy(p285)
ensure_layer_del(p285_noalign, 'risk_alignment_mode')
r285_noalign = to_rows(_build_buyable_universe_rows(p285_noalign, max_rows=5000))
s285_noalign = set(ts_map(r285_noalign).keys())

print('FINAL_SUMMARY_BEGIN')
print(f'BASELINE N161={len(s161)} N285={len(s285)} jaccard_161_285={jaccard(s161,s285):.6f}')
print(f'SINGLE_VAR JACCARD 161_legacy_vs_285={jaccard(s161_legacy,s285):.6f} 161_vs_285_noalign={jaccard(s161,s285_noalign):.6f}')

pair_stats('161_vs_161_legacy', r161, r161_legacy)
pair_stats('285_vs_285_noalign', r285, r285_noalign)
pair_stats('161_legacy_vs_285', r161_legacy, r285)
pair_stats('161_vs_285_noalign', r161, r285_noalign)

f161 = flatten(p161)
f285 = flatten(p285)
all_keys = sorted(set(f161.keys()) | set(f285.keys()))
diffs = []
for k in all_keys:
    v1 = f161.get(k, '<MISSING>')
    v2 = f285.get(k, '<MISSING>')
    if v1 != v2:
        diffs.append((k, v1, v2))

print(f'KEY_DIFF_TOTAL={len(diffs)} SHOW_TOP={min(80,len(diffs))}')
for i, (k, v1, v2) in enumerate(diffs[:80], 1):
    print(f'KEY_DIFF[{i}] path={k} | 161={v1} | 285={v2}')

print('FINAL_SUMMARY_END')
