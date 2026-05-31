import json
from collections import Counter
from django.apps import apps
from backtest.views import _resolve_run_payload, _build_buyable_universe_rows

RUN_IDS = [161, 285]
KEYS = [
    'scope','market','mode','start_date','end_date','entry_date_source','valuation_source','band_pct','min_score',
    'risk_level','risk_variant_policy','risk_alignment_mode','valuation_variant','min_netprofit_yoy','min_ebit_yoy',
    'require_positive_prev_netprofit','require_positive_prev_ebit','financial_filter_mode','priority_policy',
    'max_buy_per_day','max_position_pct','valuation_method','valuation_pick_strategy','earnings_report_type'
]

def get_model(name):
    for m in apps.get_models():
        if m.__name__ == name:
            return m
    return None

def as_dict(x):
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    out = {}
    for k in dir(x):
        if k.startswith('_'):
            continue
        try:
            v = getattr(x, k)
            if callable(v):
                continue
            out[k] = v
        except Exception:
            pass
    return out

def to_rows(x):
    if x is None:
        return []
    if isinstance(x, dict):
        return x.get('rows') or x.get('data') or x.get('items') or x.get('candidate_rows') or []
    try:
        return list(x)
    except Exception:
        return []

def choose_field(payload, key):
    p = as_dict(payload)
    params = as_dict(p.get('params'))
    strat = as_dict(p.get('strategy'))
    result = as_dict(p.get('result'))
    for src, d in [('params', params), ('strategy', strat), ('payload', p), ('result', result)]:
        if key in d and d.get(key) is not None:
            return d.get(key), src
    return None, 'NA'

def to_str(v):
    if v is None:
        return 'NA'
    if isinstance(v, float):
        s = ('%.6f' % v).rstrip('0').rstrip('.')
        return s if s else '0'
    if isinstance(v, (list, tuple, set)):
        vals = list(v)
        if len(vals) > 8:
            vals = vals[:8] + ['...']
        return '[' + ','.join(str(x) for x in vals) + ']'
    return str(v)

def parse_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    if len(s) == 8 and s.isdigit():
        return s[:4] + '-' + s[4:6] + '-' + s[6:8]
    return s

def get_ts_and_date_fields(model):
    if model is None:
        return None, None, None
    fset = {f.name for f in model._meta.fields}
    date_field = next((x for x in ['trade_date','date','snapshot_date','dt','asof_date'] if x in fset), None)
    ts_field = next((x for x in ['ts_code','stock_code','code','symbol'] if x in fset), None)
    market_field = next((x for x in ['market','market_code'] if x in fset), None)
    return date_field, ts_field, market_field

def pick_ts_universe(payload, market):
    p = as_dict(payload)
    candidates = []
    for d in [p, as_dict(p.get('params')), as_dict(p.get('strategy')), as_dict(p.get('result'))]:
        for k in ['universe_ts_codes','ts_codes','stock_pool','universe','scope_ts_codes','symbols','stocks','codes']:
            if k in d and d.get(k) is not None:
                candidates.append(d.get(k))
    out = set()
    for c in candidates:
        if isinstance(c, str):
            for x in c.replace(';', ',').split(','):
                x = x.strip()
                if x:
                    out.add(x)
        elif isinstance(c, dict):
            for kk in ['ts_codes','codes','stocks','items','rows','data']:
                vv = c.get(kk)
                if isinstance(vv, (list, tuple, set)):
                    for x in vv:
                        if isinstance(x, dict):
                            t = x.get('ts_code') or x.get('code') or x.get('symbol')
                            if t:
                                out.add(str(t))
                        elif x is not None:
                            out.add(str(x))
        elif isinstance(c, (list, tuple, set)):
            for x in c:
                if isinstance(x, dict):
                    t = x.get('ts_code') or x.get('code') or x.get('symbol')
                    if t:
                        out.add(str(t))
                elif x is not None:
                    out.add(str(x))
    out = {x for x in out if x and x != 'None'}
    if out:
        return out, 'payload_universe'

    Corp = get_model('Corporation')
    if Corp is None:
        return set(), 'no_corporation_model'
    fset = {f.name for f in Corp._meta.fields}
    qs = Corp.objects.all()
    if market and 'market' in fset:
        qs = qs.filter(market=market)
    if 'ts_code' in fset:
        return set(qs.values_list('ts_code', flat=True)), 'fallback_market_corporation'
    if 'code' in fset:
        return set(qs.values_list('code', flat=True)), 'fallback_market_code'
    return set(), 'no_ts_field'

