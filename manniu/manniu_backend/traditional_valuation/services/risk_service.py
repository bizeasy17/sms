from __future__ import annotations

from datetime import date

FACTOR_WEIGHTS = {
    'method_coverage': 0.15, 'method_dispersion': 0.15, 'core_method_presence': 0.07,
    'report_freshness': 0.09, 'profit_source': 0.07, 'data_completeness': 0.06,
    'report_alignment': 0.07, 'variant_dependency': 0.04, 'gap_pressure': 0.04,
    'leverage_stress': 0.05, 'liquidity_structure': 0.05, 'profitability_quality': 0.05,
    'receivable_pressure': 0.04, 'inventory_pressure': 0.04, 'goodwill_pressure': 0.03,
}


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _percent(value):
    number = _number(value)
    return number * 100.0 if number is not None and abs(number) <= 1 else number


def _as_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _factor(score, reason, normalized_input=None):
    score = max(0.0, min(100.0, float(score)))
    return {'factor_score': score, 'severity': 'HIGH' if score >= 66 else 'MEDIUM' if score >= 33 else 'LOW', 'is_triggered': score >= 40, 'reason': reason, 'normalized_input': normalized_input}


def _build_factors(result):
    methods = result.get('methods') or {}
    core = {name: value for name, value in methods.items() if name != 'scarcity_overlay'}
    summary = result.get('summary') or {}
    inputs = result.get('inputs') or {}
    valid_count = sum(1 for item in core.values() if _number(item.get('valuation_price')) not in (None, 0))
    coverage = 100 if valid_count >= 5 else 70 if valid_count >= 3 else 40 if valid_count == 2 else 90 if valid_count == 1 else 100
    dispersion = min(100.0, float(summary.get('dispersion_ratio') or 0) * 100.0)
    missing_core = len({'pe', 'pb', 'ps'} - set(core))
    announcement = _as_date(inputs.get('financial_ann_date'))
    asof = _as_date(inputs.get('asof_date'))
    age = (asof - announcement).days if announcement and asof else None
    source = str(inputs.get('profit_source') or '')
    report_type = str(result.get('report_type') or inputs.get('report_type') or '').upper()
    end_date = _as_date(inputs.get('financial_end_date'))
    suffix = {'Q1': (3, 31), 'H1': (6, 30), 'Q3': (9, 30), 'FY': (12, 31)}.get(report_type)
    profile = result.get('financial_profile') or {}
    leverage, liquidity = _percent(profile.get('debt_to_assets')), _percent(profile.get('ca_to_assets'))
    roe, net_margin, gross_margin = _percent(profile.get('roe')), _percent(profile.get('netprofit_margin')), _percent(profile.get('gross_margin'))
    ar, inventory, goodwill = (_percent(profile.get(key)) for key in ('ar_to_assets', 'inventory_to_assets', 'goodwill_to_assets'))
    composite, current = _number(summary.get('composite_valuation_price_raw')), _number(summary.get('current_price'))
    gap = abs(composite - current) / current * 100 if composite and current else 80
    variant = str(result.get('valuation_variant') or 'default')
    return {
        'method_coverage': _factor(coverage, f'valid_methods={valid_count}', valid_count),
        'method_dispersion': _factor(dispersion, f'dispersion_ratio={dispersion / 100:.4f}', dispersion),
        'core_method_presence': _factor(min(100, missing_core * 35), f'missing_core_methods={missing_core}', missing_core),
        'report_freshness': _factor(10 if age is not None and age <= 180 else 60 if age is not None else 90, f'announcement_age_days={age}', age),
        'profit_source': _factor(10 if source == 'fina_indicator_income' else 35 if source == 'express_vip_blended' else 50 if source == 'express_vip' else 75, f'profit_source={source or "missing"}', source),
        'data_completeness': _factor(10 if announcement and end_date and source else 80, 'financial lineage fields incomplete' if not (announcement and end_date and source) else 'complete'),
        'report_alignment': _factor(10 if suffix and end_date and (end_date.month, end_date.day) == suffix else 60, f'report_type={report_type}', report_type),
        'variant_dependency': _factor(10 if variant == 'default' else 25 if variant.startswith('sw_') else 45, f'valuation_variant={variant}', variant),
        'gap_pressure': _factor(min(100, gap * 2), f'absolute_gap_pct={gap:.2f}', gap),
        'leverage_stress': _factor(80 if leverage is None else max(0, (leverage - 35) * 2), f'debt_to_assets_pct={leverage}', leverage),
        'liquidity_structure': _factor(70 if liquidity is None else max(0, (35 - liquidity) * 2), f'ca_to_assets_pct={liquidity}', liquidity),
        'profitability_quality': _factor(70 if roe is None else max(0, (12 - roe) * 3) + max(0, (15 - (net_margin or 0)) * 1.5) + max(0, (25 - (gross_margin or 0)) * 0.5), f'roe={roe},net_margin={net_margin},gross_margin={gross_margin}', {'roe': roe, 'net_margin': net_margin, 'gross_margin': gross_margin}),
        'receivable_pressure': _factor(60 if ar is None else max(0, (ar - 12) * 3), f'ar_to_assets_pct={ar}', ar),
        'inventory_pressure': _factor(60 if inventory is None else max(0, (inventory - 18) * 2), f'inventory_to_assets_pct={inventory}', inventory),
        'goodwill_pressure': _factor(60 if goodwill is None else max(0, (goodwill - 6) * 4), f'goodwill_to_assets_pct={goodwill}', goodwill),
    }


def build_risk_payload(result):
    factors = _build_factors(result)
    score = max(0.0, min(100.0, sum(item['factor_score'] * FACTOR_WEIGHTS[name] for name, item in factors.items())))
    level = 'HIGH' if score >= 66 else 'MEDIUM' if score >= 33 else 'LOW'
    inputs = result.get('inputs') or {}
    valid_methods = sum(1 for item in (result.get('methods') or {}).values() if _number(item.get('valuation_price')) not in (None, 0))
    confidence = 85.0 - (15 if valid_methods < 3 else 0) - (10 if not inputs.get('financial_ann_date') else 0) - (10 if not inputs.get('profit_source') else 0)
    discount = min(0.35, max(0.03, score / 250.0))
    summary = result.get('summary') or {}
    composite, conservative = _number(summary.get('composite_valuation_price_raw')), _number(summary.get('conservative_valuation_price_raw'))
    triggered = sorted(((name, item) for name, item in factors.items() if item['is_triggered']), key=lambda item: item[1]['factor_score'], reverse=True)[:3]
    groups = {'valuation_stability': ('method_coverage', 'method_dispersion', 'core_method_presence'), 'disclosure_quality': ('report_freshness', 'profit_source', 'data_completeness', 'report_alignment'), 'context_dependency': ('variant_dependency',), 'valuation_output': ('gap_pressure',), 'asset_quality': ('leverage_stress', 'liquidity_structure', 'profitability_quality', 'receivable_pressure', 'inventory_pressure', 'goodwill_pressure')}
    dimensions = {group: sum(factors[name]['factor_score'] * FACTOR_WEIGHTS[name] for name in names) for group, names in groups.items()}
    return {'risk_score': score, 'risk_level': level, 'confidence': max(0.0, min(100.0, confidence)), 'factors': {'weights': FACTOR_WEIGHTS, 'items': factors, 'dimensions': dimensions, 'top_triggered': [name for name, _ in triggered]}, 'adjustment': {'valuation_discount_pct': discount, 'adjusted_composite_valuation_price': composite * (1 - discount) if composite else None, 'adjusted_conservative_valuation_price': conservative * (1 - discount) if conservative else None}}
