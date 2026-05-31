import json
import math
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from django.conf import settings

from valuation.services.sw_history_quantiles import SwHistoryQuantileService
from valuation.services.validation_loader import ValuationConfig


SW_HISTORY_DEFAULT_YEARS = (3, 5, 10)
SW_HISTORY_DEFAULT_QUANTILE = 0.5
SW_HISTORY_DEFAULT_MIN_SAMPLES = 120


def build_sw_history_variant(history_windows, history_quantile, history_min_samples):
    years = []
    for item in history_windows or []:
        text = str(item or "").strip().lower()
        if text.endswith("y"):
            text = text[:-1]
        if text.isdigit():
            years.append(int(text))

    years = sorted(set(years))
    years_text = "-".join(str(y) for y in years) if years else "na"
    quantile_value = SW_HISTORY_DEFAULT_QUANTILE if history_quantile is None else float(history_quantile)
    quantile_text = f"q{int(round(quantile_value * 100))}"
    min_samples_value = SW_HISTORY_DEFAULT_MIN_SAMPLES if history_min_samples is None else int(history_min_samples)
    return f"hist_y{years_text}_{quantile_text}_m{min_samples_value}"[:128]


def build_sw_history_component_rows(snapshot, sw_history_result):
    if not isinstance(sw_history_result, dict):
        return []

    component_implied_prices = sw_history_result.get("component_implied_prices") or {}
    component_target_multiples = sw_history_result.get("component_target_multiples") or {}
    industry_code = sw_history_result.get("industry_code")
    industry_name = sw_history_result.get("industry_name")
    history_windows = sw_history_result.get("history_windows") or []
    history_quantile = sw_history_result.get("history_quantile")
    history_min_samples = sw_history_result.get("history_min_samples")
    variant = build_sw_history_variant(history_windows, history_quantile, history_min_samples)

    base_payload = {
        "ts_code": sw_history_result.get("ts_code"),
        "valuation_variant": variant,
        "compare_group": "sw_history_anchor",
        "industry_level": "L3" if industry_code else None,
        "industry_code": industry_code,
        "industry_name": industry_name,
        "target_source": "sw_history_anchor_component",
        "history_windows": history_windows,
        "history_quantile": history_quantile,
        "history_min_samples": history_min_samples,
    }

    rows = []
    for method in ["pe", "pb", "ps"]:
        implied_price = component_implied_prices.get(method)
        target_multiple = component_target_multiples.get(method)
        if implied_price is None or target_multiple in (None, 0):
            continue

        total_share = snapshot.get("total_share")
        equity_value = float(implied_price) * float(total_share) if total_share not in (None, 0) else None
        current_multiple = snapshot.get("pe_ttm") if method == "pe" else snapshot.get("pb") if method == "pb" else snapshot.get("ps_ttm")
        rows.append(
            {
                "method": method,
                "equity_value": equity_value,
                "implied_price": float(implied_price),
                "applied_multiple": float(target_multiple),
                "current_multiple": current_multiple,
                **base_payload,
            }
        )
    return rows


def normalize_sw_history_years(history_years):
    if history_years in (None, ""):
        return SW_HISTORY_DEFAULT_YEARS

    if isinstance(history_years, str):
        items = [item.strip() for item in history_years.split(",") if item.strip()]
    elif isinstance(history_years, (list, tuple, set)):
        items = list(history_years)
    else:
        items = [history_years]

    normalized = []
    for item in items:
        try:
            years = int(item)
        except (TypeError, ValueError):
            continue
        if years > 0:
            normalized.append(years)
    return tuple(sorted(set(normalized))) or SW_HISTORY_DEFAULT_YEARS


def resolve_sw_history_trade_date(trade_date, snapshot_trade_date):
    candidate = trade_date or snapshot_trade_date
    if candidate is None:
        raise ValueError("SW historical valuation requires a valid trade date.")
    if isinstance(candidate, datetime):
        return candidate.strftime("%Y%m%d")
    if isinstance(candidate, date):
        return candidate.strftime("%Y%m%d")

    text = str(candidate).replace("-", "").strip()
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid trade_date for SW historical valuation: {candidate}")
    return text


