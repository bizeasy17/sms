import math


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def calculate_method(name, current_price, current_metric, p50, sample_count, band_pct=0.1, min_samples=20):
    current_price = _positive(current_price)
    current_metric = _positive(current_metric)
    p50 = _positive(p50)
    if current_price is None or current_metric is None or p50 is None or sample_count < min_samples:
        return {'name': name, 'current': current_metric, 'p50': p50, 'implied': None, 'status': 'UNAVAILABLE', 'gap': None, 'sample_count': sample_count}
    implied = current_price * p50 / current_metric
    gap = (current_price - implied) / implied
    status = 'UNDERVALUED' if gap <= -band_pct else 'OVERVALUED' if gap >= band_pct else 'FAIR'
    return {'name': name, 'current': current_metric, 'p50': p50, 'implied': implied, 'status': status, 'gap': gap, 'sample_count': sample_count}


def summarize_buy_candidate(methods):
    valid = [item for item in methods.values() if item.get('implied') is not None]
    prices = [item['implied'] for item in valid]
    if not prices:
        return {'composite_valuation_price': None, 'conservative_valuation_price': None, 'undervalue_score': None, 'buy_candidate': False, 'under_methods': [], 'valid_method_count': 0, 'status': 'UNAVAILABLE'}
    under_methods = [item['name'] for item in valid if item['status'] == 'UNDERVALUED']
    return {'composite_valuation_price': sum(prices) / len(prices), 'conservative_valuation_price': min(prices), 'undervalue_score': len(under_methods) / len(valid), 'buy_candidate': bool(under_methods), 'under_methods': under_methods, 'valid_method_count': len(valid), 'status': 'VALID'}