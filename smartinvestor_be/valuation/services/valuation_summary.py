import pandas as pd
from django.conf import settings


BUY_CANDIDATE_CORE_METHODS = ("pe", "pb", "ps")
BUY_CANDIDATE_SUPPORT_METHODS = ("fcff_dcf", "ddm")
BUY_CANDIDATE_OPTIONAL_METHODS = ("peg",)
BUY_CANDIDATE_RULE_VERSION = "baseline_v20260414_core_guardrails"
BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER = float(
    getattr(settings, "BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER", 0.5) or 0.5
)
BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER = float(
    getattr(settings, "BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER", 2.05) or 2.05
)
BUY_CANDIDATE_CORE_SPREAD_RATIO_MAX = float(
    getattr(settings, "BUY_CANDIDATE_CORE_SPREAD_RATIO_MAX", 2.2) or 2.2
)
BUY_CANDIDATE_CORE_SOFT_MIN_WEIGHT = float(
    getattr(settings, "BUY_CANDIDATE_CORE_SOFT_MIN_WEIGHT", 0.25) or 0.25
)
BUY_CANDIDATE_CORE_SOFT_MAX_DECAY = float(
    getattr(settings, "BUY_CANDIDATE_CORE_SOFT_MAX_DECAY", 0.75) or 0.75
)
BUY_CANDIDATE_CORE_SOFT_ACTIVE_MIN_WEIGHT = float(
    getattr(settings, "BUY_CANDIDATE_CORE_SOFT_ACTIVE_MIN_WEIGHT", 0.95) or 0.95
)
BUY_CANDIDATE_CORE_SOFT_UNDER_MIN_WEIGHT = float(
    getattr(settings, "BUY_CANDIDATE_CORE_SOFT_UNDER_MIN_WEIGHT", 0.98) or 0.98
)
BUY_CANDIDATE_SOFT_INCLUDE_SCORE_CAP = int(
    getattr(settings, "BUY_CANDIDATE_SOFT_INCLUDE_SCORE_CAP", 97) or 97
)
BUY_CANDIDATE_MULTI_SOFT_INCLUDE_SCORE_CAP = int(
    getattr(settings, "BUY_CANDIDATE_MULTI_SOFT_INCLUDE_SCORE_CAP", 95) or 95
)
BUY_CANDIDATE_RECOVERY_ANCHOR_MIN_GAP_PCT = float(
    getattr(settings, "BUY_CANDIDATE_RECOVERY_ANCHOR_MIN_GAP_PCT", 0.25) or 0.25
)
BUY_CANDIDATE_RECOVERY_ANCHOR_MAX_PRICE_MULTIPLIER = float(
    getattr(settings, "BUY_CANDIDATE_RECOVERY_ANCHOR_MAX_PRICE_MULTIPLIER", 1.35) or 1.35
)
BUY_CANDIDATE_RECOVERY_ANCHOR_MIN_PRICE_MULTIPLIER = float(
    getattr(settings, "BUY_CANDIDATE_RECOVERY_ANCHOR_MIN_PRICE_MULTIPLIER", 0.7) or 0.7
)
BUY_CANDIDATE_RECOVERY_ANCHOR_WEIGHT = float(
    getattr(settings, "BUY_CANDIDATE_RECOVERY_ANCHOR_WEIGHT", 0.45) or 0.45
)

BUY_CANDIDATE_MIN_CORE_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_CORE_UNDER_COUNT = 1
BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT = -0.02
BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT = -0.12

COMPOSITE_SIZE_SMALL_CAP_MAX = float(
    getattr(settings, "COMPOSITE_SIZE_SMALL_CAP_MAX", 30_000_000_000) or 30_000_000_000
)
COMPOSITE_SIZE_MID_CAP_MAX = float(
    getattr(settings, "COMPOSITE_SIZE_MID_CAP_MAX", 100_000_000_000) or 100_000_000_000
)
COMPOSITE_SIZE_LARGE_CAP_MAX = float(
    getattr(settings, "COMPOSITE_SIZE_LARGE_CAP_MAX", 300_000_000_000) or 300_000_000_000
)
COMPOSITE_SIZE_SMALL_CAP_FACTOR = float(
    getattr(settings, "COMPOSITE_SIZE_SMALL_CAP_FACTOR", 1.05) or 1.05
)
COMPOSITE_SIZE_MID_CAP_FACTOR = float(
    getattr(settings, "COMPOSITE_SIZE_MID_CAP_FACTOR", 1.02) or 1.02
)
COMPOSITE_SIZE_LARGE_CAP_FACTOR = float(
    getattr(settings, "COMPOSITE_SIZE_LARGE_CAP_FACTOR", 0.99) or 0.99
)
COMPOSITE_SIZE_MEGA_CAP_FACTOR = float(
    getattr(settings, "COMPOSITE_SIZE_MEGA_CAP_FACTOR", 0.96) or 0.96
)


