from __future__ import annotations

from statistics import median

from django.conf import settings


CORE_METHODS = ("pe", "pb", "ps")
SUPPORT_METHODS = ("fcff_dcf", "ddm")
OPTIONAL_METHODS = ("peg",)
RULE_VERSION = "baseline_v20260414_core_guardrails"
MIN_CORE_METHOD_COUNT = 2
MIN_CORE_UNDER_COUNT = 1
MIN_UNDER_METHOD_COUNT = 2
MIN_COMPOSITE_GAP_PCT = -0.02
MIN_CONSERVATIVE_GAP_PCT = -0.12


def _float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _setting(name, default):
    value = getattr(settings, name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _market_cap(current_price, method_map):
    if current_price in (None, 0):
        return None
    inferred = []
    for payload in (method_map or {}).values():
        price = _float((payload or {}).get("valuation_price"))
        market_cap = _float((payload or {}).get("valuation_market_cap"))
        if price and price > 0 and market_cap and market_cap > 0:
            inferred.append(market_cap * float(current_price) / price)
    if inferred:
        return median(inferred)
    payload = (method_map or {}).get("market_cap") or {}
    market_cap = _float(payload.get("valuation_market_cap"))
    return market_cap if market_cap and market_cap > 0 else None


def _size_factor(market_cap):
    if market_cap is None:
        return 1.0
    if market_cap <= _setting("COMPOSITE_SIZE_SMALL_CAP_MAX", 30_000_000_000):
        return _setting("COMPOSITE_SIZE_SMALL_CAP_FACTOR", 1.05)
    if market_cap <= _setting("COMPOSITE_SIZE_MID_CAP_MAX", 100_000_000_000):
        return _setting("COMPOSITE_SIZE_MID_CAP_FACTOR", 1.02)
    if market_cap <= _setting("COMPOSITE_SIZE_LARGE_CAP_MAX", 300_000_000_000):
        return _setting("COMPOSITE_SIZE_LARGE_CAP_FACTOR", 0.99)
    return _setting("COMPOSITE_SIZE_MEGA_CAP_FACTOR", 0.96)


def summarize_buy_candidate(current_price, method_map, band_pct=0.1):
    summary = {
        "composite_valuation_price": None,
        "conservative_valuation_price": None,
        "undervalue_score": None,
        "buy_candidate": False,
        "buy_candidate_reason": "no_valid_valuation_methods",
        "buy_candidate_rule_version": RULE_VERSION,
        "valuation_valid_methods": [],
        "valuation_under_methods": [],
        "valuation_core_methods": [],
    }
    current = _float(current_price)
    if current is None or current <= 0:
        return summary

    valid = {}
    for method, payload in (method_map or {}).items():
        price = _float((payload or {}).get("valuation_price"))
        if price is not None and price > 0:
            valid[str(method)] = price
    if not valid:
        return summary

    lower = current * _setting("BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER", 0.5)
    upper = current * _setting("BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER", 2.05)
    core = {method: valid[method] for method in CORE_METHODS if method in valid and lower <= valid[method] <= upper}
    excluded = [method for method in CORE_METHODS if method in valid and method not in core]
    if len(core) > 1 and max(core.values()) / min(core.values()) > _setting("BUY_CANDIDATE_CORE_SPREAD_RATIO_MAX", 2.2):
        outlier = max(core, key=lambda method: abs(core[method] - current))
        core.pop(outlier)
        excluded.append(outlier)

    raw_core = [valid[method] for method in CORE_METHODS if method in valid]
    if len(core) >= MIN_CORE_METHOD_COUNT:
        base_prices = list(core.values())
        mode = "core_only"
    elif raw_core:
        base_prices = list(core.values()) or raw_core
        mode = "raw_core_fallback"
    else:
        base_prices = [valid[method] for method in (*SUPPORT_METHODS, *OPTIONAL_METHODS) if method in valid]
        mode = "fallback_support"
    if not base_prices:
        return summary

    base_composite = median(base_prices)
    composite = base_composite * _size_factor(_market_cap(current, method_map))
    conservative_pool = list(core.values()) or raw_core or base_prices
    conservative = min(conservative_pool)
    under = [method for method, price in valid.items() if current <= price * (1 - float(band_pct))]
    core_under = [method for method in CORE_METHODS if method in core and current <= core[method] * (1 - float(band_pct))]
    composite_gap = (composite - current) / current
    conservative_gap = (conservative - current) / current

    score = 0
    if len(valid) >= 4:
        score += 20
    elif len(valid) >= 3:
        score += 15
    elif len(valid) >= 2:
        score += 8
    score += 25 if len(core) >= 3 else 18 if len(core) >= 2 else 8 if len(core) == 1 else 0
    score += 30 if len(core_under) >= 3 else 24 if len(core_under) >= 2 else 16 if core_under else 0
    score += 10 if len(under) >= 4 else 7 if len(under) >= 3 else 4 if len(under) >= 2 else 0
    score += 15 if composite_gap >= 0.3 else 10 if composite_gap >= 0.15 else 5 if composite_gap >= float(band_pct) else 0
    score += 10 if conservative_gap >= 0.15 else 6 if conservative_gap >= 0.08 else 3 if conservative_gap >= 0.03 else 0

    summary.update({
        "composite_valuation_price": round(composite, 4),
        "conservative_valuation_price": round(conservative, 4),
        "undervalue_score": min(score, 100),
        "buy_candidate": (
            len(core) >= MIN_CORE_METHOD_COUNT
            and len(core_under) >= MIN_CORE_UNDER_COUNT
            and len(under) >= MIN_UNDER_METHOD_COUNT
            and composite_gap >= MIN_COMPOSITE_GAP_PCT
            and conservative_gap >= MIN_CONSERVATIVE_GAP_PCT
        ),
        "buy_candidate_reason": "; ".join([
            f"valid_methods={len(valid)}",
            f"core_methods={len(core)}",
            f"core_under={len(core_under)}",
            f"under_methods={len(under)}",
            f"composite_mode={mode}",
            f"core_excluded={','.join(sorted(excluded)) or 'none'}",
            f"size_factor={round(_size_factor(_market_cap(current, method_map)), 4)}",
            f"composite_gap_pct={round(composite_gap * 100, 2)}",
            f"conservative_gap_pct={round(conservative_gap * 100, 2)}",
        ]),
        "valuation_valid_methods": sorted(valid),
        "valuation_under_methods": sorted(under),
        "valuation_core_methods": [method for method in CORE_METHODS if method in core],
    })
    return summary
