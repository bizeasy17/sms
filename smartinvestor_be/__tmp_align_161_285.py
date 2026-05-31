import json, hashlib, inspect
from backtest import views as v

def to_plain(x):
    if isinstance(x, dict):
        return {str(k): to_plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [to_plain(i) for i in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)

def stable_hash(x):
    s = json.dumps(to_plain(x), ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def as_dict(x):
    if x is None:
        return {}
    if isinstance(x, dict):
        return dict(x)
    try:
        return dict(x)
    except Exception:
        return {}

def extract_params(x):
    d = as_dict(x)
    p = d.get('params')
    if isinstance(p, dict):
        return dict(p)
    return d

def diff_dict(a, b):
    out = {}
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        va = a.get(k)
        vb = b.get(k)
        if va != vb:
            out[k] = {'161': to_plain(va), '285': to_plain(vb)}
    return out

def choose_fn():
    fn = getattr(v, 'run_traditional_value_exit_account_backtest', None)
    if fn is not None:
        return fn, 'run_traditional_value_exit_account_backtest'
    fn = getattr(v, 'run_traditional_value_exit_backtest', None)
    if fn is not None:
        return fn, 'run_traditional_value_exit_backtest'
    raise RuntimeError('No backtest runner found')

def filter_kwargs(fn, params):
    sig = inspect.signature(fn)
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if has_varkw:
        return dict(params)
    names = set(sig.parameters.keys())
    return {k: v for k, v in params.items() if k in names}

def run_with_params(fn, params):
    kwargs = filter_kwargs(fn, params)
    return fn(**kwargs)

def find_metric(result, key):
    d = as_dict(result)
    if key == 'final_asset_or_equity':
        for cand in ('final_asset', 'final_equity', 'final_value', 'equity', 'asset'):
            if cand in d:
                return d.get(cand)
        for p in ('summary', 'result', 'metrics', 'meta', 'statistics', 'data'):
            sub = d.get(p)
            if isinstance(sub, dict):
                for cand in ('final_asset', 'final_equity', 'final_value', 'equity', 'asset'):
                    if cand in sub:
                        return sub.get(cand)
        return None
    if key == 'trade_count':
        for cand in ('trade_count', 'trades', 'total_trades'):
            if cand in d:
                return d.get(cand)
        for p in ('summary', 'result', 'metrics', 'meta', 'statistics', 'data'):
            sub = d.get(p)
            if isinstance(sub, dict):
                for cand in ('trade_count', 'trades', 'total_trades'):
                    if cand in sub:
                        return sub.get(cand)
        return None
    if key in d:
        return d.get(key)
    for p in ('summary', 'result', 'metrics', 'meta', 'statistics', 'data'):
        sub = d.get(p)
        if isinstance(sub, dict) and key in sub:
            return sub.get(key)
    return None

def extract_sample_trades(result):
    d = as_dict(result)
    cands = []
    for k in ('sample_trades', 'trades'):
        cands.append(d.get(k))
    for p in ('result', 'summary', 'data', 'meta'):
        sub = d.get(p)
        if isinstance(sub, dict):
            cands.extend([sub.get('sample_trades'), sub.get('trades')])
    for c in cands:
        if isinstance(c, list):
            return c
        if isinstance(c, dict):
            for k in ('trades', 'rows', 'items', 'data'):
                v0 = c.get(k)
                if isinstance(v0, list):
                    return v0
    return []

def trade_key(t):
    if not isinstance(t, dict):
        return str(t)
    def pick(keys):
        for k in keys:
            v0 = t.get(k)
            if v0 not in (None, ''):
                return str(v0)
        return 'NA'
    return '|'.join([
        pick(('ts_code', 'code', 'symbol', 'ticker')),
        pick(('entry_date', 'buy_date', 'open_date', 'signal_date')),
        pick(('exit_date', 'sell_date', 'close_date')),
    ])

resolve = getattr(v, '_resolve_run_payload')
normalize = getattr(v, '_normalize_run_request')
p161 = resolve(161)
p285 = resolve(285)

n161 = extract_params(normalize(as_dict(p161).get('params', {})))
n285 = extract_params(normalize(as_dict(p285).get('params', {})))
n285_aligned = dict(n285)
n285_aligned.update(n161)

fn, fn_name = choose_fn()
r161_new = run_with_params(fn, n161)
r285_aligned_new = run_with_params(fn, n285_aligned)

diff_before = diff_dict(n161, n285)
diff_after = diff_dict(n161, n285_aligned)

h161 = stable_hash(r161_new)
h285 = stable_hash(r285_aligned_new)

metric_names = ['total_return', 'annual_return', 'win_rate', 'max_drawdown', 'sharpe', 'final_asset_or_equity', 'trade_count']
metrics = {}
for m in metric_names:
    v1 = find_metric(r161_new, m)
    v2 = find_metric(r285_aligned_new, m)
    metrics[m] = {'161': to_plain(v1), '285_aligned': to_plain(v2), 'equal': to_plain(v1) == to_plain(v2)}

s161 = extract_sample_trades(r161_new)
s285 = extract_sample_trades(r285_aligned_new)
set161 = {trade_key(t) for t in s161}
set285 = {trade_key(t) for t in s285}
inter = set161 & set285
only161 = set161 - set285
only285 = set285 - set161
union = set161 | set285
jacc = (len(inter) / len(union)) if union else 1.0

def top_diff_fields(a, b, n=5):
    da = as_dict(a)
    db = as_dict(b)
    out = []
    for k in sorted(set(da.keys()) | set(db.keys())):
        va = to_plain(da.get(k))
        vb = to_plain(db.get(k))
        if va != vb:
            out.append({'field': k, '161': va, '285_aligned': vb})
        if len(out) >= n:
            break
    return out

result = {
    'chosen_function': fn_name,
    'diff_before': diff_before,
    'diff_after': diff_after,
    'hash161': h161,
    'hash285_aligned': h285,
    'hash_equal': h161 == h285,
    'metrics': metrics,
    'sample_trades': {
        'count161': len(s161),
        'count285_aligned': len(s285),
        'intersection': len(inter),
        'only161': len(only161),
        'only285_aligned': len(only285),
        'jaccard': jacc,
    },
    'top_diff_fields': top_diff_fields(r161_new, r285_aligned_new, 5),
}

with open('__tmp_align_161_285_result.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))

print('WROTE __tmp_align_161_285_result.json')