def _estimate_current_market_cap(current_price, method_map):
    if current_price in (None, 0):
        return None

    current_price = float(current_price)
    inferred_caps = []
    for payload in (method_map or {}).values():
        valuation_price = payload.get("valuation_price")
        valuation_market_cap = payload.get("valuation_market_cap")
        if valuation_price in (None, 0) or valuation_market_cap in (None, 0):
            continue
        valuation_price = float(valuation_price)
        valuation_market_cap = float(valuation_market_cap)
        if valuation_price <= 0 or valuation_market_cap <= 0:
            continue
        inferred_caps.append(valuation_market_cap * current_price / valuation_price)

    if inferred_caps:
        return float(pd.Series(inferred_caps, dtype="float64").median())

    market_cap_payload = (method_map or {}).get("market_cap") or {}
    market_cap_value = market_cap_payload.get("valuation_market_cap")
    if market_cap_value not in (None, 0):
        market_cap_value = float(market_cap_value)
        if market_cap_value > 0:
            return market_cap_value

    return None


def _resolve_composite_size_factor(current_market_cap):
    if current_market_cap in (None, 0):
        return 1.0

    current_market_cap = float(current_market_cap)
    if current_market_cap <= COMPOSITE_SIZE_SMALL_CAP_MAX:
        return COMPOSITE_SIZE_SMALL_CAP_FACTOR
    if current_market_cap <= COMPOSITE_SIZE_MID_CAP_MAX:
        return COMPOSITE_SIZE_MID_CAP_FACTOR
    if current_market_cap <= COMPOSITE_SIZE_LARGE_CAP_MAX:
        return COMPOSITE_SIZE_LARGE_CAP_FACTOR
    return COMPOSITE_SIZE_MEGA_CAP_FACTOR


def _filter_core_method_prices(valid_methods, current_price):
    filtered_methods = {}
    excluded_methods = {}
    lower_bound = current_price * BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER
    upper_bound = current_price * BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER

    for method in BUY_CANDIDATE_CORE_METHODS:
        valuation_price = valid_methods.get(method)
        if valuation_price is None:
            continue
        if lower_bound <= valuation_price <= upper_bound:
            filtered_methods[method] = valuation_price
        else:
            excluded_methods[method] = "out_of_band"

    if not filtered_methods:
        return filtered_methods, excluded_methods

    filtered_prices = list(filtered_methods.values())
    min_price = min(filtered_prices)
    max_price = max(filtered_prices)
    if min_price > 0 and (max_price / min_price) > BUY_CANDIDATE_CORE_SPREAD_RATIO_MAX:
        farthest_method = max(
            filtered_methods.items(),
            key=lambda item: abs(item[1] - current_price),
        )[0]
        excluded_methods[farthest_method] = "core_outlier"
        filtered_methods.pop(farthest_method, None)

    return filtered_methods, excluded_methods


def _compute_core_method_soft_weights(valid_methods, current_price):
    """Compute soft weights for core valuation methods outside hard filter band.

    Weight is 1.0 in-band and decays smoothly when price is slightly out-of-band.
    """
    weights = {}
    if current_price in (None, 0):
        return weights

    current_price = float(current_price)
    lower_bound = current_price * BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER
    upper_bound = current_price * BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER

    for method in BUY_CANDIDATE_CORE_METHODS:
        valuation_price = valid_methods.get(method)
        if valuation_price is None:
            continue
        if lower_bound <= valuation_price <= upper_bound:
            weights[method] = 1.0
            continue

        if valuation_price > upper_bound:
            overflow = (valuation_price - upper_bound) / max(upper_bound, 1e-9)
            weight = 1.0 - min(BUY_CANDIDATE_CORE_SOFT_MAX_DECAY, overflow)
        else:
            underflow = (lower_bound - valuation_price) / max(lower_bound, 1e-9)
            weight = 1.0 - min(BUY_CANDIDATE_CORE_SOFT_MAX_DECAY, underflow)

        weights[method] = max(BUY_CANDIDATE_CORE_SOFT_MIN_WEIGHT, weight)

    return weights


def _build_effective_core_methods(
    valid_methods,
    filtered_core_methods,
    core_soft_weights,
    excluded_core_methods,
):
    """Build effective core method set using hard pass first and soft hysteresis fallback."""
    effective = dict(filtered_core_methods or {})
    for method in BUY_CANDIDATE_CORE_METHODS:
        if method in effective:
            continue
        if (excluded_core_methods or {}).get(method) == "core_outlier":
            continue
        valuation_price = valid_methods.get(method)
        weight = core_soft_weights.get(method)
        if valuation_price is None or weight is None:
            continue
        if weight >= BUY_CANDIDATE_CORE_SOFT_ACTIVE_MIN_WEIGHT:
            effective[method] = valuation_price
    return effective


