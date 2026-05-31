from datetime import date, datetime

import pandas as pd
from django.conf import settings
from django.db import connections

from datastore.models import StockFundamentalHistory


def get_tushare_pro(token=None):
    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("tushare is not installed.") from exc

    if token:
        ts.set_token(token)
    return ts.pro_api()


def safe_float(value, default=None):
    if value is None or value == "":
        return default
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pick_value(row, candidates, default=None, safe_float_func=None):
    resolver = safe_float if safe_float_func is None else safe_float_func
    for key in candidates:
        if key in row:
            value = resolver(row.get(key), None)
            if value is not None:
                return value
    return default


def latest_record(df, sort_cols=None):
    if df is None or df.empty:
        return {}
    if sort_cols:
        valid_cols = [col for col in sort_cols if col in df.columns]
        if valid_cols:
            df = df.sort_values(valid_cols, ascending=False)
    return df.iloc[0].to_dict()


def normalize_date_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return text.replace("-", "").strip()


def parse_date_yyyymmdd(value):
    text = normalize_date_text(value)
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _valid_ann_ge_end_row(row, parse_date_func):
    ann_dt = parse_date_func(row.get("ann_date"))
    end_dt = parse_date_func(row.get("end_date"))
    if ann_dt is None or end_dt is None:
        return True
    return ann_dt >= end_dt


def record_for_end_date(df, end_date, sort_cols=None, normalize_date_text_func=None, latest_record_func=None):
    normalize_func = normalize_date_text if normalize_date_text_func is None else normalize_date_text_func
    latest_func = latest_record if latest_record_func is None else latest_record_func

    if df is None or df.empty or not end_date or "end_date" not in df.columns:
        return {}

    target = normalize_func(end_date)
    if not target:
        return {}

    matched = df[df["end_date"].map(normalize_func).eq(target)].copy()
    if matched.empty:
        return {}

    if "ann_date" in matched.columns:
        valid_mask = matched.apply(
            lambda row: _valid_ann_ge_end_row(row, parse_date_yyyymmdd),
            axis=1,
        )
        if valid_mask.any():
            matched = matched[valid_mask].copy()

    return latest_func(matched, sort_cols or ["end_date", "ann_date", "f_ann_date"])


def filter_financial_frame_asof(df, trade_date=None, normalize_date_text_func=None):
    normalize_func = normalize_date_text if normalize_date_text_func is None else normalize_date_text_func

    if df is None or df.empty or trade_date is None:
        return df

    cutoff = normalize_func(trade_date)
    if len(cutoff) != 8 or not cutoff.isdigit():
        return df

    ann_col = None
    for candidate in ["ann_date", "f_ann_date"]:
        if candidate in df.columns:
            ann_col = candidate
            break
    if ann_col is None:
        return df

    ann_series = df[ann_col].map(normalize_func)
    visible_mask = ann_series.eq("") | ann_series.le(cutoff)
    return df[visible_mask].copy()


def filter_financial_frames_asof(frames, trade_date=None, filter_financial_frame_asof_func=None):
    filter_func = filter_financial_frame_asof if filter_financial_frame_asof_func is None else filter_financial_frame_asof_func

    if not isinstance(frames, dict) or trade_date is None:
        return frames

    filtered = dict(frames)
    for key in ["fina_indicator", "income", "balancesheet", "cashflow", "dividend", "express_vip"]:
        filtered[key] = filter_func(filtered.get(key), trade_date=trade_date)
    return filtered


def _previous_year_end_date_text(end_date):
    text = normalize_date_text(end_date)
    if len(text) != 8 or not text.isdigit():
        return None
    return f"{int(text[:4]) - 1:04d}1231"


def _same_period_last_year_end_date_text(end_date):
    text = normalize_date_text(end_date)
    if len(text) != 8 or not text.isdigit():
        return None
    return f"{int(text[:4]) - 1:04d}{text[4:]}"


