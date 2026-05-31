import json, hashlib, inspect
from backtest import views as v

resolve = v._resolve_run_payload
normalize = v._normalize_run_request

p161 = resolve(161)
p285 = resolve(285)


def as_dict(x):
    if isinstance(x, dict):
        return dict(x)
    try:
        return dict(x)
    except Exception:
        return {}


def params_from(payload):
    d = as_dict(payload)
    p = d.get('params')
    if isinstance(p, dict):
        return dict(p)
    return d

n161 = normalize(params_from(p161))
n285 = normalize(params_from(p285))
if not isinstance(n161, dict):
    n161 = as_dict(n161)
if not isinstance(n285, dict):
    n285 = as_dict(n285)

n285_aligned = dict(n285)
n285_aligned.update(dict(n161))

fn = v.run_traditional_value_exit_account_backtest
sig = inspect.signature(fn)
if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
    k161 = dict(n161)
    k285 = dict(n285_aligned)
else:
    allowed = set(sig.parameters.keys())
    k161 = {k: v0 for k, v0 in n161.items() if k in allowed}
    k285 = {k: v0 for k, v0 in n285_aligned.items() if k in allowed}

r161_new = fn(**k161)
r285_aligned_new = fn(**k285)


def to_plain(x):
    if isinstance(x, dict):
        return {str(k): to_plain(v0) for k, v0 in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_plain(i) for i in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def stable_hash(x):
    s = json.dumps(to_plain(x), ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def describe(name, obj):
    print(f'{name}_TYPE', type(obj).__name__)
    if isinstance(obj, (list, tuple)):
        print(f'{name}_LEN', len(obj))
        elem_types = [type(i).__name__ for i in obj]
        print(f'{name}_ELEM_TYPES', elem_types)
        dict_keys = []
        str_elems = []
        for i, e in enumerate(obj):
            if isinstance(e, dict):
                dict_keys.append((i, list(e.keys())[:20]))
            if isinstance(e, str):
                str_elems.append((i, e))
        if dict_keys:
            print(f'{name}_DICT_KEYS', dict_keys)
        if str_elems:
            print(f'{name}_STRING_ELEMS', {'count': len(str_elems), 'values': str_elems[:10]})
    elif isinstance(obj, dict):
        print(f'{name}_DICT_KEYS', list(obj.keys())[:20])


def find_result_dict(obj):
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, (list, tuple)):
        for e in obj:
            if isinstance(e, dict):
                keys = set(e.keys())
                if keys & {'result', 'summary', 'meta', 'data', 'sample_trades', 'trade_count', 'total_return', 'win_rate', 'max_drawdown'}:
                    return e
        for e in obj:
            if isinstance(e, dict):
                return e
    return None


def string_path_seq(obj):
    if isinstance(obj, (list, tuple)):
        return [e for e in obj if isinstance(e, str)]
    return []

print('FINAL_SUMMARY_BEGIN')
describe('R161', r161_new)
describe('R285', r285_aligned_new)

rd161 = find_result_dict(r161_new)
rd285 = find_result_dict(r285_aligned_new)
if rd161 is not None and rd285 is not None:
    print('RESULT_DICT_HASH_EQUAL', stable_hash(rd161) == stable_hash(rd285))
else:
    print('RESULT_DICT_HASH_EQUAL', 'NA')

s161 = string_path_seq(r161_new)
s285 = string_path_seq(r285_aligned_new)
if s161 or s285:
    print('STRING_PATHS_DIFFER', s161 != s285)
else:
    print('STRING_PATHS_DIFFER', 'NA')
print('FINAL_SUMMARY_END')
