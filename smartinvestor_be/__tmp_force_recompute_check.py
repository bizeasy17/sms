import json, traceback
from django.apps import apps
from backtest import views as v


def as_list_rows(ret):
    if isinstance(ret, dict):
        for k in ('rows','data','items','candidates','result'):
            vv = ret.get(k)
            if isinstance(vv, list):
                return vv
        p = ret.get('payload')
        if isinstance(p, dict):
            for k in ('rows','data','items','candidates'):
                vv = p.get(k)
                if isinstance(vv, list):
                    return vv
        return []
    if isinstance(ret, list):
        return ret
    try:
        return list(ret)
    except Exception:
        return []


def code_set(rows):
    s = set()
    for r in rows:
        if isinstance(r, dict):
            c = r.get('ts_code') or r.get('code') or r.get('symbol')
            if c is not None:
                s.add(str(c))
    return s

print('FINAL_SUMMARY_BEGIN')
try:
    Run = next((m for m in apps.get_models() if m.__name__ == 'TraditionalBacktestRun'), None)
    if Run is None:
        raise RuntimeError('TraditionalBacktestRun model not found')

    picked = None
    cache_len = 0
    qs = Run.objects.order_by('-id')[:100]
    for run in qs:
        result = getattr(run, 'result', None)
        summary = None
        if isinstance(result, dict):
            summary = result.get('buy_candidates_summary')
        elif isinstance(result, str):
            try:
                rr = json.loads(result)
                if isinstance(rr, dict):
                    summary = rr.get('buy_candidates_summary')
            except Exception:
                summary = None
        if isinstance(summary, list) and len(summary) > 0:
            picked = run
            cache_len = len(summary)
            break

    if picked is None:
        print('STEP1 no_run_found_with_nonempty_buy_candidates_summary_in_latest_100')
    else:
        run_id = picked.id
        print(f'STEP1 run_id={run_id} cache_rows={cache_len}')

        payload = v._resolve_run_payload(run_id)
        print(f'STEP2 payload_type={type(payload).__name__}')

        ret_cache = v._build_buyable_universe_rows(payload, max_rows=500, force_recompute=False)
        ret_recompute = v._build_buyable_universe_rows(payload, max_rows=500, force_recompute=True)

        rows_cache = as_list_rows(ret_cache)
        rows_recompute = as_list_rows(ret_recompute)
        s_cache = code_set(rows_cache)
        s_recompute = code_set(rows_recompute)

        inter = len(s_cache & s_recompute)
        union = len(s_cache | s_recompute)
        jaccard = (inter / union) if union else 0.0
        only_cache = sorted(list(s_cache - s_recompute))
        only_recompute = sorted(list(s_recompute - s_cache))

        print(f'STEP3 n_cache_mode={len(rows_cache)} n_recompute_mode={len(rows_recompute)}')
        print(f'STEP4 ts_intersection={inter} ts_union={union} ts_jaccard={jaccard:.6f}')
        if only_cache or only_recompute:
            print('STEP4_DIFF only_cache_top10=' + json.dumps(only_cache[:10], ensure_ascii=False))
            print('STEP4_DIFF only_recompute_top10=' + json.dumps(only_recompute[:10], ensure_ascii=False))
        else:
            print('STEP4_DIFF none')

        b1 = v._parse_bool_or_default('1')
        b2 = v._parse_bool_or_default('true')
        b3 = v._parse_bool_or_default('0')
        b4 = v._parse_bool_or_default(None)
        print(f"STEP5 parse_bool _parse_bool_or_default('1')={b1} _parse_bool_or_default('true')={b2} _parse_bool_or_default('0')={b3} _parse_bool_or_default(None)={b4}")
except Exception as e:
    print('ERROR', repr(e))
    traceback.print_exc()
print('FINAL_SUMMARY_END')
