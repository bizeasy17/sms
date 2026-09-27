from __future__ import annotations

import math
from typing import Any

SCORING_VERSION = 'topn-dimension-v2'
FEATURE_SCHEMA_VERSION = 'metrics-feature-schema-v1'
MAPPING_VERSION = 'metrics-feature-map-v1'
NORMALIZATION_VERSION = 'metrics-feature-transform-v1'
DIMENSION_WEIGHT_VERSION = 'topn-dimension-weights-v1'
PROFILE_VERSION = 'topn-profile-generic-v1'

DIMENSIONS = (
    {'key': 'growth_momentum', 'name': '增长动能', 'weight': 0.18, 'explanation': '收入与利润增长趋势以及持续性'},
    {'key': 'profitability_quality', 'name': '盈利质量', 'weight': 0.18, 'explanation': '回报能力与利润结构质量'},
    {'key': 'cashflow_resilience', 'name': '现金流韧性', 'weight': 0.16, 'explanation': '经营、投资、筹资现金流的承压能力'},
    {'key': 'balance_sheet_safety', 'name': '资产负债安全', 'weight': 0.16, 'explanation': '杠杆水平与偿债安全边际'},
    {'key': 'valuation_position', 'name': '估值与市场位置', 'weight': 0.16, 'explanation': '估值水平与市场定价位置'},
    {'key': 'operation_efficiency', 'name': '经营效率与周转', 'weight': 0.16, 'explanation': '资产周转与经营效率表现'},
)

OPERATION_TURNOVER_KEYS = {'assets_turn', 'turnover_lb_mean', 'turnover_rate', 'turnover_rate_ind_rank'}
NON_FINANCIAL_CONTEXT_KEYS = {'close', 'fiscal_year', 'ann_date_lag_days', 'report_type_code'}


def _feature_entries(
    keys: tuple[str, ...],
    dimension: str,
    unit: str,
    transform: str,
    business_direction: str,
    *,
    scoreable: bool = True,
) -> dict[str, dict[str, Any]]:
    return {
        key: {
            'dimension': dimension,
            'unit': unit,
            'transform': transform,
            'business_direction': business_direction,
            'scoreable': scoreable,
        }
        for key in keys
    }