def coverage(model, start_date, end_date, market, universe_codes):
    if model is None:
        return {'date_count': None, 'ts_count': None, 'note': 'model_missing'}
    date_field, ts_field, market_field = get_ts_and_date_fields(model)
    qs = model.objects.all()
    if date_field and start_date:
        qs = qs.filter(**{date_field + '__gte': start_date})
    if date_field and end_date:
        qs = qs.filter(**{date_field + '__lte': end_date})
    if market_field and market:
        qs = qs.filter(**{market_field: market})
    if ts_field and universe_codes:
        qs = qs.filter(**{ts_field + '__in': list(universe_codes)})
    dc = qs.values(date_field).distinct().count() if date_field else None
    tc = qs.values(ts_field).distinct().count() if ts_field else None
    return {'date_count': dc, 'ts_count': tc, 'note': 'ok'}

def ts_set(rows):
    return {r.get('ts_code') for r in rows if isinstance(r, dict) and r.get('ts_code')}

def jacc(a, b):
    u = a | b
    return (len(a & b) / float(len(u))) if u else 0.0

def find_cache_rows(payload):
    p = as_dict(payload)
    result = as_dict(p.get('result'))
    cands = ['candidate_rows','buyable_rows','rows','data','items','candidates']
    found = {}
    rows = []
    for k in cands:
        if k in result and result.get(k) is not None:
            rr = to_rows(result.get(k))
            found[k] = len(rr)
            if not rows and rr:
                rows = rr
    return found, rows

def find_sample_trades(payload):
    p = as_dict(payload)
    result = as_dict(p.get('result'))
    sample = None
    src = 'NA'
    for dname, d in [('result', result), ('payload', p)]:
        for k in ['sample_trades','trades','sample_rows']:
            if k in d and d.get(k) is not None:
                sample = d.get(k)
                src = dname + '.' + k
                break
        if sample is not None:
            break
    if isinstance(sample, str):
        try:
            sample = json.loads(sample)
        except Exception:
            pass
    rows = to_rows(sample)
    return src, len(rows)

def exists_for_ts(model, ts_code, start_date, end_date, market):
    if model is None or not ts_code:
        return False
    date_field, ts_field, market_field = get_ts_and_date_fields(model)
    if ts_field is None:
        return False
    qs = model.objects.filter(**{ts_field: ts_code})
    if date_field and start_date:
        qs = qs.filter(**{date_field + '__gte': start_date})
    if date_field and end_date:
        qs = qs.filter(**{date_field + '__lte': end_date})
    if market_field and market:
        qs = qs.filter(**{market_field: market})
    return qs.exists()

payloads = {rid: _resolve_run_payload(rid) for rid in RUN_IDS}
field_vals = {rid: {} for rid in RUN_IDS}
field_src = {rid: {} for rid in RUN_IDS}
for rid in RUN_IDS:
    for k in KEYS:
        v, s = choose_field(payloads[rid], k)
        field_vals[rid][k] = v
        field_src[rid][k] = s

StockTradingHistory = get_model('StockTradingHistory')
ValuationRiskSnapshot = get_model('ValuationRiskSnapshot')
StockValuationSnapshotHistory = get_model('StockValuationSnapshotHistory') or get_model('StockValuationSnapshot')
Corporation = get_model('Corporation')
RunModel = get_model('TraditionalBacktestRun')