def _resolve_recovery_anchor_price(valid_methods, current_price, core_reference_price):
    if current_price in (None, 0) or core_reference_price in (None, 0):
        return None

    sw_history_price = valid_methods.get("sw_history")
    if sw_history_price is None:
        return None

    lower_bound = current_price * BUY_CANDIDATE_RECOVERY_ANCHOR_MIN_PRICE_MULTIPLIER
    upper_bound = current_price * BUY_CANDIDATE_RECOVERY_ANCHOR_MAX_PRICE_MULTIPLIER
    if not (lower_bound <= sw_history_price <= upper_bound):
        return None

    core_gap_pct = abs(core_reference_price - current_price) / current_price
    anchor_gap_pct = abs(sw_history_price - current_price) / current_price
    if core_gap_pct < BUY_CANDIDATE_RECOVERY_ANCHOR_MIN_GAP_PCT:
        return None
    if anchor_gap_pct >= core_gap_pct:
        return None

    return sw_history_price


def summarize_buy_candidate(current_price, method_map, band_pct):
    summary = {
        "composite_valuation_price": None,
        "conservative_valuation_price": None,
        "undervalue_score": None,
        "buy_candidate": False,
        "buy_candidate_reason": "no_valid_valuation_methods",
        "buy_candidate_rule_version": BUY_CANDIDATE_RULE_VERSION,
        "valuation_valid_methods": [],
        "valuation_under_methods": [],
        "valuation_core_methods": [],
    }

    if current_price in (None, 0) or not method_map:
        return summary

    current_price = float(current_price)
    valid_methods = {}
    for method, payload in (method_map or {}).items():
        valuation_price = payload.get("valuation_price")
        if valuation_price is None:
            continue
        valuation_price = float(valuation_price)
        if valuation_price <= 0:
            continue
        valid_methods[method] = valuation_price

    if not valid_methods:
        return summary

    raw_core_prices = [valid_methods[m] for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods]
    filtered_core_methods, excluded_core_methods = _filter_core_method_prices(valid_methods, current_price)
    core_soft_weights = _compute_core_method_soft_weights(valid_methods, current_price)
    effective_core_methods = _build_effective_core_methods(
        valid_methods=valid_methods,
        filtered_core_methods=filtered_core_methods,
        core_soft_weights=core_soft_weights,
        excluded_core_methods=excluded_core_methods,
    )
    core_prices = [effective_core_methods[m] for m in BUY_CANDIDATE_CORE_METHODS if m in effective_core_methods]
    support_prices = [valid_methods[m] for m in BUY_CANDIDATE_SUPPORT_METHODS if m in valid_methods]
    optional_prices = []
    for method in BUY_CANDIDATE_OPTIONAL_METHODS:
        price = valid_methods.get(method)
        if price is None:
            continue
        if 0.5 * current_price <= price <= 2.5 * current_price:
            optional_prices.append(price)

    recovery_anchor_used = False
    if len(core_prices) >= BUY_CANDIDATE_MIN_CORE_METHOD_COUNT:
        candidate_prices = list(core_prices)
        composite_mode = "core_only"
    elif raw_core_prices:
        candidate_prices = list(core_prices or raw_core_prices)
        composite_mode = "raw_core_fallback"
    else:
        candidate_prices = core_prices + support_prices + optional_prices
        composite_mode = "fallback_all"
    if not candidate_prices:
        return summary

    base_composite_price = float(pd.Series(candidate_prices, dtype="float64").median())
    if core_prices:
        core_weighted_pairs = [
            (effective_core_methods[m], core_soft_weights.get(m, 1.0))
            for m in BUY_CANDIDATE_CORE_METHODS
            if m in effective_core_methods
        ]
        if core_weighted_pairs:
            total_weight = sum(weight for _, weight in core_weighted_pairs)
            if total_weight > 0:
                base_composite_price = sum(price * weight for price, weight in core_weighted_pairs) / total_weight
                composite_mode = f"{composite_mode}_soft_weighted"
    recovery_anchor_price = _resolve_recovery_anchor_price(
        valid_methods=valid_methods,
        current_price=current_price,
        core_reference_price=base_composite_price,
    )
    if recovery_anchor_price is not None:
        base_composite_price = (
            (1.0 - BUY_CANDIDATE_RECOVERY_ANCHOR_WEIGHT) * base_composite_price
            + BUY_CANDIDATE_RECOVERY_ANCHOR_WEIGHT * recovery_anchor_price
        )
        composite_mode = f"{composite_mode}_recovery_anchor"
        recovery_anchor_used = True

    current_market_cap = _estimate_current_market_cap(current_price, method_map)
    composite_size_factor = _resolve_composite_size_factor(current_market_cap)
    composite_price = base_composite_price * composite_size_factor
    conservative_pool = core_prices or raw_core_prices or candidate_prices
    conservative_price = min(conservative_pool)

    under_methods = [
        method for method, valuation_price in valid_methods.items()
        if current_price <= valuation_price * (1 - band_pct)
    ]
    core_under_methods = [
        method
        for method in BUY_CANDIDATE_CORE_METHODS
        if method in effective_core_methods
        and current_price <= effective_core_methods[method] * (1 - band_pct)
        and (
            method in filtered_core_methods
            or core_soft_weights.get(method, 0.0) >= BUY_CANDIDATE_CORE_SOFT_UNDER_MIN_WEIGHT
        )
    ]
    soft_included_methods = [
        method for method in BUY_CANDIDATE_CORE_METHODS
        if method in effective_core_methods and method not in filtered_core_methods
    ]
    soft_under_methods = [
        method for method in core_under_methods if method in soft_included_methods
    ]

    composite_gap_pct = (composite_price - current_price) / current_price
    conservative_gap_pct = (conservative_price - current_price) / current_price

    score = 0
    valid_method_count = len(valid_methods)
    core_method_count = len(core_prices)
    core_under_count = len(core_under_methods)

    if valid_method_count >= 4:
        score += 20
    elif valid_method_count >= 3:
        score += 15
    elif valid_method_count >= 2:
        score += 8

    if core_method_count >= 3:
        score += 25
    elif core_method_count >= 2:
        score += 18
    elif core_method_count == 1:
        score += 8

    if core_under_count >= 3:
        score += 30
    elif core_under_count >= 2:
        score += 24
    elif core_under_count == 1:
        score += 16

    under_method_count = len(under_methods)
    if under_method_count >= 4:
        score += 10
    elif under_method_count >= 3:
        score += 7
    elif under_method_count >= 2:
        score += 4

    if composite_gap_pct >= 0.3:
        score += 15
    elif composite_gap_pct >= 0.15:
        score += 10
    elif composite_gap_pct >= band_pct:
        score += 5

    if conservative_gap_pct >= 0.15:
        score += 10
    elif conservative_gap_pct >= 0.08:
        score += 6
    elif conservative_gap_pct >= 0.03:
        score += 3

    score_cap = 100
    if soft_included_methods:
        score_cap = min(score_cap, BUY_CANDIDATE_SOFT_INCLUDE_SCORE_CAP)
        if len(soft_included_methods) >= 2:
            score_cap = min(score_cap, BUY_CANDIDATE_MULTI_SOFT_INCLUDE_SCORE_CAP)

    buy_candidate = (
        core_method_count >= BUY_CANDIDATE_MIN_CORE_METHOD_COUNT
        and core_under_count >= BUY_CANDIDATE_MIN_CORE_UNDER_COUNT
        and under_method_count >= BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT
        and composite_gap_pct >= BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT
        and conservative_gap_pct >= BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT
    )

    reasons = [
        f"valid_methods={valid_method_count}",
        f"core_methods={core_method_count}",
        f"core_under={core_under_count}",
        f"under_methods={under_method_count}",
        f"composite_mode={composite_mode}",
        f"core_excluded={','.join(sorted(excluded_core_methods.keys())) or 'none'}",
        f"soft_core_included={','.join(sorted(soft_included_methods)) or 'none'}",
        f"soft_core_under={','.join(sorted(soft_under_methods)) or 'none'}",
        f"score_cap={score_cap}",
        f"recovery_anchor={'sw_history' if recovery_anchor_used else 'none'}",
        f"size_factor={round(composite_size_factor, 4)}",
        f"composite_gap_pct={round(composite_gap_pct * 100, 2)}",
        f"conservative_gap_pct={round(conservative_gap_pct * 100, 2)}",
    ]

    summary.update(
        {
            "composite_valuation_price": round(composite_price, 4),
            "conservative_valuation_price": round(conservative_price, 4),
            "undervalue_score": min(score, score_cap),
            "buy_candidate": buy_candidate,
            "buy_candidate_reason": "; ".join(reasons),
            "valuation_valid_methods": sorted(valid_methods.keys()),
            "valuation_under_methods": sorted(under_methods),
            "valuation_core_methods": [m for m in BUY_CANDIDATE_CORE_METHODS if m in effective_core_methods],
        }
    )
    return summary