def _load_financial_feature_panel_rows(ts_code, query_local_financial_df_func=None):
    query_local = query_local_financial_df if query_local_financial_df_func is None else query_local_financial_df_func
    return query_local(
        """
        SELECT *
        FROM earnings_financial_feature_panel
        WHERE ts_code = %s
        ORDER BY end_date DESC, ann_date DESC
        LIMIT 16
        """,
        [ts_code],
        db_alias=str(getattr(settings, "VALUATION_LOCAL_FINANCIAL_DB_ALIAS", "earnings") or "earnings"),
    )


def _panel_to_endpoint_frame(panel_df, endpoint):
    if panel_df is None or panel_df.empty:
        return pd.DataFrame()

    field_map = {
        "fina_indicator": [
            "roe", "roe_dt", "roa", "q_dt_roe", "tr_yoy", "netprofit_yoy",
            "grossprofit_margin", "netprofit_margin", "debt_to_assets", "current_ratio",
            "quick_ratio", "cash_ratio", "assets_turn", "ocf_to_or",
        ],
        "income": [
            "revenue", "total_revenue", "operate_profit", "total_profit", "n_income",
            "n_income_attr_p", "basic_eps", "diluted_eps",
        ],
        "balancesheet": [
            "total_assets", "total_liab", "total_hldr_eqy_exc_min_int", "money_cap",
            "accounts_receiv", "inventories", "st_borr", "lt_borr",
        ],
        "cashflow": [
            "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act", "n_incr_cash_cash_equ",
        ],
    }
    selected_fields = field_map.get(endpoint)
    if not selected_fields:
        return pd.DataFrame()

    rows = []
    for _, row in panel_df.iterrows():
        payload = {
            "ts_code": row.get("ts_code"),
            "ann_date": normalize_date_text(row.get("ann_date")),
            "f_ann_date": "",
            "end_date": normalize_date_text(row.get("end_date")),
            "period": normalize_date_text(row.get("end_date")),
            "report_type": row.get("report_type") or "",
            "comp_type": "",
        }
        for field in selected_fields:
            if field in row.index:
                payload[field] = row.get(field)
        rows.append(payload)
    return pd.DataFrame(rows)


def _append_missing_panel_rows(existing_frame, panel_frame):
    if panel_frame is None or panel_frame.empty:
        return existing_frame

    if existing_frame is None or existing_frame.empty:
        return panel_frame.copy()

    if "end_date" not in existing_frame.columns:
        return pd.concat([existing_frame, panel_frame], ignore_index=True, sort=False)

    existing_end_dates = set(existing_frame["end_date"].map(normalize_date_text).tolist())
    append_rows = panel_frame[~panel_frame["end_date"].map(normalize_date_text).isin(existing_end_dates)].copy()
    if append_rows.empty:
        return existing_frame
    return pd.concat([existing_frame, append_rows], ignore_index=True, sort=False)


def _augment_frames_with_feature_panel(frames, ts_code, forced_report_end_date=None, query_local_financial_df_func=None):
    forced_end_date = normalize_date_text(forced_report_end_date)
    if not forced_end_date:
        return frames

    target_dates = {
        forced_end_date,
        _previous_year_end_date_text(forced_end_date),
        _same_period_last_year_end_date_text(forced_end_date),
    }
    target_dates = {item for item in target_dates if item}

    panel_df = _load_financial_feature_panel_rows(
        ts_code,
        query_local_financial_df_func=query_local_financial_df_func,
    )
    if panel_df is None or panel_df.empty:
        return frames

    panel_df = panel_df[panel_df["end_date"].map(normalize_date_text).isin(target_dates)].copy()
    if panel_df.empty:
        return frames

    augmented = dict(frames)
    for endpoint in ["fina_indicator", "income", "balancesheet", "cashflow"]:
        panel_frame = _panel_to_endpoint_frame(panel_df, endpoint)
        augmented[endpoint] = _append_missing_panel_rows(augmented.get(endpoint), panel_frame)
    return augmented


