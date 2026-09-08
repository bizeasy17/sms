def _score_coverage(method_count):
    return {0: 100, 1: 90, 2: 70, 3: 40, 4: 20}.get(min(method_count, 4), 10)


def build_risk_payload(result):
    methods = result.get('methods') or {}
    core_methods = {name: value for name, value in methods.items() if name != 'scarcity_overlay'}
    summary = result.get('summary') or {}
    dispersion = float(summary.get('dispersion_ratio') or 0)
    coverage = _score_coverage(len(core_methods))
    disagreement = min(100.0, dispersion * 100.0)
    missing = 35.0 if not result.get('inputs', {}).get('financial_ann_date') else 10.0
    score = max(0.0, min(100.0, coverage * 0.45 + disagreement * 0.35 + missing * 0.20))
    level = 'HIGH' if score >= 66 else 'MEDIUM' if score >= 33 else 'LOW'
    confidence = max(0.0, min(100.0, 85.0 - (15 if len(core_methods) < 3 else 0) - (10 if missing > 20 else 0)))
    discount = min(0.35, max(0.03, score / 250.0))
    composite = summary.get('composite_valuation_price_raw')
    conservative = summary.get('conservative_valuation_price_raw')
    return {
        'risk_score': score, 'risk_level': level, 'confidence': confidence,
        'factors': {'method_coverage': coverage, 'method_dispersion': disagreement, 'data_completeness': missing},
        'adjustment': {
            'valuation_discount_pct': discount,
            'adjusted_composite_valuation_price': composite * (1 - discount) if composite else None,
            'adjusted_conservative_valuation_price': conservative * (1 - discount) if conservative else None,
        },
    }