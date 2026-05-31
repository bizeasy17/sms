import json, traceback, inspect
from collections import Counter
from django.apps import apps
from backtest import views as v

print('FINAL_SUMMARY_BEGIN')
try:
    if not hasattr(v, '_resolve_run_payload'):
        raise RuntimeError('_resolve_run_payload not found in backtest.views')
    if not hasattr(v, '_build_buyable_universe_rows'):
        raise RuntimeError('_build_buyable_universe_rows not found in backtest.views')

    resolve_fn = v._resolve_run_payload
    build_fn = v._build_buyable_universe_rows

    p161 = resolve_fn(161)
    p285 = resolve_fn(285)

    def call_build(payload):
        attempts = [
            lambda: build_fn(payload, max_rows=5000, force_recompute=True),
            lambda: build_fn(payload, 5000, True),
            lambda: build_fn(payload, max_rows=5000),
            lambda: build_fn(payload, force_recompute=True),
            lambda: build_fn(payload),
        ]
        errs = []
        for fn in attempts:
            try:
                return fn(), None
            except TypeError as e:
                errs.append(repr(e))
            except Exception:
                raise
        raise RuntimeError('build_call_failed: ' + ' | '.join(errs))

    rows161_raw, build_note_161 = call_build(p161)
    rows285_raw, build_note_285 = call_build(p285)

    def normalize_rows(obj):
        if isinstance(obj, dict):
            for k in ('rows','data','items'):
                v0 = obj.get(k)
                if isinstance(v0, list):
                    return v0
            data = obj.get('data')
            if isinstance(data, dict):
                for k in ('rows','items','data'):
                    v0 = data.get(k)
                    if isinstance(v0, list):
                        return v0
            return []
        try:
            return list(obj)
        except Exception:
            return []

    rows161 = normalize_rows(rows161_raw)
    rows285 = normalize_rows(rows285_raw)

    def row_code(row):
        if not isinstance(row, dict):
            return None
        for k in ('ts_code','code','symbol'):
            v0 = row.get(k)
            if v0:
                return str(v0)
        corp = row.get('corporation')
        if isinstance(corp, dict):
            for k in ('ts_code','code','symbol'):
                v0 = corp.get(k)
                if v0:
                    return str(v0)
        return None

    map161 = {}
    map285 = {}
    for r in rows161:
        c = row_code(r)
        if c and c not in map161:
            map161[c] = r
    for r in rows285:
        c = row_code(r)
        if c and c not in map285:
            map285[c] = r

    s161 = set(map161.keys())
    s285 = set(map285.keys())
    inter = s161 & s285
    only161 = s161 - s285
    only285 = s285 - s161
    union = s161 | s285
    jaccard = (len(inter) / len(union)) if union else 0.0

    corp_model = next((m for m in apps.get_models() if m.__name__ == 'Corporation'), None)
    corp_field_note = []
    corp_map = {}

    def pick_industry_from_row(row):
        if not isinstance(row, dict):
            return None, None
        if row.get('sw_l1_name'):
            return row.get('sw_l1_name'), 'row.sw_l1_name'
        if row.get('industry'):
            return row.get('industry'), 'row.industry'
        if row.get('industry_name'):
            return row.get('industry_name'), 'row.industry_name'
        corp = row.get('corporation')
        if isinstance(corp, dict):
            if corp.get('sw_l1_name'):
                return corp.get('sw_l1_name'), 'row.corporation.sw_l1_name'
            if corp.get('industry'):
                return corp.get('industry'), 'row.corporation.industry'
            if corp.get('industry_name'):
                return corp.get('industry_name'), 'row.corporation.industry_name'
        return None, None

    sample_note = None
    for sample_row in list(map161.values())[:3] + list(map285.values())[:3]:
        ind, src = pick_industry_from_row(sample_row)
        if src:
            sample_note = 'industry_source_detected=' + src
            break

    if corp_model is not None:
        field_names = {f.name for f in corp_model._meta.get_fields() if getattr(f, 'concrete', False)}
        code_field = None
        for cand in ('ts_code','code','symbol'):
            if cand in field_names:
                code_field = cand
                break
        ind_field = None
        for cand in ('sw_l1_name','industry','industry_name'):
            if cand in field_names:
                ind_field = cand
                break
        corp_field_note.append('Corporation_code_field=' + str(code_field))
        corp_field_note.append('Corporation_industry_field=' + str(ind_field))
        if code_field and ind_field:
            all_codes = sorted(list(s161 | s285))
            qs = corp_model.objects.filter(**{code_field + '__in': all_codes}).values(code_field, ind_field)
            for rec in qs:
                code_val = rec.get(code_field)
                ind_val = rec.get(ind_field)
                if code_val is not None and ind_val not in (None, ''):
                    corp_map[str(code_val)] = ind_val
        else:
            corp_field_note.append('Corporation_fallback_unavailable_missing_fields')
    else:
        corp_field_note.append('Corporation_model_not_found')

    def industry_for_code(code, row_map):
        row = row_map.get(code)
        ind, src = pick_industry_from_row(row)
        if ind not in (None, ''):
            return str(ind), src
        if code in corp_map:
            return str(corp_map[code]), 'Corporation_fallback'
        return 'UNKNOWN', 'missing'

    def top_industry(code_set, row_map):
        ctr = Counter()
        src_ctr = Counter()
        for code in code_set:
            ind, src = industry_for_code(code, row_map)
            ctr[ind] += 1
            src_ctr[src] += 1
        return ctr.most_common(10), dict(src_ctr)

    top_only161, src_only161 = top_industry(only161, map161)
    top_only285, src_only285 = top_industry(only285, map285)
    top_inter, src_inter = top_industry(inter, map161)

    notes = []
    if sample_note:
        notes.append(sample_note)
    notes.extend(corp_field_note)
    if build_note_161:
        notes.append('build161=' + build_note_161)
    if build_note_285:
        notes.append('build285=' + build_note_285)

    print('COUNTS', json.dumps({
        'N161': len(s161),
        'N285': len(s285),
        'intersection': len(inter),
        'only161': len(only161),
        'only285': len(only285),
        'jaccard': round(jaccard, 6)
    }, ensure_ascii=True, separators=(',', ':')))
    print('ONLY161_TOP30', json.dumps(sorted(list(only161))[:30], ensure_ascii=True, separators=(',', ':')))
    print('ONLY285_TOP30', json.dumps(sorted(list(only285))[:30], ensure_ascii=True, separators=(',', ':')))
    print('INDUSTRY_ONLY161_TOP10', json.dumps(top_only161, ensure_ascii=True, separators=(',', ':')))
    print('INDUSTRY_ONLY285_TOP10', json.dumps(top_only285, ensure_ascii=True, separators=(',', ':')))
    print('INDUSTRY_INTERSECTION_TOP10', json.dumps(top_inter, ensure_ascii=True, separators=(',', ':')))
    print('INDUSTRY_SOURCE_ONLY161', json.dumps(src_only161, ensure_ascii=True, separators=(',', ':')))
    print('INDUSTRY_SOURCE_ONLY285', json.dumps(src_only285, ensure_ascii=True, separators=(',', ':')))
    print('INDUSTRY_SOURCE_INTERSECTION', json.dumps(src_inter, ensure_ascii=True, separators=(',', ':')))
    print('FALLBACK_NOTES', json.dumps(notes, ensure_ascii=True, separators=(',', ':')))
except Exception as e:
    print('ERROR', repr(e))
    traceback.print_exc()
print('FINAL_SUMMARY_END')
