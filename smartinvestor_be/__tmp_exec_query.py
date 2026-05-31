import math
from backtest.views import _resolve_run_payload, _build_buyable_universe_rows

def try_get(obj, path, default=None):
    cur = obj
    for p in path.split('.'):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p, default)
        else:
            cur = getattr(cur, p, default)
    return default if cur is None else cur

def to_list_rows(rows):
    if rows is None:
        return []
    if isinstance(rows, dict):
        return rows.get('rows') or rows.get('data') or rows.get('items') or []
    return list(rows)

def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace(',', '').strip()
        if s == '':
            return None
        return float(s)
    except Exception:
        return None

def pct(vals, p):
    vals = sorted([x for x in vals if x is not None])
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] * (c - k) + vals[c] * (k - f)

def stats(vals):
    vals = [x for x in vals if x is not None]
    if not vals:
        return {'mean':None,'median':None,'p10':None,'p90':None}
    return {
        'mean': sum(vals) / len(vals),
        'median': pct(vals, 50),
        'p10': pct(vals, 10),
        'p90': pct(vals, 90),
    }

def fmt(x):
    return 'NA' if x is None else f'{x:.3f}'

run_ids = [161, 282, 283]
res = {}

for run_id in run_ids:
    payload = _resolve_run_payload(run_id)
    rows_raw = _build_buyable_universe_rows(payload, max_rows=3000)
    rows = to_list_rows(rows_raw)

    hit = []
    max_score = []
    best_discount = []
    latest_discount = []

    for r in rows:
        if not isinstance(r, dict):
            continue
        hc = num(r.get('hit_count'))
        ms = num(r.get('max_score'))
        bd = num(r.get('best_discount_pct'))
        lep = num(r.get('latest_entry_price'))
        lcp = num(r.get('latest_conservative_price'))
        ld = None
        if lep not in (None, 0) and lcp is not None:
            ld = (lcp / lep - 1.0) * 100.0
        hit.append(hc)
        max_score.append(ms)
        best_discount.append(bd)
        latest_discount.append(ld)

    risk_level = try_get(payload, 'strategy.risk_level') or try_get(payload, 'result.strategy.risk_level') or try_get(payload, 'risk_level') or try_get(payload, 'result.risk_level')
    risk_variant_policy = try_get(payload, 'strategy.risk_variant_policy') or try_get(payload, 'result.strategy.risk_variant_policy') or try_get(payload, 'risk_variant_policy') or try_get(payload, 'result.risk_variant_policy')
    risk_alignment_mode = try_get(payload, 'strategy.risk_alignment_mode') or try_get(payload, 'result.strategy.risk_alignment_mode') or try_get(payload, 'risk_alignment_mode') or try_get(payload, 'result.risk_alignment_mode')
    valuation_variant = try_get(payload, 'strategy.valuation_variant') or try_get(payload, 'result.strategy.valuation_variant') or try_get(payload, 'valuation_variant') or try_get(payload, 'result.valuation_variant')

    bcs = try_get(payload, 'result.buy_candidates_summary')
    cache_note = ''
    if bcs is None:
        cache_note = '?????'
    else:
        c_rows = to_list_rows(bcs)
        c_set = {r.get('ts_code') for r in c_rows if isinstance(r, dict) and r.get('ts_code')}
        r_set = {r.get('ts_code') for r in rows if isinstance(r, dict) and r.get('ts_code')}
        if len(c_rows) != len(rows) or c_set != r_set:
            cache_note = '?????'
        else:
            cache_note = '????'

    res[run_id] = {
        'rows': rows,
        'N': len(rows),
        'hit': stats(hit),
        'max_score': stats(max_score),
        'best_discount': stats(best_discount),
        'latest_discount': stats(latest_discount),
        'meta': {
            'risk_level': risk_level,
            'risk_variant_policy': risk_variant_policy,
            'risk_alignment_mode': risk_alignment_mode,
            'valuation_variant': valuation_variant,
            'cache_note': cache_note,
        }
    }

for rid in run_ids:
    r = res[rid]
    m = r['meta']
    print(f"RUN {rid} N={r['N']} hit_count(mean/median/p90)={fmt(r['hit']['mean'])}/{fmt(r['hit']['median'])}/{fmt(r['hit']['p90'])} max_score(mean/median/p10/p90)={fmt(r['max_score']['mean'])}/{fmt(r['max_score']['median'])}/{fmt(r['max_score']['p10'])}/{fmt(r['max_score']['p90'])} best_discount_pct(mean/median/p10/p90)={fmt(r['best_discount']['mean'])}/{fmt(r['best_discount']['median'])}/{fmt(r['best_discount']['p10'])}/{fmt(r['best_discount']['p90'])} latest_discount_pct(mean/median/p10/p90)={fmt(r['latest_discount']['mean'])}/{fmt(r['latest_discount']['median'])}/{fmt(r['latest_discount']['p10'])}/{fmt(r['latest_discount']['p90'])}")
    print(f"RUN {rid} strategy risk_level={m['risk_level']} risk_variant_policy={m['risk_variant_policy']} risk_alignment_mode={m['risk_alignment_mode']} valuation_variant={m['valuation_variant']} cache={m['cache_note']}")

pairs = [(161,282), (161,283), (282,283)]
for a,b in pairs:
    sa = {r.get('ts_code') for r in res[a]['rows'] if isinstance(r, dict) and r.get('ts_code')}
    sb = {r.get('ts_code') for r in res[b]['rows'] if isinstance(r, dict) and r.get('ts_code')}
    inter = len(sa & sb)
    onlya = len(sa - sb)
    onlyb = len(sb - sa)
    jac = inter / len(sa | sb) if (sa | sb) else 0.0
    print(f"PAIR {a}-{b} intersection={inter} only{a}={onlya} only{b}={onlyb} jaccard={jac:.3f}")

sa = {r.get('ts_code'): r for r in res[282]['rows'] if isinstance(r, dict) and r.get('ts_code')}
sb = {r.get('ts_code'): r for r in res[283]['rows'] if isinstance(r, dict) and r.get('ts_code')}
onlyA = [sa[k] for k in sa.keys() - sb.keys()]
onlyB = [sb[k] for k in sb.keys() - sa.keys()]

def mean_fields(rows):
    m1 = stats([num(r.get('max_score')) if isinstance(r, dict) else None for r in rows])['mean']
    m2 = stats([num(r.get('best_discount_pct')) if isinstance(r, dict) else None for r in rows])['mean']
    lds = []
    for r in rows:
        if not isinstance(r, dict):
            lds.append(None)
            continue
        lep = num(r.get('latest_entry_price'))
        lcp = num(r.get('latest_conservative_price'))
        if lep not in (None, 0) and lcp is not None:
            lds.append((lcp / lep - 1.0) * 100.0)
        else:
            lds.append(None)
    m3 = stats(lds)['mean']
    return m1, m2, m3

a1,a2,a3 = mean_fields(onlyA)
b1,b2,b3 = mean_fields(onlyB)
print(f"PAIR 282-283 onlyA(282) mean max_score/best_discount_pct/latest_discount_pct={fmt(a1)}/{fmt(a2)}/{fmt(a3)}")
print(f"PAIR 282-283 onlyB(283) mean max_score/best_discount_pct/latest_discount_pct={fmt(b1)}/{fmt(b2)}/{fmt(b3)}")
