import json, hashlib, inspect, io, contextlib
from backtest import views as v


def to_plain(x):
    if isinstance(x, dict):
        return {str(k): to_plain(v0) for k, v0 in x.items()}
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


def diff_count(a, b):
    ks = set(a.keys()) | set(b.keys())
    return sum(1 for k in ks if to_plain(a.get(k)) != to_plain(b.get(k)))


def choose_fn():
    fn = getattr(v, 'run_traditional_value_exit_account_backtest', None)
    if callable(fn):
        return fn, 'run_traditional_value_exit_account_backtest'
    fn = getattr(v, 'run_traditional_value_exit_backtest', None)
    if callable(fn):
        return fn, 'run_traditional_value_exit_backtest'
    raise RuntimeError('No backtest runner found')


def filter_kwargs(fn, params):
    sig = inspect.signature(fn)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return dict(params)
    names = set(sig.parameters.keys())
    return {k: v for k, v in params.items() if k in names}


def run_silent(fn, params):
    kwargs = filter_kwargs(fn, params)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(**kwargs)


def find_metric(result, key):
    d = as_dict(result)
    search_objs = [d]
    for p in ('summary', 'result'):
        sub = d.get(p)
        if isinstance(sub, dict):
            search_objs.append(sub)
            sub2 = sub.get('summary')
            if isinstance(sub2, dict):
                search_objs.append(sub2)
    if key == 'trade_count':
        candidates = ('trade_count', 'trades', 'total_trades')
    else:
        candidates = (key,)
    for obj in search_objs:
        for cand in candidates:
            if cand in obj and obj.get(cand) is not None:
                return obj.get(cand)
    return None


def extract_sample_trades(result):
    d = as_dict(result)
    cands = [d.get('sample_trades'), d.get('trades')]
    for p in ('result', 'summary'):
        sub = d.get(p)
        if isinstance(sub, dict):
            cands.extend([sub.get('sample_trades'), sub.get('trades')])
            sub2 = sub.get('summary')
            if isinstance(sub2, dict):
                cands.extend([sub2.get('sample_trades'), sub2.get('trades')])
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

diff_before_count = diff_count(n161, n285)
diff_after_count = diff_count(n161, n285_aligned)

fn, chosen_function = choose_fn()
r161_new = run_silent(fn, n161)
r285_aligned_new = run_silent(fn, n285_aligned)

hash_equal = stable_hash(r161_new) == stable_hash(r285_aligned_new)

metric_names = ['total_return', 'annual_return', 'win_rate', 'max_drawdown', 'trade_count']
metric_eq = {}
for m in metric_names:
    metric_eq[m] = to_plain(find_metric(r161_new, m)) == to_plain(find_metric(r285_aligned_new, m))

s161 = extract_sample_trades(r161_new)
s285 = extract_sample_trades(r285_aligned_new)
set161 = {trade_key(t) for t in s161}
set285 = {trade_key(t) for t in s285}
union = set161 | set285
sample_jaccard = (len(set161 & set285) / len(union)) if union else 1.0

print('FINAL_SUMMARY_BEGIN')
print('chosen_function=' + chosen_function)
print('diff_before_count=' + str(diff_before_count))
print('diff_after_count=' + str(diff_after_count))
print('hash_equal=' + str(hash_equal))
print('total_return_equal=' + str(metric_eq['total_return']))
print('annual_return_equal=' + str(metric_eq['annual_return']))
print('win_rate_equal=' + str(metric_eq['win_rate']))
print('max_drawdown_equal=' + str(metric_eq['max_drawdown']))
print('trade_count_equal=' + str(metric_eq['trade_count']))
print('sample_jaccard=' + str(round(sample_jaccard, 6)))
print('FINAL_SUMMARY_END')