def _load_sw_history_anchor_cache(base_dir: Path, market: str = "CN"):
    cache_file = base_dir / "valuation_cache" / f"sw_history_anchor_{market}.json"
    if not cache_file.exists():
        return {}
    try:
        with cache_file.open("r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
        if not isinstance(payload, dict):
            return {}
        return payload.get("data", {}) or {}
    except Exception:  # pylint: disable=broad-exception-caught
        return {}


def _get_cached_sw_history_payload(base_dir: Path, market: str, industry_code: str, safe_float):
    if not industry_code:
        return None

    cache = _load_sw_history_anchor_cache(base_dir, market=market)
    payload = cache.get(industry_code)
    if not isinstance(payload, dict):
        return None

    anchors = payload.get("anchors") or {}
    if not any(safe_float(anchors.get(metric)) for metric in ("pe", "pb", "ps")):
        return None
    return payload


def resolve_sw_history_context(
    ts_code,
    trade_date,
    market="CN",
    token=None,
    pro=None,
    history_years=None,
    history_quantile=SW_HISTORY_DEFAULT_QUANTILE,
    history_min_samples=SW_HISTORY_DEFAULT_MIN_SAMPLES,
    safe_float=None,
    get_tushare_pro=None,
):
    if safe_float is None:
        raise ValueError("safe_float callback is required.")
    if get_tushare_pro is None:
        raise ValueError("get_tushare_pro callback is required.")

    base_dir = Path(settings.BASE_DIR) / "static"
    cfg = ValuationConfig(base_dir, market=market)
    sw_info = cfg.get_sw_params_by_tscode(ts_code)
    industry_code = sw_info.get("industry_code")
    if not industry_code:
        raise ValueError(f"未找到 {ts_code} 的申万行业编码，无法计算行业历史估值。")

    use_local_cache = str(getattr(settings, "SW_HISTORY_USE_LOCAL_CACHE", "1")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    use_remote_fallback = str(getattr(settings, "SW_HISTORY_USE_REMOTE_FALLBACK", "1")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if use_local_cache:
        cached_payload = _get_cached_sw_history_payload(base_dir, market, industry_code, safe_float)
        if isinstance(cached_payload, dict):
            return {"sw_info": sw_info, "history_payload": cached_payload}

    if not use_remote_fallback:
        raise ValueError(f"{ts_code} 的 sw_history 本地缓存缺失，且已禁用远端回退。")

    effective_pro = pro or get_tushare_pro(token=token)
    history_service = SwHistoryQuantileService(
        pro=effective_pro,
        window_years=normalize_sw_history_years(history_years),
        quantile=SW_HISTORY_DEFAULT_QUANTILE if history_quantile is None else float(history_quantile),
        min_samples=SW_HISTORY_DEFAULT_MIN_SAMPLES if history_min_samples is None else int(history_min_samples),
    )
    history_payload = history_service.build_history_payload(industry_code, trade_date)
    return {"sw_info": sw_info, "history_payload": history_payload}


def median_value(values):
    normalized = []
    for value in values:
        if value is None:
            continue
        try:
            value_float = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value_float):
            normalized.append(value_float)

    if not normalized:
        return None

    normalized.sort()
    mid = len(normalized) // 2
    if len(normalized) % 2 == 1:
        return normalized[mid]
    return (normalized[mid - 1] + normalized[mid]) / 2


def clamp_unit(value, safe_float, default=None):
    value_float = safe_float(value)
    if value_float is None:
        return default
    return max(0.0, min(1.0, value_float))


def resolve_scarcity_inputs(snapshot, valuations_df, scarcity_kwargs=None, safe_float=None, parse_date_yyyymmdd=None):
    if safe_float is None or parse_date_yyyymmdd is None:
        raise ValueError("safe_float and parse_date_yyyymmdd callbacks are required.")

    payload = dict(scarcity_kwargs or {})
    enabled = payload.get("enabled")
    if enabled is None:
        enabled = False
    if not bool(enabled):
        return None

    beta = safe_float(payload.get("beta"), 1.0)
    cap_pct = safe_float(payload.get("cap_pct"), 80.0)

    score = clamp_unit(payload.get("score"), safe_float=safe_float)
    if score is None:
        anchor_count = 0
        if valuations_df is not None and not valuations_df.empty and "method" in valuations_df.columns:
            for method in ["pe", "pb", "ps", "sw_history"]:
                rows = valuations_df[valuations_df["method"].astype(str).str.lower() == method]
                if rows.empty:
                    continue
                prices = pd.to_numeric(rows.get("implied_price"), errors="coerce").dropna()
                if not prices.empty and float(prices.iloc[0]) > 0:
                    anchor_count += 1
        score = max(0.2, min(1.0, anchor_count / 3.0))

    confidence = clamp_unit(payload.get("confidence"), safe_float=safe_float)
    if confidence is None:
        report_date = parse_date_yyyymmdd(snapshot.get("report_date"))
        if report_date is None:
            report_factor = 0.7
        elif report_date.month == 12:
            report_factor = 1.0
        elif report_date.month == 9:
            report_factor = 0.85
        elif report_date.month == 6:
            report_factor = 0.75
        elif report_date.month == 3:
            report_factor = 0.65
        else:
            report_factor = 0.7
        confidence = report_factor

    confidence_floor = clamp_unit(payload.get("confidence_floor"), safe_float=safe_float, default=0.35)
    confidence = max(confidence, confidence_floor)

    premium_pct = min(max(beta * score * confidence * 100.0, 0.0), max(cap_pct, 0.0))
    if premium_pct <= 0:
        return None

    return {
        "beta": beta,
        "cap_pct": cap_pct,
        "score": score,
        "confidence": confidence,
        "premium_pct": premium_pct,
    }


def select_scarcity_base_row(valuations_df, safe_float=None):
    if safe_float is None:
        raise ValueError("safe_float callback is required.")
    if valuations_df is None or valuations_df.empty:
        return None
    if "method" not in valuations_df.columns or "implied_price" not in valuations_df.columns:
        return None

    candidates = []
    for _, row in valuations_df.iterrows():
        method = str(row.get("method") or "").strip().lower()
        implied_price = safe_float(row.get("implied_price"))
        equity_value = safe_float(row.get("equity_value"))
        if not method or implied_price is None or implied_price <= 0:
            continue
        candidates.append(
            {
                "method": method,
                "implied_price": implied_price,
                "equity_value": equity_value,
            }
        )

    if not candidates:
        return None

    preference = {"sw_history": 0, "ps": 1, "pb": 2, "pe": 3}
    candidates.sort(key=lambda item: preference.get(item.get("method"), 100))
    return candidates[0]


def build_scarcity_overlay_row(snapshot, valuations_df, scarcity_kwargs=None, safe_float=None, parse_date_yyyymmdd=None):
    base_row = select_scarcity_base_row(valuations_df, safe_float=safe_float)
    if base_row is None:
        return None

    scarcity_inputs = resolve_scarcity_inputs(
        snapshot=snapshot,
        valuations_df=valuations_df,
        scarcity_kwargs=scarcity_kwargs,
        safe_float=safe_float,
        parse_date_yyyymmdd=parse_date_yyyymmdd,
    )
    if scarcity_inputs is None:
        return None

    multiplier = 1.0 + scarcity_inputs["premium_pct"] / 100.0
    return {
        "method": "scarcity_overlay",
        "ts_code": snapshot.get("ts_code"),
        "equity_value": base_row.get("equity_value") * multiplier if base_row.get("equity_value") is not None else None,
        "total_share": snapshot.get("total_share"),
        "implied_price": base_row.get("implied_price") * multiplier,
        "scarcity_base_method": base_row.get("method"),
        "scarcity_score": round(scarcity_inputs["score"], 4),
        "scarcity_confidence": round(scarcity_inputs["confidence"], 4),
        "scarcity_beta": round(scarcity_inputs["beta"], 4),
        "scarcity_cap_pct": round(scarcity_inputs["cap_pct"], 2),
        "scarcity_premium_pct": round(scarcity_inputs["premium_pct"], 2),
        "target_source": "scarcity_overlay",
    }
