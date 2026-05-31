import json, statistics, math, traceback, inspect
from collections import Counter
from django.apps import apps
from django.db.models import Avg, Max, Min, Count
from backtest.views import _build_buyable_universe_rows

Run = None
for m in apps.get_models():
    if m.__name__ == 'TraditionalBacktestRun':
        Run = m
        break
if Run is None:
    raise RuntimeError('TraditionalBacktestRun model not found')

runs = list(Run.objects.filter(id__in=[161,282,283]).order_by('id'))
if len(runs) != 3:
    raise RuntimeError('Expected 3 runs, got %s' % [r.id for r in runs])

print('SIGNATURE', str(inspect.signature(_build_buyable_universe_rows)))

# helpers

def pct(vals, p):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    vals = sorted(vals)
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p / 100.0
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] * (c - k) + vals[c] * (k - f)

def med(vals):
    return pct(vals, 50)

def try_get(obj, path, default=None):
    cur = obj
    for part in path.split('.'):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        else:
            cur = getattr(cur, part, default)
    return cur if cur is not None else default

def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {'mean':None,'median':None,'p10':None,'p90':None,'n':0}
    return {'mean': sum(vals)/len(vals), 'median': med(vals), 'p10': pct(vals,10), 'p90': pct(vals,90), 'n': len(vals)}

def fmt(x):
    if x is None:
        return 'NA'
    if isinstance(x, float):
        return f'{x:.4f}'
    return str(x)

results = {}
for run in runs:
    # strategy metadata paths
    strat = try_get(run, 'strategy', None)
    strategy_info = {
        'risk_level': try_get(run, 'strategy.risk_level') or try_get(run, 'risk_level'),
        'risk_variant_policy': try_get(run, 'strategy.risk_variant_policy') or try_get(run, 'risk_variant_policy'),
        'risk_alignment_mode': try_get(run, 'strategy.risk_alignment_mode') or try_get(run, 'risk_alignment_mode'),
        'valuation_variant': try_get(run, 'strategy.valuation_variant') or try_get(run, 'valuation_variant'),
    }

    # build buyable universe rows with flexible signature handling
    rows = None
    sig = inspect.signature(_build_buyable_universe_rows)
    params = list(sig.parameters)
    candidates = [
        (run,),
        (run, ),
        (run, getattr(run, 'result', None)),
        (run, getattr(run, 'result', None), None),
        (run, getattr(run, 'result', None), {}),
        (getattr(run, 'result', None), run),
    ]
    # Additionally try keyword combinations if simple positional attempts fail
    last_err = None
    for args in candidates:
        try:
            # filter Nones at end only if function likely accepts fewer args
            rows = _build_buyable_universe_rows(*[a for a in args if a is not None])
            break
        except TypeError as e:
            last_err = e
        except Exception as e:
            last_err = e
            break
    if rows is None:
        # try with common kwargs
        for kwargs in [
            {'run': run}, {'backtest_run': run}, {'bt_run': run}, {'run_obj': run},
            {'result': getattr(run,'result',None), 'run': run},
        ]:
            try:
                rows = _build_buyable_universe_rows(**{k:v for k,v in kwargs.items() if v is not None})
                break
            except Exception as e:
                last_err = e
    if rows is None:
        raise RuntimeError(f'Failed to call _build_buyable_universe_rows for run {run.id}: {last_err}')

    # normalize rows
    if isinstance(rows, dict):
        row_list = rows.get('rows') or rows.get('data') or rows.get('items') or []
    else:
        row_list = list(rows)

    def num(x):
        if x is None:
            return None
        if isinstance(x, bool):
            return float(x)
        if isinstance(x, (int, float)):
            return float(x)
        try:
            s = str(x).replace(',', '').strip()
            if s == '':
                return None
            return float(s)
        except Exception:
            return None

    hit = []
    max_score = []
    best_disc = []
    latest_disc = []
    # identify field path diffs
    field_samples = []
    for r in row_list:
        if isinstance(r, dict):
            field_samples.append(sorted(list(r.keys()))[:20])
        else:
            field_samples.append(type(r).__name__)
        hc = num(r.get('hit_count') if isinstance(r, dict) else None)
        ms = num(r.get('max_score') if isinstance(r, dict) else None)
        bd = num(r.get('best_discount_pct') if isinstance(r, dict) else None)
        lep = num(r.get('latest_entry_price') if isinstance(r, dict) else None)
        lcp = num(r.get('latest_conservative_price') if isinstance(r, dict) else None)
        ld = None
        if lep not in (None, 0) and lcp is not None:
            ld = (lcp / lep - 1.0) * 100.0
        hit.append(hc); max_score.append(ms); best_disc.append(bd); latest_disc.append(ld)

    # sample_trades freq and risk_score summary
    sample = try_get(run, 'sample_trades', None)
    if sample is None:
        sample = try_get(run, 'result.sample_trades', None)
    if isinstance(sample, str):
        try:
            sample = json.loads(sample)
        except Exception:
            pass
    if isinstance(sample, dict):
        sample_list = sample.get('trades') or sample.get('rows') or sample.get('items') or sample.get('data') or []
    elif sample is None:
        sample_list = []
    else:
        sample_list = list(sample)

    risk_levels = []
    risk_scores = []
    for t in sample_list:
        if isinstance(t, dict):
            rl = t.get('risk_level') or try_get(t,'risk.level')
            rs = t.get('risk_score') or try_get(t,'risk.score')
        else:
            rl = None; rs = None
        if rl is not None:
            risk_levels.append(str(rl))
        rsn = num(rs)
        if rsn is not None:
            risk_scores.append(rsn)

    results[run.id] = {
        'strategy': strategy_info,
        'N': len(row_list),
        'hit': stats(hit),
        'max_score': stats(max_score),
        'best_discount_pct': stats(best_disc),
        'latest_discount_pct': stats(latest_disc),
        'sample_trade_risk_freq': Counter(risk_levels),
        'sample_trade_risk_score': stats(risk_scores),
        'field_samples': field_samples[:3],
        'row_keys_union': sorted(set().union(*[set(r.keys()) for r in row_list if isinstance(r, dict)])) if row_list and isinstance(row_list[0], dict) else [],
        'rows': row_list,
    }

