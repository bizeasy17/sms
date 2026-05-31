import json, inspect, hashlib, traceback, ast
from copy import deepcopy
from backtest import views as v
from backtest import services as s


def stable(x):
    def norm(o):
        if isinstance(o, dict):
            return {str(k): norm(v) for k, v in sorted(o.items(), key=lambda kv: str(kv[0]))}
        if isinstance(o, (list, tuple)):
            return [norm(i) for i in o]
        if isinstance(o, set):
            return sorted([norm(i) for i in o], key=lambda z: json.dumps(z, ensure_ascii=True, sort_keys=True, default=str))
        if isinstance(o, (str, int, float, bool)) or o is None:
            return o
        return str(o)
    return json.dumps(norm(x), ensure_ascii=True, sort_keys=True, separators=(',', ':'), default=str)

def as_dict(x):
    return x if isinstance(x, dict) else {}

def diff_dict(a, b):
    a = as_dict(a); b = as_dict(b)
    keys = sorted(set(a.keys()) | set(b.keys()), key=lambda x: str(x))
    out = []
    for k in keys:
        va = a.get(k, '<MISSING>')
        vb = b.get(k, '<MISSING>')
        if stable(va) != stable(vb):
            out.append((k, va, vb))
    return out

required = [
    ('views', '_resolve_run_payload', getattr(v, '_resolve_run_payload', None)),
    ('views', '_extract_params_from_result', getattr(v, '_extract_params_from_result', None)),
    ('views', '_normalize_run_request', getattr(v, '_normalize_run_request', None)),
    ('views', '_run_one_task_item', getattr(v, '_run_one_task_item', None)),
    ('services', 'run_traditional_value_exit_backtest', getattr(s, 'run_traditional_value_exit_backtest', None)),
    ('services', 'run_traditional_value_exit_account_backtest', getattr(s, 'run_traditional_value_exit_account_backtest', None)),
]

source_meta = []
for mod, name, fn in required:
    if fn is None:
        source_meta.append((mod, name, 'MISSING', 'MISSING', 'MISSING'))
        continue
    try:
        src = inspect.getsource(fn)
        file = inspect.getsourcefile(fn)
        line = inspect.getsourcelines(fn)[1]
        h = hashlib.sha1(src.encode('utf-8', 'ignore')).hexdigest()[:12]
        source_meta.append((mod, name, file, line, h))
    except Exception as e:
        source_meta.append((mod, name, 'ERR', 'ERR', str(e)))

# load payloads
p161 = v._resolve_run_payload(161)
p285 = v._resolve_run_payload(285)
raw161 = as_dict(as_dict(p161).get('params'))
raw285 = as_dict(as_dict(p285).get('params'))

# normalize via API-like entry
class DummyReq:
    method = 'POST'
    def __init__(self, params):
        self.data = params
        self.GET = params
        self.query_params = params


def call_normalize(params):
    fn = getattr(v, '_normalize_run_request')
    req = DummyReq(params)
    tries = [
        ((params,), {}),
        ((req, params), {}),
        ((), {'params': params}),
        ((), {'request': req, 'params': params}),
        ((req,), {}),
    ]
    last = None
    for args, kwargs in tries:
        try:
            r = fn(*args, **kwargs)
            return r
        except Exception as e:
            last = e
    raise RuntimeError('normalize failed: %r' % (last,))

n161_raw = call_normalize(deepcopy(raw161))
n285_raw = call_normalize(deepcopy(raw285))

# normalize result shape
n161 = as_dict(n161_raw)
n285 = as_dict(n285_raw)
if isinstance(n161.get('params'), dict):
    n161_params = n161.get('params')
else:
    n161_params = n161
if isinstance(n285.get('params'), dict):
    n285_params = n285.get('params')
else:
    n285_params = n285

# try capture effective kwargs through _run_one_task_item
capture = {'161': {'bt': None, 'acct': None, 'err': None}, '285': {'bt': None, 'acct': None, 'err': None}}
orig = {
    'v_bt': getattr(v, 'run_traditional_value_exit_backtest', None),
    'v_ac': getattr(v, 'run_traditional_value_exit_account_backtest', None),
    's_bt': getattr(s, 'run_traditional_value_exit_backtest', None),
    's_ac': getattr(s, 'run_traditional_value_exit_account_backtest', None),
}