run_objs = {}
if RunModel is not None:
    for rid in RUN_IDS:
        run_objs[rid] = RunModel.objects.filter(id=rid).first()

run_data = {}
for rid in RUN_IDS:
    market = field_vals[rid].get('market')
    start_date = parse_date(field_vals[rid].get('start_date'))
    end_date = parse_date(field_vals[rid].get('end_date'))
    universe, uni_note = pick_ts_universe(payloads[rid], market)
    rebuilt = to_rows(_build_buyable_universe_rows(payloads[rid], max_rows=5000))
    rebuilt_set = ts_set(rebuilt)
    cov_trade = coverage(StockTradingHistory, start_date, end_date, None, universe)
    cov_risk = coverage(ValuationRiskSnapshot, start_date, end_date, market, universe)
    cov_val = coverage(StockValuationSnapshotHistory, start_date, end_date, market, universe)
    cache_fields, cache_rows = find_cache_rows(payloads[rid])
    cache_set = ts_set(cache_rows)
    sample_src, sample_n = find_sample_trades(payloads[rid])

    p = as_dict(payloads[rid])
    strategy = as_dict(p.get('strategy'))
    result = as_dict(p.get('result'))
    run = run_objs.get(rid)

    def pick_any(dlist, keys):
        for d in dlist:
            for k in keys:
                if d.get(k) is not None:
                    return d.get(k), k
        return None, 'NA'

    batch_v, batch_k = pick_any([p, as_dict(p.get('params')), strategy, result], ['batch_key','batch_id','batch'])
    asof_v, asof_k = pick_any([p, as_dict(p.get('params')), strategy, result], ['asof','asof_date','valuation_asof','snapshot_date','data_asof'])
    version_v, version_k = pick_any([strategy, p, result], ['version','strategy_version','engine_version'])

    run_data[rid] = {
        'market': market,
        'start_date': start_date,
        'end_date': end_date,
        'universe_n': len(universe),
        'universe_note': uni_note,
        'rebuilt_rows': rebuilt,
        'rebuilt_set': rebuilt_set,
        'cov_trade': cov_trade,
        'cov_risk': cov_risk,
        'cov_val': cov_val,
        'cache_fields': cache_fields,
        'cache_rows': cache_rows,
        'cache_set': cache_set,
        'cache_vs_rebuilt_j': jacc(rebuilt_set, cache_set),
        'sample_src': sample_src,
        'sample_n': sample_n,
        'created_at': getattr(run, 'created_at', None) if run is not None else None,
        'updated_at': getattr(run, 'updated_at', None) if run is not None else None,
        'strategy_obj': getattr(run, 'strategy', None) if run is not None else None,
        'version': version_v,
        'version_key': version_k,
        'batch': batch_v,
        'batch_key': batch_k,
        'asof': asof_v,
        'asof_key': asof_k,
    }

set161 = run_data[161]['rebuilt_set']
set285 = run_data[285]['rebuilt_set']
inter = len(set161 & set285)
only161 = sorted(set161 - set285)
only285 = sorted(set285 - set161)
jac = jacc(set161, set285)

params_equal = all(str(field_vals[161].get(k)) == str(field_vals[285].get(k)) for k in KEYS)
diff_keys = [k for k in KEYS if str(field_vals[161].get(k)) != str(field_vals[285].get(k))]