# print run summaries
for rid in [161,282,283]:
    r = results[rid]
    print(f'RUN {rid} META risk_level={fmt(r["strategy"]["risk_level"])} risk_variant_policy={fmt(r["strategy"]["risk_variant_policy"])} risk_alignment_mode={fmt(r["strategy"]["risk_alignment_mode"])} valuation_variant={fmt(r["strategy"]["valuation_variant"])}')
    print(f'RUN {rid} BUYABLE N={r["N"]} hit_count mean/median/p90={fmt(r["hit"]["mean"])}/{fmt(r["hit"]["median"])}/{fmt(r["hit"]["p90"])} max_score mean/median/p10/p90={fmt(r["max_score"]["mean"])}/{fmt(r["max_score"]["median"])}/{fmt(r["max_score"]["p10"])}/{fmt(r["max_score"]["p90"])} best_discount_pct mean/median/p10/p90={fmt(r["best_discount_pct"]["mean"])}/{fmt(r["best_discount_pct"]["median"])}/{fmt(r["best_discount_pct"]["p10"])}/{fmt(r["best_discount_pct"]["p90"])} latest_discount_pct mean/median/p10/p90={fmt(r["latest_discount_pct"]["mean"])}/{fmt(r["latest_discount_pct"]["median"])}/{fmt(r["latest_discount_pct"]["p10"])}/{fmt(r["latest_discount_pct"]["p90"])}')
    print(f'RUN {rid} SAMPLE_TRADES risk_level_freq={dict(r["sample_trade_risk_freq"])} risk_score mean/median={fmt(r["sample_trade_risk_score"]["mean"])}/{fmt(r["sample_trade_risk_score"]["median"])}')
    print(f'RUN {rid} ROW_KEYS_SAMPLE={r["field_samples"]}')

# pairwise relations
for a,b in [(161,282),(161,283),(282,283)]:
    sa = {row.get("ts_code") for row in results[a]['rows'] if isinstance(row, dict) and row.get('ts_code') is not None}
    sb = {row.get("ts_code") for row in results[b]['rows'] if isinstance(row, dict) and row.get('ts_code') is not None}
    inter = len(sa & sb)
    onlya = len(sa - sb)
    onlyb = len(sb - sa)
    j = inter / len(sa | sb) if sa | sb else 0.0
    print(f'PAIR {a}-{b} intersection={inter} only{a}={onlya} only{b}={onlyb} jaccard={j:.4f}')

# 282 vs 283 onlyA/onlyB means
for a,b in [(282,283)]:
    sa = {row.get("ts_code"): row for row in results[a]['rows'] if isinstance(row, dict) and row.get('ts_code') is not None}
    sb = {row.get("ts_code"): row for row in results[b]['rows'] if isinstance(row, dict) and row.get('ts_code') is not None}
    onlya = [sa[k] for k in sa.keys() - sb.keys()]
    onlyb = [sb[k] for k in sb.keys() - sa.keys()]
    def avg_fields(rows):
        def getn(r, key):
            v = r.get(key)
            try:
                return float(v)
            except Exception:
                return None
        return {
            'max_score_mean': stats([getn(r,'max_score') for r in rows])['mean'],
            'best_discount_pct_mean': stats([getn(r,'best_discount_pct') for r in rows])['mean'],
            'latest_discount_pct_mean': stats([((getn(r,'latest_conservative_price')/getn(r,'latest_entry_price')-1)*100) if getn(r,'latest_entry_price') not in (None,0) and getn(r,'latest_conservative_price') is not None else None for r in rows])['mean'],
        }
    aa = avg_fields(onlya)
    bb = avg_fields(onlyb)
    print(f'PAIR_282_283_ONLYA mean max_score={fmt(aa["max_score_mean"])} best_discount_pct={fmt(aa["best_discount_pct_mean"])} latest_discount_pct={fmt(aa["latest_discount_pct_mean"])}')
    print(f'PAIR_282_283_ONLYB mean max_score={fmt(bb["max_score_mean"])} best_discount_pct={fmt(bb["best_discount_pct_mean"])} latest_discount_pct={fmt(bb["latest_discount_pct_mean"])}')

# explicit path diff note
for rid in [161,282,283]:
    r = results[rid]
    top = r['row_keys_union']
    print(f'RUN {rid} FIELD_PATH_NOTE top_level_rows_keys_sample={top[:25]} strategy_path_used=top-level-or-strategy fallback sample_trades_path_used=top-level-or-result fallback')
