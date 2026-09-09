from __future__ import annotations

from math import isfinite


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def positive(value):
    value = number(value)
    return value if value is not None and value > 0 else None


def raw_number(record, *names):
    payload = getattr(record, 'raw_payload', {}) or {}
    for name in names:
        value = number(payload.get(name))
        if value is not None:
            return value, name
    return None, None


def calculate_ev_ebitda(income, balance, shares, target_multiple, per_share_scale=10_000.0):
    ebitda, ebitda_source = raw_number(income, 'ebitda', 'EBITDA', 'n_ebitda')
    cash = positive(getattr(balance, 'money_cap', None)) if balance else None
    short_debt = number(getattr(balance, 'st_borr', None)) if balance else None
    long_debt = number(getattr(balance, 'lt_borr', None)) if balance else None
    debt = (short_debt or 0.0) + (long_debt or 0.0) if balance else None
    multiple = positive(target_multiple)
    shares = positive(shares)
    if ebitda is None:
        return None, 'ebitda_missing'
    if multiple is None:
        return None, 'target_ev_ebitda_invalid'
    if shares is None:
        return None, 'total_share_missing'
    if cash is None or debt is None:
        return None, 'cash_or_debt_missing'
    enterprise_value = ebitda * multiple
    equity_value = enterprise_value - debt + cash
    price = equity_value / shares / per_share_scale
    if price <= 0:
        return None, 'equity_value_nonpositive'
    return {
        'valuation_price': round(price, 6),
        'input': {
            'ebitda': ebitda, 'ebitda_source': ebitda_source,
            'target_ev_ebitda': multiple, 'cash': cash, 'debt': debt,
            'enterprise_value': enterprise_value, 'equity_value': equity_value,
        },
    }, None


def calculate_sw_history(metrics, shares, net_income, revenue, equity, per_share_scale=10_000.0):
    history = metrics.get('history_quantiles') or {}
    weights = {'3y': 0.2, '5y': 0.5, '10y': 0.3}
    anchors = {}
    coverage = {}
    for metric in ('pe', 'pb', 'ps'):
        values = []
        total_weight = 0.0
        coverage[metric] = {}
        for window, weight in weights.items():
            entry = history.get(metric, {}).get(window) or {}
            sample_count = int(entry.get('sample_count') or 0)
            quantile = positive(entry.get('p50'))
            coverage[metric][window] = {'sample_count': sample_count, 'p50': quantile}
            if sample_count < 120 or quantile is None:
                continue
            values.append((quantile, weight))
            total_weight += weight
        if total_weight > 0:
            anchors[metric] = sum(value * weight for value, weight in values) / total_weight

    shares = positive(shares)
    prices = []
    price_inputs = {}
    if shares and net_income and anchors.get('pe'):
        price_inputs['pe'] = (net_income / shares / per_share_scale) * anchors['pe']
        prices.append(price_inputs['pe'])
    if shares and equity and anchors.get('pb'):
        price_inputs['pb'] = (equity / shares / per_share_scale) * anchors['pb']
        prices.append(price_inputs['pb'])
    if shares and revenue and anchors.get('ps'):
        price_inputs['ps'] = (revenue / shares / per_share_scale) * anchors['ps']
        prices.append(price_inputs['ps'])
    if not prices:
        return None, 'history_anchor_unavailable', {'coverage': coverage, 'anchors': anchors}
    return {
        'valuation_price': round(sum(prices) / len(prices), 6),
        'input': {
            'anchors': anchors, 'coverage': coverage,
            'anchor_weights': weights, 'component_prices': price_inputs,
            'target_source': 'template_history_quantiles',
        },
    }, None, {'coverage': coverage, 'anchors': anchors}


def calculate_scarcity_overlay(base_price, growth, roe, config):
    if base_price is None or base_price <= 0:
        return None, 'base_price_missing'
    config = config or {}
    profile = str(config.get('fallback_profile') or 'balanced')
    circuit = config.get('circuit_breaker') or {}
    if not config.get('enabled', True) and config.get('enabled') is not None:
        return None, 'scarcity_disabled'
    beta = 0.35
    cap_pct = 30.0
    confidence_floor = float((config.get('missing_policy') or {}).get('confidence_floor', 0.35))
    growth_score = min(1.0, max(0.0, (growth or 0.0) / 50.0))
    roe_score = min(1.0, max(0.0, (roe or 0.0) / 30.0))
    available = int(growth is not None) + int(roe is not None)
    if available == 0:
        return None, 'scarcity_score_inputs_missing'
    score = (growth_score + roe_score) / (2 if available == 2 else 1)
    confidence = 1.0 if available == 2 else 0.5
    if confidence < confidence_floor:
        return None, 'scarcity_confidence_below_floor'
    premium_pct = min(cap_pct, max(0.0, beta * score * confidence * 100.0))
    return {
        'valuation_price': round(base_price * (1.0 + premium_pct / 100.0), 6),
        'input': {
            'base_price': base_price, 'beta': beta, 'score': score,
            'confidence': confidence, 'cap_pct': cap_pct,
            'premium_pct': premium_pct, 'profile': profile,
            'confidence_floor': confidence_floor,
            'circuit_breaker': circuit,
        },
    }, None