attribution = None
if params_equal and (len(only161) + len(only285) > 0):
    r161 = run_data[161]
    r285 = run_data[285]
    sample161 = only161[:20]
    sample285 = only285[:20]

    miss = {
        'only161_in_285_window': {'risk_missing': 0, 'val_missing': 0, 'n': len(sample161)},
        'only285_in_161_window': {'risk_missing': 0, 'val_missing': 0, 'n': len(sample285)}
    }

    for ts in sample161:
        has_risk = exists_for_ts(ValuationRiskSnapshot, ts, r285['start_date'], r285['end_date'], r285['market'])
        has_val = exists_for_ts(StockValuationSnapshotHistory, ts, r285['start_date'], r285['end_date'], r285['market'])
        if not has_risk:
            miss['only161_in_285_window']['risk_missing'] += 1
        if not has_val:
            miss['only161_in_285_window']['val_missing'] += 1

    for ts in sample285:
        has_risk = exists_for_ts(ValuationRiskSnapshot, ts, r161['start_date'], r161['end_date'], r161['market'])
        has_val = exists_for_ts(StockValuationSnapshotHistory, ts, r161['start_date'], r161['end_date'], r161['market'])
        if not has_risk:
            miss['only285_in_161_window']['risk_missing'] += 1
        if not has_val:
            miss['only285_in_161_window']['val_missing'] += 1

    top161 = []
    top285 = []
    ind_field = 'NA'
    if Corporation is not None:
        fset = {f.name for f in Corporation._meta.fields}
        ind_field = next((x for x in ['sw_l1_name','industry','industry_name','sw_industry_l1','csrc_industry_name'] if x in fset), None)
        if ind_field:
            if only161:
                c1 = Counter(str(x) if x else 'UNKNOWN' for x in Corporation.objects.filter(ts_code__in=only161).values_list(ind_field, flat=True))
                top161 = c1.most_common(10)
            if only285:
                c2 = Counter(str(x) if x else 'UNKNOWN' for x in Corporation.objects.filter(ts_code__in=only285).values_list(ind_field, flat=True))
                top285 = c2.most_common(10)
        else:
            ind_field = 'no_industry_field'

    attribution = {'missing': miss, 'industry_field': ind_field, 'top161': top161, 'top285': top285}

snapshot_diff = False
if params_equal:
    a1 = str(run_data[161]['asof'])
    a2 = str(run_data[285]['asof'])
    b1 = str(run_data[161]['batch'])
    b2 = str(run_data[285]['batch'])
    c1 = str(run_data[161]['created_at'])
    c2 = str(run_data[285]['created_at'])
    u1 = str(run_data[161]['updated_at'])
    u2 = str(run_data[285]['updated_at'])
    snapshot_diff = (a1 != a2) or (b1 != b2) or (c1 != c2) or (u1 != u2)

print('FINAL_SUMMARY_BEGIN')
print('SECTION1_FIELD_DIFF')
print('field|161|src161|285|src285|diff')
for k in KEYS:
    v1 = to_str(field_vals[161].get(k)); s1 = field_src[161].get(k)
    v2 = to_str(field_vals[285].get(k)); s2 = field_src[285].get(k)
    diff = 'Y' if v1 != v2 else 'N'
    print('%s|%s|%s|%s|%s|%s' % (k, v1, s1, v2, s2, diff))

print('SECTION2_BUYABLE_SET')
print('N161=%s N285=%s inter=%s only161=%s only285=%s jaccard=%.6f' % (len(set161), len(set285), inter, len(only161), len(only285), jac))

print('SECTION3_COVERAGE')
for rid in RUN_IDS:
    d = run_data[rid]
    print('RUN %s universe_n=%s universe_note=%s trade(date,ts)=(%s,%s) risk(date,ts)=(%s,%s) val(date,ts)=(%s,%s)' % (
        rid, d['universe_n'], d['universe_note'],
        to_str(d['cov_trade']['date_count']), to_str(d['cov_trade']['ts_count']),
        to_str(d['cov_risk']['date_count']), to_str(d['cov_risk']['ts_count']),
        to_str(d['cov_val']['date_count']), to_str(d['cov_val']['ts_count'])
    ))

print('SECTION4_CACHE_HIT')
for rid in RUN_IDS:
    d = run_data[rid]
    print('RUN %s cache_fields=%s sample_trades_src=%s sample_trades_n=%s rebuilt_n=%s cache_rows_n=%s cache_vs_rebuilt_jaccard=%.6f' % (
        rid, d['cache_fields'], d['sample_src'], d['sample_n'], len(d['rebuilt_set']), len(d['cache_set']), d['cache_vs_rebuilt_j']
    ))

