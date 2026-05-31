import json, hashlib
from backtest.views import _resolve_run_payload

CORE_KEYS = [
    'scope','market','mode','start_date','end_date','entry_date_source','valuation_source','band_pct','min_score',
    'risk_level','risk_variant_policy','risk_alignment_mode','valuation_variant','min_netprofit_yoy','min_ebit_yoy',
    'financial_filter_mode','priority_policy','max_buy_per_day','max_position_pct','valuation_method',
    'valuation_pick_strategy','earnings_report_type'
]

def normalize(x):
    if isinstance(x, dict):
        return {str(k): normalize(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (list, tuple)):
        return [normalize(v) for v in x]
    if isinstance(x, set):
        return sorted([normalize(v) for v in x], key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, default=str))
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)

def stable(x):
    return json.dumps(normalize(x), ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)

def layer(d, key):
    v = d.get(key)
    return v if isinstance(v, dict) else {}

def payload_top(d):
    p = d.get('payload')
    if not isinstance(p, dict):
        return {}
    return {k: v for k, v in p.items() if k != 'result'}

def get_core_value(d, key):
    for sec in ('params', 'strategy'):
        s = d.get(sec)
        if isinstance(s, dict) and key in s:
            return s.get(key)
    p = d.get('payload')
    if isinstance(p, dict) and key in p and key != 'result':
        return p.get(key)
    return None

p161 = _resolve_run_payload(161)
p285 = _resolve_run_payload(285)

params161, params285 = layer(p161, 'params'), layer(p285, 'params')
strategy161, strategy285 = layer(p161, 'strategy'), layer(p285, 'strategy')
payload161, payload285 = payload_top(p161), payload_top(p285)

diffs = []
for sec_name, a, b in [
    ('params', params161, params285),
    ('strategy', strategy161, strategy285),
    ('payload', payload161, payload285),
]:
    keys = sorted(set(a.keys()) | set(b.keys()), key=lambda x: str(x))
    for k in keys:
        va = a.get(k, '<MISSING>')
        vb = b.get(k, '<MISSING>')
        if stable(va) != stable(vb):
            diffs.append((f'{sec_name}.{k}', va, vb))

diffs.sort(key=lambda t: t[0])

h161_obj = {'params': params161, 'strategy': strategy161, 'payload_top': payload161}
h285_obj = {'params': params285, 'strategy': strategy285, 'payload_top': payload285}
h161 = hashlib.sha256(stable(h161_obj).encode('utf-8')).hexdigest()
h285 = hashlib.sha256(stable(h285_obj).encode('utf-8')).hexdigest()

print('FINAL_SUMMARY_BEGIN')
print('PARAM_DIFF_BEGIN')
for path, v161, v285 in diffs:
    print(f'{path}|{stable(v161)}|{stable(v285)}')
print('PARAM_DIFF_END')

print('SAME_CORE_KEYS_CHECK')
for k in CORE_KEYS:
    v161 = get_core_value(p161, k)
    v285 = get_core_value(p285, k)
    same = (stable(v161) == stable(v285))
    print(f'{k}|same={str(same).lower()}|v161={stable(v161)}|v285={stable(v285)}')

print(f'PAYLOAD_HASH|run=161|sha256={h161}')
print(f'PAYLOAD_HASH|run=285|sha256={h285}')
print('FINAL_SUMMARY_END')
