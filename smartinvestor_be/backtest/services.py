import json
from bisect import bisect_left, insort
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
import math
from collections import deque
from pathlib import Path

from django.db.models import Q

from datastore.models import Corporation, StockTradingHistory
from prediction.management.commands.backtestbuycandidates import (
    _build_price_history,
    _resolve_entry_dates,
    _safe_price,
)
from prediction.management.commands.pickbuycandidates import (
    _build_snapshot_method_map,
    _summarize_buy_candidate,
)
from prediction.models import StockThsMoneyflowDaily, StockThsMoneyflowFeatureDaily
from valuation.models import StockValuationSnapshotHistory
from valuation.services.snapshot_provider import query_local_financial_df
from valuation_risk.models import ValuationRiskSnapshot
from backtest.models import TraditionalBacktestRun


TECHNICAL_FACTOR_ALIAS_MAP = {
    "price": "price",
    "close": "price",
    "close_qfq": "price",
    "pe": "pe",
    "pe_ttm": "pe",
    "pb": "pb",
    "ps": "ps",
    "turnover_rate": "turnover_rate_f",
    "turnover_rate_f": "turnover_rate_f",
    "volume_ratio": "volume_ratio",
    "vol_ratio": "volume_ratio",
}

MONEYFLOW_WINDOW_OPTIONS = (5, 10, 15, 30, 60)