def fetch_tushare_frames(ts_code, trade_date=None, pro=None, get_tushare_pro_func=None):
    pro_factory = get_tushare_pro if get_tushare_pro_func is None else get_tushare_pro_func
    resolved_pro = pro or pro_factory()

    trade_date_str = str(trade_date).replace("-", "") if trade_date else None
    daily_basic = resolved_pro.daily_basic(ts_code=ts_code, trade_date=trade_date_str)
    if daily_basic is None or daily_basic.empty:
        daily_basic = resolved_pro.daily_basic(ts_code=ts_code, limit=1)

    fina_indicator = resolved_pro.fina_indicator(ts_code=ts_code, limit=8)
    income = resolved_pro.income(ts_code=ts_code, limit=8)
    balancesheet = resolved_pro.balancesheet(ts_code=ts_code, limit=8)
    cashflow = resolved_pro.cashflow(ts_code=ts_code, limit=8)
    dividend = resolved_pro.dividend(ts_code=ts_code)
    try:
        express_vip = resolved_pro.express_vip(ts_code=ts_code, limit=4)
    except Exception:
        express_vip = None

    return {
        "daily_basic": daily_basic,
        "fina_indicator": fina_indicator,
        "income": income,
        "balancesheet": balancesheet,
        "cashflow": cashflow,
        "dividend": dividend,
        "express_vip": express_vip,
        "__fetch_source__": "tushare",
        "__tushare_endpoints__": [
            "daily_basic",
            "fina_indicator",
            "income",
            "balancesheet",
            "cashflow",
            "dividend",
            "express_vip",
        ],
    }


def fetch_tushare_dividend_frame(ts_code, pro=None, get_tushare_pro_func=None):
    pro_factory = get_tushare_pro if get_tushare_pro_func is None else get_tushare_pro_func
    resolved_pro = pro or pro_factory()
    try:
        return resolved_pro.dividend(ts_code=ts_code)
    except Exception:
        return pd.DataFrame()