current_run = {'id': None}

def fake_bt(*args, **kwargs):
    capture[str(current_run['id'])]['bt'] = {'args_len': len(args), 'kwargs': kwargs}
    return {'ok': True, 'source': 'fake_bt'}

def fake_ac(*args, **kwargs):
    capture[str(current_run['id'])]['acct'] = {'args_len': len(args), 'kwargs': kwargs}
    return {'ok': True, 'source': 'fake_acct'}

for k in ['run_traditional_value_exit_backtest', 'run_traditional_value_exit_account_backtest']:
    if hasattr(v, k):
        setattr(v, k, fake_bt if k.endswith('_backtest') and 'account' not in k else fake_ac)
    if hasattr(s, k):
        setattr(s, k, fake_bt if k.endswith('_backtest') and 'account' not in k else fake_ac)


def call_run_one(run_id, payload, nparams):
    fn = getattr(v, '_run_one_task_item')
    sig = inspect.signature(fn)
    req = DummyReq(nparams)
    task_item = {'run_id': run_id, 'id': run_id, 'params': nparams, 'payload': payload, 'result': {'params': nparams}}

    attempts = []
    attempts.append(((task_item,), {}))
    attempts.append(((payload,), {}))
    attempts.append(((run_id, task_item), {}))
    attempts.append(((run_id, payload), {}))

    kw = {}
    for pn, p in sig.parameters.items():
        if pn in ('task_item', 'item', 'task', 'job_item'):
            kw[pn] = task_item
        elif pn in ('run_id', 'id'):
            kw[pn] = run_id
        elif pn in ('payload', 'run_payload'):
            kw[pn] = payload
        elif pn in ('params', 'normalized_params', 'run_params'):
            kw[pn] = nparams
        elif pn in ('request', 'req'):
            kw[pn] = req
        elif p.default is inspect._empty:
            kw[pn] = None
    attempts.append(((), kw))

    last = None
    for args, kwargs in attempts:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
    raise RuntimeError('run_one failed: %r' % (last,))

for rid, pp, nn in [(161, p161, n161_params), (285, p285, n285_params)]:
    current_run['id'] = rid
    try:
        call_run_one(rid, pp, nn)
    except Exception as e:
        capture[str(rid)]['err'] = str(e)

# restore
for name, val in orig.items():
    if val is None:
        continue
    if name.startswith('v_'):
        setattr(v, 'run_traditional_value_exit_backtest' if name.endswith('bt') else 'run_traditional_value_exit_account_backtest', val)
    else:
        setattr(s, 'run_traditional_value_exit_backtest' if name.endswith('bt') else 'run_traditional_value_exit_account_backtest', val)

# fallback effective kwargs by signature-key intersection
sig_bt = list(inspect.signature(s.run_traditional_value_exit_backtest).parameters.keys()) if hasattr(s, 'run_traditional_value_exit_backtest') else []
sig_ac = list(inspect.signature(s.run_traditional_value_exit_account_backtest).parameters.keys()) if hasattr(s, 'run_traditional_value_exit_account_backtest') else []

def effective_from_capture_or_fallback(rid, nparams):
    c = capture[str(rid)]
    out = {'bt': {}, 'acct': {}, 'mode': ''}
    if c.get('bt') and isinstance(c['bt'], dict):
        out['bt'] = as_dict(c['bt'].get('kwargs'))
    if c.get('acct') and isinstance(c['acct'], dict):
        out['acct'] = as_dict(c['acct'].get('kwargs'))
    if out['bt'] or out['acct']:
        out['mode'] = 'captured_via__run_one_task_item'
        return out
    out['mode'] = 'fallback_signature_intersection'
    out['bt'] = {k: nparams.get(k) for k in sig_bt if k in nparams}
    out['acct'] = {k: nparams.get(k) for k in sig_ac if k in nparams}
    return out

