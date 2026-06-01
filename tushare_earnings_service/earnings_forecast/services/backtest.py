from __future__ import annotations

from datetime import date, datetime
from typing import Any

from earnings_forecast.models import EarningsSignalSnapshotHistory, LocalTradingHistory

RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
REPORT_RANK = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4, "FUSION": 5}


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
    stop_mode: str,
    single_stop_dd: float,
) -> tuple[list[float], int, list[str]]:
    next_date_map: dict[date, date] = {}
    for idx in range(len(market_dates) - 1):
        next_date_map[market_dates[idx]] = market_dates[idx + 1]

    daily_returns: list[float] = []
    active_days = 0

    stopped_codes: set[str] = set()
    stock_nav: dict[str, float] = {}
    stock_peak: dict[str, float] = {}

    for asof_date in market_dates:
        if asof_date.year != year:
            continue

        next_date = next_date_map.get(asof_date)
        if next_date is None:
            continue

        candidates: list[float] = []
        for code in ts_codes:
            if stop_mode == "single" and code in stopped_codes:
                continue

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

            p0 = price_map.get(code, {}).get(asof_date)
            p1 = price_map.get(code, {}).get(next_date)
            if p0 is None or p1 is None or p0 <= 0:
                continue

            ret = (p1 / p0) - 1.0
            candidates.append(ret)

            if stop_mode == "single" and float(single_stop_dd or 0.0) > 0:
                nav = stock_nav.get(code, 1.0) * (1.0 + ret)
                peak = max(stock_peak.get(code, 1.0), nav)
                stock_nav[code] = nav
                stock_peak[code] = peak
                drawdown = (nav / peak) - 1.0 if peak > 0 else 0.0
                if drawdown <= -float(single_stop_dd):
                    stopped_codes.add(code)

        if candidates:
            daily_ret = sum(candidates) / len(candidates)
            active_days += 1
        else:
            daily_ret = 0.0

        daily_returns.append(daily_ret)

    return daily_returns, active_days, sorted(stopped_codes)


def run_predictive_valuation_backtest(
    *,
    batch_key: str,
    ts_codes: list[str],
    start_year: int = 2024,
    end_year: int = 2025,
    min_score: float = 70.0,
    max_risk: str = "MEDIUM",
    stop_mode: str = "none",
    global_stop_dd: float = 0.0,
    single_stop_dd: float = 0.1,
    report_type: str = "ALL",
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

    qs = EarningsSignalSnapshotHistory.objects.filter(
        batch_key=str(batch_key or "").strip(),
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
        key = (row.asof_date, row.ts_code)
        by_date_code.setdefault(key, []).append(row)

    price_map, market_dates = _build_price_map(normalized_codes, int(start_year), int(end_year))
    market_dates = [item for item in market_dates if int(start_year) <= item.year <= int(end_year)]

    metrics: list[dict[str, Any]] = []
    for year in range(int(start_year), int(end_year) + 1):
        year_daily, year_active, stopped_codes = _simulate_year(
            year=year,
            market_dates=market_dates,
            ts_codes=normalized_codes,
            by_date_code=by_date_code,
            price_map=price_map,
            min_score=float(min_score),
            max_risk=risk_level,
            stop_mode=stop_mode_normalized,
            single_stop_dd=float(single_stop_dd),
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

    return {
        "batch_key": str(batch_key or "").strip(),
        "pool_size": len(normalized_codes),
        "min_score": float(min_score),
        "max_risk": risk_level,
        "report_type": report_filter,
        "stop_mode": stop_mode_normalized,
        "global_stop_dd": float(global_stop_dd),
        "single_stop_dd": float(single_stop_dd),
        "metrics": metrics,
    }
