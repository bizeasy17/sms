from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db import connection

REPORT_END_SUFFIX = {"Q1": "0331", "H1": "0630", "Q3": "0930", "FY": "1231"}
FINANCIAL_METRIC_FIELDS = {
    "revenue_yoy_pct",
    "revenue_qoq_pct",
    "netprofit_yoy_pct",
    "netprofit_qoq_pct",
    "ebit_yoy_pct",
    "ebit_qoq_pct",
    "roe_pct",
    "roe_dt_pct",
}


def _as_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _growth_pct(current: float | None, previous: float | None) -> tuple[float | None, bool]:
    if current is None or previous is None or abs(previous) < 1e-9:
        return None, False
    return ((current - previous) / abs(previous)) * 100.0, previous < 0 <= current


def _period_dates(fiscal_year: int, report_type: str) -> tuple[str, str, str, str]:
    suffix = REPORT_END_SUFFIX[report_type]
    current_end = f"{fiscal_year}{suffix}"
    prior_year_end = f"{fiscal_year - 1}{suffix}"
    previous_map = {
        "Q1": (f"{fiscal_year - 1}1231", f"{fiscal_year - 1}0930"),
        "H1": (f"{fiscal_year}0331", f"{fiscal_year - 1}1231"),
        "Q3": (f"{fiscal_year}0630", f"{fiscal_year}0331"),
        "FY": (f"{fiscal_year}0930", f"{fiscal_year}0630"),
    }
    previous_end, previous_previous_end = previous_map[report_type]
    return current_end, prior_year_end, previous_end, previous_previous_end


def _standalone(cumulative: float | None, preceding_cumulative: float | None, report_type: str) -> float | None:
    if cumulative is None:
        return None
    if report_type == "Q1":
        return cumulative
    if preceding_cumulative is None:
        return None
    return cumulative - preceding_cumulative


def _previous_quarter_report_type(report_type: str) -> str:
    return {"Q1": "FY", "H1": "Q1", "Q3": "H1", "FY": "Q3"}[report_type]


def _threshold_value(filters: dict[str, Any], key: str) -> float | None:
    value = _as_number(filters.get(key))
    return value


def _matches_threshold(value: float | None, threshold: float | None) -> bool:
    return threshold is None or (value is not None and value >= threshold)


@dataclass(frozen=True)
class ScreenRequest:
    candidate_codes: list[str]
    fiscal_year: int
    report_type: str
    filters: dict[str, Any]
    sort_by: str = "financial_score"
    sort_order: str = "desc"


