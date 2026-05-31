from backtest.views import _resolve_run_payload, _build_buyable_universe_rows

def try_get(obj, path, default=None):
    cur = obj
    for p in path.split('.'):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p, default)
        else:
            cur = getattr(cur, p, default)
    return default if cur is None else cur

def to_rows(x):
    if x is None:
        return []
    if isinstance(x, dict):
        return x.get('rows') or x.get('data') or x.get('items') or []
    return list(x)

for run_id in [161,282,283]:
    payload = _resolve_run_payload(run_id)
    rows = to_rows(_build_buyable_universe_rows(payload, max_rows=3000))
    bcs = try_get(payload, 'result.buy_candidates_summary')
    if bcs is None:
        note = 'NO_CACHE_SUMMARY'
    else:
        c_rows = to_rows(bcs)
        c_set = {r.get('ts_code') for r in c_rows if isinstance(r, dict) and r.get('ts_code')}
        r_set = {r.get('ts_code') for r in rows if isinstance(r, dict) and r.get('ts_code')}
        note = 'RECOMPUTED_FOR_DISPLAY' if (len(c_rows) != len(rows) or c_set != r_set) else 'CACHE_MATCH'
    print(f'RUN {run_id} CACHE_NOTE {note}')