def query_local_financial_df(sql, params, db_alias=None):
    alias = db_alias or str(getattr(settings, "VALUATION_LOCAL_FINANCIAL_DB_ALIAS", "earnings") or "earnings")
    with connections[alias].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in (cursor.description or [])]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def fetch_local_financial_frames(
    ts_code,
    trade_date=None,
    forced_report_end_date=None,
    parse_date_yyyymmdd_func=None,
    safe_float_func=None,
    query_local_financial_df_func=None,
    pro=None,
    get_tushare_pro_func=None,
):
    parse_func = parse_date_yyyymmdd if parse_date_yyyymmdd_func is None else parse_date_yyyymmdd_func
    safe_float_resolver = safe_float if safe_float_func is None else safe_float_func
    query_local = query_local_financial_df if query_local_financial_df_func is None else query_local_financial_df_func

    trade_date_obj = None
    if trade_date is not None:
        if isinstance(trade_date, date):
            trade_date_obj = trade_date
        else:
            trade_date_obj = parse_func(trade_date)

    fundamental_qs = StockFundamentalHistory.objects.filter(ts_code=ts_code, freq="D")
    if trade_date_obj is not None:
        fundamental_qs = fundamental_qs.filter(trade_date__lte=trade_date_obj)
    fundamental_row = (
        fundamental_qs.order_by("-trade_date")
        .values("trade_date", "close", "total_share", "total_mv", "circ_mv", "pe", "pe_ttm", "ps", "ps_ttm", "pb")
        .first()
    )

    daily_basic = pd.DataFrame()
    if fundamental_row:
        trade_date_value = fundamental_row.get("trade_date")
        if hasattr(trade_date_value, "strftime"):
            trade_date_value = trade_date_value.strftime("%Y%m%d")

        daily_basic = pd.DataFrame(
            [
                {
                    "trade_date": trade_date_value,
                    "close": safe_float_resolver(fundamental_row.get("close"), None),
                    # StockFundamentalHistory follows tushare daily_basic units (share in 万股, mv in 万元).
                    # Keep raw values here because snapshot builder converts 万 -> 元/股.
                    "total_share": safe_float_resolver(fundamental_row.get("total_share"), None),
                    "total_mv": safe_float_resolver(fundamental_row.get("total_mv"), None),
                    "circ_mv": safe_float_resolver(fundamental_row.get("circ_mv"), None),
                    "pe": safe_float_resolver(fundamental_row.get("pe"), None),
                    "pe_ttm": safe_float_resolver(fundamental_row.get("pe_ttm"), None),
                    "ps": safe_float_resolver(fundamental_row.get("ps"), None),
                    "ps_ttm": safe_float_resolver(fundamental_row.get("ps_ttm"), None),
                    "pb": safe_float_resolver(fundamental_row.get("pb"), None),
                }
            ]
        )

    db_alias = str(getattr(settings, "VALUATION_LOCAL_FINANCIAL_DB_ALIAS", "earnings") or "earnings")

    fina_indicator = query_local(
        """
        SELECT *
        FROM earnings_fin_fina_indicator_vip
        WHERE ts_code = %s
        ORDER BY end_date DESC, ann_date DESC
        LIMIT 8
        """,
        [ts_code],
        db_alias=db_alias,
    )
    income = query_local(
        """
        SELECT *
        FROM earnings_fin_income
        WHERE ts_code = %s
        ORDER BY end_date DESC, ann_date DESC
        LIMIT 8
        """,
        [ts_code],
        db_alias=db_alias,
    )
    balancesheet = query_local(
        """
        SELECT *
        FROM earnings_fin_balancesheet_vip
        WHERE ts_code = %s
        ORDER BY end_date DESC, ann_date DESC
        LIMIT 8
        """,
        [ts_code],
        db_alias=db_alias,
    )
    cashflow = query_local(
        """
        SELECT *
        FROM earnings_fin_cashflow_vip
        WHERE ts_code = %s
        ORDER BY end_date DESC, ann_date DESC
        LIMIT 8
        """,
        [ts_code],
        db_alias=db_alias,
    )
    dividend = query_local(
        """
        SELECT *
        FROM earnings_fin_dividend
        WHERE ts_code = %s
        ORDER BY end_date DESC, ann_date DESC
        LIMIT 8
        """,
        [ts_code],
        db_alias=db_alias,
    )
    express_vip = query_local(
        """
        SELECT *
        FROM earnings_fin_express_vip
        WHERE ts_code = %s
        ORDER BY end_date DESC, ann_date DESC
        LIMIT 4
        """,
        [ts_code],
        db_alias=db_alias,
    )

    remote_fallback_frames = []
    enable_remote_dividend_fallback = bool(
        getattr(settings, "VALUATION_REMOTE_DIVIDEND_FALLBACK", True)
    )
    if enable_remote_dividend_fallback and (dividend is None or dividend.empty):
        dividend = fetch_tushare_dividend_frame(
            ts_code,
            pro=pro,
            get_tushare_pro_func=get_tushare_pro_func,
        )
        if dividend is not None and not dividend.empty:
            remote_fallback_frames.append("dividend")

    frames = {
        "daily_basic": daily_basic,
        "fina_indicator": fina_indicator,
        "income": income,
        "balancesheet": balancesheet,
        "cashflow": cashflow,
        "dividend": dividend,
        "express_vip": express_vip,
        "__fetch_source__": "local",
        "__remote_fallback_frames__": remote_fallback_frames,
    }
    return _augment_frames_with_feature_panel(
        frames,
        ts_code=ts_code,
        forced_report_end_date=forced_report_end_date,
        query_local_financial_df_func=query_local,
    )
