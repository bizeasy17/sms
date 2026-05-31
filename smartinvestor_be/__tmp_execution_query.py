import json, traceback
from django.apps import apps
from django.test import RequestFactory
from backtest import views as v

print('FINAL_SUMMARY_BEGIN')
try:
    Run = next((m for m in apps.get_models() if m.__name__ == 'TraditionalBacktestRun'), None)
    if Run is None:
        raise RuntimeError('TraditionalBacktestRun model not found')

    target_run_id = 161 if Run.objects.filter(id=161).exists() else 285

    rf = RequestFactory()
    req_a = rf.get('/?limit=200')
    req_b = rf.get('/?limit=200&force_recompute=1')

    def invoke(req, rid):
        errs = []
        for fn in (
            lambda: v.list_traditional_backtest_run_buy_candidates(req, rid),
            lambda: v.list_traditional_backtest_run_buy_candidates(req, run_id=rid),
            lambda: v.list_traditional_backtest_run_buy_candidates(request=req, run_id=rid),
        ):
            try:
                return fn()
            except Exception as e:
                errs.append(repr(e))
        raise RuntimeError('invoke_failed: ' + ' | '.join(errs))

    def to_rows(data):
        if isinstance(data, dict):
            x = data.get('data')
            if isinstance(x, list):
                return x
            if isinstance(x, dict):
                for k in ('rows','items','data'):
                    y = x.get(k)
                    if isinstance(y, list):
                        return y
            for k in ('rows','items'):
                y = data.get(k)
                if isinstance(y, list):
                    return y
        return []

    def pick(d, key, default=None):
        if not isinstance(d, dict):
            return default
        if key in d:
            return d.get(key)
        m = d.get('meta')
        if isinstance(m, dict) and key in m:
            return m.get(key)
        return default

    def code_set(rows):
        s = set()
        for r in rows:
            if isinstance(r, dict):
                c = r.get('ts_code') or r.get('code') or r.get('symbol')
                if c is not None:
                    s.add(str(c))
        return s

    resp_a = invoke(req_a, target_run_id)
    resp_b = invoke(req_b, target_run_id)

    d_a = getattr(resp_a, 'data', None)
    d_b = getattr(resp_b, 'data', None)

    rows_a = to_rows(d_a)
    rows_b = to_rows(d_b)

    print('RESP_A', json.dumps({
        'ok': pick(d_a, 'ok'),
        'run_id': pick(d_a, 'run_id', target_run_id),
        'total': pick(d_a, 'total', len(rows_a)),
        'force_recompute': pick(d_a, 'force_recompute')
    }, ensure_ascii=False))

    print('RESP_B', json.dumps({
        'ok': pick(d_b, 'ok'),
        'run_id': pick(d_b, 'run_id', target_run_id),
        'total': pick(d_b, 'total', len(rows_b)),
        'force_recompute': pick(d_b, 'force_recompute')
    }, ensure_ascii=False))

    s_a = code_set(rows_a)
    s_b = code_set(rows_b)
    inter = len(s_a & s_b)
    union = len(s_a | s_b)
    j = (inter / union) if union else 0.0
    only_a = sorted(list(s_a - s_b))[:10]
    only_b = sorted(list(s_b - s_a))[:10]

    print('SET_COMPARE', json.dumps({
        'n_a': len(s_a),
        'n_b': len(s_b),
        'intersection': inter,
        'union': union,
        'jaccard': round(j, 6),
        'only_a_top10': only_a,
        'only_b_top10': only_b
    }, ensure_ascii=False))

    parse_out = {
        "'1'": v._parse_bool_or_default('1'),
        "'true'": v._parse_bool_or_default('true'),
        "'0'": v._parse_bool_or_default('0'),
        "None": v._parse_bool_or_default(None),
        "'off'": v._parse_bool_or_default('off'),
        "'on'": v._parse_bool_or_default('on'),
    }
    print('PARSE_BOOL', json.dumps(parse_out, ensure_ascii=False))

except Exception as e:
    print('ERROR', repr(e))
    traceback.print_exc()
print('FINAL_SUMMARY_END')
