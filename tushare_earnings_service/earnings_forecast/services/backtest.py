from __future__ import annotations

from datetime import date, datetime
from typing import Any

from earnings_forecast.models import EarningsSignalSnapshotHistory, LocalTradingHistory

RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
REPORT_RANK = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4, "FUSION": 5}


def _normalize_batch_key_map(batch_key_map: dict[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(batch_key_map, dict):
        return normalized

    for raw_key, raw_value in batch_key_map.items():
        report_type = str(raw_key or "").strip().upper()
        batch_key = str(raw_value or "").strip()
        if not report_type or not batch_key:
            continue
        if report_type not in {"Q1", "H1", "Q3", "FY", "FUSION"}:
            continue
        normalized[report_type] = batch_key
    return normalized


def _resolve_batch_key_for_report_type(
    report_type: str,
    *,
    default_batch_key: str,
    batch_key_map: dict[str, str],
) -> str | None:
    rt = str(report_type or "").strip().upper()
    if batch_key_map:
        # Per requirement: if a report_type is missing in batch_key_map, skip it directly.
        mapped = batch_key_map.get(rt)
        return mapped if mapped else None
    return default_batch_key or None


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            if fmt == "%Y-%m-%d":
                return datetime.strptime(text[:10], fmt).date()
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _risk_ok(risk_level: str, max_risk: str) -> bool:
    a = RISK_ORDER.get(str(risk_level or "").upper(), 99)
    b = RISK_ORDER.get(str(max_risk or "").upper(), 99)
    return a <= b


def _pick_latest_report_row(rows: list[EarningsSignalSnapshotHistory]) -> EarningsSignalSnapshotHistory | None:
    best_row = None
    best_key = None
    for row in rows:
        raw = row.raw_result if isinstance(row.raw_result, dict) else {}
        ann_date = _to_date(raw.get("financial_ann_date") or raw.get("ann_date") or row.asof_date)
        score = float(row.signal_score) if row.signal_score is not None else -1.0
        report_type = str(row.report_type or "").upper()
        key = (ann_date or date.min, REPORT_RANK.get(report_type, 0), score)
        if best_key is None or key > best_key:
            best_key = key
            best_row = row
    return best_row


def _build_price_map(ts_codes: list[str], start_year: int, end_year: int) -> tuple[dict[str, dict[date, float]], list[date]]:
    qs = (
        LocalTradingHistory.objects.filter(
            ts_code__in=ts_codes,
            freq="D",
            trade_date__gte=date(start_year, 1, 1),
            trade_date__lte=date(end_year, 12, 31),
        )
        .values("ts_code", "trade_date", "close")
        .order_by("trade_date")
    )
    price_map: dict[str, dict[date, float]] = {}
    date_set: set[date] = set()
    for row in qs:
        code = str(row["ts_code"])
        trade_date = row["trade_date"]
        close = row.get("close")
        if close is None:
            continue
        try:
            price = float(close)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        price_map.setdefault(code, {})[trade_date] = price
        date_set.add(trade_date)
    return price_map, sorted(date_set)


def _compute_year_metrics(year: int, daily_returns: list[float], active_days: int) -> dict[str, Any]:
    n = len(daily_returns)
    cumulative = 1.0
    for value in daily_returns:
        cumulative *= 1.0 + float(value)
    cumulative -= 1.0

    annualized = 0.0
    if n > 0 and cumulative > -1.0:
        annualized = (1.0 + cumulative) ** (252.0 / n) - 1.0

    return {
        "year": year,
        "days": n,
        "active_days": active_days,
        "active_ratio": (active_days / n) if n else 0.0,
        "avg_daily_return": (sum(daily_returns) / n) if n else 0.0,
        "cumulative_return": cumulative,
        "annualized_return": annualized,
    }


def _build_trade_row(
    *,
    chosen: EarningsSignalSnapshotHistory,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    exit_price: float,
    ret: float,
    max_drawdown: float,
    holding_days: int,
    exit_reason: str,
) -> dict[str, Any]:
    raw = chosen.raw_result if isinstance(chosen.raw_result, dict) else {}
    quant = raw.get("quantitative_target") if isinstance(raw.get("quantitative_target"), dict) else {}
    return {
        "ts_code": str(chosen.ts_code or "").upper(),
        "stock_name": "",
        "entry_date": entry_date.isoformat(),
        "exit_date": exit_date.isoformat(),
        "entry_price": round(float(entry_price), 4),
        "exit_price": round(float(exit_price), 4),
        "return_pct": round(float(ret) * 100.0, 4),
        "max_drawdown_pct": round(float(max_drawdown) * 100.0, 4),
        "holding_days": int(holding_days),
        "exit_reason": exit_reason,
        "signal_score": round(float(chosen.signal_score), 4) if chosen.signal_score is not None else None,
        "risk_level": str(chosen.risk_level or "").upper() or None,
        "report_type": str(chosen.report_type or "").upper() or None,
        "model_version": chosen.model_version or None,
        "target_return_pct": round(float(chosen.target_return_pct), 4) if chosen.target_return_pct is not None else None,
        "target_price": round(float(chosen.target_price), 4) if chosen.target_price is not None else None,
        "conservative_price": round(float(quant.get("target_price_low")), 4)
        if quant.get("target_price_low") is not None else None,
        "optimistic_price": round(float(quant.get("target_price_high")), 4)
        if quant.get("target_price_high") is not None else None,
        "target_market_cap": round(float(chosen.target_market_cap), 4) if chosen.target_market_cap is not None else None,
        "financial_end_date": raw.get("financial_end_date") or chosen.financial_end_date or None,
        "financial_ann_date": raw.get("financial_ann_date") or chosen.financial_ann_date or None,
        "pred_earnings_growth": round(float(raw.get("pred_earnings_growth")), 4)
        if raw.get("pred_earnings_growth") is not None else None,
    }


def _resolve_conservative_price(chosen: EarningsSignalSnapshotHistory) -> float | None:
    raw = chosen.raw_result if isinstance(chosen.raw_result, dict) else {}
    quant = raw.get("quantitative_target") if isinstance(raw.get("quantitative_target"), dict) else {}
    target_price_low = quant.get("target_price_low")
    if target_price_low is not None:
        try:
            value = float(target_price_low)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    target_price = chosen.target_price
    if target_price is not None:
        try:
            value = float(target_price)
            if value > 0:
                return value * 0.9
        except (TypeError, ValueError):
            pass
    return None


def _resolve_optimistic_price(chosen: EarningsSignalSnapshotHistory) -> float | None:
    raw = chosen.raw_result if isinstance(chosen.raw_result, dict) else {}
    quant = raw.get("quantitative_target") if isinstance(raw.get("quantitative_target"), dict) else {}
    target_price_high = quant.get("target_price_high")
    if target_price_high is not None:
        try:
            value = float(target_price_high)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    target_price = chosen.target_price
    if target_price is not None:
        try:
            value = float(target_price)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return None


def _summarize_trade_bucket(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trade_count": 0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "win_rate_pct": 0.0,
            "avg_holding_days": 0.0,
            "target_exit_count": 0,
            "eop_exit_count": 0,
        }

    returns = sorted(float(item.get("return_pct") or 0.0) for item in trades)
    mid = len(returns) // 2
    median = returns[mid] if len(returns) % 2 == 1 else (returns[mid - 1] + returns[mid]) / 2.0
    wins = sum(1 for item in trades if float(item.get("return_pct") or 0.0) > 0)
    avg_holding_days = sum(float(item.get("holding_days") or 0.0) for item in trades) / len(trades)
    target_exit_count = sum(
        1 for item in trades
        if str(item.get("exit_reason") or "") in {"optimistic_price_hit", "take_profit_pct_hit"}
    )
    eop_exit_count = sum(1 for item in trades if str(item.get("exit_reason") or "") == "year_end_close")
    return {
        "trade_count": len(trades),
        "avg_return_pct": round(sum(returns) / len(returns), 4),
        "median_return_pct": round(median, 4),
        "win_rate_pct": round((wins / len(trades)) * 100.0, 2),
        "avg_holding_days": round(avg_holding_days, 2),
        "target_exit_count": target_exit_count,
        "eop_exit_count": eop_exit_count,
    }


def _apply_global_stop(daily_returns: list[float], stop_dd: float) -> tuple[list[float], int | None]:
    threshold = float(stop_dd or 0.0)
    if threshold <= 0:
        return list(daily_returns), None

    output: list[float] = []
    nav = 1.0
    peak = 1.0
    triggered_index = None

    for idx, value in enumerate(daily_returns):
        if triggered_index is not None:
            output.append(0.0)
            continue

        output.append(value)
        nav *= 1.0 + value
        if nav > peak:
            peak = nav

        drawdown = (nav / peak) - 1.0 if peak > 0 else 0.0
        if drawdown <= -threshold:
            triggered_index = idx

    return output, triggered_index


def _simulate_year(
    *,
    year: int,
    market_dates: list[date],
    ts_codes: list[str],
    by_date_code: dict[tuple[date, str], list[EarningsSignalSnapshotHistory]],
    price_map: dict[str, dict[date, float]],
    min_score: float,
    max_risk: str,
    mode: str,
    starting_capital: float,
    max_position_pct: float,
    first_entry_pct: float,
    max_buy_per_day: int,
    stop_mode: str,
    single_stop_dd: float,
    sell_strategy: str,
    take_profit_pct: float,
    stop_loss_pct: float,
    max_holding_days: int,
) -> tuple[list[float], int, list[str], list[dict[str, Any]]]:
    year_dates = [item for item in market_dates if item.year == year]
    daily_returns: list[float] = []
    active_days = 0
    sample_trades: list[dict[str, Any]] = []

    stopped_codes: set[str] = set()
    stock_nav: dict[str, float] = {}
    stock_peak: dict[str, float] = {}
    open_positions: dict[str, dict[str, Any]] = {}
    mode_normalized = str(mode or "signal").strip().lower()
    if mode_normalized not in {"signal", "account"}:
        mode_normalized = "signal"
    account_cash = float(starting_capital or 0.0) if mode_normalized == "account" else 0.0
    account_prev_nav = max(1.0, float(starting_capital or 0.0)) if mode_normalized == "account" else 1.0

    for idx, asof_date in enumerate(year_dates):
        is_last_day = idx == len(year_dates) - 1
        current_returns: list[float] = []
        to_close: list[tuple[str, float, str]] = []
        buys_today = 0

        for code, position in list(open_positions.items()):
            current_price = price_map.get(code, {}).get(asof_date)
            if current_price is None or current_price <= 0:
                continue

            trade_min_price = float(position.get("trade_min_price") or 0.0)
            if trade_min_price <= 0:
                trade_min_price = float(current_price)
            position["trade_min_price"] = min(trade_min_price, float(current_price))

            prev_price = float(position.get("last_mark_price") or 0.0)
            if prev_price > 0:
                pos_ret = (current_price / prev_price) - 1.0
                current_returns.append(pos_ret)
                nav = stock_nav.get(code, 1.0) * (1.0 + pos_ret)
            else:
                pos_ret = 0.0
                nav = stock_nav.get(code, 1.0)

            peak = max(stock_peak.get(code, 1.0), nav)
            stock_nav[code] = nav
            stock_peak[code] = peak
            position["last_mark_price"] = current_price
            position["holding_days"] = int(position.get("holding_days") or 0) + 1

            exit_reason = None
            optimistic_price = position.get("optimistic_price")
            if optimistic_price is not None and current_price >= float(optimistic_price):
                exit_reason = "optimistic_price_hit"

            take_profit_threshold = float(take_profit_pct or 0.0)
            if exit_reason is None and take_profit_threshold > 0:
                entry_price = float(position.get("entry_price") or 0.0)
                if entry_price > 0 and ((current_price / entry_price) - 1.0) >= take_profit_threshold:
                    exit_reason = "take_profit_pct_hit"

            stop_loss_threshold = float(stop_loss_pct or 0.0)
            if exit_reason is None and stop_loss_threshold > 0:
                entry_price = float(position.get("entry_price") or 0.0)
                if entry_price > 0 and ((current_price / entry_price) - 1.0) <= -stop_loss_threshold:
                    exit_reason = "stop_loss_pct_hit"

            if stop_mode == "single" and float(single_stop_dd or 0.0) > 0:
                drawdown = (nav / peak) - 1.0 if peak > 0 else 0.0
                if drawdown <= -float(single_stop_dd):
                    exit_reason = exit_reason or "single_stop_dd"
                    stopped_codes.add(code)

            if exit_reason is None and int(max_holding_days or 0) > 0 and int(position.get("holding_days") or 0) >= int(max_holding_days):
                exit_reason = "max_holding_days"

            if exit_reason is None and sell_strategy == "next_day" and int(position.get("holding_days") or 0) >= 1:
                exit_reason = "next_day_rebalance"

            if exit_reason is None and is_last_day:
                exit_reason = "year_end_close"

            if exit_reason is not None:
                to_close.append((code, current_price, exit_reason))

        if current_returns:
            daily_ret = sum(current_returns) / len(current_returns)
        else:
            daily_ret = 0.0
        if mode_normalized == "signal":
            daily_returns.append(daily_ret)
            if current_returns:
                active_days += 1

        for code, exit_price, exit_reason in to_close:
            position = open_positions.pop(code, None)
            if position is None:
                continue
            entry_price = float(position.get("entry_price") or 0.0)
            if entry_price <= 0:
                continue
            total_ret = (float(exit_price) / entry_price) - 1.0
            min_price = float(position.get("trade_min_price") or entry_price)
            if min_price <= 0:
                min_price = entry_price
            max_drawdown = min(0.0, (min_price / entry_price) - 1.0)
            if mode_normalized == "account":
                shares = float(position.get("shares") or 0.0)
                if shares > 0:
                    account_cash += shares * float(exit_price)
            sample_trades.append(
                _build_trade_row(
                    chosen=position["chosen"],
                    entry_date=position["entry_date"],
                    exit_date=asof_date,
                    entry_price=entry_price,
                    exit_price=float(exit_price),
                    ret=total_ret,
                    max_drawdown=max_drawdown,
                    holding_days=int(position.get("holding_days") or 0),
                    exit_reason=exit_reason,
                )
            )

        for code in ts_codes:
            if code in open_positions:
                continue
            if stop_mode == "single" and code in stopped_codes:
                continue
            if mode_normalized == "account" and int(max_buy_per_day or 0) > 0 and buys_today >= int(max_buy_per_day or 0):
                break

            rows = by_date_code.get((asof_date, code), [])
            if not rows:
                continue
            chosen = _pick_latest_report_row(rows)
            if chosen is None:
                continue

            action = str(chosen.action or "").upper()
            risk = str(chosen.risk_level or "").upper()
            score = float(chosen.signal_score) if chosen.signal_score is not None else None
            if action != "BUY":
                continue
            if score is None or score < float(min_score):
                continue
            if not _risk_ok(risk, max_risk):
                continue

            entry_price = price_map.get(code, {}).get(asof_date)
            if entry_price is None or entry_price <= 0:
                continue

            conservative_price = _resolve_conservative_price(chosen)
            if conservative_price is None or entry_price > conservative_price:
                continue

            optimistic_price = _resolve_optimistic_price(chosen)
            shares = 0.0
            if mode_normalized == "account":
                nav_reference = account_cash
                for hold_code, hold_position in open_positions.items():
                    hold_price = price_map.get(hold_code, {}).get(asof_date)
                    if hold_price is None or hold_price <= 0:
                        hold_price = float(hold_position.get("last_mark_price") or 0.0)
                    if hold_price is None or hold_price <= 0:
                        continue
                    nav_reference += float(hold_position.get("shares") or 0.0) * float(hold_price)

                per_position_capital = nav_reference * float(max_position_pct or 0.0)
                first_entry_capital = nav_reference * float(first_entry_pct or 0.0)
                buy_budget = min(account_cash, per_position_capital, first_entry_capital)
                if buy_budget <= 0:
                    continue
                shares = buy_budget / float(entry_price)
                if shares <= 0:
                    continue
                account_cash -= shares * float(entry_price)
                buys_today += 1

            open_positions[code] = {
                "chosen": chosen,
                "entry_date": asof_date,
                "entry_price": float(entry_price),
                "last_mark_price": float(entry_price),
                "trade_min_price": float(entry_price),
                "holding_days": 0,
                "optimistic_price": optimistic_price,
                "shares": float(shares) if mode_normalized == "account" else 0.0,
            }

        if mode_normalized == "account":
            account_nav = account_cash
            for hold_code, hold_position in open_positions.items():
                hold_price = price_map.get(hold_code, {}).get(asof_date)
                if hold_price is None or hold_price <= 0:
                    hold_price = float(hold_position.get("last_mark_price") or 0.0)
                if hold_price is None or hold_price <= 0:
                    continue
                account_nav += float(hold_position.get("shares") or 0.0) * float(hold_price)

            account_daily_ret = (account_nav / account_prev_nav) - 1.0 if account_prev_nav > 0 else 0.0
            daily_returns.append(account_daily_ret)
            if open_positions:
                active_days += 1
            account_prev_nav = account_nav if account_nav > 0 else account_prev_nav

    return daily_returns, active_days, sorted(stopped_codes), sample_trades


def run_predictive_valuation_backtest(
    *,
    batch_key: str,
    batch_key_map: dict[str, Any] | None = None,
    ts_codes: list[str],
    mode: str = "signal",
    starting_capital: float = 200000.0,
    max_position_pct: float = 0.2,
    first_entry_pct: float = 0.1,
    max_buy_per_day: int = 3,
    start_year: int = 2024,
    end_year: int = 2025,
    min_score: float = 90.0,
    max_risk: str = "MEDIUM",
    stop_mode: str = "none",
    global_stop_dd: float = 0.0,
    single_stop_dd: float = 0.1,
    report_type: str = "ALL",
    sell_strategy: str = "optimistic_price",
    take_profit_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
    max_holding_days: int = 0,
) -> dict[str, Any]:
    normalized_codes = []
    seen = set()
    for raw in ts_codes or []:
        code = str(raw or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        normalized_codes.append(code)
    if not normalized_codes:
        raise ValueError("ts_codes is required")

    report_filter = str(report_type or "ALL").strip().upper()
    if report_filter in {"", "*"}:
        report_filter = "ALL"

    stop_mode_normalized = str(stop_mode or "none").strip().lower()
    if stop_mode_normalized not in {"none", "global", "single"}:
        stop_mode_normalized = "none"

    risk_level = str(max_risk or "MEDIUM").strip().upper()
    if risk_level not in {"LOW", "MEDIUM", "HIGH"}:
        risk_level = "MEDIUM"

    mode_normalized = str(mode or "signal").strip().lower()
    if mode_normalized not in {"signal", "account"}:
        mode_normalized = "signal"

    starting_capital_value = float(starting_capital or 200000.0)
    if starting_capital_value <= 0:
        starting_capital_value = 200000.0
    max_position_pct_value = min(1.0, max(0.0, float(max_position_pct or 0.2)))
    first_entry_pct_value = min(1.0, max(0.0, float(first_entry_pct or 0.1)))
    max_buy_per_day_value = max(1, int(max_buy_per_day or 3))

    sell_strategy_normalized = str(sell_strategy or "optimistic_price").strip().lower()
    if sell_strategy_normalized not in {"next_day", "optimistic_price", "take_profit_pct", "optimistic_or_take_profit"}:
        sell_strategy_normalized = "optimistic_price"

    take_profit_pct_value = max(0.0, float(take_profit_pct or 0.0))
    stop_loss_pct_value = max(0.0, float(stop_loss_pct or 0.0))
    max_holding_days_value = max(0, int(max_holding_days or 0))

    default_batch_key = str(batch_key or "").strip()
    normalized_batch_key_map = _normalize_batch_key_map(batch_key_map)
    candidate_batch_keys = set(normalized_batch_key_map.values()) if normalized_batch_key_map else {default_batch_key}
    candidate_batch_keys = {item for item in candidate_batch_keys if item}
    if not candidate_batch_keys:
        raise ValueError("batch_key or batch_key_map is required")

    qs = EarningsSignalSnapshotHistory.objects.filter(
        batch_key__in=list(candidate_batch_keys),
        ts_code__in=normalized_codes,
        asof_date__gte=date(int(start_year), 1, 1),
        asof_date__lte=date(int(end_year), 12, 31),
    ).only(
        "ts_code",
        "asof_date",
        "report_type",
        "action",
        "risk_level",
        "signal_score",
        "raw_result",
    )
    if report_filter not in {"ALL", "FUSION"}:
        qs = qs.filter(report_type=report_filter)

    by_date_code: dict[tuple[date, str], list[EarningsSignalSnapshotHistory]] = {}
    for row in qs.iterator(chunk_size=5000):
        expected_batch_key = _resolve_batch_key_for_report_type(
            str(row.report_type or ""),
            default_batch_key=default_batch_key,
            batch_key_map=normalized_batch_key_map,
        )
        if not expected_batch_key:
            continue
        if str(row.batch_key or "").strip() != expected_batch_key:
            continue
        key = (row.asof_date, row.ts_code)
        by_date_code.setdefault(key, []).append(row)

    price_map, market_dates = _build_price_map(normalized_codes, int(start_year), int(end_year))
    market_dates = [item for item in market_dates if int(start_year) <= item.year <= int(end_year)]

    metrics: list[dict[str, Any]] = []
    year_buckets: dict[str, list[dict[str, Any]]] = {}
    sample_trades: list[dict[str, Any]] = []
    for year in range(int(start_year), int(end_year) + 1):
        year_daily, year_active, stopped_codes, year_trades = _simulate_year(
            year=year,
            market_dates=market_dates,
            ts_codes=normalized_codes,
            by_date_code=by_date_code,
            price_map=price_map,
            min_score=float(min_score),
            max_risk=risk_level,
            mode=mode_normalized,
            starting_capital=starting_capital_value,
            max_position_pct=max_position_pct_value,
            first_entry_pct=first_entry_pct_value,
            max_buy_per_day=max_buy_per_day_value,
            stop_mode=stop_mode_normalized,
            single_stop_dd=float(single_stop_dd),
            sell_strategy=sell_strategy_normalized,
            take_profit_pct=(take_profit_pct_value if sell_strategy_normalized in {"take_profit_pct", "optimistic_or_take_profit"} else 0.0),
            stop_loss_pct=stop_loss_pct_value,
            max_holding_days=max_holding_days_value,
        )

        if stop_mode_normalized == "global":
            adjusted_daily, triggered_idx = _apply_global_stop(year_daily, float(global_stop_dd))
        else:
            adjusted_daily, triggered_idx = list(year_daily), None

        yearly_metric = _compute_year_metrics(year, adjusted_daily, year_active)
        yearly_metric["global_stop_dd"] = float(global_stop_dd)
        yearly_metric["global_stop_triggered"] = bool(triggered_idx is not None and stop_mode_normalized == "global")
        yearly_metric["global_stop_trigger_day_index"] = triggered_idx if stop_mode_normalized == "global" else None
        yearly_metric["stop_mode"] = stop_mode_normalized
        yearly_metric["single_stop_dd"] = float(single_stop_dd)
        yearly_metric["single_stop_triggered_stock_count"] = len(stopped_codes) if stop_mode_normalized == "single" else 0
        yearly_metric["single_stopped_codes"] = stopped_codes if stop_mode_normalized == "single" else []
        metrics.append(yearly_metric)
        year_buckets[str(year)] = year_trades
        sample_trades.extend(year_trades)

    return {
        "batch_key": default_batch_key,
        "effective_batch_key_map": normalized_batch_key_map,
        "mode": mode_normalized,
        "pool_size": len(normalized_codes),
        "min_score": float(min_score),
        "max_risk": risk_level,
        "report_type": report_filter,
        "stop_mode": stop_mode_normalized,
        "starting_capital": starting_capital_value,
        "max_position_pct": max_position_pct_value,
        "first_entry_pct": first_entry_pct_value,
        "max_buy_per_day": max_buy_per_day_value,
        "global_stop_dd": float(global_stop_dd),
        "single_stop_dd": float(single_stop_dd),
        "sell_strategy": sell_strategy_normalized,
        "take_profit_pct": take_profit_pct_value,
        "stop_loss_pct": stop_loss_pct_value,
        "max_holding_days": max_holding_days_value,
        "combined": _summarize_trade_bucket(sample_trades),
        "by_year": {year: _summarize_trade_bucket(trades) for year, trades in sorted(year_buckets.items())},
        "sample_trades": sample_trades[:100],
        "metrics": metrics,
    }
