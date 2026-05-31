import json
from backtest.views import _resolve_run_payload

def normalize(x):
    if isinstance(x, dict):
        return {str(k): normalize(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (list, tuple)):
        return [normalize(v) for v in x]
    if isinstance(x, set):
        return sorted([normalize(v) for v in x], key=lambda v: json.dumps(v, ensure_ascii=True, sort_keys=True, default=str))
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)

def stable(x):
    return json.dumps(normalize(x), ensure_ascii=True, sort_keys=True, separators=(',', ':'), default=str)

def as_dict(v):
    return v if isinstance(v, dict) else {}

p161 = _resolve_run_payload(161)
p285 = _resolve_run_payload(285)

params161 = as_dict(as_dict(p161).get('params'))
params285 = as_dict(as_dict(p285).get('params'))

keys = sorted(set(params161.keys()) | set(params285.keys()), key=lambda x: str(x))

print('FINAL_SUMMARY_BEGIN')
for k in keys:
    v161 = params161.get(k, '<MISSING>')
    v285 = params285.get(k, '<MISSING>')
    if stable(v161) != stable(v285):
        print('params.{0}|{1}|{2}'.format(k, stable(v161), stable(v285)))
print('FINAL_SUMMARY_END')
