import json
from collections import Counter
from django.apps import apps
from backtest.views import _resolve_run_payload, _build_buyable_universe_rows

RUN_IDS = [161, 282, 283]
KEYS = [
    'scope','market','mode','start_date','end_date','entry_date_source','valuation_source','band_pct','min_score',
    'risk_level','risk_variant_policy','risk_alignment_mode','valuation_variant',
    'min_netprofit_yoy','min_ebit_yoy','require_positive_prev_netprofit','require_positive_prev_ebit',
    'financial_filter_mode','priority_policy','max_buy_per_day','max_position_pct'
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

def choose_field(payload, key):
    p = as_dict(payload)
    params = as_dict(p.get('params'))
    strat = as_dict(p.get('strategy'))
    if key in params and params.get(key) is not None:
        return params.get(key), 'params'
    if key in strat and strat.get(key) is not None:
        return strat.get(key), 'strategy'
    if key in p and p.get(key) is not None:
        return p.get(key), 'payload'
    rp = as_dict(p.get('result'))
    if key in rp and rp.get(key) is not None:
        return rp.get(key), 'result'
    return None, 'NA'

def to_str(v):
    if v is None:
        return 'NA'
    if isinstance(v, float):
        return ('%.4f' % v).rstrip('0').rstrip('.') if '.' in ('%.4f' % v) else ('%.4f' % v)
    if isinstance(v, (list, tuple, set)):
        vals = list(v)
        if len(vals) > 6:
            vals = vals[:6] + ['...']
        return '[' + ','.join(str(x) for x in vals) + ']'
    return str(v)

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
            s = c.replace(';',',').split(',')
            for x in s:
                x = x.strip()
                if '.' in x or x.isdigit() or len(x) >= 6:
                    out.add(x)
        elif isinstance(c, dict):
            for kk in ['ts_codes','codes','stocks','items']:
                vv = c.get(kk)
                if isinstance(vv, (list,tuple,set)):
                    for x in vv:
                        if isinstance(x, dict):
                            t = x.get('ts_code') or x.get('code')
                            if t:
                                out.add(str(t))
                        else:
                            out.add(str(x))
        elif isinstance(c, (list,tuple,set)):
            for x in c:
                if isinstance(x, dict):
                    t = x.get('ts_code') or x.get('code')
                    if t:
                        out.add(str(t))
                else:
                    out.add(str(x))
    out = {x for x in out if x and x != 'None'}
    note = 'payload_universe'
    if out:
        return out, note

    Corp = get_model('Corporation')
    if Corp is None:
        return set(), 'no_corporation_model'
    fields = {f.name for f in Corp._meta.fields}
    qs = Corp.objects.all()
    if market and 'market' in fields:
        qs = qs.filter(market=market)
    if 'ts_code' in fields:
        return set(qs.values_list('ts_code', flat=True)), 'fallback_market_corporation'
    if 'code' in fields:
        return set(qs.values_list('code', flat=True)), 'fallback_market_code'
    return set(), 'no_ts_field'

def parse_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    if len(s) == 8 and s.isdigit():
        return s[:4] + '-' + s[4:6] + '-' + s[6:8]
    return s

def coverage(model, start_date, end_date, market, universe_codes):
    if model is None:
        return {'date_count': None, 'ts_count': None, 'note': 'model_missing'}
    fset = {f.name for f in model._meta.fields}
    date_field = None
    for c in ['trade_date','date','snapshot_date','dt']:
        if c in fset:
            date_field = c
            break
    ts_field = None
    for c in ['ts_code','stock_code','code']:
        if c in fset:
            ts_field = c
            break
    market_field = None
    for c in ['market','market_code']:
        if c in fset:
            market_field = c
            break

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

def to_rows(x):
    if x is None:
        return []
    if isinstance(x, dict):
        return x.get('rows') or x.get('data') or x.get('items') or []
    return list(x)

def rows_summary(rows):
    seen = set()
    ts10 = []
    date_vals = []
    date_keys = ['first_hit_date','last_hit_date','first_hit_trade_date','last_hit_trade_date','latest_hit_date','hit_date']
    for r in rows:
        if not isinstance(r, dict):
            continue
        ts = r.get('ts_code')
        if ts and ts not in seen:
            seen.add(ts)
            if len(ts10) < 10:
                ts10.append(ts)
        for k in date_keys:
            v = r.get(k)
            if v:
                date_vals.append(str(v)[:10])
    dmin = min(date_vals) if date_vals else 'NA'
    dmax = max(date_vals) if date_vals else 'NA'
    return {'N': len(rows), 'hit_min': dmin, 'hit_max': dmax, 'ts10': ts10}

payloads = {rid: _resolve_run_payload(rid) for rid in RUN_IDS}
field_vals = {rid: {} for rid in RUN_IDS}
field_srcs = {rid: {} for rid in RUN_IDS}
for rid in RUN_IDS:
    for k in KEYS:
        v, src = choose_field(payloads[rid], k)
        field_vals[rid][k] = v
        field_srcs[rid][k] = src

StockTradingHistory = get_model('StockTradingHistory')
ValuationRiskSnapshot = get_model('ValuationRiskSnapshot')
StockValuationSnapshotHistory = get_model('StockValuationSnapshotHistory') or get_model('StockValuationSnapshot')
Corporation = get_model('Corporation')

run_data = {}
for rid in RUN_IDS:
    market = field_vals[rid].get('market')
    start_date = parse_date(field_vals[rid].get('start_date'))
    end_date = parse_date(field_vals[rid].get('end_date'))
    uni, uni_note = pick_ts_universe(payloads[rid], market)

    cov_trade = coverage(StockTradingHistory, start_date, end_date, None, uni)
    cov_risk = coverage(ValuationRiskSnapshot, start_date, end_date, market, uni)
    cov_val = coverage(StockValuationSnapshotHistory, start_date, end_date, market, uni)

    rows = to_rows(_build_buyable_universe_rows(payloads[rid], max_rows=3000))
    rs = rows_summary(rows)
    run_data[rid] = {
        'universe_n': len(uni), 'universe_note': uni_note,
        'cov_trade': cov_trade, 'cov_risk': cov_risk, 'cov_val': cov_val,
        'rows': rows, 'rows_summary': rs,
    }

set161 = {r.get('ts_code') for r in run_data[161]['rows'] if isinstance(r, dict) and r.get('ts_code')}
set282 = {r.get('ts_code') for r in run_data[282]['rows'] if isinstance(r, dict) and r.get('ts_code')}
set283 = {r.get('ts_code') for r in run_data[283]['rows'] if isinstance(r, dict) and r.get('ts_code')}
only161_282 = sorted(set161 - set282)

industry_note = 'sw_l1_name'
ind_counter = Counter()
if Corporation is not None and only161_282:
    fset = {f.name for f in Corporation._meta.fields}
    q = Corporation.objects.filter(ts_code__in=only161_282) if 'ts_code' in fset else Corporation.objects.none()
    ind_field = None
    for c in ['sw_l1_name','industry','industry_name','sw_industry_l1','csrc_industry_name']:
        if c in fset:
            ind_field = c
            break
    if ind_field:
        for x in q.values_list(ind_field, flat=True):
            ind_counter[str(x) if x else 'UNKNOWN'] += 1
        industry_note = ind_field
    else:
        nm_field = 'name' if 'name' in fset else ('short_name' if 'short_name' in fset else None)
        if nm_field:
            for x in q.values_list(nm_field, flat=True):
                s = (str(x) if x else 'UNKNOWN')
                ind_counter[s[:2]] += 1
            industry_note = 'fallback_name_prefix2'
        else:
            industry_note = 'no_industry_no_name_field'

# diffs
param_diffs_161_282 = [k for k in KEYS if str(field_vals[161].get(k)) != str(field_vals[282].get(k))]
param_diffs_161_283 = [k for k in KEYS if str(field_vals[161].get(k)) != str(field_vals[283].get(k))]

inter_161_282 = len(set161 & set282)
union_161_282 = len(set161 | set282)
j_161_282 = (float(inter_161_282) / union_161_282) if union_161_282 else 0.0
inter_161_283 = len(set161 & set283)
union_161_283 = len(set161 | set283)
j_161_283 = (float(inter_161_283) / union_161_283) if union_161_283 else 0.0

print('FINAL_SUMMARY_BEGIN')
print('SECTION1_FIELD_DIFF')
print('field|161|282|283|diff')
for k in KEYS:
    v161 = to_str(field_vals[161].get(k))
    v282 = to_str(field_vals[282].get(k))
    v283 = to_str(field_vals[283].get(k))
    diff = 'Y' if not (v161 == v282 == v283) else 'N'
    print('%s|%s|%s|%s|%s' % (k, v161, v282, v283, diff))

print('SECTION2_COVERAGE')
for rid in RUN_IDS:
    d = run_data[rid]
    print('RUN %s universe_n=%s universe_note=%s trade_days=%s risk_days=%s risk_ts=%s val_days=%s val_ts=%s' % (
        rid, d['universe_n'], d['universe_note'],
        to_str(d['cov_trade']['date_count']),
        to_str(d['cov_risk']['date_count']), to_str(d['cov_risk']['ts_count']),
        to_str(d['cov_val']['date_count']), to_str(d['cov_val']['ts_count'])
    ))

print('SECTION3_BUYABLE_ROWS')
for rid in RUN_IDS:
    rs = run_data[rid]['rows_summary']
    print('RUN %s N=%s hit_range=%s..%s ts10=%s' % (rid, rs['N'], rs['hit_min'], rs['hit_max'], to_str(rs['ts10'])))

print('SECTION4_ONLY_161_VS_282')
print('only161_count=%s only282_count=%s inter=%s jaccard=%.4f industry_field=%s top10=%s' % (
    len(set161 - set282), len(set282 - set161), inter_161_282, j_161_282, industry_note, ind_counter.most_common(10)
))

print('SECTION5_TOP3_EVIDENCE')
print('1) candidate_set_divergence: 161vs282 only161=%s only282=%s inter=%s jaccard=%.4f; 161vs283 only161=%s only283=%s inter=%s jaccard=%.4f' % (
    len(set161 - set282), len(set282 - set161), inter_161_282, j_161_282,
    len(set161 - set283), len(set283 - set161), inter_161_283, j_161_283
))
print('2) key_param_diff_count: 161vs282=%s (%s); 161vs283=%s (%s)' % (
    len(param_diffs_161_282), ','.join(param_diffs_161_282[:12]), len(param_diffs_161_283), ','.join(param_diffs_161_283[:12])
))
print('3) data_coverage_delta(161-282): trade_days=%s risk_days=%s risk_ts=%s val_days=%s val_ts=%s' % (
    (run_data[161]['cov_trade']['date_count'] or 0) - (run_data[282]['cov_trade']['date_count'] or 0),
    (run_data[161]['cov_risk']['date_count'] or 0) - (run_data[282]['cov_risk']['date_count'] or 0),
    (run_data[161]['cov_risk']['ts_count'] or 0) - (run_data[282]['cov_risk']['ts_count'] or 0),
    (run_data[161]['cov_val']['date_count'] or 0) - (run_data[282]['cov_val']['date_count'] or 0),
    (run_data[161]['cov_val']['ts_count'] or 0) - (run_data[282]['cov_val']['ts_count'] or 0)
))
print('FINAL_SUMMARY_END')
