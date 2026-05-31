import inspect, json, re
from copy import deepcopy
from backtest import views as v


def as_dict(x):
    return x if isinstance(x, dict) else {}

def rows_from_any(ret):
    if isinstance(ret, dict):
        for k in ('rows','data','items','candidates','result'):
            vv = ret.get(k)
            if isinstance(vv, list):
                return vv
        if 'payload' in ret and isinstance(ret.get('payload'), dict):
            p = ret['payload']
            for k in ('rows','data','items','candidates'):
                vv = p.get(k)
                if isinstance(vv, list):
                    return vv
        return []
    if isinstance(ret, list):
        return ret
    try:
        return list(ret)
    except Exception:
        return []

def extract_codes(rows):
    out = set()
    for r in rows:
        if isinstance(r, dict):
            c = r.get('ts_code') or r.get('code') or r.get('symbol')
            if c is not None:
                out.add(str(c))
    return out

def jac(a, b):
    u = a | b
    i = a & b
    return (len(i) / len(u)) if u else 0.0, len(i), len(u)

def call_build(payload, max_rows=5000):
    fn = getattr(v, '_build_buyable_universe_rows')
    tries = [
        ((), {'run_payload': payload, 'max_rows': max_rows}),
        ((payload,), {'max_rows': max_rows}),
        ((payload, max_rows), {}),
        ((payload,), {}),
        ((), {'payload': payload, 'max_rows': max_rows}),
        ((), {'params': as_dict(payload).get('params', {}), 'max_rows': max_rows}),
    ]
    last = None
    for args, kwargs in tries:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
    raise RuntimeError('call_build failed: %r' % (last,))

p161 = v._resolve_run_payload(161)
p285 = v._resolve_run_payload(285)

# baseline
r161_raw = call_build(p161, max_rows=5000)
r285_raw = call_build(p285, max_rows=5000)
r161 = rows_from_any(r161_raw)
r285 = rows_from_any(r285_raw)
s161 = extract_codes(r161)
s285 = extract_codes(r285)
j_base, inter_base, uni_base = jac(s161, s285)

# clone 1: params aligned only
p285_clone = deepcopy(p285)
p285_clone = as_dict(p285_clone)
p285_clone['params'] = deepcopy(as_dict(p161).get('params', {}))
r285c_raw = call_build(p285_clone, max_rows=5000)
r285c = rows_from_any(r285c_raw)
s285c = extract_codes(r285c)
j_c_vs_161, inter_c161, uni_c161 = jac(s285c, s161)
j_c_vs_285, inter_c285, uni_c285 = jac(s285c, s285)

# clone 2: strategy top-level aligned too
p285_clone2 = deepcopy(p285_clone)
if 'strategy' in as_dict(p161) or 'strategy' in as_dict(p285_clone2):
    p285_clone2['strategy'] = deepcopy(as_dict(p161).get('strategy'))
r285c2_raw = call_build(p285_clone2, max_rows=5000)
r285c2 = rows_from_any(r285c2_raw)
s285c2 = extract_codes(r285c2)
j_c2_vs_161, inter_c2161, uni_c2161 = jac(s285c2, s161)
j_c2_vs_285, inter_c2285, uni_c2285 = jac(s285c2, s285)

# non-params source diffs
k161 = set(as_dict(p161).keys())
k285 = set(as_dict(p285).keys())
top_only_161 = sorted(k161 - k285)
top_only_285 = sorted(k285 - k161)
top_common = sorted(k161 & k285)

def strat_keys(p):
    s = as_dict(as_dict(p).get('strategy'))
    return set(s.keys())

sk161 = strat_keys(p161)
sk285 = strat_keys(p285)

# simple source scan for result-related accesses
fn = getattr(v, '_build_buyable_universe_rows')
src = inspect.getsource(fn)
lines = src.splitlines()
focus = []
for ln in lines:
    l = ln.strip()
    ll = l.lower()
    if any(x in ll for x in ['result', 'snapshot', 'candidate', 'universe', 'pool', 'params', 'strategy']):
        focus.append(l)

# extract possible keys from get('...') and ['...'] around result-related lines
cand_keys = set()
for l in focus:
    for m in re.findall(r"\.get\(\s*['\"]([^'\"]+)['\"]", l):
        cand_keys.add(m)
    for m in re.findall(r"\[['\"]([^'\"]+)['\"]\]", l):
        cand_keys.add(m)

# compare likely non-params contextual values in payload
non_params_fields = ['result','snapshot','universe','candidate_pool','candidates','as_of_date','trade_date','task_id','run_id','id','strategy']
non_params_diffs = []
for f in non_params_fields:
    v1 = as_dict(p161).get(f, '<MISSING>')
    v2 = as_dict(p285).get(f, '<MISSING>')
    same = (json.dumps(v1, ensure_ascii=False, default=str, sort_keys=True) == json.dumps(v2, ensure_ascii=False, default=str, sort_keys=True))
    if not same:
        non_params_diffs.append(f)

# conclusion rule
# if clone(s) still far from 161 and remain closer to original 285 => non-params context dominates
far_threshold = 0.5
close_threshold = 0.8
if j_c_vs_161 < far_threshold and j_c2_vs_161 < far_threshold and (j_c_vs_285 >= j_c_vs_161 or j_c2_vs_285 >= j_c2_vs_161):
    conclusion = '??????? params ????? result/snapshot/candidate source?'
elif j_c_vs_161 >= close_threshold or j_c2_vs_161 >= close_threshold:
    conclusion = '?????? params'
else:
    conclusion = 'params ?? params ??????? params ??????'

print('FINAL_SUMMARY_BEGIN')
print(f'STEP1 payload_loaded p161_keys={len(k161)} p285_keys={len(k285)}')
print(f'STEP2 baseline N161={len(r161)} N285={len(r285)} S161={len(s161)} S285={len(s285)} INTER={inter_base} UNION={uni_base} JACCARD={j_base:.6f}')
print(f'STEP3 clone_params_only N285C={len(r285c)} S285C={len(s285c)} VS161_INTER={inter_c161} VS161_UNION={uni_c161} VS161_JACCARD={j_c_vs_161:.6f} VS285_INTER={inter_c285} VS285_UNION={uni_c285} VS285_JACCARD={j_c_vs_285:.6f}')
print(f'STEP4 clone_params_plus_strategy N285C2={len(r285c2)} S285C2={len(s285c2)} VS161_INTER={inter_c2161} VS161_UNION={uni_c2161} VS161_JACCARD={j_c2_vs_161:.6f} VS285_INTER={inter_c2285} VS285_UNION={uni_c2285} VS285_JACCARD={j_c2_vs_285:.6f}')
print('STEP5_NON_PARAMS_TOPLEVEL only161=' + json.dumps(top_only_161[:40], ensure_ascii=False))
print('STEP5_NON_PARAMS_TOPLEVEL only285=' + json.dumps(top_only_285[:40], ensure_ascii=False))
print('STEP5_STRATEGY_KEYS only161=' + json.dumps(sorted(sk161 - sk285)[:60], ensure_ascii=False) + ' only285=' + json.dumps(sorted(sk285 - sk161)[:60], ensure_ascii=False))
print('STEP5_SOURCE_SCAN_RESULT_KEYS=' + json.dumps(sorted(cand_keys)[:120], ensure_ascii=False))
print('STEP5_NON_PARAMS_DIFF_FIELDS=' + json.dumps(non_params_diffs, ensure_ascii=False))
print('STEP6_CONCLUSION ' + conclusion)
print('FINAL_SUMMARY_END')