print('SECTION5_RUNTIME_METADATA')
for rid in RUN_IDS:
    d = run_data[rid]
    print('RUN %s created_at=%s updated_at=%s strategy=%s version[%s]=%s batch[%s]=%s asof[%s]=%s' % (
        rid, to_str(d['created_at']), to_str(d['updated_at']), to_str(d['strategy_obj']), d['version_key'], to_str(d['version']), d['batch_key'], to_str(d['batch']), d['asof_key'], to_str(d['asof'])
    ))
print('SNAPSHOT_JUDGMENT same_params=%s snapshot_time_diff=%s' % (params_equal, snapshot_diff))

print('SECTION6_ATTRIBUTION')
if attribution is None:
    print('SKIPPED reason=params_not_identical_or_no_diff diff_keys=%s' % diff_keys)
else:
    m = attribution['missing']
    n1 = max(1, m['only161_in_285_window']['n'])
    n2 = max(1, m['only285_in_161_window']['n'])
    print('MISSING_CHECK only161_sample_n=%s risk_missing=%s(%.2f%%) val_missing=%s(%.2f%%)' % (
        m['only161_in_285_window']['n'], m['only161_in_285_window']['risk_missing'], 100.0*m['only161_in_285_window']['risk_missing']/n1,
        m['only161_in_285_window']['val_missing'], 100.0*m['only161_in_285_window']['val_missing']/n1
    ))
    print('MISSING_CHECK only285_sample_n=%s risk_missing=%s(%.2f%%) val_missing=%s(%.2f%%)' % (
        m['only285_in_161_window']['n'], m['only285_in_161_window']['risk_missing'], 100.0*m['only285_in_161_window']['risk_missing']/n2,
        m['only285_in_161_window']['val_missing'], 100.0*m['only285_in_161_window']['val_missing']/n2
    ))
    print('INDUSTRY_TOP10 field=%s only161=%s only285=%s' % (attribution['industry_field'], attribution['top161'], attribution['top285']))

print('SECTION7_ROOT_CAUSE_RANKED')
confirmed = []
inferred = []
if diff_keys:
    confirmed.append('?????: %s' % ','.join(diff_keys[:12]))
if len(only161) + len(only285) > 0:
    confirmed.append('???????: N161=%s N285=%s only161=%s only285=%s jaccard=%.4f' % (len(set161), len(set285), len(only161), len(only285), jac))
if run_data[161]['cache_vs_rebuilt_j'] < 0.999 or run_data[285]['cache_vs_rebuilt_j'] < 0.999:
    inferred.append('?????????????cache???????')
else:
    inferred.append('?????????????????????/????')
if params_equal and snapshot_diff:
    confirmed.append('???????/????')
elif params_equal and not snapshot_diff:
    inferred.append('??????????????????????')
if attribution is not None:
    m = attribution['missing']
    n1 = max(1, m['only161_in_285_window']['n']); n2 = max(1, m['only285_in_161_window']['n'])
    r1 = 100.0*m['only161_in_285_window']['risk_missing']/n1
    v1 = 100.0*m['only161_in_285_window']['val_missing']/n1
    r2 = 100.0*m['only285_in_161_window']['risk_missing']/n2
    v2 = 100.0*m['only285_in_161_window']['val_missing']/n2
    if max(r1, v1, r2, v2) >= 20:
        confirmed.append('only?????????risk/valuation??(>=20%)???????????')
    else:
        inferred.append('only??????????/???????????')

ranked = []
for x in confirmed:
    ranked.append(('???', x))
for x in inferred:
    ranked.append(('??', x))
for i, (tag, msg) in enumerate(ranked[:3], 1):
    print('%s) [%s] %s' % (i, tag, msg))

print('FINAL_SUMMARY_END')
