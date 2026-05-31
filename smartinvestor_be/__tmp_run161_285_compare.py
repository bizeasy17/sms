import json, traceback, inspect, hashlib
from backtest import views as v

print('FINAL_SUMMARY_BEGIN')
try:
    if not hasattr(v, '_resolve_run_payload'):
        raise RuntimeError('_resolve_run_payload not found')
    resolve = v._resolve_run_payload
    build_fn = getattr(v, '_build_buyable_universe_rows', None)

    p161 = resolve(161)
    p285 = resolve(285)

    def to_plain(x):
        try:
            json.dumps(x)
            return x
        except Exception:
            if isinstance(x, dict):
                return {str(k): to_plain(v) for k,v in x.items()}
            if isinstance(x, (list, tuple)):
                return [to_plain(i) for i in x]
            return str(x)

    def stable_hash(x):
        s = json.dumps(to_plain(x), ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        return hashlib.md5(s.encode('ascii', errors='ignore')).hexdigest(), len(s)

    def get_result(payload):
        if isinstance(payload, dict):
            r = payload.get('result')
            if r is not None:
                return r
        return None

    def get_sample_trades(payload, result):
        candidates = []
        if isinstance(result, dict):
            candidates.append(result.get('sample_trades'))
        if isinstance(payload, dict):
            candidates.append(payload.get('sample_trades'))
        for c in candidates:
            if isinstance(c, list):
                return c
            if isinstance(c, dict):
                for k in ('trades','rows','items','data'):
                    v0 = c.get(k)
                    if isinstance(v0, list):
                        return v0
        return []

    r161 = get_result(p161)
    r285 = get_result(p285)

    common_keys = [
        'total_return','annual_return','win_rate','max_drawdown','sharpe','trades','trade_count','final_equity','final_asset','cash','total_pnl','avg_return','avg_holding_days','total_buys','total_sells','strategy','summary'
    ]

    print('PAYLOAD_KEYS', json.dumps({
        '161': sorted(list(p161.keys())) if isinstance(p161, dict) else str(type(p161)),
        '285': sorted(list(p285.keys())) if isinstance(p285, dict) else str(type(p285))
    }, ensure_ascii=True, separators=(',', ':')))
    print('RESULT_PRESENT', json.dumps({'161': r161 is not None, '285': r285 is not None}, ensure_ascii=True, separators=(',', ':')))

    key_cmp = {}
    for k in common_keys:
        v1 = r161.get(k) if isinstance(r161, dict) and k in r161 else None
        v2 = r285.get(k) if isinstance(r285, dict) and k in r285 else None
        if (isinstance(r161, dict) and k in r161) or (isinstance(r285, dict) and k in r285):
            key_cmp[k] = {'161': to_plain(v1), '285': to_plain(v2), 'equal': to_plain(v1) == to_plain(v2)}
    print('RESULT_KEY_COMPARE', json.dumps(key_cmp, ensure_ascii=True, separators=(',', ':')))

    t161 = get_sample_trades(p161, r161)
    t285 = get_sample_trades(p285, r285)

    def pick(d, keys):
        if not isinstance(d, dict):
            return None
        for k in keys:
            v0 = d.get(k)
            if v0 not in (None, ''):
                return v0
        return None

    def tkey(t):
        ts = pick(t, ('ts_code','code','symbol','ticker'))
        ed = pick(t, ('entry_date','buy_date','open_date','signal_date'))
        xd = pick(t, ('exit_date','sell_date','close_date'))
        return (str(ts) if ts is not None else 'NA', str(ed) if ed is not None else 'NA', str(xd) if xd is not None else 'NA')

    def num(x):
        try:
            if x is None or x == '':
                return None
            return float(x)
        except Exception:
            return None

    map161 = {}
    seq161 = []
    for t in t161:
        k = tkey(t)
        seq161.append(k)
        if k not in map161:
            map161[k] = t
    map285 = {}
    seq285 = []
    for t in t285:
        k = tkey(t)
        seq285.append(k)
        if k not in map285:
            map285[k] = t

    s161 = set(map161.keys())
    s285 = set(map285.keys())
    inter = s161 & s285
    only161 = s161 - s285
    only285 = s285 - s161
    union = s161 | s285
    jaccard = (len(inter) / len(union)) if union else 1.0

    seq_equal = (seq161 == seq285)
    first_mismatch = -1
    m = min(len(seq161), len(seq285))
    for i in range(m):
        if seq161[i] != seq285[i]:
            first_mismatch = i
            break
    if first_mismatch == -1 and len(seq161) != len(seq285):
        first_mismatch = m

    pnl_diffs = {}
    for fld in ('pnl_pct','return_pct','profit_pct'):
        vals1 = []
        vals2 = []
        for k in inter:
            a = map161.get(k, {})
            b = map285.get(k, {})
            v1 = num(a.get(fld) if isinstance(a, dict) else None)
            v2 = num(b.get(fld) if isinstance(b, dict) else None)
            if v1 is not None and v2 is not None:
                vals1.append(v1)
                vals2.append(v2)
        if vals1 and vals2:
            mean1 = sum(vals1)/len(vals1)
            mean2 = sum(vals2)/len(vals2)
            pnl_diffs[fld] = {'n': len(vals1), 'mean161': round(mean1, 8), 'mean285': round(mean2, 8), 'delta_161_minus_285': round(mean1-mean2, 8)}

    print('SAMPLE_TRADES_COMPARE', json.dumps({
        'count161': len(t161),
        'count285': len(t285),
        'key_intersection': len(inter),
        'key_only161': len(only161),
        'key_only285': len(only285),
        'jaccard': round(jaccard, 6),
        'seq_equal': seq_equal,
        'first_mismatch_index': first_mismatch,
        'only161_top10': [list(x) for x in sorted(list(only161))[:10]],
        'only285_top10': [list(x) for x in sorted(list(only285))[:10]],
        'intersection_metric_diff': pnl_diffs
    }, ensure_ascii=True, separators=(',', ':')))

    # force_recompute impact check
    h161_before, l161_before = stable_hash(r161)
    h285_before, l285_before = stable_hash(r285)

    build_calls = []
    if build_fn is not None:
        def call_build(payload, rid):
            attempts = [
                lambda: build_fn(payload, max_rows=5000, force_recompute=True),
                lambda: build_fn(payload, force_recompute=True),
                lambda: build_fn(payload, 5000, True),
                lambda: build_fn(payload),
            ]
            errs = []
            for fn in attempts:
                try:
                    fn()
                    return 'ok'
                except TypeError as e:
                    errs.append(repr(e))
            return 'failed:' + '|'.join(errs[:2])
        build_calls.append({'161': call_build(p161, 161)})
        build_calls.append({'285': call_build(p285, 285)})

    p161_after = resolve(161)
    p285_after = resolve(285)
    r161_after = get_result(p161_after)
    r285_after = get_result(p285_after)
    h161_after, l161_after = stable_hash(r161_after)
    h285_after, l285_after = stable_hash(r285_after)

    rewritten161 = (h161_before != h161_after)
    rewritten285 = (h285_before != h285_after)
    force_recompute_rewrites = rewritten161 or rewritten285

    # 161 vs 285 stored result identity
    result_equal_161_285 = (h161_before == h285_before)

    def find_trend_pct(payload, result):
        paths = []
        if isinstance(payload, dict):
            paths.append(payload)
            s = payload.get('strategy')
            if isinstance(s, dict):
                paths.append(s)
            kw = payload.get('kwargs')
            if isinstance(kw, dict):
                paths.append(kw)
        if isinstance(result, dict):
            s = result.get('strategy')
            if isinstance(s, dict):
                paths.append(s)
            sm = result.get('summary')
            if isinstance(sm, dict):
                paths.append(sm)
        for d in paths:
            if 'trend_position_pct' in d:
                return d.get('trend_position_pct')
        return None

    tp161 = find_trend_pct(p161, r161)
    tp285 = find_trend_pct(p285, r285)

    print('FORCE_RECOMPUTE_CHECK', json.dumps({
        'build_fn_found': build_fn is not None,
        'build_calls': build_calls,
        'hash_before': {'161': h161_before, '285': h285_before},
        'hash_after': {'161': h161_after, '285': h285_after},
        'rewritten161': rewritten161,
        'rewritten285': rewritten285,
        'force_recompute_rewrites_existing_result': force_recompute_rewrites
    }, ensure_ascii=True, separators=(',', ':')))

    print('RESULT_EQUALITY', json.dumps({
        'stored_result_equal_161_285': result_equal_161_285,
        'result_hash_161': h161_before,
        'result_hash_285': h285_before,
        'trend_position_pct_161': tp161,
        'trend_position_pct_285': tp285,
        'short_cause_if_diff': 'trend_position_pct differs' if (not result_equal_161_285 and tp161 != tp285) else ('NA' if result_equal_161_285 else 'not_only_trend_position_pct')
    }, ensure_ascii=True, separators=(',', ':')))

except Exception as e:
    print('ERROR', repr(e))
    traceback.print_exc()
print('FINAL_SUMMARY_END')
