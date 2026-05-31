import datetime
from collections import defaultdict

import pandas as pd
from django.db.models import Max

from datastore.models import StockFundamentalHistory
from datastore.utils.tushare_util import call_tushare_api
from valuation.models import ValuationFundBasic, ValuationFundNav, ValuationFundPortfolio


def _normalize_stock_ts_code(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        return text
    if text.startswith(("60", "68", "90")):
        return f"{text}.SH"
    if text.startswith(("00", "30", "20")):
        return f"{text}.SZ"
    if text.startswith("8") or text.startswith("4"):
        return f"{text}.BJ"
    return text


def _safe_float(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _coerce_nav_date(row):
    for key in ("nav_date", "end_date", "trade_date", "ann_date"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _pick_nav_value(row):
    for key in ("adj_nav", "accum_nav", "unit_nav"):
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _find_point_value(nav_rows, start_date, end_date):
    candidates = []
    for item in nav_rows:
        nav_date = str(item.get("nav_date") or "")
        nav_value = _pick_nav_value(item)
        if not nav_date or nav_value is None:
            continue
        if start_date <= nav_date <= end_date:
            candidates.append((nav_date, nav_value))
    if not candidates:
        return None, None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1], candidates[-1][1]


def _calc_return_pct(start_value, end_value):
    if start_value is None or end_value is None:
        return None
    if start_value <= 0:
        return None
    return round((end_value / start_value - 1.0) * 100.0, 2)


def _sum_nullable(values):
    total = 0.0
    has_value = False
    for value in values:
        number = _safe_float(value)
        if number is None:
            continue
        total += number
        has_value = True
    if not has_value:
        return None
    return round(total, 2)


def _calc_ratio_pct(numerator, denominator):
    numerator_value = _safe_float(numerator)
    denominator_value = _safe_float(denominator)
    if numerator_value is None or denominator_value is None or denominator_value <= 0:
        return None
    return round(numerator_value / denominator_value * 100.0, 4)


def _load_latest_stock_totals(ts_code):
    row = (
        StockFundamentalHistory.objects.filter(ts_code=ts_code, freq="D")
        .order_by("-trade_date")
        .values("trade_date", "total_mv", "total_share")
        .first()
    )
    if not row:
        return {
            "trade_date": None,
            "total_mv": None,
            "total_share": None,
        }

    total_mv_wan = _safe_float(row.get("total_mv"))
    total_share_wan = _safe_float(row.get("total_share"))
    return {
        "trade_date": row.get("trade_date"),
        "total_mv": None if total_mv_wan is None else total_mv_wan * 10000.0,
        "total_share": None if total_share_wan is None else total_share_wan * 10000.0,
    }


def upsert_fund_basic_records(records):
    if not records:
        return 0
    count = 0
    for row in records:
        fund_ts_code = str(row.get("ts_code") or "").strip().upper()
        if not fund_ts_code:
            continue
        defaults = {
            "name": str(row.get("name") or "").strip(),
            "management": str(row.get("management") or "").strip(),
            "custodian": str(row.get("custodian") or "").strip(),
            "fund_type": str(row.get("fund_type") or "").strip(),
            "found_date": str(row.get("found_date") or "").strip(),
            "due_date": str(row.get("due_date") or "").strip(),
            "status": str(row.get("status") or "").strip(),
            "market": str(row.get("market") or "").strip(),
            "is_updated": True,
        }
        ValuationFundBasic.objects.update_or_create(ts_code=fund_ts_code, defaults=defaults)
        count += 1
    return count


def upsert_fund_portfolio_records(fund_ts_code, records):
    if not fund_ts_code or not records:
        return 0
    normalized_fund = str(fund_ts_code).strip().upper()
    count = 0
    for row in records:
        stock_ts_code = _normalize_stock_ts_code(row.get("symbol") or row.get("stock_ts_code"))
        if not stock_ts_code:
            continue
        end_date = str(row.get("end_date") or "").strip()
        if not end_date:
            continue
        defaults = {
            "stock_symbol": str(row.get("symbol") or "").strip().upper(),
            "ann_date": str(row.get("ann_date") or "").strip(),
            "mkv": _safe_float(row.get("mkv")),
            "amount": _safe_float(row.get("amount")),
            "stk_mkv_ratio": _safe_float(row.get("stk_mkv_ratio")),
            "stk_float_ratio": _safe_float(row.get("stk_float_ratio")),
        }
        ValuationFundPortfolio.objects.update_or_create(
            fund_ts_code=normalized_fund,
            stock_ts_code=stock_ts_code,
            end_date=end_date,
            defaults=defaults,
        )
        count += 1
    return count


def upsert_fund_nav_records(fund_ts_code, records):
    if not fund_ts_code or not records:
        return 0
    normalized_fund = str(fund_ts_code).strip().upper()
    count = 0
    for row in records:
        nav_date = _coerce_nav_date(row)
        if not nav_date:
            continue
        defaults = {
            "unit_nav": _safe_float(row.get("unit_nav")),
            "accum_nav": _safe_float(row.get("accum_nav")),
            "adj_nav": _safe_float(row.get("adj_nav")),
        }
        if defaults["unit_nav"] is None and defaults["accum_nav"] is None and defaults["adj_nav"] is None:
            continue
        ValuationFundNav.objects.update_or_create(
            fund_ts_code=normalized_fund,
            nav_date=nav_date,
            defaults=defaults,
        )
        count += 1
    return count


def sync_fund_basics_from_tushare(pro, market="E"):
    df = call_tushare_api(pro, "fund_basic", market=market)
    if df is None or df.empty:
        return 0
    return upsert_fund_basic_records(df.to_dict(orient="records"))


def sync_single_fund_from_tushare(
    pro,
    fund_ts_code,
    start_date="",
    portfolio_start_date="",
    nav_start_date="",
):
    normalized_fund = str(fund_ts_code or "").strip().upper()
    if not normalized_fund:
        return {"portfolio": 0, "nav": 0}

    portfolio_kwargs = {"ts_code": normalized_fund}
    nav_kwargs = {"ts_code": normalized_fund}
    effective_portfolio_start = str(portfolio_start_date or start_date or "").strip()
    effective_nav_start = str(nav_start_date or start_date or "").strip()
    if effective_portfolio_start:
        portfolio_kwargs["start_date"] = effective_portfolio_start
    if effective_nav_start:
        nav_kwargs["start_date"] = effective_nav_start

    portfolio_df = call_tushare_api(pro, "fund_portfolio", **portfolio_kwargs)
    nav_df = call_tushare_api(pro, "fund_nav", **nav_kwargs)

    portfolio_count = upsert_fund_portfolio_records(
        normalized_fund,
        [] if portfolio_df is None or portfolio_df.empty else portfolio_df.to_dict(orient="records"),
    )
    nav_count = upsert_fund_nav_records(
        normalized_fund,
        [] if nav_df is None or nav_df.empty else nav_df.to_dict(orient="records"),
    )

    return {
        "portfolio": portfolio_count,
        "nav": nav_count,
    }


def get_stock_fund_holding_snapshot(ts_code, limit=0):
    normalized_ts_code = _normalize_stock_ts_code(ts_code)
    if not normalized_ts_code:
        return {
            "rows": [],
            "summary": {
                "latest_end_date": "",
                "fund_count": 0,
                "total_mkv": None,
                "total_amount": None,
                "stock_total_mv": None,
                "stock_total_share": None,
                "hold_market_cap_ratio_pct": None,
                "hold_total_share_ratio_pct": None,
            },
        }

    latest_end_date = str(
        ValuationFundPortfolio.objects.filter(stock_ts_code=normalized_ts_code)
        .aggregate(latest_end_date=Max("end_date"))
        .get("latest_end_date")
        or ""
    )
    if not latest_end_date:
        return {
            "rows": [],
            "summary": {
                "latest_end_date": "",
                "fund_count": 0,
                "total_mkv": None,
                "total_amount": None,
                "stock_total_mv": None,
                "stock_total_share": None,
                "hold_market_cap_ratio_pct": None,
                "hold_total_share_ratio_pct": None,
            },
        }

    portfolio_rows = list(
        ValuationFundPortfolio.objects.filter(
            stock_ts_code=normalized_ts_code,
            end_date=latest_end_date,
        ).order_by("-stk_mkv_ratio", "-mkv", "fund_ts_code")
    )

    if not portfolio_rows:
        return {
            "rows": [],
            "summary": {
                "latest_end_date": latest_end_date,
                "fund_count": 0,
                "total_mkv": None,
                "total_amount": None,
                "stock_total_mv": None,
                "stock_total_share": None,
                "hold_market_cap_ratio_pct": None,
                "hold_total_share_ratio_pct": None,
            },
        }

    fund_codes = [row.fund_ts_code for row in portfolio_rows]

    basic_map = {
        item.ts_code: item
        for item in ValuationFundBasic.objects.filter(ts_code__in=fund_codes)
    }

    nav_rows = list(
        ValuationFundNav.objects.filter(fund_ts_code__in=fund_codes)
        .order_by("fund_ts_code", "-nav_date")
        .values("fund_ts_code", "nav_date", "unit_nav", "accum_nav", "adj_nav")
    )

    nav_map = defaultdict(list)
    for row in nav_rows:
        nav_map[row["fund_ts_code"]].append(row)

    today = datetime.date.today()
    current_year = today.year
    prev_year = current_year - 1
    month_start = today.replace(day=1).strftime("%Y%m%d")
    this_year_start = f"{current_year}0101"
    prev_year_start = f"{prev_year}0101"
    prev_year_end = f"{prev_year}1231"

    result = []
    for holding_row in portfolio_rows:
        fund_code = holding_row.fund_ts_code
        fund_nav_rows = nav_map.get(fund_code, [])
        latest_nav = None
        if fund_nav_rows:
            latest_nav = _pick_nav_value(fund_nav_rows[0])

        py_start, py_end = _find_point_value(fund_nav_rows, prev_year_start, prev_year_end)
        ytd_start, ytd_end = _find_point_value(fund_nav_rows, this_year_start, today.strftime("%Y%m%d"))
        month_start_nav, month_end_nav = _find_point_value(fund_nav_rows, month_start, today.strftime("%Y%m%d"))

        basic = basic_map.get(fund_code)
        result.append(
            {
                "fund_ts_code": fund_code,
                "fund_name": "" if basic is None else basic.name,
                "end_date": holding_row.end_date,
                "ann_date": holding_row.ann_date,
                "mkv": holding_row.mkv,
                "amount": holding_row.amount,
                "stk_mkv_ratio": holding_row.stk_mkv_ratio,
                "stk_float_ratio": holding_row.stk_float_ratio,
                "latest_nav": latest_nav,
                "ret_prev_year": _calc_return_pct(py_start, py_end),
                "ret_ytd": _calc_return_pct(ytd_start, ytd_end),
                "ret_month": _calc_return_pct(month_start_nav, month_end_nav),
            }
        )

    result.sort(key=lambda item: item.get("stk_mkv_ratio") or 0.0, reverse=True)

    normalized_limit = int(limit or 0)
    if normalized_limit > 0:
        rows = result[:normalized_limit]
    else:
        rows = result

    total_mkv = _sum_nullable(item.get("mkv") for item in result)
    total_amount = _sum_nullable(item.get("amount") for item in result)
    stock_totals = _load_latest_stock_totals(normalized_ts_code)

    summary = {
        "latest_end_date": latest_end_date,
        "fund_count": len(result),
        "total_mkv": total_mkv,
        "total_amount": total_amount,
        "stock_total_mv": stock_totals.get("total_mv"),
        "stock_total_share": stock_totals.get("total_share"),
        "hold_market_cap_ratio_pct": _calc_ratio_pct(total_mkv, stock_totals.get("total_mv")),
        "hold_total_share_ratio_pct": _calc_ratio_pct(total_amount, stock_totals.get("total_share")),
    }
    return {
        "rows": rows,
        "summary": summary,
    }


def list_stock_fund_holding_rows(ts_code, limit=100):
    snapshot = get_stock_fund_holding_snapshot(ts_code, limit=limit)
    return snapshot["rows"]