FEATURE_SCHEMA: dict[str, dict[str, Any]] = {}
FEATURE_SCHEMA.update(_feature_entries(
    ('or_yoy', 'tr_yoy', 'netprofit_yoy'), 'growth_momentum', 'percentage_point',
    'growth_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('revenue',), 'growth_momentum', 'CNY', 'revenue_size_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('ret_lb', 'ret_5d'), 'growth_momentum', 'percentage_point',
    'return_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('roe',), 'profitability_quality', 'percentage_point', 'roe_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('roe_dt',), 'profitability_quality', 'percentage_point', 'roe_dt_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('q_dt_roe',), 'profitability_quality', 'percentage_point', 'quarterly_roe_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('roa',), 'profitability_quality', 'percentage_point', 'roa_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('netprofit_margin', 'gross_margin', 'grossprofit_margin'), 'profitability_quality',
    'percentage_point', 'margin_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('basic_eps', 'diluted_eps'), 'profitability_quality', 'CNY_per_share',
    'eps_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('operate_profit', 'n_income', 'n_income_attr_p'), 'profitability_quality', 'CNY',
    'evidence_only', 'not_scored', scoreable=False,
))
FEATURE_SCHEMA.update(_feature_entries(
    ('n_cashflow_act', 'n_cashflow_inv_act', 'n_cash_flows_fnc_act', 'n_incr_cash_cash_equ', 'free_cashflow'),
    'cashflow_resilience', 'CNY', 'cash_amount_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('ocf_to_or',), 'cashflow_resilience', 'percentage_point', 'cashflow_ratio_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('ocf_yoy',), 'cashflow_resilience', 'percentage_point', 'growth_percent_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('debt_to_assets',), 'balance_sheet_safety', 'percentage_point',
    'debt_percent_v1', 'lower_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('assets_to_eqt',), 'balance_sheet_safety', 'ratio', 'leverage_multiple_v1', 'lower_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('current_ratio', 'quick_ratio', 'cash_ratio'), 'balance_sheet_safety', 'ratio',
    'liquidity_ratio_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('total_liab', 'total_assets', 'st_borr', 'lt_borr', 'total_hldr_eqy_exc_min_int'),
    'balance_sheet_safety', 'CNY', 'evidence_only', 'not_scored', scoreable=False,
))
FEATURE_SCHEMA.update(_feature_entries(
    ('pe', 'pe_ttm'), 'valuation_position', 'multiple', 'pe_multiple_v1', 'lower_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('pb',), 'valuation_position', 'multiple', 'pb_multiple_v1', 'lower_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('ps',), 'valuation_position', 'multiple', 'ps_multiple_v1', 'lower_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('pe_ind_rank', 'pb_ind_rank', 'ps_ind_rank', 'pe_rank_120d'),
    'valuation_position', 'rank_fraction_0_1', 'rank_low_better_v1', 'lower_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('ret_lb_ind_rank', 'ret_5d_ind_rank'), 'valuation_position',
    'rank_fraction_0_1', 'rank_high_better_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('dv_ttm',), 'valuation_position', 'percentage_point', 'dividend_yield_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('total_mv', 'circ_mv'), 'valuation_position', '10k_CNY',
    'evidence_only', 'not_scored', scoreable=False,
))
FEATURE_SCHEMA.update(_feature_entries(
    ('industry_code',), 'valuation_position', 'category_code',
    'evidence_only', 'not_scored', scoreable=False,
))
FEATURE_SCHEMA.update(_feature_entries(
    ('assets_turn',), 'operation_efficiency', 'ratio', 'assets_turn_v1', 'higher_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('turnover_lb_mean', 'turnover_rate'), 'operation_efficiency', 'percentage_point',
    'evidence_only', 'non_monotonic', scoreable=False,
))
FEATURE_SCHEMA.update(_feature_entries(
    ('turnover_rate_ind_rank',), 'operation_efficiency', 'rank_fraction_0_1',
    'rank_low_better_v1', 'lower_better',
))
FEATURE_SCHEMA.update(_feature_entries(
    ('accounts_receiv', 'inventories'), 'operation_efficiency', 'CNY',
    'evidence_only', 'not_scored', scoreable=False,
))

FEATURE_ALIASES = {
    'gross_margin': ('grossprofit_margin',),
    'grossprofit_margin': ('gross_margin',),
}

TRANSFORM_RANGES = {
    'growth_percent_v1': (-50.0, 100.0, False),
    'return_percent_v1': (-30.0, 30.0, False),
    'roe_percent_v1': (0.0, 25.0, False),
    'roe_dt_percent_v1': (0.0, 20.0, False),
    'quarterly_roe_percent_v1': (-10.0, 20.0, False),
    'roa_percent_v1': (0.0, 15.0, False),
    'margin_percent_v1': (-5.0, 40.0, False),
    'eps_v1': (-50.0, 100.0, False),
    'cashflow_ratio_percent_v1': (-20.0, 50.0, False),
    'debt_percent_v1': (20.0, 90.0, True),
    'leverage_multiple_v1': (1.0, 10.0, True),
    'liquidity_ratio_v1': (0.0, 3.0, False),
    'pe_multiple_v1': (5.0, 80.0, True),
    'pb_multiple_v1': (0.5, 10.0, True),
    'ps_multiple_v1': (0.5, 10.0, True),
    'dividend_yield_v1': (0.0, 8.0, False),
    'assets_turn_v1': (0.0, 2.0, False),
}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _normalize_feature_score(transform: str, value: float) -> float | None:
    if transform in {'cash_amount_v1', 'revenue_size_v1'}:
        return _clamp(50.0 + math.tanh(value / 1e9) * 50.0)
    if transform == 'rank_low_better_v1':
        return _clamp((1.0 - value) * 100.0) if 0.0 <= value <= 1.0 else None
    if transform == 'rank_high_better_v1':
        return _clamp(value * 100.0) if 0.0 <= value <= 1.0 else None
    bounds = TRANSFORM_RANGES.get(transform)
    if bounds is None:
        return None
    low, high, invert = bounds
    if high <= low:
        return None
    normalized = (value - low) * 100.0 / (high - low)
    if invert:
        normalized = 100.0 - normalized
    return _clamp(normalized)