def _fetch_rows(table: str, columns: list[str], codes: list[str], end_dates: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    if not codes:
        return {}
    sql = f"""
        SELECT DISTINCT ON (ts_code, end_date) {', '.join(columns)}
        FROM {table}
        WHERE ts_code = ANY(%s) AND end_date = ANY(%s)
        ORDER BY ts_code, end_date, ann_date DESC, id DESC
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [codes, end_dates])
        field_names = [column[0] for column in cursor.description]
        return {
            (str(row[0]), str(row[2])): dict(zip(field_names, row))
            for row in cursor.fetchall()
        }


def _panel_metric(row: dict[str, Any] | None, field: str) -> float | None:
    return _as_number((row or {}).get(field))


def _ebit(row: dict[str, Any] | None) -> tuple[float | None, str]:
    direct = _as_number((row or {}).get("ebit"))
    if direct is not None:
        return direct, "reported_ebit"
    operate_profit = _as_number((row or {}).get("operate_profit"))
    finance_expense = _as_number((row or {}).get("fin_exp"))
    if operate_profit is not None and finance_expense is not None:
        return operate_profit + finance_expense, "operate_profit_plus_fin_exp"
    return None, "unavailable"


def _score(metrics: dict[str, float | None]) -> float | None:
    values = [metrics[key] for key in ("revenue_yoy_pct", "netprofit_yoy_pct", "ebit_yoy_pct", "roe_pct", "roe_dt_pct") if metrics.get(key) is not None]
    if not values:
        return None
    return round(max(0.0, min(100.0, sum(values) / len(values))), 2)


def screen_financial_performance(request: ScreenRequest) -> list[dict[str, Any]]:
    report_type = str(request.report_type or "").upper()
    if report_type not in REPORT_END_SUFFIX:
        raise ValueError("report_type must be Q1, H1, Q3, or FY")
    codes = list(dict.fromkeys(str(code).strip().upper() for code in request.candidate_codes if str(code).strip()))
    if not codes:
        return []
    if len(codes) > 10000:
        raise ValueError("candidate_codes exceeds 10000")

    current_end, prior_year_end, previous_end, previous_previous_end = _period_dates(request.fiscal_year, report_type)
    end_dates = [current_end, prior_year_end, previous_end, previous_previous_end]
    panel_rows = _fetch_rows(
        "earnings_financial_feature_panel",
        ["ts_code", "ann_date", "end_date", "revenue", "n_income_attr_p", "roe", "roe_dt"],
        codes,
        end_dates,
    )
    income_rows = _fetch_rows(
        "earnings_fin_income",
        ["ts_code", "ann_date", "end_date", "ebit", "operate_profit", "fin_exp"],
        codes,
        end_dates,
    )

    filters = request.filters or {}
    thresholds = {
        key: _threshold_value(filters, key)
        for key in (
            "min_ebit_yoy_pct", "min_ebit_qoq_pct", "min_revenue_yoy_pct",
            "min_revenue_qoq_pct", "min_netprofit_yoy_pct", "min_netprofit_qoq_pct",
            "min_roe_pct", "min_roe_dt_pct",
        )
    }
    enabled_metric_keys = [key for key, value in thresholds.items() if value is not None]
    require_all_metrics = bool(filters.get("require_all_metrics", False))
    result = []
    for code in codes:
        current = panel_rows.get((code, current_end))
        if not current:
            continue
        previous_year = panel_rows.get((code, prior_year_end))
        previous = panel_rows.get((code, previous_end))
        previous_previous = panel_rows.get((code, previous_previous_end))
        current_income = income_rows.get((code, current_end))
        previous_year_income = income_rows.get((code, prior_year_end))
        previous_income = income_rows.get((code, previous_end))
        previous_previous_income = income_rows.get((code, previous_previous_end))

        revenue_yoy, revenue_turnaround = _growth_pct(_panel_metric(current, "revenue"), _panel_metric(previous_year, "revenue"))
        netprofit_yoy, netprofit_turnaround = _growth_pct(_panel_metric(current, "n_income_attr_p"), _panel_metric(previous_year, "n_income_attr_p"))
        current_revenue_quarter = _standalone(_panel_metric(current, "revenue"), _panel_metric(previous, "revenue"), report_type)
        previous_revenue_quarter = _standalone(_panel_metric(previous, "revenue"), _panel_metric(previous_previous, "revenue"), _previous_quarter_report_type(report_type))
        revenue_qoq, _ = _growth_pct(current_revenue_quarter, previous_revenue_quarter)
        current_netprofit_quarter = _standalone(_panel_metric(current, "n_income_attr_p"), _panel_metric(previous, "n_income_attr_p"), report_type)
        previous_netprofit_quarter = _standalone(_panel_metric(previous, "n_income_attr_p"), _panel_metric(previous_previous, "n_income_attr_p"), _previous_quarter_report_type(report_type))
        netprofit_qoq, _ = _growth_pct(current_netprofit_quarter, previous_netprofit_quarter)
        current_ebit, ebit_source = _ebit(current_income)
        previous_year_ebit, _ = _ebit(previous_year_income)
        previous_ebit, _ = _ebit(previous_income)
        previous_previous_ebit, _ = _ebit(previous_previous_income)
        ebit_yoy, ebit_turnaround = _growth_pct(current_ebit, previous_year_ebit)
        current_ebit_quarter = _standalone(current_ebit, previous_ebit, report_type)
        previous_ebit_quarter = _standalone(previous_ebit, previous_previous_ebit, _previous_quarter_report_type(report_type))
        ebit_qoq, _ = _growth_pct(current_ebit_quarter, previous_ebit_quarter)
        metrics = {
            "revenue_yoy_pct": revenue_yoy, "revenue_qoq_pct": revenue_qoq,
            "netprofit_yoy_pct": netprofit_yoy, "netprofit_qoq_pct": netprofit_qoq,
            "ebit_yoy_pct": ebit_yoy, "ebit_qoq_pct": ebit_qoq,
            "roe_pct": _panel_metric(current, "roe"), "roe_dt_pct": _panel_metric(current, "roe_dt"),
        }
        if not all(_matches_threshold(metrics[key.removeprefix("min_")], threshold) for key, threshold in thresholds.items()):
            continue
        quality_flags = [key.removeprefix("min_") for key in enabled_metric_keys if metrics[key.removeprefix("min_")] is None]
        if require_all_metrics and quality_flags:
            continue
        matched_conditions = [f"{key.removeprefix('min_')} >= {threshold:g}%" for key, threshold in thresholds.items() if threshold is not None]
        result.append({
            "ts_code": code,
            "fiscal_year": request.fiscal_year,
            "report_type": report_type,
            "financial_end_date": current_end,
            "financial_ann_date": str(current.get("ann_date") or ""),
            "revenue": _panel_metric(current, "revenue"),
            "netprofit": _panel_metric(current, "n_income_attr_p"),
            "ebit": current_ebit,
            "ebit_source": ebit_source,
            **metrics,
            "financial_score": _score(metrics),
            "matched_conditions": matched_conditions,
            "data_quality_flags": quality_flags,
            "turnaround": revenue_turnaround or netprofit_turnaround or ebit_turnaround,
        })
    sort_by = request.sort_by if request.sort_by in {"financial_score", *FINANCIAL_METRIC_FIELDS} else "financial_score"
    descending = str(request.sort_order).lower() != "asc"
    result.sort(key=lambda row: (row.get(sort_by) is None, -(row.get(sort_by) or float("-inf")) if descending else row.get(sort_by) or float("inf"), row["ts_code"]))
    return result