e161 = effective_from_capture_or_fallback(161, n161_params)
e285 = effective_from_capture_or_fallback(285, n285_params)

# classify keys
raw_diff = diff_dict(raw161, raw285)
norm_diff = diff_dict(n161_params, n285_params)
eff_bt_diff = diff_dict(e161['bt'], e285['bt'])
eff_ac_diff = diff_dict(e161['acct'], e285['acct'])

def smoothed_fields(raw_diffs, n1, n2):
    out = []
    for k, v1, v2 in raw_diffs:
        if stable(n1.get(k, '<MISSING>')) == stable(n2.get(k, '<MISSING>')):
            out.append((k, n1.get(k, '<MISSING>')))
    return out

smoothed = smoothed_fields(raw_diff, n161_params, n285_params)

pool_keywords = ('universe','pool','candidate','filter','risk','valuation','pb','pe','roe','market_cap','industry','board','st','suspended','limit','blacklist','whitelist','score','discount')
manage_keywords = ('take_profit','stop_loss','trend','position','rebalance','hold','exit','atr','drawdown','max_position','min_position')

def classify_key(k):
    lk = str(k).lower()
    if any(t in lk for t in pool_keywords):
        return 'POOL'
    if any(t in lk for t in manage_keywords):
        return 'POSITION_MGMT'
    return 'OTHER'

changed_norm_class = [(k, classify_key(k), v1, v2) for k,v1,v2 in norm_diff]

# concise outputs
print('FINAL_SUMMARY_BEGIN')
print('SOURCE_FUNCTIONS')
for mod,name,file,line,h in source_meta:
    print(f'{mod}.{name}|file={file}|line={line}|sha={h}')

print('A_RAW_PARAMS_DIFF_COUNT', len(raw_diff))
for k,v1,v2 in raw_diff[:30]:
    print('A|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))

print('B_NORMALIZED_PARAMS_DIFF_COUNT', len(norm_diff))
for k,v1,v2 in norm_diff[:30]:
    print('B|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))

print('C_EFFECTIVE_KWARGS_MODE', e161['mode'], e285['mode'])
print('C_EFFECTIVE_BT_DIFF_COUNT', len(eff_bt_diff))
for k,v1,v2 in eff_bt_diff[:30]:
    print('C_BT|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))
print('C_EFFECTIVE_ACCT_DIFF_COUNT', len(eff_ac_diff))
for k,v1,v2 in eff_ac_diff[:30]:
    print('C_AC|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))

print('SMOOTHED_FIELDS_COUNT', len(smoothed))
for k,v in smoothed[:30]:
    print('SMOOTHED|{0}|{1}'.format(k, stable(v)))

pool_changed = [x for x in changed_norm_class if x[1]=='POOL']
mgmt_changed = [x for x in changed_norm_class if x[1]=='POSITION_MGMT']
print('POOL_CHANGED_COUNT', len(pool_changed))
for k,cls,v1,v2 in pool_changed[:20]:
    print('POOL|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))
print('POSITION_MGMT_CHANGED_COUNT', len(mgmt_changed))
for k,cls,v1,v2 in mgmt_changed[:20]:
    print('MGMT|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))

consistent = (len(eff_bt_diff)==0 and len(eff_ac_diff)==0)
print('CONSISTENT_EFFECTIVE_KWARGS', 'YES' if consistent else 'NO')
if not consistent:
    ex = (eff_bt_diff + eff_ac_diff)[:5]
    for k,v1,v2 in ex:
        print('EVIDENCE|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))
else:
    if len(raw_diff)>0 and len(norm_diff)==0:
        k,v1,v2 = raw_diff[0]
        print('EVIDENCE|raw_diff_but_normalized_equal|{0}|{1}|{2}'.format(k, stable(v1), stable(v2)))
    elif len(raw_diff)==0:
        print('EVIDENCE|all_equal_raw_normalized_effective')
    else:
        print('EVIDENCE|effective_equal_despite_nonzero_raw_or_norm_diffs')

print('FINAL_SUMMARY_END')