def _feature_candidates(key: str) -> list[str]:
    return [key, *FEATURE_ALIASES.get(key, ())]


def _lookup_value(feature_key: str, values: dict[str, Any]) -> tuple[Any, str]:
    for candidate in _feature_candidates(feature_key.lower()):
        if candidate in values:
            return values[candidate], candidate
    return None, ''


def attach_feature_hints(payload: dict[str, Any], top_features: list[dict[str, Any]]) -> None:
    for dimension in payload.get('dimension_scores', []):
        evidence = dimension.get('evidence') or {}
        values = {str(key).lower(): value for key, value in evidence.items()}
        hints = []
        for feature in top_features:
            key = str(feature.get('feature_key') or '').strip()
            if not key:
                continue
            _, matched = _lookup_value(key, values)
            if matched:
                hints.append({
                    'rank': feature.get('rank'), 'feature_key': key,
                    'feature_label': feature.get('feature_label'), 'weight': feature.get('weight'),
                    'direction': feature.get('direction'), 'matched_evidence_key': matched,
                })
        dimension['model_feature_hints'] = hints[:3]
        dimension['model_feature_hint_count'] = len(hints)


def rebuild_score(
    payload: dict[str, Any],
    top_features: list[dict[str, Any]],
    score_topn: int,
    feature_values: dict[str, Any] | None = None,
    normalized_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, raw_value in (feature_values or {}).items():
        values[str(key).strip().lower()] = raw_value
    for dimension in payload.get('dimension_scores', []):
        for key, raw_value in (dimension.get('evidence') or {}).items():
            values.setdefault(str(key).strip().lower(), raw_value)

    selected = []
    seen = set()
    for feature in top_features:
        key = str(feature.get('feature_key') or '').strip()
        normalized_key = key.lower()
        if not normalized_key or normalized_key == 'fiscal_year' or normalized_key in seen:
            continue
        selected.append(feature)
        seen.add(normalized_key)
        if len(selected) >= score_topn:
            break

    operation_count = sum(
        1 for feature in selected
        if str(feature.get('feature_key') or '').strip().lower() in OPERATION_TURNOVER_KEYS
    )
    if operation_count < 2:
        operation_candidates = [
            feature for feature in top_features
            if str(feature.get('feature_key') or '').strip().lower() in OPERATION_TURNOVER_KEYS
            and str(feature.get('feature_key') or '').strip().lower() not in seen
        ]
        for candidate in operation_candidates:
            if operation_count >= 2:
                break
            replaceable = [
                feature for feature in selected
                if str(feature.get('feature_key') or '').strip().lower() not in OPERATION_TURNOVER_KEYS
            ]
            if not replaceable:
                break

            def replace_priority(feature):
                key = str(feature.get('feature_key') or '').strip().lower()
                try:
                    weight = abs(float(feature.get('weight') or 0.0))
                except (TypeError, ValueError):
                    weight = 0.0
                if key in NON_FINANCIAL_CONTEXT_KEYS or key == 'industry_code':
                    return (0, weight)
                if key.endswith('_ind_rank') or key.endswith('_rank_120d'):
                    return (1, weight)
                return (2, weight)

            victim = min(replaceable, key=replace_priority)
            victim_key = str(victim.get('feature_key') or '').strip().lower()
            selected[selected.index(victim)] = candidate
            seen.remove(victim_key)
            candidate_key = str(candidate.get('feature_key') or '').strip().lower()
            seen.add(candidate_key)
            operation_count += 1

    items_by_dimension: dict[str, list[dict[str, Any]]] = {item['key']: [] for item in DIMENSIONS}
    mappings = []
    unmapped_features = []
    scored_feature_count = 0
    scored_model_weight = 0.0
    selected_model_weight = 0.0
    for feature in selected:
        key = str(feature.get('feature_key') or '').strip()
        normalized_key = key.lower()
        schema = FEATURE_SCHEMA.get(normalized_key)
        dimension = schema['dimension'] if schema else None
        raw_value, matched_key = _lookup_value(normalized_key, values)
        try:
            value = float(raw_value) if raw_value is not None and str(raw_value).strip() else None
        except (TypeError, ValueError):
            value = None
        value_status = 'MISSING' if raw_value is None or not str(raw_value).strip() else 'AVAILABLE'
        if value_status == 'AVAILABLE' and (value is None or not math.isfinite(value)):
            value_status = 'INVALID'

        unit_conversion = 'identity'
        canonical_value = value if value_status == 'AVAILABLE' else None
        input_unit = schema['unit'] if schema else None
        if normalized_key == 'debt_to_assets' and value_status == 'AVAILABLE' and abs(value) <= 1.0:
            canonical_value = value * 100.0
            unit_conversion = 'ratio_to_percentage_point'
            input_unit = 'ratio'

        mapping_status = 'MAPPED' if schema else 'UNMAPPED'
        score_status = 'UNMAPPED' if not schema else value_status if value_status in {'MISSING', 'INVALID'} else 'NOT_SCORED'
        transform = schema['transform'] if schema else None
        normalized_score = None
        if schema and value_status == 'AVAILABLE':
            if not schema['scoreable']:
                score_status = 'EVIDENCE_ONLY'
            else:
                normalized_score = _normalize_feature_score(transform, canonical_value)
                if normalized_score is None:
                    value_status = 'INVALID'
                    score_status = 'INVALID'
                else:
                    override = (normalized_overrides or {}).get(normalized_key)
                    try:
                        override = float(override) if override is not None else None
                    except (TypeError, ValueError):
                        override = None
                    if override is not None and math.isfinite(override) and 0.0 <= override <= 100.0:
                        normalized_score = override
                    score_status = 'SCORED'

        try:
            weight = float(feature.get('weight') or 0.0)
            direction = 1 if int(feature.get('direction') or 1) >= 0 else -1
        except (TypeError, ValueError):
            weight, direction = 0.0, 1
        if not math.isfinite(weight):
            weight = 0.0
        if score_status == 'SCORED':
            scored_feature_count += 1
            scored_model_weight += abs(weight)
        selected_model_weight += abs(weight)

        item = {
            'rank': feature.get('rank', 0),
            'feature_key': key,
            'feature_label': feature.get('feature_label') or key,
            'feature_value': value if value_status == 'AVAILABLE' else None,
            'raw_value': raw_value if value_status == 'AVAILABLE' else None,
            'canonical_value': canonical_value,
            'unit': schema['unit'] if schema else None,
            'input_unit': input_unit,
            'unit_conversion': unit_conversion,
            'weight': weight,
            'model_weight': weight,
            'direction': direction,
            'predictive_direction': direction,
            'business_direction': schema['business_direction'] if schema else None,
            'matched_dimension': dimension,
            'mapping_status': mapping_status,
            'matched_rule': 'explicit' if schema else 'unmapped',
            'matched_evidence_key': matched_key,
            'value_status': value_status,
            'score_status': score_status,
            'transform_id': transform,
            'normalized_score': round(normalized_score, 4) if normalized_score is not None else None,
            'contribution_score': (
                round((normalized_score - 50) * abs(weight) * direction, 6)
                if normalized_score is not None else None
            ),
        }
        mappings.append({
            'feature_key': key,
            'dimension': dimension,
            'mapping_status': mapping_status,
            'rule': 'explicit' if schema else 'unmapped',
            'unit': schema['unit'] if schema else None,
            'transform_id': transform,
        })
        if dimension:
            items_by_dimension[dimension].append(item)
        else:
            unmapped_features.append(item)

    if payload.get('stock_type') == 'finance_realestate':
        def append_derived(key, value, dimension, rule, sources, normalized_score=None):
            if value is None or not math.isfinite(value):
                return
            item = {
                'rank': 0,
                'feature_key': key,
                'feature_label': key,
                'feature_value': value,
                'raw_value': value,
                'canonical_value': value,
                'unit': 'percentage_point',
                'input_unit': 'percentage_point',
                'unit_conversion': 'derived',
                'weight': 0.0,
                'model_weight': 0.0,
                'direction': 1,
                'predictive_direction': 1,
                'business_direction': 'higher_better',
                'matched_dimension': dimension,
                'mapping_status': 'DERIVED',
                'matched_rule': rule,
                'matched_evidence_key': ','.join(sources),
                'value_status': 'AVAILABLE',
                'score_status': 'SCORED',
                'transform_id': 'bank_ratio_v1',
                'normalized_score': round(_clamp(value if normalized_score is None else normalized_score), 4),
                'contribution_score': 0.0,
            }
            items_by_dimension[dimension].append(item)
            mappings.append({
                'feature_key': key,
                'dimension': dimension,
                'mapping_status': 'DERIVED',
                'rule': rule,
                'unit': 'percentage_point',
                'transform_id': 'bank_ratio_v1',
            })

        def number(key):
            try:
                value = float(values.get(key))
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) else None

        total_revenue = number('total_revenue')
        total_profit = number('total_profit')
        total_assets = number('total_assets')
        money_cap = number('money_cap')
        operating_cashflow = number('n_cashflow_act')
        operation_target = max(1, len(items_by_dimension['operation_efficiency']))
        operation_derived = []
        if total_profit is not None and total_revenue:
            operation_derived.append(('bank_profit_to_revenue_ratio', total_profit * 100.0 / total_revenue, ('total_profit', 'total_revenue')))
        if total_revenue is not None and total_assets:
            operation_derived.append(('bank_revenue_to_assets_ratio', total_revenue * 100.0 / total_assets, ('total_revenue', 'total_assets')))
        if total_assets is not None and total_assets != 0:
            equity = number('total_hldr_eqy_exc_min_int')
            if equity is not None:
                operation_derived.append(('bank_equity_to_assets_ratio', equity * 100.0 / total_assets, ('total_hldr_eqy_exc_min_int', 'total_assets')))
        short_borrowing = number('st_borr') or 0.0
        long_borrowing = number('lt_borr') or 0.0
        if money_cap is not None and short_borrowing + long_borrowing > 0:
            operation_derived.append(('bank_cash_to_borrow_ratio', money_cap * 100.0 / (short_borrowing + long_borrowing), ('money_cap', 'st_borr', 'lt_borr')))
        items_by_dimension['operation_efficiency'] = []
        for key, value, sources in operation_derived[:operation_target]:
            append_derived(key, value, 'operation_efficiency', 'bank_derived_from_existing_dims', sources)

        cashflow_target = max(1, len(items_by_dimension['cashflow_resilience']))
        cashflow_derived = []
        if operating_cashflow is not None and total_revenue:
            cashflow_derived.append(('bank_ocf_to_revenue_ratio', operating_cashflow * 100.0 / total_revenue, ('n_cashflow_act', 'total_revenue')))
        if money_cap is not None and total_assets:
            cashflow_derived.append(('bank_cash_to_assets_ratio', money_cap * 100.0 / total_assets, ('money_cap', 'total_assets')))
        items_by_dimension['cashflow_resilience'] = []
        for key, value, sources in cashflow_derived[:cashflow_target]:
            append_derived(key, value, 'cashflow_resilience', 'bank_cashflow_derived_from_existing_dims', sources)
        if len(items_by_dimension['cashflow_resilience']) < cashflow_target and operating_cashflow is not None:
            fallback_score = _clamp(50.0 + math.tanh(operating_cashflow / 1e9) * 50.0)
            append_derived(
                'n_cashflow_act',
                operating_cashflow,
                'cashflow_resilience',
                'fallback_bank_cashflow_candidate',
                ('n_cashflow_act',),
                normalized_score=fallback_score,
            )

    dimensions = []
    weights = {}
    available_dimension_weight = 0.0
    weighted_total = 0.0
    for meta in DIMENSIONS:
        key, weight = meta['key'], meta['weight']
        items = items_by_dimension[key]
        scored_items = [item for item in items if item['score_status'] == 'SCORED']
        weight_total = sum(abs(item['weight']) for item in scored_items)
        if scored_items and weight_total:
            score = sum(item['normalized_score'] * abs(item['weight']) for item in scored_items) / weight_total
        elif scored_items:
            score = sum(item['normalized_score'] for item in scored_items) / len(scored_items)
        else:
            score = None

        total_item_weight = sum(abs(item['weight']) for item in items)
        feature_coverage = (
            sum(abs(item['weight']) for item in scored_items) / total_item_weight
            if total_item_weight else len(scored_items) / len(items) if items else 0.0
        )
        if not items or not scored_items:
            status = 'NOT_AVAILABLE'
        elif len(scored_items) == len(items):
            status = 'AVAILABLE'
        else:
            status = 'PARTIAL'

        if score is not None:
            score = _clamp(score)
            weighted_total += score * weight
            available_dimension_weight += weight

        evidence = {
            item['feature_key']: item['canonical_value']
            for item in items if item['canonical_value'] is not None
        }
        display_metrics = [
            {
                'key': item['feature_key'],
                'label': item['feature_label'],
                'value': str(item['raw_value']),
                'unit': item['unit'],
                'status': item['score_status'],
            }
            for item in items if item['raw_value'] is not None
        ]
        dimensions.append({
            'key': key,
            'name': meta['name'],
            'score': round(score, 2) if score is not None else None,
            'weight': weight,
            'status': status,
            'available': score is not None,
            'available_weight': round(feature_coverage, 4),
            'feature_coverage': round(feature_coverage, 4),
            'feature_count': len(items),
            'scored_feature_count': len(scored_items),
            'missing_features': [
                {'feature_key': item['feature_key'], 'status': item['score_status']}
                for item in items if item['score_status'] != 'SCORED'
            ],
            'evidence': evidence,
            'explanation': meta['explanation'],
            'display_metrics': display_metrics,
            'feature_items': items,
        })
        weights[key] = weight

    total = weighted_total / available_dimension_weight if available_dimension_weight else None
    total = round(_clamp(total), 2) if total is not None else None
    grade = 'N/A' if total is None else 'A' if total >= 85 else 'B' if total >= 70 else 'C' if total >= 55 else 'D' if total >= 40 else 'E'
    if total is None:
        score_status = 'NOT_AVAILABLE'
    elif selected and scored_feature_count == len(selected):
        score_status = 'COMPLETE'
    else:
        score_status = 'PARTIAL'
    feature_coverage = scored_feature_count / len(selected) if selected else 0.0
    feature_weight_coverage = (
        scored_model_weight / selected_model_weight if selected_model_weight else feature_coverage
    )
    return {
        'total_score': total,
        'score_grade': grade,
        'dimension_scores': dimensions,
        'dimension_weights': weights,
        'score_type': 'MODEL_TOPN_DIMENSION',
        'score_status': score_status,
        'feature_coverage': round(feature_coverage, 4),
        'feature_weight_coverage': round(feature_weight_coverage, 4),
        'available_dimension_weight': round(available_dimension_weight * 100, 2),
        'selected_feature_count': len(selected),
        'scored_feature_count': scored_feature_count,
        'unmapped_features': unmapped_features,
        'scoring_version': SCORING_VERSION,
        'feature_schema_version': FEATURE_SCHEMA_VERSION,
        'mapping_version': MAPPING_VERSION,
        'normalization_version': NORMALIZATION_VERSION,
        'dimension_weight_version': DIMENSION_WEIGHT_VERSION,
        'profile_id': 'generic',
        'profile_version': PROFILE_VERSION,
        'feature_dimension_mapping': {
            'report_type': payload.get('report_type') or '',
            'model_version': payload.get('model_version') or '',
            'score_topn': score_topn,
            'mapping_version': MAPPING_VERSION,
            'feature_schema_version': FEATURE_SCHEMA_VERSION,
            'normalization_version': NORMALIZATION_VERSION,
            'mapping': mappings,
        },
    }