def _normalize_moneyflow_window_days(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 10
    if parsed not in MONEYFLOW_WINDOW_OPTIONS:
        parsed = 10
    return parsed


def _load_moneyflow_feature_map(*, ts_codes, trade_date, window_days):
    normalized_codes = sorted({str(code or "").strip().upper() for code in (ts_codes or []) if str(code or "").strip()})
    if not normalized_codes or trade_date is None:
        return {}

    normalized_window_days = _normalize_moneyflow_window_days(window_days)
    sum_field = f"mf_sum_{normalized_window_days}"
    obs_field = f"obs_days_{normalized_window_days}"

    feature_rows = (
        StockThsMoneyflowFeatureDaily.objects.filter(ts_code__in=normalized_codes, trade_date=trade_date)
        .values("ts_code", sum_field, obs_field)
    )
    result = {}
    for row in feature_rows.iterator(chunk_size=2000):
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code:
            continue
        result[ts_code] = {
            "net_inflow_sum": _safe_float(row.get(sum_field)),
            "observed_days": int(row.get(obs_field) or 0),
        }

    missing_codes = [code for code in normalized_codes if code not in result]
    if not missing_codes:
        return result

    # Fallback path: compute from daily table for symbols missing feature rows.
    start_date = trade_date - timedelta(days=normalized_window_days * 3)
    rows = (
        StockThsMoneyflowDaily.objects.filter(
            ts_code__in=missing_codes,
            trade_date__gte=start_date,
            trade_date__lte=trade_date,
        )
        .order_by("ts_code", "trade_date")
        .values("ts_code", "net_amount", "net_mf_amount")
    )

    state_map = {
        code: {"queue": deque(), "sum": 0.0}
        for code in missing_codes
    }
    for row in rows.iterator(chunk_size=5000):
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if ts_code not in state_map:
            continue
        value = _safe_float(row.get("net_amount"))
        if value is None:
            value = _safe_float(row.get("net_mf_amount"))
        value = float(value) if value is not None else 0.0
        state = state_map[ts_code]
        state["queue"].append(value)
        state["sum"] += value
        if len(state["queue"]) > normalized_window_days:
            state["sum"] -= state["queue"].popleft()

    for ts_code in missing_codes:
        state = state_map[ts_code]
        result[ts_code] = {
            "net_inflow_sum": float(state["sum"]) if state["queue"] else None,
            "observed_days": len(state["queue"]),
        }
    return result


def _normalize_technical_factors(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value).split(",")

    normalized = []
    for item in raw_items:
        text = str(item or "").strip().lower()
        mapped = TECHNICAL_FACTOR_ALIAS_MAP.get(text)
        if mapped and mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _calc_low_quantile(values, quantile):
    if not values:
        return None
    q = min(1.0, max(0.0, float(quantile)))
    sorted_values = sorted(values)
    idx = int(math.floor((len(sorted_values) - 1) * q))
    idx = min(max(idx, 0), len(sorted_values) - 1)
    return float(sorted_values[idx])


def _build_technical_feature_history(*, ts_codes, start_date, end_date, lookback_days, factors, technical_low_quantile):
    normalized_factors = _normalize_technical_factors(factors)
    if not ts_codes or not normalized_factors:
        return {}

    lookback_days = max(5, int(lookback_days or 60))
    quantile = min(1.0, max(0.0, float(technical_low_quantile or 0.1)))
    history_start_date = start_date - timedelta(days=max(lookback_days * 3, 400))
    rows = (
        StockTradingHistory.objects.filter(
            ts_code__in=sorted(set(ts_codes)),
            freq="D",
            trade_date__gte=history_start_date,
            trade_date__lte=end_date,
        )
        .order_by("ts_code", "trade_date")
        .values(
            "ts_code",
            "trade_date",
            "close_qfq",
            "close",
            "pe_ttm",
            "pb",
            "ps",
            "turnover_rate_f",
            "volume_ratio",
        )
    )

    feature_history = {}
    for row in rows.iterator(chunk_size=5000):
        ts_code = str(row.get("ts_code") or "").strip().upper()
        trade_date = row.get("trade_date")
        if not ts_code or trade_date is None:
            continue

        row_price = _safe_price(row.get("close_qfq"))
        if row_price is None:
            row_price = _safe_price(row.get("close"))

        factor_values = {
            "price": row_price,
            "pe": _safe_float(row.get("pe_ttm")),
            "pb": _safe_float(row.get("pb")),
            "ps": _safe_float(row.get("ps")),
            "turnover_rate_f": _safe_float(row.get("turnover_rate_f")),
            "volume_ratio": _safe_float(row.get("volume_ratio")),
        }

        ts_payload = feature_history.setdefault(ts_code, {})
        for factor in normalized_factors:
            value = factor_values.get(factor)
            if value is None or not math.isfinite(float(value)) or float(value) <= 0:
                continue
            factor_payload = ts_payload.setdefault(
                factor,
                {
                    "status_by_date": {},
                    "_window": deque(),
                    "_sorted_window": [],
                },
            )
            window = factor_payload["_window"]
            sorted_window = factor_payload["_sorted_window"]
            if len(window) == lookback_days:
                oldest_value = window.popleft()
                oldest_idx = bisect_left(sorted_window, oldest_value)
                if oldest_idx < len(sorted_window):
                    sorted_window.pop(oldest_idx)
            value_float = float(value)
            window.append(value_float)
            insort(sorted_window, value_float)
            if len(window) < lookback_days:
                factor_payload["status_by_date"][trade_date] = "missing"
                continue
            threshold_index = int(math.floor((lookback_days - 1) * quantile))
            threshold_index = min(max(threshold_index, 0), len(sorted_window) - 1)
            threshold = sorted_window[threshold_index]
            factor_payload["status_by_date"][trade_date] = "passed" if value_float <= threshold + 1e-12 else "not_low_quantile"

    for ts_payload in feature_history.values():
        for factor_payload in ts_payload.values():
            factor_payload.pop("_window", None)
            factor_payload.pop("_sorted_window", None)

    return feature_history


def _build_price_technical_history_from_price_history(*, price_history, start_date, end_date, lookback_days, technical_low_quantile):
    if not price_history:
        return {}

    lookback_days = max(5, int(lookback_days or 60))
    quantile = min(1.0, max(0.0, float(technical_low_quantile or 0.1)))
    threshold_index = int(math.floor((lookback_days - 1) * quantile))
    threshold_index = min(max(threshold_index, 0), lookback_days - 1)

    feature_history = {}
    for ts_code, series in price_history.items():
        if not ts_code or not series:
            continue

        ts_payload = feature_history.setdefault(ts_code, {})
        factor_payload = ts_payload.setdefault(
            "price",
            {
                "status_by_date": {},
                "_window": deque(),
                "_sorted_window": [],
            },
        )
        window = factor_payload["_window"]
        sorted_window = factor_payload["_sorted_window"]

        for trade_date, raw_price in series:
            if trade_date is None:
                continue
            if trade_date < start_date or trade_date > end_date:
                continue

            price = _safe_price(raw_price)
            if price is None or not math.isfinite(float(price)) or float(price) <= 0:
                factor_payload["status_by_date"][trade_date] = "missing"
                continue

            if len(window) == lookback_days:
                oldest_value = window.popleft()
                oldest_idx = bisect_left(sorted_window, oldest_value)
                if oldest_idx < len(sorted_window):
                    sorted_window.pop(oldest_idx)

            price_value = float(price)
            window.append(price_value)
            insort(sorted_window, price_value)

            if len(window) < lookback_days:
                factor_payload["status_by_date"][trade_date] = "missing"
                continue

            threshold_idx = min(max(threshold_index, 0), len(sorted_window) - 1)
            threshold = sorted_window[threshold_idx]
            factor_payload["status_by_date"][trade_date] = "passed" if price_value <= threshold + 1e-12 else "not_low_quantile"

    for ts_payload in feature_history.values():
        for factor_payload in ts_payload.values():
            factor_payload.pop("_window", None)
            factor_payload.pop("_sorted_window", None)

    return feature_history


def _passes_technical_filters(
    *,
    technical_history_map,
    ts_code,
    trade_date,
    technical_factors,
):
    normalized_factors = _normalize_technical_factors(technical_factors)
    if not normalized_factors:
        return True, "disabled"

    ts_payload = technical_history_map.get(str(ts_code or "").strip().upper()) or {}

    for factor in normalized_factors:
        factor_payload = ts_payload.get(factor) or {}
        status = (factor_payload.get("status_by_date") or {}).get(trade_date)

        if status is None:
            return False, "missing"
        if status != "passed":
            return False, status

    return True, "passed"


def _build_date_price_map(price_history):
    date_price_map = {}
    for ts_code, series in price_history.items():
        for trade_date, price in series:
            date_price_map.setdefault(trade_date, {})[ts_code] = price
    return date_price_map


def _build_daily_ohlc_map(ts_codes, start_date, end_date):
    if not ts_codes:
        return {}

    rows = (
        StockTradingHistory.objects.filter(
            ts_code__in=sorted(set(ts_codes)),
            freq="D",
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        .order_by("ts_code", "trade_date")
        .values(
            "ts_code",
            "trade_date",
            "open_qfq",
            "high_qfq",
            "low_qfq",
            "close_qfq",
            "open",
            "high",
            "low",
            "close",
        )
    )

    ohlc_map = {}
    for row in rows.iterator(chunk_size=5000):
        ts_code = row.get("ts_code")
        trade_date = row.get("trade_date")
        if not ts_code or trade_date is None:
            continue

        open_px = _safe_price(row.get("open_qfq"))
        if open_px is None:
            open_px = _safe_price(row.get("open"))
        high_px = _safe_price(row.get("high_qfq"))
        if high_px is None:
            high_px = _safe_price(row.get("high"))
        low_px = _safe_price(row.get("low_qfq"))
        if low_px is None:
            low_px = _safe_price(row.get("low"))
        close_px = _safe_price(row.get("close_qfq"))
        if close_px is None:
            close_px = _safe_price(row.get("close"))
        if close_px is None:
            continue
        if open_px is None:
            open_px = close_px
        if high_px is None:
            high_px = max(open_px, close_px)
        if low_px is None:
            low_px = min(open_px, close_px)

        ohlc_map.setdefault(ts_code, {})[trade_date] = {
            "open": float(open_px),
            "high": float(high_px),
            "low": float(low_px),
            "close": float(close_px),
        }
    return ohlc_map


def _split_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _normalize_stop_loss_scope(value):
    scope = str(value or "position").strip().lower()
    if scope not in {"position", "account"}:
        raise ValueError("stop_loss_scope must be 'position' or 'account'")
    return scope


def _normalize_scope(scope):
    return str(scope or "ALL").strip().upper()


def _apply_scope_qs_filter(qs, scope):
    normalized_scope = _normalize_scope(scope)
    if normalized_scope == "ALL":
        return qs
    prefixes = _split_csv(normalized_scope)
    if not prefixes:
        return qs

    q = Q()
    for prefix in prefixes:
        q |= Q(ts_code__startswith=prefix)
    return qs.filter(q)


def _normalize_valuation_method_name(method_name):
    if method_name is None:
        return ""
    return (
        str(method_name)
        .strip()
        .lower()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "")
    )


def _resolve_history_entry_dates(*, scope, market, start_date, end_date):
    qs = StockValuationSnapshotHistory.objects.filter(market=market)
    if start_date is not None:
        qs = qs.filter(trade_date__gte=start_date)
    if end_date is not None:
        qs = qs.filter(trade_date__lte=end_date)
    qs = _apply_scope_qs_filter(qs, scope)
    return list(qs.values_list("trade_date", flat=True).distinct().order_by("trade_date"))


def _build_history_method_map(*, ts_codes, trade_date, market):
    if not ts_codes:
        return {}

    rows = (
        StockValuationSnapshotHistory.objects.filter(
            ts_code__in=ts_codes,
            trade_date=trade_date,
            market=market,
        )
        .order_by("ts_code", "valuation_method", "-archived_at", "-id")
        .values(
            "ts_code",
            "valuation_method",
            "valuation_price",
            "valuation_market_cap",
            "source",
        )
    )

    method_map = {}
    for row in rows:
        ts_code = row["ts_code"]
        method = _normalize_valuation_method_name(row.get("valuation_method"))
        if not method:
            continue
        price = _safe_price(row.get("valuation_price"))
        if price is None:
            continue
        ts_payload = method_map.setdefault(ts_code, {})
        if method in ts_payload:
            continue
        valuation_market_cap = row.get("valuation_market_cap")
        ts_payload[method] = {
            "valuation_price": float(price),
            "valuation_market_cap": float(valuation_market_cap) if valuation_market_cap is not None else None,
            "source": row.get("source"),
        }
    return method_map


def _build_risk_map(entry_dates, market, valuation_variant=None):
    rows = (
        ValuationRiskSnapshot.objects.filter(
            market=market,
            trade_date__in=entry_dates,
        )
        .order_by("trade_date", "ts_code", "-updated_at")
        .values("trade_date", "ts_code", "valuation_variant", "risk_level", "risk_score")
    )
    risk_map = {}
    for row in rows.iterator(chunk_size=5000):
        key = (row["trade_date"], row["ts_code"])
        payload = risk_map.setdefault(
            key,
            {
                "risk_levels": set(),
                "risk_scores": [],
                "variants": set(),
                "variant_levels": {},
            },
        )
        risk_level = str(row.get("risk_level") or "").upper()
        variant = str(row.get("valuation_variant") or "")
        if risk_level:
            payload["risk_levels"].add(risk_level)
        if row.get("risk_score") is not None:
            payload["risk_scores"].append(float(row["risk_score"]))
        if variant:
            payload["variants"].add(variant)
            if risk_level:
                payload["variant_levels"][variant] = risk_level

    normalized_variant = str(valuation_variant or "").strip()
    for payload in risk_map.values():
        payload["risk_levels"] = sorted(payload["risk_levels"])
        payload["variants"] = sorted(payload["variants"])
        payload["min_risk_score"] = min(payload["risk_scores"]) if payload["risk_scores"] else None
        payload["max_risk_score"] = max(payload["risk_scores"]) if payload["risk_scores"] else None
        if normalized_variant:
            payload["selected_variant_risk_level"] = payload["variant_levels"].get(normalized_variant)
        else:
            payload["selected_variant_risk_level"] = None
    return risk_map


def _build_latest_risk_snapshot_map(ts_codes, market):
    ts_code_list = sorted({str(ts_code or "").strip().upper() for ts_code in (ts_codes or []) if str(ts_code or "").strip()})
    if not ts_code_list:
        return {}

    rows = (
        ValuationRiskSnapshot.objects.filter(
            market=market,
            ts_code__in=ts_code_list,
        )
        .order_by("ts_code", "trade_date", "-updated_at")
        .values("ts_code", "trade_date", "valuation_variant", "risk_level", "risk_score")
    )

    latest_map = {}
    for row in rows.iterator(chunk_size=5000):
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code or ts_code in latest_map:
            continue
        latest_map[ts_code] = {
            "valuation_risk_level": str(row.get("risk_level") or "").strip().upper() or None,
            "valuation_risk_score": _safe_float(row.get("risk_score")),
            "valuation_risk_trade_date": row.get("trade_date"),
        }
    return latest_map


def _resolve_risk_alignment_payload(risk_payload, fallback_risk_payload=None, risk_alignment_mode="legacy"):
    _ = risk_alignment_mode
    mode = "legacy"

    payload = risk_payload or {}
    fallback = fallback_risk_payload or {}
    matched_risk_level = str(payload.get("selected_variant_risk_level") or "").strip().upper() or None
    risk_levels = [
        str(level or "").strip().upper() or None
        for level in (payload.get("risk_levels") or [])
    ]
    risk_levels = [level for level in risk_levels if level]

    fallback_risk_level = str(fallback.get("valuation_risk_level") or "").strip().upper() or None
    fallback_risk_score = _safe_float(fallback.get("valuation_risk_score"))
    if mode == "current":
        if not risk_levels and fallback_risk_level:
            risk_levels = [fallback_risk_level]
        if matched_risk_level is None and fallback_risk_level:
            matched_risk_level = fallback_risk_level

    row_risk_score = _safe_float(payload.get("min_risk_score"))
    if mode == "current" and row_risk_score is None:
        row_risk_score = fallback_risk_score

    return {
        "risk_levels": risk_levels,
        "matched_risk_level": matched_risk_level,
        "row_risk_score": row_risk_score,
        "fallback_risk_level": fallback_risk_level,
        "fallback_risk_score": fallback_risk_score,
    }


def _summarize_trade_bucket(trades):
    if not trades:
        return {
            "trade_count": 0,
            "avg_return_pct": None,
            "median_return_pct": None,
            "win_rate_pct": None,
            "avg_holding_days": None,
            "target_exit_count": 0,
            "take_profit_exit_count": 0,
            "stop_loss_exit_count": 0,
            "eop_exit_count": 0,
        }

    returns = sorted(float(item["return_pct"]) for item in trades)
    hold_days = [int(item["holding_days"]) for item in trades]
    n = len(trades)
    wins = sum(1 for item in trades if float(item["return_pct"]) > 0)
    target_exits = sum(1 for item in trades if item.get("exit_reason") == "target_hit")
    take_profit_exits = sum(1 for item in trades if item.get("exit_reason") == "take_profit_pct_hit")
    stop_loss_exits = sum(
        1
        for item in trades
        if item.get("exit_reason") in {"stop_loss_pct_hit", "account_stop_loss_pct_hit"}
    )
    account_stop_loss_exits = sum(1 for item in trades if item.get("exit_reason") == "account_stop_loss_pct_hit")
    eop_exits = sum(1 for item in trades if item.get("exit_reason") == "end_of_period")
    return {
        "trade_count": n,
        "avg_return_pct": round(sum(returns) / n, 4),
        "median_return_pct": round(returns[n // 2], 4),
        "win_rate_pct": round(wins / n * 100.0, 2),
        "avg_holding_days": round(sum(hold_days) / n, 2),
        "target_exit_count": target_exits,
        "take_profit_exit_count": take_profit_exits,
        "stop_loss_exit_count": stop_loss_exits,
        "account_stop_loss_exit_count": account_stop_loss_exits,
        "eop_exit_count": eop_exits,
    }


def _compute_saved_backtesting_like_metrics(*, starting_capital, final_asset, daily_equity, closed_trades, kline_days, exposure_days):
    trade_returns_pct = [float(item.get("return_pct") or 0.0) for item in closed_trades]
    trade_returns_dec = [value / 100.0 for value in trade_returns_pct]
    trade_count = len(trade_returns_pct)

    avg_trade_pct = round(sum(trade_returns_pct) / trade_count, 4) if trade_count else 0.0
    best_trade_pct = round(max(trade_returns_pct), 4) if trade_count else None
    worst_trade_pct = round(min(trade_returns_pct), 4) if trade_count else None

    positive = [value for value in trade_returns_pct if value > 0]
    negative = [value for value in trade_returns_pct if value < 0]
    avg_win = (sum(positive) / len(positive)) if positive else 0.0
    avg_loss = (sum(negative) / len(negative)) if negative else 0.0
    win_rate = (len(positive) / trade_count) if trade_count else 0.0
    loss_rate = (len(negative) / trade_count) if trade_count else 0.0
    expectancy_pct = round((win_rate * avg_win) + (loss_rate * avg_loss), 4) if trade_count else None

    gross_profit = sum(value for value in trade_returns_dec if value > 0)
    gross_loss_abs = sum(abs(value) for value in trade_returns_dec if value < 0)
    profit_factor = round(gross_profit / gross_loss_abs, 4) if gross_loss_abs > 0 else None

    equity_values = [float(item[1]) for item in daily_equity if isinstance(item, (list, tuple)) and len(item) >= 2]
    equity_final = round(float(final_asset), 2)
    equity_peak = round(max(equity_values), 2) if equity_values else equity_final

    daily_returns = []
    for idx in range(1, len(equity_values)):
        prev_equity = equity_values[idx - 1]
        curr_equity = equity_values[idx]
        if prev_equity > 0:
            daily_returns.append((curr_equity / prev_equity) - 1.0)

    sharpe_ratio = None
    sortino_ratio = None
    if daily_returns:
        mean_daily = sum(daily_returns) / len(daily_returns)
        variance = sum((ret - mean_daily) ** 2 for ret in daily_returns) / len(daily_returns)
        std = math.sqrt(variance)
        if std > 0:
            sharpe_ratio = round((mean_daily / std) * math.sqrt(252.0), 4)

        downside = [ret for ret in daily_returns if ret < 0]
        if downside:
            downside_mean = sum(downside) / len(downside)
            downside_var = sum((ret - downside_mean) ** 2 for ret in downside) / len(downside)
            downside_std = math.sqrt(downside_var)
            if downside_std > 0:
                sortino_ratio = round((mean_daily / downside_std) * math.sqrt(252.0), 4)

    peak = None
    max_drawdown = 0.0
    drawdowns = []
    for equity in equity_values:
        if peak is None or equity > peak:
            peak = equity
        if peak and peak > 0:
            dd = (peak - equity) / peak
            drawdowns.append(dd)
            if dd > max_drawdown:
                max_drawdown = dd
    avg_drawdown_pct = round((sum(drawdowns) / len(drawdowns)) * 100.0, 4) if drawdowns else None

    total_return_pct = round((float(final_asset) / float(starting_capital) - 1.0) * 100.0, 4) if float(starting_capital) > 0 else 0.0
    calmar_ratio = round((total_return_pct / 100.0) / max_drawdown, 4) if max_drawdown > 0 else None

    exposure_time_pct = round((float(exposure_days) / float(kline_days)) * 100.0, 4) if kline_days > 0 else 0.0

    sqn = None
    if trade_count >= 2:
        mean_trade = sum(trade_returns_dec) / trade_count
        var_trade = sum((ret - mean_trade) ** 2 for ret in trade_returns_dec) / (trade_count - 1)
        std_trade = math.sqrt(var_trade) if var_trade > 0 else 0.0
        if std_trade > 0:
            sqn = round((math.sqrt(trade_count) * mean_trade) / std_trade, 4)

    return {
        "mode": "saved_backtesting_like",
        "kline_days": int(kline_days),
        "trade_count": int(trade_count),
        "return_pct": total_return_pct,
        "buy_hold_return_pct": None,
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "avg_drawdown_pct": avg_drawdown_pct,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "profit_factor": profit_factor,
        "expectancy_pct": expectancy_pct,
        "avg_trade_pct": avg_trade_pct,
        "best_trade_pct": best_trade_pct,
        "worst_trade_pct": worst_trade_pct,
        "exposure_time_pct": exposure_time_pct,
        "equity_final": equity_final,
        "equity_peak": equity_peak,
        "sqn": sqn,
    }


def _resolve_output_path(project_root, strategy_name, start_date, end_date, output_json=None):
    if output_json:
        return Path(output_json)
    file_name = f"{strategy_name}_{start_date.isoformat()}_{end_date.isoformat()}.json"
    return project_root / "output" / "backtests" / strategy_name / file_name


def _candidate_buy_rank_key(item, priority_policy="score_desc"):
    policy = str(priority_policy or "score_desc").strip().lower()
    score = float(item.get("score") or 0.0)
    entry_price = float(item.get("entry_price") or 0.0)
    discount_pct = float(item.get("discount_pct") or 0.0)
    target_discount_pct = float(item.get("target_discount_pct") or 0.0)
    risk_score = _safe_float(item.get("risk_score"))
    normalized_risk_score = float(risk_score) if risk_score is not None else math.inf
    ts_code = str(item.get("ts_code") or "")

    if policy == "high_price_first":
        return (-score, -entry_price, ts_code)
    if policy == "low_price_first":
        return (-score, entry_price, ts_code)
    if policy == "deep_discount_first":
        return (-discount_pct, -score, entry_price, ts_code)
    if policy == "target_discount_first":
        return (-target_discount_pct, -score, entry_price, ts_code)
    if policy == "low_risk_high_score":
        return (normalized_risk_score, -score, entry_price, ts_code)
    return (-score, -entry_price, ts_code)


def _is_bj_code(ts_code):
    return str(ts_code or "").strip().upper().endswith(".BJ")


def _is_kcb_code(ts_code):
    code = str(ts_code or "").strip().upper()
    return code.startswith("688") and code.endswith(".SH")


def _buy_lot_size_for_code(ts_code):
    if _is_kcb_code(ts_code):
        return 200
    if _is_bj_code(ts_code):
        return 1
    return 100


def _calc_buy_shares(budget, unit_cost, ts_code):
    if unit_cost <= 0:
        return 0
    raw_shares = int(math.floor(float(budget) / float(unit_cost)))
    lot_size = int(_buy_lot_size_for_code(ts_code))
    if raw_shares < lot_size:
        return 0
    if lot_size <= 1:
        return raw_shares
    return raw_shares - (raw_shares % lot_size)


def _calc_sell_shares(held_shares, ts_code, desired_shares=None):
    held = max(0, int(held_shares or 0))
    if held <= 0:
        return 0
    desired = held if desired_shares is None else max(0, int(desired_shares or 0))
    desired = min(desired, held)
    if desired <= 0:
        return 0

    if _is_kcb_code(ts_code) or _is_bj_code(ts_code):
        return desired

    lot_size = 100
    if desired >= held:
        return held
    if held <= lot_size:
        return held

    sell = desired - (desired % lot_size)
    if sell <= 0:
        return 0
    remaining = held - sell
    if 0 < remaining < lot_size:
        return held
    return sell


def _calc_sma_up_to_date(series, trade_date, period):
    if not series:
        return None
    window = []
    for row_date, row_price in series:
        if row_date is None or row_price is None:
            continue
        if row_date > trade_date:
            break
        window.append(float(row_price))
    if len(window) < int(period):
        return None
    sliced = window[-int(period):]
    return sum(sliced) / float(period)


def _normalize_take_profit_tiers(tiers):
    normalized = []
    raw = tiers if isinstance(tiers, list) else []
    for row in raw:
        if not isinstance(row, dict):
            continue
        trigger = _safe_float(row.get("trigger_pct"))
        ratio = _safe_float(row.get("sell_ratio"))
        if trigger is None or ratio is None:
            continue
        if trigger <= 0:
            continue
        ratio = max(0.0, min(1.0, float(ratio)))
        if ratio <= 0:
            continue
        normalized.append({"trigger_pct": float(trigger), "sell_ratio": float(ratio)})
    normalized.sort(key=lambda item: item["trigger_pct"])
    return normalized


def _calc_tier_sell_shares(held_shares, tp_base_shares, tier_sell_ratio, ts_code):
    held = max(0, int(held_shares or 0))
    base = max(0, int(tp_base_shares or 0))
    ratio = max(0.0, float(tier_sell_ratio or 0.0))
    if held <= 0 or base <= 0 or ratio <= 0:
        return 0
    desired = int(math.floor(base * ratio))
    if desired <= 0:
        return 0
    return _calc_sell_shares(held, ts_code, desired)


def _calc_trend_reserved_shares(tp_base_shares, trend_position_pct):
    base = max(0, int(tp_base_shares or 0))
    pct = max(0.0, min(1.0, float(trend_position_pct or 0.0)))
    if base <= 0 or pct <= 0:
        return 0
    reserved = int(math.floor(base * pct))
    return max(0, min(base, reserved))


def _calc_limited_sell_shares(held_shares, desired_shares, ts_code, min_remaining_shares=0):
    held = max(0, int(held_shares or 0))
    desired = max(0, int(desired_shares or 0))
    min_remaining = max(0, int(min_remaining_shares or 0))
    if held <= 0 or desired <= 0:
        return 0
    if min_remaining >= held:
        return 0
    max_sell = held - min_remaining
    desired = min(desired, max_sell)
    if desired <= 0:
        return 0

    if _is_kcb_code(ts_code) or _is_bj_code(ts_code):
        return desired

    lot_size = 100
    if desired >= held and min_remaining == 0:
        return held

    sell = desired - (desired % lot_size)
    while sell > 0 and (held - sell) < min_remaining:
        sell -= lot_size
    if sell <= 0:
        return 0
    return sell


def _is_trend_activation_met(position, trend_activation_profit):
    threshold = max(0.0, float(trend_activation_profit or 0.0))
    if threshold <= 0:
        return True
    entry_price = float(position.get("entry_price") or 0.0)
    if entry_price <= 0:
        return False
    peak_price = float(position.get("peak_price") or entry_price)
    if peak_price <= 0:
        peak_price = entry_price
    return (peak_price / entry_price - 1.0) >= (threshold - 1e-12)


def _persist_traditional_backtest_run(
    *,
    run_key,
    strategy_name,
    scope,
    market,
    start_date,
    end_date,
    risk_level,
    valuation_variant,
    risk_variant_policy,
    band_pct,
    min_score,
    min_netprofit_yoy,
    min_ebit_yoy,
    require_positive_prev_netprofit,
    require_positive_prev_ebit,
    financial_filter_mode,
    take_profit_mode,
    take_profit_tiers,
    trend_take_profit_enabled,
    trend_position_pct,
    trend_activation_profit,
    trend_ma_period,
    trend_confirm_days,
    take_profit_pct,
    stop_loss_mode,
    stop_loss_pct,
    trailing_stop_pct,
    stop_loss_scope,
    disable_target_hit,
    max_holding_days=0,
    starting_capital=None,
    max_position_pct=None,
    first_entry_pct=None,
    add_on_entry_pct=None,
    add_on_drop_pct=None,
    add_on2_drop_pct=None,
    add_on2_fill_remaining=None,
    max_buy_per_day=None,
    priority_policy=None,
    buy_weight_ladder=None,
    technical_strategy_enabled=False,
    technical_lookback_days=60,
    technical_factors=None,
    technical_low_quantile=0.1,
    apply_moneyflow_filters=False,
    moneyflow_net_inflow_days_window=10,
    result_file,
    summary,
):
    stored_summary = (summary or {}).get("account") or (summary or {}).get("combined") or {}
    TraditionalBacktestRun.objects.update_or_create(
        run_key=run_key,
        defaults={
            "batch_key": strategy_name,
            "strategy_name": strategy_name,
            "status": "success",
            "scope": str(scope or "ALL"),
            "market": str(market or "CN"),
            "start_date": start_date,
            "end_date": end_date,
            "params_json": {
                "band_pct": band_pct,
                "min_score": min_score,
                "risk_level": risk_level,
                "valuation_variant": valuation_variant,
                "risk_variant_policy": risk_variant_policy,
                "min_netprofit_yoy": min_netprofit_yoy,
                "min_ebit_yoy": min_ebit_yoy,
                "require_positive_prev_netprofit": require_positive_prev_netprofit,
                "require_positive_prev_ebit": require_positive_prev_ebit,
                "financial_filter_mode": financial_filter_mode,
                "take_profit_mode": take_profit_mode,
                "take_profit_tiers": take_profit_tiers,
                "trend_take_profit_enabled": trend_take_profit_enabled,
                "trend_position_pct": trend_position_pct,
                "trend_activation_profit": trend_activation_profit,
                "trend_ma_period": trend_ma_period,
                "trend_confirm_days": trend_confirm_days,
                "max_holding_days": max_holding_days,
                "take_profit_pct": take_profit_pct,
                "stop_loss_mode": stop_loss_mode,
                "stop_loss_pct": stop_loss_pct,
                "trailing_stop_pct": trailing_stop_pct,
                "stop_loss_scope": stop_loss_scope,
                "disable_target_hit": bool(disable_target_hit),
                "starting_capital": starting_capital,
                "max_position_pct": max_position_pct,
                "first_entry_pct": first_entry_pct,
                "add_on_entry_pct": add_on_entry_pct,
                "add_on_drop_pct": add_on_drop_pct,
                "add_on2_drop_pct": add_on2_drop_pct,
                "add_on2_fill_remaining": add_on2_fill_remaining,
                "max_buy_per_day": max_buy_per_day,
                "priority_policy": priority_policy,
                "buy_weight_ladder": buy_weight_ladder or [],
                "technical_strategy_enabled": bool(technical_strategy_enabled),
                "technical_lookback_days": int(technical_lookback_days or 60),
                "technical_factors": _normalize_technical_factors(technical_factors),
                "technical_low_quantile": float(technical_low_quantile or 0.1),
                "apply_moneyflow_filters": bool(apply_moneyflow_filters),
                "moneyflow_net_inflow_days_window": _normalize_moneyflow_window_days(moneyflow_net_inflow_days_window),
            },
            "summary_json": stored_summary,
            "result_json": summary or {},
            "result_file": result_file,
            "error_message": "",
        },
    )


def _normalize_risk_levels(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value).split(",")

    normalized = []
    for item in raw_items:
        text = str(item or "").strip().upper()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _chunked(items, chunk_size):
    chunk_size = max(1, int(chunk_size or 500))
    for start_idx in range(0, len(items), chunk_size):
        yield items[start_idx : start_idx + chunk_size]


def _parse_panel_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _same_period_last_year(end_date_value):
    normalized = _parse_panel_date(end_date_value)
    if normalized is None:
        return None
    try:
        return normalized.replace(year=normalized.year - 1)
    except ValueError:
        return None


def _calc_yoy_pct(current_value, previous_value):
    current_num = _safe_float(current_value)
    previous_num = _safe_float(previous_value)
    if current_num is None or previous_num in (None, 0):
        return None
    return ((current_num - previous_num) / abs(previous_num)) * 100.0


def _load_financial_panel_map(ts_codes, max_ann_date):
    if not ts_codes or max_ann_date is None:
        return {}

    rows = []
    for code_chunk in _chunked(sorted(set(ts_codes)), 500):
        placeholders = ",".join(["%s"] * len(code_chunk))
        sql = f"""
            SELECT ts_code, ann_date, end_date, report_type, netprofit_yoy, operate_profit, n_income, n_income_attr_p
            FROM earnings_financial_feature_panel
            WHERE ts_code IN ({placeholders})
              AND ann_date IS NOT NULL
              AND ann_date <= %s
            ORDER BY ts_code, ann_date DESC, end_date DESC
        """
        chunk_df = query_local_financial_df(
            sql,
            [*code_chunk, max_ann_date.strftime("%Y%m%d")],
            db_alias="earnings",
        )
        if chunk_df is None or chunk_df.empty:
            continue
        rows.extend(chunk_df.to_dict(orient="records"))

    panel_map = defaultdict(list)
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        ann_date = _parse_panel_date(row.get("ann_date"))
        end_date = _parse_panel_date(row.get("end_date"))
        if not ts_code or ann_date is None or end_date is None:
            continue
        payload = dict(row)
        payload["ann_date_obj"] = ann_date
        payload["end_date_obj"] = end_date
        payload["netprofit_yoy_value"] = _safe_float(row.get("netprofit_yoy"))
        payload["operate_profit_value"] = _safe_float(row.get("operate_profit"))
        payload["netprofit_value"] = _safe_float(row.get("n_income_attr_p"))
        if payload["netprofit_value"] is None:
            payload["netprofit_value"] = _safe_float(row.get("n_income"))
        panel_map[ts_code].append(payload)
    return panel_map


def _resolve_financial_metrics(financial_panel_map, ts_code, trade_date, cache):
    cache_key = (ts_code, trade_date)
    if cache_key in cache:
        return cache[cache_key]

    rows = financial_panel_map.get(ts_code) or []
    selected_row = None
    for row in rows:
        ann_date = row.get("ann_date_obj")
        if ann_date is not None and ann_date <= trade_date:
            selected_row = row
            break

    if selected_row is None:
        cache[cache_key] = None
        return None

    prev_same_end_date = _same_period_last_year(selected_row.get("end_date_obj"))
    prev_same_row = None
    if prev_same_end_date is not None:
        for row in rows:
            if row.get("end_date_obj") == prev_same_end_date and row.get("ann_date_obj") <= trade_date:
                prev_same_row = row
                break

    netprofit_yoy = selected_row.get("netprofit_yoy_value")
    if netprofit_yoy is None:
        netprofit_yoy = _calc_yoy_pct(
            selected_row.get("netprofit_value"),
            (prev_same_row or {}).get("netprofit_value"),
        )

    ebit_yoy = _calc_yoy_pct(
        selected_row.get("operate_profit_value"),
        (prev_same_row or {}).get("operate_profit_value"),
    )

    payload = {
        "ann_date": selected_row.get("ann_date_obj"),
        "end_date": selected_row.get("end_date_obj"),
        "report_type": selected_row.get("report_type"),
        "netprofit_yoy": round(netprofit_yoy, 4) if netprofit_yoy is not None else None,
        "ebit_yoy": round(ebit_yoy, 4) if ebit_yoy is not None else None,
        "prev_netprofit": _safe_float((prev_same_row or {}).get("netprofit_value")),
        "prev_ebit": _safe_float((prev_same_row or {}).get("operate_profit_value")),
    }
    cache[cache_key] = payload
    return payload


def _passes_financial_filters(
    financial_payload,
    min_netprofit_yoy,
    min_ebit_yoy,
    financial_filter_mode,
    require_positive_prev_netprofit=True,
    require_positive_prev_ebit=True,
):
    conditions = []
    if min_netprofit_yoy is not None:
        netprofit_yoy = None if not financial_payload else financial_payload.get("netprofit_yoy")
        conditions.append(netprofit_yoy is not None and float(netprofit_yoy) >= float(min_netprofit_yoy))
    if min_ebit_yoy is not None:
        ebit_yoy = None if not financial_payload else financial_payload.get("ebit_yoy")
        conditions.append(ebit_yoy is not None and float(ebit_yoy) >= float(min_ebit_yoy))
    if require_positive_prev_netprofit:
        prev_netprofit = None if not financial_payload else financial_payload.get("prev_netprofit")
        conditions.append(prev_netprofit is not None and float(prev_netprofit) >= 0)
    if require_positive_prev_ebit:
        prev_ebit = None if not financial_payload else financial_payload.get("prev_ebit")
        conditions.append(prev_ebit is not None and float(prev_ebit) >= 0)
    if not conditions:
        return True
    if str(financial_filter_mode or "all").strip().lower() == "any":
        return any(conditions)
    return all(conditions)


def run_traditional_value_exit_backtest(
    *,
    scope,
    market,
    start_date,
    end_date,
    band_pct,
    min_score,
    risk_level,
    valuation_variant="",
    risk_variant_policy="any",
    risk_alignment_mode="legacy",
    min_netprofit_yoy=None,
    min_ebit_yoy=None,
    require_positive_prev_netprofit=True,
    require_positive_prev_ebit=True,
    financial_filter_mode="all",
    take_profit_mode="fixed",
    take_profit_tiers=None,
    trend_take_profit_enabled=False,
    trend_position_pct=0.0,
    trend_activation_profit=0.0,
    trend_ma_period=20,
    trend_confirm_days=2,
    take_profit_pct=0.0,
    stop_loss_mode="fixed",
    stop_loss_pct=0.0,
    trailing_stop_pct=0.0,
    stop_loss_scope="position",
    technical_strategy_enabled=False,
    technical_lookback_days=60,
    technical_factors=None,
    technical_low_quantile=0.1,
    apply_moneyflow_filters=False,
    moneyflow_net_inflow_days_window=10,
    disable_target_hit=False,
    progress_every=50,
    output_json=None,
    stdout=None,
):
    project_root = Path(__file__).resolve().parents[1]
    strategy_name = "traditional_value_exit"
    risk_variant_policy = str(risk_variant_policy or "any").strip().lower()
    if risk_variant_policy not in {"any", "specific"}:
        raise ValueError("risk_variant_policy must be 'any' or 'specific'")
    risk_alignment_mode = "legacy"
    financial_filter_mode = str(financial_filter_mode or "all").strip().lower()
    if financial_filter_mode not in {"all", "any"}:
        raise ValueError("financial_filter_mode must be 'all' or 'any'")
    take_profit_mode = str(take_profit_mode or "fixed").strip().lower()
    take_profit_tiers = _normalize_take_profit_tiers(take_profit_tiers)
    trend_take_profit_enabled = bool(trend_take_profit_enabled)
    trend_position_pct = max(0.0, min(1.0, float(trend_position_pct or 0.0)))
    trend_activation_profit = max(0.0, min(1.0, float(trend_activation_profit or 0.0)))
    trend_ma_period = max(2, int(trend_ma_period or 20))
    trend_confirm_days = max(1, int(trend_confirm_days or 2))
    take_profit_pct = max(0.0, float(take_profit_pct or 0.0))
    stop_loss_mode = str(stop_loss_mode or "fixed").strip().lower()
    stop_loss_pct = max(0.0, float(stop_loss_pct or 0.0))
    trailing_stop_pct = max(0.0, float(trailing_stop_pct or 0.0))
    stop_loss_scope = _normalize_stop_loss_scope(stop_loss_scope)
    disable_target_hit = bool(disable_target_hit)
    allowed_risk_levels = _normalize_risk_levels(risk_level)
    if not allowed_risk_levels:
        raise ValueError("risk_level must contain at least one value")
    technical_factors = _normalize_technical_factors(technical_factors)
    technical_strategy_enabled = bool(technical_strategy_enabled)
    technical_filters_enabled = bool(technical_strategy_enabled and technical_factors)
    technical_lookback_days = max(5, int(technical_lookback_days or 60))
    technical_low_quantile = min(1.0, max(0.0, float(technical_low_quantile or 0.1)))
    apply_moneyflow_filters = bool(apply_moneyflow_filters)
    moneyflow_net_inflow_days_window = _normalize_moneyflow_window_days(moneyflow_net_inflow_days_window)

    entry_dates = _resolve_entry_dates(
        scope=scope,
        start_date=start_date,
        end_date=end_date,
        snapshot_only=True,
        rebalance_step=1,
    )
    entry_dates = [trade_date for trade_date in entry_dates if trade_date is not None]
    if not entry_dates:
        raise ValueError("No entry dates found for the requested range")

    technical_price_only = technical_filters_enabled and technical_factors == ["price"]
    price_history_start_date = start_date - timedelta(days=max(technical_lookback_days * 3, 400)) if technical_price_only else start_date

    price_history = _build_price_history(
        scope=scope,
        start_date=price_history_start_date,
        end_date=end_date,
        freq="D",
    )
    if not price_history:
        raise ValueError("No price history found for the requested range")

    date_price_map = _build_date_price_map(price_history)
    latest_risk_map = {}
    ohlc_map = _build_daily_ohlc_map(price_history.keys(), start_date, end_date)
    risk_map = _build_risk_map(
        entry_dates=entry_dates,
        market=market,
        valuation_variant=valuation_variant if risk_variant_policy == "specific" else None,
    )
    financial_filters_enabled = (
        min_netprofit_yoy is not None
        or min_ebit_yoy is not None
        or bool(require_positive_prev_netprofit)
        or bool(require_positive_prev_ebit)
    )
    financial_panel_map = _load_financial_panel_map(price_history.keys(), end_date) if financial_filters_enabled else {}
    financial_metric_cache = {}
    if technical_filters_enabled and technical_factors == ["price"]:
        technical_history_map = _build_price_technical_history_from_price_history(
            price_history=price_history,
            start_date=start_date,
            end_date=end_date,
            lookback_days=technical_lookback_days,
            technical_low_quantile=technical_low_quantile,
        )
    else:
        technical_history_map = _build_technical_feature_history(
            ts_codes=price_history.keys(),
            start_date=start_date,
            end_date=end_date,
            lookback_days=technical_lookback_days,
            factors=technical_factors,
            technical_low_quantile=technical_low_quantile,
        ) if technical_filters_enabled else {}

    open_positions = {}
    closed_trades = []
    buy_signal_count = 0
    risk_filtered_count = 0
    score_filtered_count = 0
    financial_filtered_count = 0
    financial_missing_count = 0
    technical_filtered_count = 0
    technical_missing_count = 0
    moneyflow_filtered_count = 0
    moneyflow_missing_count = 0

    for idx, trade_date in enumerate(sorted(entry_dates), 1):
        date_prices = date_price_map.get(trade_date, {})
        if not date_prices:
            continue

        ts_codes = sorted(date_prices.keys())
        method_map = _build_snapshot_method_map(ts_codes=ts_codes, trade_date=trade_date, market=market)
        moneyflow_sum_map = (
            _load_moneyflow_feature_map(
                ts_codes=ts_codes,
                trade_date=trade_date,
                window_days=moneyflow_net_inflow_days_window,
            )
            if apply_moneyflow_filters
            else {}
        )

        for ts_code, position in list(open_positions.items()):
            bar = (ohlc_map.get(ts_code) or {}).get(trade_date) or {}
            current_price = _safe_price(bar.get("close"))
            if current_price is None:
                current_price = _safe_price(date_prices.get(ts_code))
            low_price = _safe_price(bar.get("low"))
            if low_price is None:
                low_price = current_price
            if current_price is None:
                continue

            peak_price = max(float(position.get("peak_price") or current_price), float(current_price))
            position["peak_price"] = peak_price
            if stop_loss_mode == "trailing" and trailing_stop_pct > 0:
                position["trailing_stop_price"] = peak_price * (1.0 - trailing_stop_pct)
            if trend_take_profit_enabled:
                ma_value = _calc_sma_up_to_date(price_history.get(ts_code, []), trade_date, trend_ma_period)
                position["trend_ma_value"] = ma_value
                if ma_value is not None and float(current_price) < float(ma_value):
                    position["trend_below_ma_days"] = int(position.get("trend_below_ma_days") or 0) + 1
                else:
                    position["trend_below_ma_days"] = 0
            tp_activation_met = (not trend_take_profit_enabled) or _is_trend_activation_met(
                position,
                trend_activation_profit,
            )

            exit_reason = None
            if low_price is not None and stop_loss_scope == "position" and stop_loss_pct > 0:
                entry_price = float(position["entry_price"])
                stop_price = entry_price * (1.0 - stop_loss_pct)
                if entry_price > 0 and low_price <= stop_price:
                    exit_reason = "stop_loss_pct_hit"
                    current_price = stop_price
            if (
                exit_reason is None
                and stop_loss_mode == "trailing"
                and stop_loss_scope == "position"
                and trailing_stop_pct > 0
            ):
                trailing_stop_price = _safe_price(position.get("trailing_stop_price"))
                if trailing_stop_price is not None and low_price is not None and low_price <= trailing_stop_price:
                    exit_reason = "trailing_stop_hit"
                    current_price = trailing_stop_price
            if (
                exit_reason is None
                and take_profit_mode == "dynamic"
                and take_profit_tiers
                and tp_activation_met
            ):
                entry_price = float(position.get("entry_price") or 0.0)
                if entry_price > 0:
                    ret_ratio = float(current_price) / entry_price - 1.0
                    current_stage = int(position.get("tp_stage_done") or 0)
                    triggered_stage = None
                    while current_stage < len(take_profit_tiers):
                        tier = take_profit_tiers[current_stage] or {}
                        trigger_pct = float(tier.get("trigger_pct") or 0.0)
                        if ret_ratio < trigger_pct:
                            break
                        triggered_stage = current_stage + 1
                        current_stage += 1
                    if triggered_stage is not None:
                        position["tp_stage_done"] = current_stage
                        exit_reason = f"tier_take_profit_stage_{triggered_stage}"
            if (not disable_target_hit) and exit_reason is None and current_price >= float(position["target_price"]):
                exit_reason = "target_hit"
            elif (
                exit_reason is None
                and take_profit_pct > 0
                and (take_profit_mode != "dynamic" or not take_profit_tiers)
            ):
                entry_price = float(position["entry_price"])
                if entry_price > 0 and (float(current_price) / entry_price - 1.0) >= take_profit_pct:
                    exit_reason = "take_profit_pct_hit"

            if exit_reason is not None:
                holding_days = max(
                    1,
                    len(
                        [
                            item
                            for item in price_history.get(ts_code, [])
                            if position["entry_date"] <= item[0] <= trade_date
                        ]
                    )
                    - 1,
                )
                closed_trades.append(
                    {
                        "ts_code": ts_code,
                        "entry_date": position["entry_date"].isoformat(),
                        "exit_date": trade_date.isoformat(),
                        "entry_price": round(float(position["entry_price"]), 4),
                        "exit_price": round(float(current_price), 4),
                        "target_price": round(float(position["target_price"]), 4),
                        "conservative_price": round(float(position["conservative_price"]), 4),
                        "score": position["score"],
                        "risk_level": position["risk_level"],
                        "netprofit_yoy": (position.get("financial_metrics") or {}).get("netprofit_yoy"),
                        "ebit_yoy": (position.get("financial_metrics") or {}).get("ebit_yoy"),
                        "peak_price": round(float(position.get("peak_price") or current_price), 4),
                        "trailing_stop_price": round(float(position.get("trailing_stop_price")), 4) if position.get("trailing_stop_price") is not None else None,
                        "tp_stage_done": int(position.get("tp_stage_done") or 0),
                        "trend_ma_value": round(float(position.get("trend_ma_value")), 4) if position.get("trend_ma_value") is not None else None,
                        "trend_below_ma_days": int(position.get("trend_below_ma_days") or 0),
                        "return_pct": round(
                            (float(current_price) / float(position["entry_price"]) - 1.0) * 100.0,
                            4,
                        ),
                        "holding_days": holding_days,
                        "exit_reason": exit_reason,
                    }
                )
                open_positions.pop(ts_code, None)

        for ts_code in ts_codes:
            if ts_code in open_positions:
                continue

            current_price = date_prices.get(ts_code)
            summary = _summarize_buy_candidate(
                current_price=current_price,
                method_map=method_map.get(ts_code, {}),
                band_pct=band_pct,
            )
            if not summary.get("buy_candidate"):
                continue

            score = summary.get("undervalue_score")
            conservative_price = _safe_price(summary.get("conservative_valuation_price"))
            composite_price = _safe_price(summary.get("composite_valuation_price"))
            if conservative_price is None or composite_price is None:
                continue
            if current_price is None or current_price > conservative_price:
                continue

            buy_signal_count += 1
            if score is None or float(score) < float(min_score):
                score_filtered_count += 1
                continue

            risk_payload = risk_map.get((trade_date, ts_code)) or {}
            fallback_risk_payload = latest_risk_map.get(ts_code) or {}
            risk_alignment = _resolve_risk_alignment_payload(
                risk_payload,
                fallback_risk_payload,
                risk_alignment_mode,
            )
            if risk_variant_policy == "specific":
                passes_risk = risk_alignment["matched_risk_level"] in allowed_risk_levels
            else:
                passes_risk = any(level in risk_alignment["risk_levels"] for level in allowed_risk_levels)
            if not passes_risk:
                risk_filtered_count += 1
                continue

            financial_payload = None
            if financial_filters_enabled:
                financial_payload = _resolve_financial_metrics(
                    financial_panel_map=financial_panel_map,
                    ts_code=ts_code,
                    trade_date=trade_date,
                    cache=financial_metric_cache,
                )
                if financial_payload is None:
                    financial_missing_count += 1
                if not _passes_financial_filters(
                    financial_payload,
                    min_netprofit_yoy=min_netprofit_yoy,
                    min_ebit_yoy=min_ebit_yoy,
                    financial_filter_mode=financial_filter_mode,
                    require_positive_prev_netprofit=require_positive_prev_netprofit,
                    require_positive_prev_ebit=require_positive_prev_ebit,
                ):
                    financial_filtered_count += 1
                    continue

            if technical_filters_enabled:
                passes_technical, technical_reason = _passes_technical_filters(
                    technical_history_map=technical_history_map,
                    ts_code=ts_code,
                    trade_date=trade_date,
                    technical_factors=technical_factors,
                )
                if not passes_technical:
                    if technical_reason == "missing":
                        technical_missing_count += 1
                    technical_filtered_count += 1
                    continue

            moneyflow_payload = None
            if apply_moneyflow_filters:
                moneyflow_payload = moneyflow_sum_map.get(ts_code) or {}
                net_inflow_sum = _safe_float(moneyflow_payload.get("net_inflow_sum"))
                if net_inflow_sum is None:
                    moneyflow_missing_count += 1
                    moneyflow_filtered_count += 1
                    continue
                if float(net_inflow_sum) <= 0:
                    moneyflow_filtered_count += 1
                    continue

            open_positions[ts_code] = {
                "entry_date": trade_date,
                "entry_price": float(current_price),
                "target_price": float(composite_price),
                "conservative_price": float(conservative_price),
                "score": float(score),
                "risk_level": ",".join(allowed_risk_levels),
                "financial_metrics": financial_payload or {},
                "peak_price": float(current_price),
                "trailing_stop_price": (float(current_price) * (1.0 - trailing_stop_pct)) if (stop_loss_mode == "trailing" and trailing_stop_pct > 0) else None,
                "tp_stage_done": 0,
                "trend_ma_value": None,
                "trend_below_ma_days": 0,
                "moneyflow_net_inflow_sum": (
                    _safe_float((moneyflow_payload or {}).get("net_inflow_sum"))
                    if apply_moneyflow_filters
                    else None
                ),
            }

        if stdout is not None and (idx % progress_every == 0 or idx == len(entry_dates)):
            stdout.write(
                "progress {}/{} trade_date={} open_positions={} closed_trades={}".format(
                    idx,
                    len(entry_dates),
                    trade_date,
                    len(open_positions),
                    len(closed_trades),
                )
            )

    for ts_code, position in list(open_positions.items()):
        series = price_history.get(ts_code, [])
        exit_price = None
        exit_date = None
        for series_date, price in reversed(series):
            if series_date <= end_date:
                exit_date = series_date
                exit_price = price
                break
        if exit_price is None or exit_date is None:
            continue

        holding_days = max(1, len([item for item in series if position["entry_date"] <= item[0] <= exit_date]) - 1)
        closed_trades.append(
            {
                "ts_code": ts_code,
                "entry_date": position["entry_date"].isoformat(),
                "exit_date": exit_date.isoformat(),
                "entry_price": round(float(position["entry_price"]), 4),
                "exit_price": round(float(exit_price), 4),
                "target_price": round(float(position["target_price"]), 4),
                "conservative_price": round(float(position["conservative_price"]), 4),
                "score": position["score"],
                "risk_level": position["risk_level"],
                "netprofit_yoy": (position.get("financial_metrics") or {}).get("netprofit_yoy"),
                "ebit_yoy": (position.get("financial_metrics") or {}).get("ebit_yoy"),
                "peak_price": round(float(position.get("peak_price") or exit_price), 4),
                "trailing_stop_price": round(float(position.get("trailing_stop_price")), 4) if position.get("trailing_stop_price") is not None else None,
                "tp_stage_done": int(position.get("tp_stage_done") or 0),
                "trend_ma_value": round(float(position.get("trend_ma_value")), 4) if position.get("trend_ma_value") is not None else None,
                "trend_below_ma_days": int(position.get("trend_below_ma_days") or 0),
                "moneyflow_net_inflow_sum": _safe_float(position.get("moneyflow_net_inflow_sum")),
                "return_pct": round((float(exit_price) / float(position["entry_price"]) - 1.0) * 100.0, 4),
                "holding_days": holding_days,
                "exit_reason": "end_of_period",
            }
        )

    year_buckets = defaultdict(list)
    for trade in closed_trades:
        year_buckets[str(trade["entry_date"])[:4]].append(trade)

    summary = {
        "metadata": {
            "strategy": strategy_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project": "smartinvestor_be",
        },
        "strategy": {
            "scope": scope,
            "market": market,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "band_pct": band_pct,
            "min_score": min_score,
            "risk_level": risk_level,
            "valuation_variant": valuation_variant,
            "risk_variant_policy": risk_variant_policy,
            "risk_alignment_mode": risk_alignment_mode,
            "min_netprofit_yoy": min_netprofit_yoy,
            "min_ebit_yoy": min_ebit_yoy,
            "require_positive_prev_netprofit": bool(require_positive_prev_netprofit),
            "require_positive_prev_ebit": bool(require_positive_prev_ebit),
            "financial_filter_mode": financial_filter_mode,
            "technical_strategy_enabled": bool(technical_filters_enabled),
            "technical_lookback_days": technical_lookback_days,
            "technical_factors": technical_factors,
            "technical_low_quantile": technical_low_quantile,
            "apply_moneyflow_filters": apply_moneyflow_filters,
            "moneyflow_net_inflow_days_window": moneyflow_net_inflow_days_window,
            "take_profit_mode": take_profit_mode,
            "take_profit_tiers": take_profit_tiers,
            "trend_take_profit_enabled": trend_take_profit_enabled,
            "trend_position_pct": trend_position_pct,
            "trend_activation_profit": trend_activation_profit,
            "trend_ma_period": trend_ma_period,
            "trend_confirm_days": trend_confirm_days,
            "take_profit_pct": take_profit_pct,
            "stop_loss_mode": stop_loss_mode,
            "stop_loss_pct": stop_loss_pct,
            "trailing_stop_pct": trailing_stop_pct,
            "stop_loss_scope": stop_loss_scope,
            "buy_rule": "buy when close <= conservative valuation and buy_candidate=true",
            "sell_rule": "sell on valuation target hit (unless disable_target_hit=true), dynamic tier take-profit, trend take-profit, or fixed/trailing stop-loss",
            "stop_loss": None,
        },
        "diagnostics": {
            "entry_dates": len(entry_dates),
            "buy_signal_count_before_score_and_risk": buy_signal_count,
            "score_filtered_count": score_filtered_count,
            "risk_filtered_count": risk_filtered_count,
            "financial_filtered_count": financial_filtered_count,
            "financial_missing_count": financial_missing_count,
            "technical_filtered_count": technical_filtered_count,
            "technical_missing_count": technical_missing_count,
            "moneyflow_filtered_count": moneyflow_filtered_count,
            "moneyflow_missing_count": moneyflow_missing_count,
            "closed_trade_count": len(closed_trades),
            "dynamic_state_enabled": bool(take_profit_mode != "fixed" or stop_loss_mode != "fixed" or trend_take_profit_enabled),
        },
        "combined": _summarize_trade_bucket(closed_trades),
        "by_year": {year: _summarize_trade_bucket(trades) for year, trades in sorted(year_buckets.items())},
        "sample_trades": closed_trades[:100],
    }

    output_path = _resolve_output_path(project_root, strategy_name, start_date, end_date, output_json=output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    run_key = output_path.stem
    try:
        result_file = str(output_path.relative_to(project_root))
    except ValueError:
        result_file = str(output_path)

    _persist_traditional_backtest_run(
        run_key=run_key,
        strategy_name=strategy_name,
        scope=scope,
        market=market,
        start_date=start_date,
        end_date=end_date,
        risk_level=risk_level,
        valuation_variant=valuation_variant,
        risk_variant_policy=risk_variant_policy,
        band_pct=band_pct,
        min_score=min_score,
        min_netprofit_yoy=min_netprofit_yoy,
        min_ebit_yoy=min_ebit_yoy,
        require_positive_prev_netprofit=require_positive_prev_netprofit,
        require_positive_prev_ebit=require_positive_prev_ebit,
        financial_filter_mode=financial_filter_mode,
        technical_strategy_enabled=technical_filters_enabled,
        technical_lookback_days=technical_lookback_days,
        technical_factors=technical_factors,
        technical_low_quantile=technical_low_quantile,
        apply_moneyflow_filters=apply_moneyflow_filters,
        moneyflow_net_inflow_days_window=moneyflow_net_inflow_days_window,
        take_profit_mode=take_profit_mode,
        take_profit_tiers=take_profit_tiers,
        trend_take_profit_enabled=trend_take_profit_enabled,
        trend_position_pct=trend_position_pct,
        trend_activation_profit=trend_activation_profit,
        trend_ma_period=trend_ma_period,
        trend_confirm_days=trend_confirm_days,
        take_profit_pct=take_profit_pct,
        stop_loss_mode=stop_loss_mode,
        stop_loss_pct=stop_loss_pct,
        trailing_stop_pct=trailing_stop_pct,
        stop_loss_scope=stop_loss_scope,
        disable_target_hit=disable_target_hit,
        max_holding_days=0,
        result_file=result_file,
        summary=summary,
    )

    return summary, output_path


def run_traditional_value_exit_account_backtest(
    *,
    scope,
    market,
    start_date,
    end_date,
    band_pct,
    min_score,
    risk_level,
    valuation_variant="",
    risk_variant_policy="any",
    risk_alignment_mode="legacy",
    min_netprofit_yoy=None,
    min_ebit_yoy=None,
    require_positive_prev_netprofit=True,
    require_positive_prev_ebit=True,
    financial_filter_mode="all",
    take_profit_mode="fixed",
    take_profit_tiers=None,
    trend_take_profit_enabled=False,
    trend_position_pct=0.0,
    trend_activation_profit=0.0,
    trend_ma_period=20,
    trend_confirm_days=2,
    take_profit_pct=0.0,
    stop_loss_mode="fixed",
    stop_loss_pct=0.0,
    trailing_stop_pct=0.0,
    stop_loss_scope="position",
    technical_strategy_enabled=False,
    technical_lookback_days=60,
    technical_factors=None,
    technical_low_quantile=0.1,
    apply_moneyflow_filters=False,
    moneyflow_net_inflow_days_window=10,
    output_json=None,
    stdout=None,
    starting_capital=200000.0,
    commission_rate=0.0005,
    valuation_source="history",
    entry_date_source="history",
    entry_end_date=None,
    max_buy_per_day=5,
    max_position_pct=1.0,
    buy_weight_ladder=None,
    first_entry_pct=1.0,
    add_on_drop_pct=0.0,
    add_on_entry_pct=0.0,
    add_on2_drop_pct=0.0,
    max_holding_days=0,
    add_on2_fill_remaining=False,
    disable_eop_exit=False,
    disable_target_hit=False,
    priority_policy="score_desc",
):
    project_root = Path(__file__).resolve().parents[1]
    strategy_name = "traditional_value_exit_account"

    risk_variant_policy = str(risk_variant_policy or "any").strip().lower()
    if risk_variant_policy not in {"any", "specific"}:
        raise ValueError("risk_variant_policy must be 'any' or 'specific'")
    risk_alignment_mode = "legacy"

    financial_filter_mode = str(financial_filter_mode or "all").strip().lower()
    if financial_filter_mode not in {"all", "any"}:
        raise ValueError("financial_filter_mode must be 'all' or 'any'")
    take_profit_mode = str(take_profit_mode or "fixed").strip().lower()
    take_profit_tiers = _normalize_take_profit_tiers(take_profit_tiers)
    trend_take_profit_enabled = bool(trend_take_profit_enabled)
    trend_position_pct = max(0.0, min(1.0, float(trend_position_pct or 0.0)))
    trend_activation_profit = max(0.0, min(1.0, float(trend_activation_profit or 0.0)))
    trend_ma_period = max(2, int(trend_ma_period or 20))
    trend_confirm_days = max(1, int(trend_confirm_days or 2))
    stop_loss_mode = str(stop_loss_mode or "fixed").strip().lower()
    trailing_stop_pct = max(0.0, float(trailing_stop_pct or 0.0))

    valuation_source = str(valuation_source or "history").strip().lower()
    if valuation_source not in {"snapshot", "history"}:
        raise ValueError("valuation_source must be 'snapshot' or 'history'")

    entry_date_source = str(entry_date_source or "history").strip().lower()
    if entry_date_source not in {"snapshot", "history"}:
        raise ValueError("entry_date_source must be 'snapshot' or 'history'")

    priority_policy = str(priority_policy or "score_desc").strip().lower()
    if priority_policy not in {"score_desc", "high_price_first", "low_price_first", "deep_discount_first", "target_discount_first", "low_risk_high_score"}:
        raise ValueError("priority_policy is invalid")

    starting_capital = float(starting_capital)
    commission_rate = float(commission_rate)
    if starting_capital <= 0:
        raise ValueError("starting_capital must be > 0")
    if commission_rate < 0:
        raise ValueError("commission_rate must be >= 0")
    max_buy_per_day = int(max_buy_per_day or 0)
    if max_buy_per_day < 0:
        raise ValueError("max_buy_per_day must be >= 0")
    max_position_pct = float(max_position_pct or 1.0)
    if max_position_pct <= 0 or max_position_pct > 1:
        raise ValueError("max_position_pct must be in (0, 1]")
    max_open_positions = max(1, int(math.floor(1.0 / max_position_pct + 1e-9)))
    first_entry_pct = float(first_entry_pct or 1.0)
    add_on_drop_pct = max(0.0, float(add_on_drop_pct or 0.0))
    add_on_entry_pct = max(0.0, float(add_on_entry_pct or 0.0))
    add_on2_drop_pct = max(0.0, float(add_on2_drop_pct or 0.0))
    max_holding_days = int(max_holding_days or 0)
    if max_holding_days < 0:
        raise ValueError("max_holding_days must be >= 0")
    add_on2_fill_remaining = bool(add_on2_fill_remaining)
    disable_eop_exit = bool(disable_eop_exit)
    disable_target_hit = bool(disable_target_hit)
    if first_entry_pct <= 0 or first_entry_pct > max_position_pct:
        raise ValueError("first_entry_pct must be >0 and <= max_position_pct")
    if add_on_entry_pct > max_position_pct:
        raise ValueError("add_on_entry_pct must be <= max_position_pct")
    if (first_entry_pct + add_on_entry_pct) > max_position_pct + 1e-9:
        raise ValueError("first_entry_pct + add_on_entry_pct must be <= max_position_pct")
    if add_on2_fill_remaining and add_on2_drop_pct <= 0:
        raise ValueError("add_on2_drop_pct must be > 0 when add_on2_fill_remaining is enabled")

    normalized_weight_ladder = []
    if buy_weight_ladder:
        normalized_weight_ladder = [float(x) for x in list(buy_weight_ladder) if float(x) > 0]
        if not normalized_weight_ladder:
            raise ValueError("buy_weight_ladder must contain positive weights")
        if sum(normalized_weight_ladder) > 1.0000001:
            raise ValueError("sum of buy_weight_ladder must be <= 1")

    take_profit_pct = max(0.0, float(take_profit_pct or 0.0))
    stop_loss_pct = max(0.0, float(stop_loss_pct or 0.0))
    stop_loss_scope = _normalize_stop_loss_scope(stop_loss_scope)
    if entry_end_date is not None and entry_end_date < start_date:
        raise ValueError("entry_end_date must be >= start_date")
    if entry_end_date is not None and entry_end_date > end_date:
        raise ValueError("entry_end_date must be <= end_date")

    allowed_risk_levels = _normalize_risk_levels(risk_level)
    if not allowed_risk_levels:
        raise ValueError("risk_level must contain at least one value")
    technical_factors = _normalize_technical_factors(technical_factors)
    technical_strategy_enabled = bool(technical_strategy_enabled)
    technical_filters_enabled = bool(technical_strategy_enabled and technical_factors)
    technical_lookback_days = max(5, int(technical_lookback_days or 60))
    technical_low_quantile = min(1.0, max(0.0, float(technical_low_quantile or 0.1)))
    apply_moneyflow_filters = bool(apply_moneyflow_filters)
    moneyflow_net_inflow_days_window = _normalize_moneyflow_window_days(moneyflow_net_inflow_days_window)

    if entry_date_source == "history":
        entry_dates = _resolve_history_entry_dates(
            scope=scope,
            market=market,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        entry_dates = _resolve_entry_dates(
            scope=scope,
            start_date=start_date,
            end_date=end_date,
            snapshot_only=True,
            rebalance_step=1,
        )
    if entry_end_date is not None:
        entry_dates = [trade_date for trade_date in entry_dates if trade_date is not None and trade_date <= entry_end_date]
    entry_dates = sorted([trade_date for trade_date in entry_dates if trade_date is not None])
    if not entry_dates:
        raise ValueError("No entry dates found for the requested range")

    technical_price_only = technical_filters_enabled and technical_factors == ["price"]
    price_history_start_date = start_date - timedelta(days=max(technical_lookback_days * 3, 400)) if technical_price_only else start_date

    price_history = _build_price_history(
        scope=scope,
        start_date=price_history_start_date,
        end_date=end_date,
        freq="D",
    )
    if not price_history:
        raise ValueError("No price history found for the requested range")

    date_price_map = _build_date_price_map(price_history)
    ohlc_map = _build_daily_ohlc_map(price_history.keys(), start_date, end_date)
    all_trade_dates = sorted([trade_date for trade_date in date_price_map.keys() if start_date <= trade_date <= end_date])
    entry_date_set = set(entry_dates)

    latest_risk_map = {}

    risk_map = _build_risk_map(
        entry_dates=entry_dates,
        market=market,
        valuation_variant=valuation_variant if risk_variant_policy == "specific" else None,
    )

    financial_filters_enabled = (
        min_netprofit_yoy is not None
        or min_ebit_yoy is not None
        or bool(require_positive_prev_netprofit)
        or bool(require_positive_prev_ebit)
    )
    financial_panel_map = _load_financial_panel_map(price_history.keys(), end_date) if financial_filters_enabled else {}
    financial_metric_cache = {}
    if technical_filters_enabled and technical_factors == ["price"]:
        technical_history_map = _build_price_technical_history_from_price_history(
            price_history=price_history,
            start_date=start_date,
            end_date=end_date,
            lookback_days=technical_lookback_days,
            technical_low_quantile=technical_low_quantile,
        )
    else:
        technical_history_map = _build_technical_feature_history(
            ts_codes=price_history.keys(),
            start_date=start_date,
            end_date=end_date,
            lookback_days=technical_lookback_days,
            factors=technical_factors,
            technical_low_quantile=technical_low_quantile,
        ) if technical_filters_enabled else {}
    buy_candidate_agg = {}
    buy_candidate_markers_map = defaultdict(list)

    cash = float(starting_capital)
    open_positions = {}
    closed_trades = []
    daily_equity = []
    last_price_cache = {}

    buy_signal_count = 0
    score_filtered_count = 0
    risk_filtered_count = 0
    financial_filtered_count = 0
    financial_missing_count = 0
    technical_filtered_count = 0
    technical_missing_count = 0
    moneyflow_filtered_count = 0
    moneyflow_missing_count = 0
    buy_executed_count = 0
    take_profit_partial_count = 0
    exposure_days = 0
    account_stop_triggered = False
    account_stop_trigger_date = None

    for idx, trade_date in enumerate(all_trade_dates, 1):
        date_prices = date_price_map.get(trade_date, {})

        for ts_code in list(open_positions.keys()):
            position = open_positions[ts_code]
            bar = (ohlc_map.get(ts_code) or {}).get(trade_date) or {}
            current_price = _safe_price(bar.get("close"))
            if current_price is None:
                current_price = _safe_price(date_prices.get(ts_code))
            low_price = _safe_price(bar.get("low"))
            if low_price is None:
                low_price = current_price
            if current_price is not None:
                last_price_cache[ts_code] = current_price
            if current_price is None:
                continue

            peak_price = max(float(position.get("peak_price") or current_price), float(current_price))
            position["peak_price"] = peak_price
            if stop_loss_mode == "trailing" and trailing_stop_pct > 0:
                position["trailing_stop_price"] = peak_price * (1.0 - trailing_stop_pct)
            if trend_take_profit_enabled:
                ma_value = _calc_sma_up_to_date(price_history.get(ts_code, []), trade_date, trend_ma_period)
                position["trend_ma_value"] = ma_value
                if ma_value is not None and float(current_price) < float(ma_value):
                    position["trend_below_ma_days"] = int(position.get("trend_below_ma_days") or 0) + 1
                else:
                    position["trend_below_ma_days"] = 0
            tp_activation_met = (not trend_take_profit_enabled) or _is_trend_activation_met(
                position,
                trend_activation_profit,
            )

            if take_profit_mode == "dynamic" and take_profit_tiers and tp_activation_met:
                entry_price = float(position.get("entry_price") or 0.0)
                if entry_price > 0:
                    ret_ratio = float(current_price) / entry_price - 1.0
                    current_stage = int(position.get("tp_stage_done") or 0)
                    base_shares = max(
                        int(position.get("tp_base_shares") or 0),
                        int(position.get("shares") or 0),
                    )
                    trend_reserved_total = int(position.get("trend_reserved_shares") or 0)
                    trend_exited_shares = int(position.get("trend_exit_shares") or 0)
                    trend_reserved_remaining = max(0, trend_reserved_total - trend_exited_shares)
                    while current_stage < len(take_profit_tiers):
                        tier = take_profit_tiers[current_stage] or {}
                        trigger_pct = float(tier.get("trigger_pct") or 0.0)
                        sell_ratio = float(tier.get("sell_ratio") or 0.0)
                        if ret_ratio < trigger_pct:
                            break
                        tier_sell_shares = _calc_tier_sell_shares(
                            held_shares=position.get("shares"),
                            tp_base_shares=base_shares,
                            tier_sell_ratio=sell_ratio,
                            ts_code=ts_code,
                        )
                        sell_shares = _calc_limited_sell_shares(
                            held_shares=position.get("shares"),
                            desired_shares=tier_sell_shares,
                            ts_code=ts_code,
                            min_remaining_shares=trend_reserved_remaining,
                        )
                        if sell_shares > 0:
                            gross = float(current_price) * sell_shares
                            exit_fee = gross * commission_rate
                            cash += gross - exit_fee
                            position["shares"] = int(position.get("shares") or 0) - sell_shares
                            position["tp_partial_exit_shares"] = int(position.get("tp_partial_exit_shares") or 0) + sell_shares
                            take_profit_partial_count += 1
                            closed_trades.append(
                                {
                                    "ts_code": ts_code,
                                    "entry_date": position["entry_date"].isoformat(),
                                    "exit_date": trade_date.isoformat(),
                                    "entry_price": round(float(position["entry_price"]), 4),
                                    "exit_price": round(float(current_price), 4),
                                    "target_price": round(float(position["target_price"]), 4),
                                    "conservative_price": round(float(position["conservative_price"]), 4),
                                    "score": position["score"],
                                    "risk_level": position["risk_level"],
                                    "risk_score": position.get("risk_score"),
                                    "netprofit_yoy": (position.get("financial_metrics") or {}).get("netprofit_yoy"),
                                    "ebit_yoy": (position.get("financial_metrics") or {}).get("ebit_yoy"),
                                    "peak_price": round(float(position.get("peak_price") or current_price), 4),
                                    "trailing_stop_price": round(float(position.get("trailing_stop_price")), 4) if position.get("trailing_stop_price") is not None else None,
                                    "tp_stage_done": current_stage + 1,
                                    "trend_ma_value": round(float(position.get("trend_ma_value")), 4) if position.get("trend_ma_value") is not None else None,
                                    "trend_below_ma_days": int(position.get("trend_below_ma_days") or 0),
                                    "shares": int(sell_shares),
                                    "entry_fee": round(0.0, 4),
                                    "exit_fee": round(float(exit_fee), 4),
                                    "add_on_done": bool(position.get("add_on_shares") or 0),
                                    "add_on_shares": int(position.get("add_on_shares") or 0),
                                    "return_pct": round((float(current_price) / float(position["entry_price"]) - 1.0) * 100.0, 4),
                                    "holding_days": max(1, len([item for item in price_history.get(ts_code, []) if position["entry_date"] <= item[0] <= trade_date]) - 1),
                                    "exit_reason": f"tier_take_profit_stage_{current_stage + 1}",
                                }
                            )
                        current_stage += 1
                        position["tp_stage_done"] = current_stage
                        if int(position.get("shares") or 0) <= 0:
                            break
                    if int(position.get("shares") or 0) <= 0:
                        open_positions.pop(ts_code, None)
                        continue

            exit_reason = None
            if low_price is not None and stop_loss_scope == "position" and stop_loss_pct > 0:
                entry_price = float(position["entry_price"])
                stop_price = entry_price * (1.0 - stop_loss_pct)
                if entry_price > 0 and low_price <= stop_price:
                    exit_reason = "stop_loss_pct_hit"
                    current_price = stop_price
            if (
                exit_reason is None
                and stop_loss_mode == "trailing"
                and stop_loss_scope == "position"
                and trailing_stop_pct > 0
            ):
                trailing_stop_price = _safe_price(position.get("trailing_stop_price"))
                if trailing_stop_price is not None and low_price is not None and low_price <= trailing_stop_price:
                    exit_reason = "trailing_stop_hit"
                    current_price = trailing_stop_price
            if exit_reason is None and max_holding_days > 0:
                entry_date = position.get("entry_date")
                if entry_date is not None:
                    holding_days_now = max(
                        1,
                        len([item for item in price_history.get(ts_code, []) if entry_date <= item[0] <= trade_date]) - 1,
                    )
                    if holding_days_now >= max_holding_days:
                        exit_reason = "max_holding_days_hit"
            if (not disable_target_hit) and exit_reason is None and current_price >= float(position["target_price"]):
                exit_reason = "target_hit"
            elif (
                exit_reason is None
                and take_profit_pct > 0
                and (take_profit_mode != "dynamic" or not take_profit_tiers)
            ):
                entry_price = float(position["entry_price"])
                if entry_price > 0 and (float(current_price) / entry_price - 1.0) >= take_profit_pct:
                    exit_reason = "take_profit_pct_hit"

            if exit_reason is None:
                continue

            shares = _calc_sell_shares(position.get("shares"), ts_code)
            if shares <= 0:
                continue
            gross = float(current_price) * shares
            exit_fee = gross * commission_rate
            cash += gross - exit_fee

            series = price_history.get(ts_code, [])
            holding_days = max(1, len([item for item in series if position["entry_date"] <= item[0] <= trade_date]) - 1)
            closed_trades.append(
                {
                    "ts_code": ts_code,
                    "entry_date": position["entry_date"].isoformat(),
                    "exit_date": trade_date.isoformat(),
                    "entry_price": round(float(position["entry_price"]), 4),
                    "exit_price": round(float(current_price), 4),
                    "target_price": round(float(position["target_price"]), 4),
                    "conservative_price": round(float(position["conservative_price"]), 4),
                    "score": position["score"],
                    "risk_level": position["risk_level"],
                    "risk_score": position.get("risk_score"),
                    "netprofit_yoy": (position.get("financial_metrics") or {}).get("netprofit_yoy"),
                    "ebit_yoy": (position.get("financial_metrics") or {}).get("ebit_yoy"),
                    "peak_price": round(float(position.get("peak_price") or current_price), 4),
                    "trailing_stop_price": round(float(position.get("trailing_stop_price")), 4) if position.get("trailing_stop_price") is not None else None,
                    "tp_stage_done": int(position.get("tp_stage_done") or 0),
                    "trend_ma_value": round(float(position.get("trend_ma_value")), 4) if position.get("trend_ma_value") is not None else None,
                    "trend_below_ma_days": int(position.get("trend_below_ma_days") or 0),
                    "shares": shares,
                    "entry_fee": round(float(position.get("entry_fee") or 0.0), 4),
                    "exit_fee": round(float(exit_fee), 4),
                    "add_on_done": bool(position.get("add_on_shares") or 0),
                    "add_on_shares": int(position.get("add_on_shares") or 0),
                    "return_pct": round((float(current_price) / float(position["entry_price"]) - 1.0) * 100.0, 4),
                    "holding_days": holding_days,
                    "exit_reason": exit_reason,
                }
            )
            open_positions.pop(ts_code, None)

        if stop_loss_scope == "account" and stop_loss_pct > 0 and open_positions and (not account_stop_triggered):
            account_mtm = 0.0
            for pos_ts_code, pos in open_positions.items():
                bar = (ohlc_map.get(pos_ts_code) or {}).get(trade_date) or {}
                px = _safe_price(bar.get("low"))
                if px is None:
                    px = _safe_price(date_prices.get(pos_ts_code))
                if px is not None:
                    last_price_cache[pos_ts_code] = px
                ref_px = px if px is not None else _safe_price(last_price_cache.get(pos_ts_code, pos["entry_price"]))
                if ref_px is None:
                    ref_px = float(pos["entry_price"])
                account_mtm += float(ref_px) * int(pos["shares"])
            account_equity = cash + account_mtm
            account_stop_floor = float(starting_capital) * (1.0 - stop_loss_pct)
            if account_equity <= account_stop_floor:
                for ts_code in list(open_positions.keys()):
                    position = open_positions[ts_code]
                    bar = (ohlc_map.get(ts_code) or {}).get(trade_date) or {}
                    current_price = _safe_price(bar.get("low"))
                    if current_price is None:
                        current_price = _safe_price(date_prices.get(ts_code))
                    if current_price is not None:
                        last_price_cache[ts_code] = current_price
                    ref_exit_price = current_price if current_price is not None else _safe_price(last_price_cache.get(ts_code, position["entry_price"]))
                    if ref_exit_price is None:
                        ref_exit_price = float(position["entry_price"])

                    shares = _calc_sell_shares(position.get("shares"), ts_code)
                    if shares <= 0:
                        continue
                    gross = float(ref_exit_price) * shares
                    exit_fee = gross * commission_rate
                    cash += gross - exit_fee

                    series = price_history.get(ts_code, [])
                    holding_days = max(1, len([item for item in series if position["entry_date"] <= item[0] <= trade_date]) - 1)
                    closed_trades.append(
                        {
                            "ts_code": ts_code,
                            "entry_date": position["entry_date"].isoformat(),
                            "exit_date": trade_date.isoformat(),
                            "entry_price": round(float(position["entry_price"]), 4),
                            "exit_price": round(float(ref_exit_price), 4),
                            "target_price": round(float(position["target_price"]), 4),
                            "conservative_price": round(float(position["conservative_price"]), 4),
                            "score": position["score"],
                            "risk_level": position["risk_level"],
                            "risk_score": position.get("risk_score"),
                            "netprofit_yoy": (position.get("financial_metrics") or {}).get("netprofit_yoy"),
                            "ebit_yoy": (position.get("financial_metrics") or {}).get("ebit_yoy"),
                            "peak_price": round(float(position.get("peak_price") or ref_exit_price), 4),
                            "trailing_stop_price": round(float(position.get("trailing_stop_price")), 4) if position.get("trailing_stop_price") is not None else None,
                            "tp_stage_done": int(position.get("tp_stage_done") or 0),
                            "trend_ma_value": round(float(position.get("trend_ma_value")), 4) if position.get("trend_ma_value") is not None else None,
                            "trend_below_ma_days": int(position.get("trend_below_ma_days") or 0),
                            "shares": shares,
                            "entry_fee": round(float(position.get("entry_fee") or 0.0), 4),
                            "exit_fee": round(float(exit_fee), 4),
                            "add_on_done": bool(position.get("add_on_shares") or 0),
                            "add_on_shares": int(position.get("add_on_shares") or 0),
                            "return_pct": round((float(ref_exit_price) / float(position["entry_price"]) - 1.0) * 100.0, 4),
                            "holding_days": holding_days,
                            "exit_reason": "account_stop_loss_pct_hit",
                        }
                    )
                    open_positions.pop(ts_code, None)
                account_stop_triggered = True
                account_stop_trigger_date = trade_date

        if ((add_on_entry_pct > 0 and add_on_drop_pct > 0) or add_on2_fill_remaining or (normalized_weight_ladder and add_on_drop_pct > 0)) and open_positions and cash > 0 and (not account_stop_triggered):
            current_mtm_for_add_on = 0.0
            for pos_ts_code, pos in open_positions.items():
                px = _safe_price(date_prices.get(pos_ts_code))
                if px is not None:
                    last_price_cache[pos_ts_code] = px
                ref_px = px if px is not None else last_price_cache.get(pos_ts_code, pos["entry_price"])
                current_mtm_for_add_on += float(ref_px) * int(pos["shares"])
            current_equity_for_add_on = cash + current_mtm_for_add_on

            for ts_code in list(open_positions.keys()):
                position = open_positions[ts_code]
                current_price = _safe_price(date_prices.get(ts_code))
                if current_price is None:
                    continue

                initial_entry_price = float(position.get("initial_entry_price") or position["entry_price"])
                if initial_entry_price <= 0:
                    continue

                per_position_cap = max(0.0, current_equity_for_add_on * max_position_pct)
                current_position_value = float(current_price) * int(position.get("shares") or 0)
                remaining_cap = max(0.0, per_position_cap - current_position_value)
                planned_position_budget = float(position.get("planned_position_budget") or 0.0)
                if planned_position_budget > 0:
                    remaining_to_plan = max(0.0, planned_position_budget - current_position_value)
                    remaining_cap = min(remaining_cap, remaining_to_plan)
                if remaining_cap <= 0:
                    continue

                if normalized_weight_ladder and add_on_entry_pct <= 0 and add_on_drop_pct > 0 and not bool(position.get("add_on1_done")):
                    trigger_price_fill = initial_entry_price * (1.0 - add_on_drop_pct)
                    if float(current_price) <= trigger_price_fill:
                        unit_cost = float(current_price) * (1.0 + commission_rate)
                        budget = min(cash, remaining_cap)
                        shares = _calc_buy_shares(budget, unit_cost, ts_code)
                        if shares > 0:
                            gross = float(current_price) * shares
                            entry_fee = gross * commission_rate
                            total_cost = gross + entry_fee
                            if total_cost <= cash:
                                prev_shares = int(position.get("shares") or 0)
                                prev_entry_price = float(position.get("entry_price") or 0.0)
                                new_total_shares = prev_shares + shares
                                if new_total_shares > 0:
                                    cash -= total_cost
                                    buy_executed_count += 1
                                    position["shares"] = new_total_shares
                                    position["entry_price"] = ((prev_entry_price * prev_shares) + (float(current_price) * shares)) / new_total_shares
                                    position["entry_fee"] = float(position.get("entry_fee") or 0.0) + float(entry_fee)
                                    position["add_on1_done"] = True
                                    position["add_on1_date"] = trade_date
                                    position["add_on_shares"] = int(position.get("add_on_shares") or 0) + shares
                                    position["add_on1_trigger_price"] = trigger_price_fill
                                    position["tp_base_shares"] = int(position.get("shares") or new_total_shares)
                                    position["trend_reserved_shares"] = _calc_trend_reserved_shares(
                                        position.get("tp_base_shares"),
                                        trend_position_pct if trend_take_profit_enabled else 0.0,
                                    )
                                    position["trend_exit_shares"] = min(
                                        int(position.get("trend_exit_shares") or 0),
                                        int(position.get("trend_reserved_shares") or 0),
                                    )
                                    last_price_cache[ts_code] = float(current_price)
                        continue

                if add_on_entry_pct > 0 and add_on_drop_pct > 0 and not bool(position.get("add_on1_done")):
                    trigger_price_1 = initial_entry_price * (1.0 - add_on_drop_pct)
                    if float(current_price) <= trigger_price_1:
                        unit_cost = float(current_price) * (1.0 + commission_rate)
                        add_on_budget = max(0.0, current_equity_for_add_on * add_on_entry_pct)
                        budget = min(cash, add_on_budget, remaining_cap)
                        shares = _calc_buy_shares(budget, unit_cost, ts_code)
                        if shares > 0:
                            gross = float(current_price) * shares
                            entry_fee = gross * commission_rate
                            total_cost = gross + entry_fee
                            if total_cost <= cash:
                                prev_shares = int(position.get("shares") or 0)
                                prev_entry_price = float(position.get("entry_price") or 0.0)
                                new_total_shares = prev_shares + shares
                                if new_total_shares > 0:
                                    cash -= total_cost
                                    buy_executed_count += 1
                                    position["shares"] = new_total_shares
                                    position["entry_price"] = ((prev_entry_price * prev_shares) + (float(current_price) * shares)) / new_total_shares
                                    position["entry_fee"] = float(position.get("entry_fee") or 0.0) + float(entry_fee)
                                    position["add_on1_done"] = True
                                    position["add_on1_date"] = trade_date
                                    position["add_on_shares"] = int(position.get("add_on_shares") or 0) + shares
                                    position["add_on1_trigger_price"] = trigger_price_1
                                    position["tp_base_shares"] = int(position.get("shares") or new_total_shares)
                                    position["trend_reserved_shares"] = _calc_trend_reserved_shares(
                                        position.get("tp_base_shares"),
                                        trend_position_pct if trend_take_profit_enabled else 0.0,
                                    )
                                    position["trend_exit_shares"] = min(
                                        int(position.get("trend_exit_shares") or 0),
                                        int(position.get("trend_reserved_shares") or 0),
                                    )
                                    last_price_cache[ts_code] = float(current_price)

                                    current_position_value = float(current_price) * int(position.get("shares") or 0)
                                    remaining_cap = max(0.0, per_position_cap - current_position_value)
                                    planned_position_budget = float(position.get("planned_position_budget") or 0.0)
                                    if planned_position_budget > 0:
                                        remaining_to_plan = max(0.0, planned_position_budget - current_position_value)
                                        remaining_cap = min(remaining_cap, remaining_to_plan)

                if add_on2_fill_remaining and add_on2_drop_pct > 0 and not bool(position.get("add_on2_done")) and remaining_cap > 0 and cash > 0:
                    trigger_price_2 = initial_entry_price * (1.0 - add_on2_drop_pct)
                    if float(current_price) <= trigger_price_2:
                        unit_cost = float(current_price) * (1.0 + commission_rate)
                        budget = min(cash, remaining_cap)
                        shares = _calc_buy_shares(budget, unit_cost, ts_code)
                        if shares > 0:
                            gross = float(current_price) * shares
                            entry_fee = gross * commission_rate
                            total_cost = gross + entry_fee
                            if total_cost <= cash:
                                prev_shares = int(position.get("shares") or 0)
                                prev_entry_price = float(position.get("entry_price") or 0.0)
                                new_total_shares = prev_shares + shares
                                if new_total_shares > 0:
                                    cash -= total_cost
                                    buy_executed_count += 1
                                    position["shares"] = new_total_shares
                                    position["entry_price"] = ((prev_entry_price * prev_shares) + (float(current_price) * shares)) / new_total_shares
                                    position["entry_fee"] = float(position.get("entry_fee") or 0.0) + float(entry_fee)
                                    position["add_on2_done"] = True
                                    position["add_on2_date"] = trade_date
                                    position["add_on_shares"] = int(position.get("add_on_shares") or 0) + shares
                                    position["add_on2_trigger_price"] = trigger_price_2
                                    position["tp_base_shares"] = int(position.get("shares") or new_total_shares)
                                    position["trend_reserved_shares"] = _calc_trend_reserved_shares(
                                        position.get("tp_base_shares"),
                                        trend_position_pct if trend_take_profit_enabled else 0.0,
                                    )
                                    position["trend_exit_shares"] = min(
                                        int(position.get("trend_exit_shares") or 0),
                                        int(position.get("trend_reserved_shares") or 0),
                                    )
                                    last_price_cache[ts_code] = float(current_price)

        if trade_date in entry_date_set and (not account_stop_triggered):
            ts_codes = sorted(date_prices.keys())
            if valuation_source == "history":
                method_map = _build_history_method_map(ts_codes=ts_codes, trade_date=trade_date, market=market)
            else:
                method_map = _build_snapshot_method_map(ts_codes=ts_codes, trade_date=trade_date, market=market)
            moneyflow_sum_map = (
                _load_moneyflow_feature_map(
                    ts_codes=ts_codes,
                    trade_date=trade_date,
                    window_days=moneyflow_net_inflow_days_window,
                )
                if apply_moneyflow_filters
                else {}
            )

            candidates = []
            for ts_code in ts_codes:
                if ts_code in open_positions:
                    continue

                current_price = _safe_price(date_prices.get(ts_code))
                if current_price is None:
                    continue

                summary = _summarize_buy_candidate(
                    current_price=current_price,
                    method_map=method_map.get(ts_code, {}),
                    band_pct=band_pct,
                )
                if not summary.get("buy_candidate"):
                    continue

                buy_signal_count += 1
                score = summary.get("undervalue_score")
                conservative_price = _safe_price(summary.get("conservative_valuation_price"))
                composite_price = _safe_price(summary.get("composite_valuation_price"))
                if score is None or float(score) < float(min_score):
                    score_filtered_count += 1
                    continue
                if conservative_price is None or composite_price is None:
                    continue
                if current_price > conservative_price:
                    continue

                risk_payload = risk_map.get((trade_date, ts_code)) or {}
                fallback_risk_payload = latest_risk_map.get(ts_code) or {}
                risk_alignment = _resolve_risk_alignment_payload(
                    risk_payload,
                    fallback_risk_payload,
                    risk_alignment_mode,
                )
                if risk_variant_policy == "specific":
                    passes_risk = risk_alignment["matched_risk_level"] in allowed_risk_levels
                else:
                    passes_risk = any(level in risk_alignment["risk_levels"] for level in allowed_risk_levels)
                if not passes_risk:
                    risk_filtered_count += 1
                    continue

                financial_payload = None
                if financial_filters_enabled:
                    financial_payload = _resolve_financial_metrics(
                        financial_panel_map=financial_panel_map,
                        ts_code=ts_code,
                        trade_date=trade_date,
                        cache=financial_metric_cache,
                    )
                    if financial_payload is None:
                        financial_missing_count += 1
                    if not _passes_financial_filters(
                        financial_payload,
                        min_netprofit_yoy=min_netprofit_yoy,
                        min_ebit_yoy=min_ebit_yoy,
                        financial_filter_mode=financial_filter_mode,
                        require_positive_prev_netprofit=require_positive_prev_netprofit,
                        require_positive_prev_ebit=require_positive_prev_ebit,
                    ):
                        financial_filtered_count += 1
                        continue

                if technical_filters_enabled:
                    passes_technical, technical_reason = _passes_technical_filters(
                        technical_history_map=technical_history_map,
                        ts_code=ts_code,
                        trade_date=trade_date,
                        technical_factors=technical_factors,
                    )
                    if not passes_technical:
                        if technical_reason == "missing":
                            technical_missing_count += 1
                        technical_filtered_count += 1
                        continue

                moneyflow_payload = None
                if apply_moneyflow_filters:
                    moneyflow_payload = moneyflow_sum_map.get(ts_code) or {}
                    net_inflow_sum = _safe_float(moneyflow_payload.get("net_inflow_sum"))
                    if net_inflow_sum is None:
                        moneyflow_missing_count += 1
                        moneyflow_filtered_count += 1
                        continue
                    if float(net_inflow_sum) <= 0:
                        moneyflow_filtered_count += 1
                        continue

                discount_pct = ((float(conservative_price) / float(current_price)) - 1.0) if float(current_price) > 0 else 0.0
                target_discount_pct = ((float(composite_price) / float(current_price)) - 1.0) if float(current_price) > 0 else 0.0
                agg_entry = buy_candidate_agg.setdefault(
                    ts_code,
                    {
                        "ts_code": ts_code,
                        "hit_count": 0,
                        "first_hit_date": trade_date,
                        "last_hit_date": trade_date,
                        "latest_entry_price": float(current_price),
                        "latest_composite_price": float(composite_price),
                        "latest_conservative_price": float(conservative_price),
                        "best_discount_pct": float(discount_pct) * 100.0,
                        "max_score": float(score),
                    },
                )
                agg_entry["hit_count"] += 1
                agg_entry["first_hit_date"] = min(agg_entry["first_hit_date"], trade_date)
                agg_entry["last_hit_date"] = max(agg_entry["last_hit_date"], trade_date)
                agg_entry["latest_entry_price"] = float(current_price)
                agg_entry["latest_composite_price"] = float(composite_price)
                agg_entry["latest_conservative_price"] = float(conservative_price)
                agg_entry["best_discount_pct"] = max(float(agg_entry.get("best_discount_pct") or 0.0), float(discount_pct) * 100.0)
                agg_entry["max_score"] = max(float(agg_entry.get("max_score") or 0.0), float(score))
                buy_candidate_markers_map[ts_code].append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "price": round(float(current_price), 4),
                        "score": round(float(score), 2),
                        "composite_price": round(float(composite_price), 4),
                        "conservative_price": round(float(conservative_price), 4),
                    }
                )
                candidates.append(
                    {
                        "ts_code": ts_code,
                        "entry_price": float(current_price),
                        "target_price": float(composite_price),
                        "conservative_price": float(conservative_price),
                        "score": float(score),
                        "discount_pct": float(discount_pct),
                        "target_discount_pct": float(target_discount_pct),
                        "risk_level": ",".join(allowed_risk_levels),
                        "risk_score": _safe_float((risk_payload or {}).get("min_risk_score")),
                        "financial_metrics": financial_payload or {},
                        "moneyflow_net_inflow_sum": _safe_float((moneyflow_payload or {}).get("net_inflow_sum")),
                    }
                )

            if candidates and cash > 0:
                selected_candidates = sorted(
                    candidates,
                    key=lambda item: _candidate_buy_rank_key(item, priority_policy=priority_policy),
                )
                if normalized_weight_ladder:
                    selected_candidates = selected_candidates[: len(normalized_weight_ladder)]
                elif max_buy_per_day > 0:
                    selected_candidates = selected_candidates[:max_buy_per_day]

                current_mtm = 0.0
                for pos_ts_code, pos in open_positions.items():
                    px = _safe_price(date_prices.get(pos_ts_code))
                    if px is not None:
                        last_price_cache[pos_ts_code] = px
                    ref_px = px if px is not None else last_price_cache.get(pos_ts_code, pos["entry_price"])
                    current_mtm += float(ref_px) * int(pos["shares"])
                current_equity = cash + current_mtm
                per_position_cap = max(0.0, current_equity * max_position_pct)
                first_entry_cap = max(0.0, current_equity * first_entry_pct)

                for candidate_index, candidate in enumerate(selected_candidates):
                    if len(open_positions) >= max_open_positions:
                        break
                    unit_cost = float(candidate["entry_price"]) * (1.0 + commission_rate)
                    planned_position_budget = 0.0
                    if normalized_weight_ladder:
                        ranked_budget = current_equity * float(normalized_weight_ladder[candidate_index])
                        planned_position_budget = min(ranked_budget, per_position_cap)
                        initial_budget = planned_position_budget * first_entry_pct
                        budget = min(cash, initial_budget)
                    else:
                        budget = min(cash, per_position_cap, first_entry_cap)
                    shares = _calc_buy_shares(budget, unit_cost, candidate["ts_code"])
                    if shares <= 0:
                        continue

                    gross = float(candidate["entry_price"]) * shares
                    entry_fee = gross * commission_rate
                    total_cost = gross + entry_fee
                    if total_cost > cash:
                        continue

                    cash -= total_cost
                    buy_executed_count += 1
                    ts_code = candidate["ts_code"]
                    open_positions[ts_code] = {
                        "entry_date": trade_date,
                        "entry_price": float(candidate["entry_price"]),
                        "initial_entry_price": float(candidate["entry_price"]),
                        "target_price": float(candidate["target_price"]),
                        "conservative_price": float(candidate["conservative_price"]),
                        "score": float(candidate["score"]),
                        "risk_level": candidate["risk_level"],
                        "risk_score": candidate.get("risk_score"),
                        "financial_metrics": candidate.get("financial_metrics") or {},
                        "moneyflow_net_inflow_sum": _safe_float(candidate.get("moneyflow_net_inflow_sum")),
                        "shares": int(shares),
                        "entry_fee": float(entry_fee),
                        "add_on1_done": bool(add_on_entry_pct <= 0),
                        "add_on2_done": bool(not add_on2_fill_remaining),
                        "add_on_shares": 0,
                        "planned_position_budget": planned_position_budget,
                        "peak_price": float(candidate["entry_price"]),
                        "trailing_stop_price": (float(candidate["entry_price"]) * (1.0 - trailing_stop_pct)) if (stop_loss_mode == "trailing" and trailing_stop_pct > 0) else None,
                        "tp_base_shares": int(shares),
                        "tp_stage_done": 0,
                        "tp_partial_exit_shares": 0,
                        "trend_reserved_shares": _calc_trend_reserved_shares(
                            int(shares),
                            trend_position_pct if trend_take_profit_enabled else 0.0,
                        ),
                        "trend_exit_shares": 0,
                        "trend_ma_value": None,
                        "trend_below_ma_days": 0,
                    }
                    last_price_cache[ts_code] = float(candidate["entry_price"])

        mtm = 0.0
        for ts_code, position in open_positions.items():
            current_price = _safe_price(date_prices.get(ts_code))
            if current_price is not None:
                last_price_cache[ts_code] = current_price
            ref_price = current_price if current_price is not None else last_price_cache.get(ts_code, position["entry_price"])
            mtm += float(ref_price) * int(position["shares"])
        daily_equity.append((trade_date, cash + mtm))
        if open_positions:
            exposure_days += 1

        if stdout is not None and (idx % 50 == 0 or idx == len(all_trade_dates)):
            stdout.write(
                "progress {}/{} trade_date={} cash={:.2f} open_positions={} closed_trades={}".format(
                    idx,
                    len(all_trade_dates),
                    trade_date,
                    cash,
                    len(open_positions),
                    len(closed_trades),
                )
            )

    if not disable_eop_exit:
        for ts_code, position in list(open_positions.items()):
            series = price_history.get(ts_code, [])
            exit_price = None
            exit_date = None
            for series_date, price in reversed(series):
                if series_date <= end_date:
                    exit_date = series_date
                    exit_price = _safe_price(price)
                    break
            if exit_price is None or exit_date is None:
                continue

            shares = _calc_sell_shares(position.get("shares"), ts_code)
            if shares <= 0:
                continue
            gross = float(exit_price) * shares
            exit_fee = gross * commission_rate
            cash += gross - exit_fee

            holding_days = max(1, len([item for item in series if position["entry_date"] <= item[0] <= exit_date]) - 1)
            closed_trades.append(
                {
                    "ts_code": ts_code,
                    "entry_date": position["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry_price": round(float(position["entry_price"]), 4),
                    "exit_price": round(float(exit_price), 4),
                    "target_price": round(float(position["target_price"]), 4),
                    "conservative_price": round(float(position["conservative_price"]), 4),
                    "score": position["score"],
                    "risk_level": position["risk_level"],
                    "risk_score": position.get("risk_score"),
                    "netprofit_yoy": (position.get("financial_metrics") or {}).get("netprofit_yoy"),
                    "ebit_yoy": (position.get("financial_metrics") or {}).get("ebit_yoy"),
                    "peak_price": round(float(position.get("peak_price") or exit_price), 4),
                    "trailing_stop_price": round(float(position.get("trailing_stop_price")), 4) if position.get("trailing_stop_price") is not None else None,
                    "tp_stage_done": int(position.get("tp_stage_done") or 0),
                    "trend_ma_value": round(float(position.get("trend_ma_value")), 4) if position.get("trend_ma_value") is not None else None,
                    "trend_below_ma_days": int(position.get("trend_below_ma_days") or 0),
                    "shares": shares,
                    "entry_fee": round(float(position.get("entry_fee") or 0.0), 4),
                    "exit_fee": round(float(exit_fee), 4),
                    "add_on_done": bool(position.get("add_on_shares") or 0),
                    "add_on_shares": int(position.get("add_on_shares") or 0),
                    "return_pct": round((float(exit_price) / float(position["entry_price"]) - 1.0) * 100.0, 4),
                    "holding_days": holding_days,
                    "exit_reason": "end_of_period",
                }
            )
            open_positions.pop(ts_code, None)

    year_buckets = defaultdict(list)
    for trade in closed_trades:
        year_buckets[str(trade["entry_date"])[:4]].append(trade)

    final_open_position_mtm = 0.0
    for ts_code, position in open_positions.items():
        ref_price = None
        series = price_history.get(ts_code, [])
        for series_date, price in reversed(series):
            if series_date <= end_date:
                ref_price = _safe_price(price)
                break
        if ref_price is None:
            ref_price = _safe_price(last_price_cache.get(ts_code, position.get("entry_price")))
        if ref_price is None:
            ref_price = float(position.get("entry_price") or 0.0)
        final_open_position_mtm += float(ref_price) * int(position.get("shares") or 0)

    final_asset = float(cash) + float(final_open_position_mtm)
    trade_count = len(closed_trades)
    wins = sum(1 for trade in closed_trades if float(trade.get("return_pct") or 0.0) > 0)
    avg_trade_return_pct = (
        round(sum(float(trade.get("return_pct") or 0.0) for trade in closed_trades) / trade_count, 4)
        if trade_count
        else 0.0
    )
    win_rate_pct = round((wins / trade_count) * 100.0, 2) if trade_count else 0.0
    total_return_pct = round((final_asset / starting_capital - 1.0) * 100.0, 4)
    saved_bt_metrics = _compute_saved_backtesting_like_metrics(
        starting_capital=starting_capital,
        final_asset=final_asset,
        daily_equity=daily_equity,
        closed_trades=closed_trades,
        kline_days=len(all_trade_dates),
        exposure_days=exposure_days,
    )

    buy_candidate_summary_rows = []
    if buy_candidate_agg:
        code_list = list(buy_candidate_agg.keys())
        name_map = {
            str(row.get("ts_code") or "").strip().upper(): str(row.get("name") or "").strip()
            for row in Corporation.objects.filter(ts_code__in=code_list).values("ts_code", "name")
        }
        for ts_code, item in buy_candidate_agg.items():
            buy_candidate_summary_rows.append(
                {
                    "ts_code": ts_code,
                    "stock_name": name_map.get(ts_code, ""),
                    "hit_count": int(item.get("hit_count") or 0),
                    "first_hit_date": item.get("first_hit_date").isoformat() if item.get("first_hit_date") else None,
                    "last_hit_date": item.get("last_hit_date").isoformat() if item.get("last_hit_date") else None,
                    "latest_entry_price": round(float(item.get("latest_entry_price") or 0.0), 4),
                    "latest_composite_price": round(float(item.get("latest_composite_price") or 0.0), 4),
                    "latest_conservative_price": round(float(item.get("latest_conservative_price") or 0.0), 4),
                    "best_discount_pct": round(float(item.get("best_discount_pct") or 0.0), 4),
                    "max_score": round(float(item.get("max_score") or 0.0), 2),
                }
            )
        buy_candidate_summary_rows.sort(
            key=lambda row: (
                -int(row.get("hit_count") or 0),
                -float(row.get("max_score") or 0.0),
                -float(row.get("best_discount_pct") or 0.0),
                str(row.get("ts_code") or ""),
            )
        )

    summary = {
        "metadata": {
            "strategy": strategy_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project": "smartinvestor_be",
        },
        "strategy": {
            "scope": scope,
            "market": market,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "band_pct": band_pct,
            "min_score": min_score,
            "risk_level": risk_level,
            "valuation_variant": valuation_variant,
            "risk_variant_policy": risk_variant_policy,
            "risk_alignment_mode": risk_alignment_mode,
            "min_netprofit_yoy": min_netprofit_yoy,
            "min_ebit_yoy": min_ebit_yoy,
            "require_positive_prev_netprofit": bool(require_positive_prev_netprofit),
            "require_positive_prev_ebit": bool(require_positive_prev_ebit),
            "financial_filter_mode": financial_filter_mode,
            "technical_strategy_enabled": bool(technical_filters_enabled),
            "technical_lookback_days": technical_lookback_days,
            "technical_factors": technical_factors,
            "technical_low_quantile": technical_low_quantile,
            "apply_moneyflow_filters": apply_moneyflow_filters,
            "moneyflow_net_inflow_days_window": moneyflow_net_inflow_days_window,
            "take_profit_mode": take_profit_mode,
            "take_profit_tiers": take_profit_tiers,
            "trend_take_profit_enabled": trend_take_profit_enabled,
            "trend_position_pct": trend_position_pct,
            "trend_activation_profit": trend_activation_profit,
            "trend_ma_period": trend_ma_period,
            "trend_confirm_days": trend_confirm_days,
            "take_profit_pct": take_profit_pct,
            "stop_loss_mode": stop_loss_mode,
            "stop_loss_pct": stop_loss_pct,
            "trailing_stop_pct": trailing_stop_pct,
            "stop_loss_scope": stop_loss_scope,
            "starting_capital": starting_capital,
            "commission_rate": commission_rate,
            "valuation_source": valuation_source,
            "entry_date_source": entry_date_source,
            "entry_end_date": entry_end_date.isoformat() if entry_end_date is not None else None,
            "max_buy_per_day": max_buy_per_day,
            "max_position_pct": max_position_pct,
            "max_open_positions": max_open_positions,
            "buy_weight_ladder": normalized_weight_ladder,
            "first_entry_pct": first_entry_pct,
            "add_on_drop_pct": add_on_drop_pct,
            "add_on_entry_pct": add_on_entry_pct,
            "add_on2_drop_pct": add_on2_drop_pct,
            "add_on2_fill_remaining": add_on2_fill_remaining,
            "disable_eop_exit": disable_eop_exit,
            "disable_target_hit": disable_target_hit,
            "priority_policy": priority_policy,
            "buy_rule": "buy when close <= conservative valuation and buy_candidate=true; rank by configured priority policy",
            "sell_rule": "sell on valuation target hit (unless disable_target_hit=true), dynamic tier take-profit, trend take-profit, or fixed/trailing stop-loss",
            "stop_loss": None,
        },
        "diagnostics": {
            "entry_dates": len(entry_dates),
            "buy_signal_count_before_score_and_risk": buy_signal_count,
            "score_filtered_count": score_filtered_count,
            "risk_filtered_count": risk_filtered_count,
            "financial_filtered_count": financial_filtered_count,
            "financial_missing_count": financial_missing_count,
            "technical_filtered_count": technical_filtered_count,
            "technical_missing_count": technical_missing_count,
            "moneyflow_filtered_count": moneyflow_filtered_count,
            "moneyflow_missing_count": moneyflow_missing_count,
            "buy_executed_count": buy_executed_count,
            "take_profit_partial_count": take_profit_partial_count,
            "closed_trade_count": trade_count,
            "buy_candidate_unique_stocks": len(buy_candidate_summary_rows),
            "dynamic_state_enabled": bool(take_profit_mode != "fixed" or stop_loss_mode != "fixed" or trend_take_profit_enabled),
        },
        "account": {
            "initial_cash": round(float(starting_capital), 2),
            "initial_capital": round(float(starting_capital), 2),
            "final_asset": round(final_asset, 2),
            "ending_capital": round(final_asset, 2),
            "net_profit": round(final_asset - float(starting_capital), 2),
            "total_return_pct": total_return_pct,
            "trade_count": trade_count,
            "win_rate_pct": win_rate_pct,
            "avg_trade_return_pct": avg_trade_return_pct,
            "closed_target_hit": sum(1 for trade in closed_trades if trade.get("exit_reason") == "target_hit"),
            "closed_take_profit": sum(1 for trade in closed_trades if trade.get("exit_reason") == "take_profit_pct_hit"),
            "closed_stop_loss": sum(
                1
                for trade in closed_trades
                if trade.get("exit_reason") in {"stop_loss_pct_hit", "account_stop_loss_pct_hit"}
            ),
            "closed_account_stop_loss": sum(1 for trade in closed_trades if trade.get("exit_reason") == "account_stop_loss_pct_hit"),
            "closed_eop": sum(1 for trade in closed_trades if trade.get("exit_reason") == "end_of_period"),
            "account_stop_triggered": account_stop_triggered,
            "account_stop_trigger_date": account_stop_trigger_date.isoformat() if account_stop_trigger_date is not None else None,
            **saved_bt_metrics,
        },
        "combined": _summarize_trade_bucket(closed_trades),
        "by_year": {year: _summarize_trade_bucket(trades) for year, trades in sorted(year_buckets.items())},
        "sample_trades": closed_trades[:100],
        "buy_candidates_summary": buy_candidate_summary_rows,
        "buy_candidate_markers": dict(buy_candidate_markers_map),
    }

    output_path = _resolve_output_path(project_root, strategy_name, start_date, end_date, output_json=output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    run_key = output_path.stem
    try:
        result_file = str(output_path.relative_to(project_root))
    except ValueError:
        result_file = str(output_path)

    _persist_traditional_backtest_run(
        run_key=run_key,
        strategy_name=strategy_name,
        scope=scope,
        market=market,
        start_date=start_date,
        end_date=end_date,
        risk_level=risk_level,
        valuation_variant=valuation_variant,
        risk_variant_policy=risk_variant_policy,
        band_pct=band_pct,
        min_score=min_score,
        min_netprofit_yoy=min_netprofit_yoy,
        min_ebit_yoy=min_ebit_yoy,
        require_positive_prev_netprofit=require_positive_prev_netprofit,
        require_positive_prev_ebit=require_positive_prev_ebit,
        financial_filter_mode=financial_filter_mode,
        technical_strategy_enabled=technical_filters_enabled,
        technical_lookback_days=technical_lookback_days,
        technical_factors=technical_factors,
        technical_low_quantile=technical_low_quantile,
        apply_moneyflow_filters=apply_moneyflow_filters,
        moneyflow_net_inflow_days_window=moneyflow_net_inflow_days_window,
        take_profit_mode=take_profit_mode,
        take_profit_tiers=take_profit_tiers,
        trend_take_profit_enabled=trend_take_profit_enabled,
        trend_position_pct=trend_position_pct,
        trend_activation_profit=trend_activation_profit,
        trend_ma_period=trend_ma_period,
        trend_confirm_days=trend_confirm_days,
        max_holding_days=max_holding_days,
        take_profit_pct=take_profit_pct,
        stop_loss_mode=stop_loss_mode,
        stop_loss_pct=stop_loss_pct,
        trailing_stop_pct=trailing_stop_pct,
        stop_loss_scope=stop_loss_scope,
        disable_target_hit=disable_target_hit,
        starting_capital=starting_capital,
        max_position_pct=max_position_pct,
        first_entry_pct=first_entry_pct,
        add_on_entry_pct=add_on_entry_pct,
        add_on_drop_pct=add_on_drop_pct,
        add_on2_drop_pct=add_on2_drop_pct,
        add_on2_fill_remaining=add_on2_fill_remaining,
        max_buy_per_day=max_buy_per_day,
        priority_policy=priority_policy,
        buy_weight_ladder=buy_weight_ladder,
        result_file=result_file,
        summary=summary,
    )

    return summary, output_path
