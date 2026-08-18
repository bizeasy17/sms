import datetime
import csv
import hashlib
import math
import threading
import uuid
from collections import defaultdict
import pandas as pd
from pathlib import Path
import json
import logging
import mimetypes
import re
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from datastore.models import (
    Corporation,
    CorporationBasic,
    StockCostHistory,
    StockFundamentalHistory,
    StockTradingHistory,
)
from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.models import Q, Max, Count
from django.http import FileResponse, Http404
from django.views.decorators.cache import never_cache
from prediction.models import (
    StockCombinedFeature,
    StockGainLossQuantile,
    StockPrediction,
    StockThsMoneyflowDaily,
)
from valuation.models import (
    StockValuationSnapshot,
    StockValuationSnapshotHistory,
    StockValuationSnapshotLatest,
    StockValuationVariantSummaryLatest,
    IndustryVariantCache,
    IndustryVariantMetricDaily,
)
from prediction.services.business_industry_matcher import BusinessIndustryMatcher
from prediction.utils.prediction_util import get_tushare_pro
from valuation.services.validation_loader import ValuationConfig
from valuation.services.fund_holdings import get_stock_fund_holding_snapshot
from valuation.services.valuation_summary import summarize_buy_candidate
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datastore.utils.tushare_util import fetch_tushare_data
from valuation.services.snapshot_provider import query_local_financial_df
from valuation.services.valuation_engine import test_valuation
from prediction.utils.ta_util import calculate_atr
from utils.analysis_utils import is_last_row_value_below_quantile
from users.models import User, UserWatchlist
from valuation_risk.models import ValuationRiskSnapshot
from valuation_risk.services import build_valuation_risk_payload
from pandas.tseries.offsets import BDay
from users.models import UserStockTag
from django.test import RequestFactory
import time


logger = logging.getLogger(__name__)


def _normalize_company_website_url(value):
    website = str(value or "").strip()
    if not website:
        return None
    website = website.replace(" ", "")
    if website.lower().startswith(("http://", "https://")):
        return website
    return f"https://{website}"


def _financial_screening_service_url():
    return str(
        getattr(
            settings,
            "FINANCIAL_SCREENING_SERVICE_BASE_URL",
            "http://127.0.0.1:5003",
        )
    ).strip().rstrip("/")


def _financial_screening_candidate_rows(request, scope, sw_industry):
    queryset = Corporation.objects.filter(list_status="L")
    scope_text = str(scope or "").strip().upper()
    if scope_text == "WATCHLIST":
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        watch_codes = UserWatchlist.objects.filter(user=user, is_enabled=True).values_list("ts_code", flat=True)
        queryset = queryset.filter(ts_code__in=watch_codes)
    elif scope_text not in {"", "SCOPE:NONE"}:
        prefixes = [item.strip() for item in scope_text.split(",") if item.strip()]
        scope_query = Q()
        for prefix in prefixes:
            normalized_prefix = {"0": "00", "3": "30", "688": "68"}.get(prefix, prefix)
            scope_query |= Q(ts_code__startswith=normalized_prefix)
        if scope_query:
            queryset = queryset.filter(scope_query)
    sw_text = str(sw_industry or "").strip()
    if sw_text:
        queryset = queryset.filter(Q(sw_l3_code=sw_text) | Q(sw_l3_name=sw_text))
    return list(queryset.values("ts_code", "name", "sw_l3_code", "sw_l3_name"))


def _attach_financial_screening_valuation_results(items, trade_date, report_type):
    if not items:
        return
    codes = [str(item.get("ts_code") or "").strip().upper() for item in items]
    codes = [code for code in codes if code]
    report_end_date = _parse_date_like(items[0].get("financial_end_date"))
    if not codes or report_end_date is None:
        return
    method_map_by_code = _build_latest_snapshot_method_map(
        codes,
        market="CN",
        profit_report_type=report_type,
        profit_report_end_date=report_end_date,
    )
    close_map = {}
    max_trade_date = _parse_date_like(trade_date)
    trade_rows = StockTradingHistory.objects.filter(ts_code__in=codes, freq="D")
    if max_trade_date is not None:
        trade_rows = trade_rows.filter(trade_date__lte=max_trade_date)
    for quote in trade_rows.order_by("ts_code", "-trade_date").values("ts_code", "close_qfq", "close"):
        code = str(quote.get("ts_code") or "").upper()
        if code in close_map:
            continue
        close_map[code] = _to_float_or_none(quote.get("close_qfq")) or _to_float_or_none(quote.get("close"))
    end_date_map = {code: report_end_date for code in codes}
    try:
        predictive_map = _fetch_earnings_signal_batch(
            codes,
            report_type=report_type,
            financial_end_date_map=end_date_map,
        )
    except Exception as exc:
        logger.warning("financial screening predictive enrichment degraded: %s", exc)
        predictive_map = {}
    for item in items:
        code = str(item.get("ts_code") or "").upper()
        traditional = _summarize_buy_candidate(
            close_map.get(code),
            method_map_by_code.get(code) or {},
            0.1,
        )
        predictive = predictive_map.get(code) or {}
        item.update({
            "current_price": close_map.get(code),
            "traditional_valuation_price": traditional.get("composite_valuation_price"),
            "traditional_conservative_price": traditional.get("conservative_valuation_price"),
            "traditional_valuation_score": traditional.get("undervalue_score"),
            "traditional_buy_candidate": bool(traditional.get("buy_candidate")),
            "predictive_signal_score": _to_float_or_none(predictive.get("signal_score")),
            "predictive_action": str(predictive.get("action") or ""),
            "predictive_risk_level": str(predictive.get("risk_level") or ""),
            "predictive_target_price": _to_float_or_none(predictive.get("target_price")),
            "predictive_target_return_pct": _to_float_or_none(predictive.get("target_return_pct")),
        })


def _sort_financial_screening_results(items, sort_by, sort_order):
    allowed_fields = {
        "financial_score",
        "current_price",
        "traditional_valuation_score",
        "predictive_signal_score",
        "predictive_target_return_pct",
    }
    field = str(sort_by or "financial_score").strip()
    if field not in allowed_fields:
        field = "financial_score"
    descending = str(sort_order or "desc").strip().lower() != "asc"

    def sort_key(item):
        value = _to_float_or_none(item.get(field))
        if value is None:
            return (1, 0.0, str(item.get("ts_code") or ""))
        return (0, -value if descending else value, str(item.get("ts_code") or ""))

    items.sort(key=sort_key)


@api_view(["GET"])
def pick_stocks_by_financial_performance(request, trade_date, scope):
    try:
        fiscal_year = int(str(request.query_params.get("fiscal_year") or "").strip())
    except (TypeError, ValueError):
        return Response({"error": "fiscal_year must be a four-digit year"}, status=400)
    report_type = str(request.query_params.get("report_type") or "").strip().upper()
    if report_type not in {"Q1", "H1", "Q3", "FY"}:
        return Response({"error": "report_type must be Q1, H1, Q3, or FY"}, status=400)

    candidate_rows = _financial_screening_candidate_rows(
        request,
        scope,
        request.query_params.get("sw_industry"),
    )
    candidate_map = {str(row["ts_code"]).upper(): row for row in candidate_rows}
    website_map = {
        str(row.ts_code or "").upper(): {
            "website": str(row.website or ""),
            "website_url": _normalize_company_website_url(row.website),
        }
        for row in CorporationBasic.objects.filter(ts_code__in=list(candidate_map))
    }
    filters = {
        key: request.query_params.get(key)
        for key in (
            "min_ebit_yoy_pct", "min_ebit_qoq_pct", "min_revenue_yoy_pct",
            "min_revenue_qoq_pct", "min_netprofit_yoy_pct", "min_netprofit_qoq_pct",
            "min_roe_pct", "min_roe_dt_pct",
        )
        if str(request.query_params.get(key) or "").strip()
    }
    filters["require_all_metrics"] = str(
        request.query_params.get("require_all_metrics", "0")
    ).strip().lower() in {"1", "true", "yes", "on"}
    payload = {
        "candidate_codes": list(candidate_map),
        "fiscal_year": fiscal_year,
        "report_type": report_type,
        "filters": filters,
        "sort": {
            "by": str(request.query_params.get("sort_by") or "financial_score"),
            "order": str(request.query_params.get("sort_order") or "desc"),
        },
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        upstream_request = urllib_request.Request(
            f"{_financial_screening_service_url()}/api/v1/financial-screening/screen",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(upstream_request, timeout=20) as upstream_response:
            upstream_payload = json.loads(upstream_response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return Response({"error": f"financial screening service unavailable: {exc}"}, status=502)
    service_data = upstream_payload.get("data") if isinstance(upstream_payload, dict) else {}
    items = service_data.get("items") if isinstance(service_data, dict) else []
    enriched = []
    for item in items if isinstance(items, list) else []:
        code = str(item.get("ts_code") or "").upper()
        corporation = candidate_map.get(code) or {}
        website = website_map.get(code) or {}
        enriched.append({
            **item,
            "name": corporation.get("name") or code,
            "sw_l3_code": corporation.get("sw_l3_code"),
            "sw_l3_name": corporation.get("sw_l3_name"),
            "website": website.get("website") or "",
            "website_url": website.get("website_url"),
        })
    _attach_financial_screening_valuation_results(enriched, trade_date, report_type)
    _sort_financial_screening_results(
        enriched,
        request.query_params.get("sort_by"),
        request.query_params.get("sort_order"),
    )
    return Response({
        "data": enriched,
        "total": len(enriched),
        "meta": {
            "trade_date": str(trade_date),
            "fiscal_year": fiscal_year,
            "report_type": report_type,
            "scope": str(scope),
            "sw_industry": str(request.query_params.get("sw_industry") or ""),
        },
    })


WEEKLY_UNDERVALUED_FILE_PREFIX = {
    "traditional": "traditional_undervalued_",
    "predictive": "predictive_undervalued_",
}

WEEKLY_UNDERVALUED_JOB_CONFIG_FILE = "job_strategy_config.json"
WEEKLY_STRATEGY_STYLE_KEYS = ("CONSERVATIVE", "BALANCED", "AGGRESSIVE")
VALUATION_PICK_CACHE_TTL_SECONDS = 90
VALUATION_PICK_JOB_CACHE_TTL_SECONDS = 1800
VALUATION_PICK_JOB_POLL_INTERVAL_SECONDS = 3
VALUATION_PICK_JOB_PREVIEW_SCAN_STEPS = (80, 300)


def _build_valuation_pick_cache_key(payload):
    normalized_payload = payload if isinstance(payload, dict) else {}
    encoded = json.dumps(
        normalized_payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.md5(encoded.encode("utf-8")).hexdigest()
    return f"valuation_pick:v1:{digest}"


def _normalize_weekly_strategy_style(value, default_style="BALANCED"):
    style = str(value or "").strip().upper()
    if style not in WEEKLY_STRATEGY_STYLE_KEYS:
        return default_style if default_style in WEEKLY_STRATEGY_STYLE_KEYS else "BALANCED"
    return style


def _normalize_weekly_market_style(payload):
    raw = payload if isinstance(payload, dict) else {}
    mode = str(raw.get("mode") or "manual").strip().lower()
    if mode not in {"manual", "auto"}:
        mode = "manual"
    default_style = _normalize_weekly_strategy_style(raw.get("default_style"), "BALANCED")
    current_style = _normalize_weekly_strategy_style(raw.get("current_style"), default_style)
    return {
        "mode": mode,
        "default_style": default_style,
        "current_style": current_style,
    }


def _normalize_weekly_style_entry(entry_payload):
    if not isinstance(entry_payload, dict):
        return None
    out = {
        "strategy_name": str(entry_payload.get("strategy_name") or "").strip(),
        "source_run_id": entry_payload.get("source_run_id"),
        "run_key": str(entry_payload.get("run_key") or "").strip(),
        "saved_at_utc": str(entry_payload.get("saved_at_utc") or "").strip(),
        "job": entry_payload.get("job") if isinstance(entry_payload.get("job"), dict) else {},
        "quick_profiles": entry_payload.get("quick_profiles") if isinstance(entry_payload.get("quick_profiles"), dict) else {},
        "metrics": entry_payload.get("metrics") if isinstance(entry_payload.get("metrics"), dict) else {},
        "score": _to_float_or_none(entry_payload.get("score")),
        "compare": entry_payload.get("compare") if isinstance(entry_payload.get("compare"), dict) else {},
    }
    return out


def _resolve_weekly_undervalued_file_stem(kind, style=None):
    normalized_kind = str(kind or "").strip().lower()
    prefix = WEEKLY_UNDERVALUED_FILE_PREFIX.get(normalized_kind)
    if not prefix:
        return None
    if style is None or str(style or "").strip() == "":
        return prefix
    normalized_style = _normalize_weekly_strategy_style(style)
    return f"{prefix}{normalized_style.lower()}"


def _resolve_weekly_undervalued_job_config_path():
    base_dir = _resolve_weekly_undervalued_output_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / WEEKLY_UNDERVALUED_JOB_CONFIG_FILE


def _default_weekly_undervalued_job_config():
    default_min_signal = float(
        getattr(settings, "PREDICTIVE_UNDERVALUED_MIN_SIGNAL_SCORE_DEFAULT", 100) or 100
    )
    return {
        "job": {
            "scope": "60,00,30,68",
            "freq": "D",
            "valuation_band_pct": 0.1,
            "pick_strategy": "baseline",
            "min_target_return_pct": 0.0,
            "min_signal_score": default_min_signal,
            "predictive_buy_signal_only": "PBS:NONE",
            "buy_candidate_only": "BC:ONLY",
            "risk_level": ["LOW", "MEDIUM"],
            "traditional_min_signal_score": 85.0,
            "traditional_risk_level": ["LOW", "MEDIUM"],
        },
        "quick_profiles": {
            "traditional": {
                "picking_mode": "MODE:BASELINE",
                "earnings_report_type": "ERT:ALL",
                "valuation_method": "VM:RECOMMENDED",
                "valuation_status": "VS:UNDER",
                "valuation_band_pct": "0.1",
                "valuation_pick_strategy": "VPS:BASELINE",
                "buy_candidate_only": "BC:ONLY",
                "risk_level": ["LOW", "MEDIUM"],
                "netprofit_growth": "NPG:HIGH",
                "min_signal_score": "85",
                "signal_action": "SA:ALL",
                "min_target_return_pct": "",
                "feature_data_source": "EDS:ALL",
                "fiscal_year": "",
            },
            "predictive": {
                "picking_mode": "MODE:PREDICTIVE",
                "earnings_report_type": "ERT:FUSION",
                "valuation_method": "VM:RECOMMENDED",
                "valuation_status": "VS:UNDER",
                "valuation_band_pct": "0.1",
                "valuation_pick_strategy": "VPS:BASELINE",
                "buy_candidate_only": "BC:ONLY",
                "risk_level": ["LOW", "MEDIUM"],
                "netprofit_growth": "NPG:ALL",
                "min_signal_score": "85",
                "signal_action": "SA:BUY",
                "min_target_return_pct": "",
                "feature_data_source": "EDS:ALL",
                "fiscal_year": "",
            },
        },
        "market_style": {
            "mode": "manual",
            "default_style": "BALANCED",
            "current_style": "BALANCED",
        },
        "weekly_style_strategies": {
            "CONSERVATIVE": None,
            "BALANCED": None,
            "AGGRESSIVE": None,
        },
    }


def _normalize_weekly_undervalued_job_config(payload):
    defaults = _default_weekly_undervalued_job_config()
    incoming = payload if isinstance(payload, dict) else {}

    incoming_job = incoming.get("job") if isinstance(incoming.get("job"), dict) else {}
    merged_job = {**defaults["job"], **incoming_job}

    scope = str(merged_job.get("scope") or defaults["job"]["scope"]).strip().upper() or defaults["job"]["scope"]
    freq = str(merged_job.get("freq") or defaults["job"]["freq"]).strip().upper() or defaults["job"]["freq"]
    if freq not in {"D", "W", "M"}:
        freq = defaults["job"]["freq"]

    try:
        valuation_band_pct = float(merged_job.get("valuation_band_pct"))
    except (TypeError, ValueError):
        valuation_band_pct = float(defaults["job"]["valuation_band_pct"])
    valuation_band_pct = max(0.01, min(0.5, valuation_band_pct))

    pick_strategy = _normalize_pick_strategy(merged_job.get("pick_strategy"))

    try:
        min_target_return_pct = float(merged_job.get("min_target_return_pct"))
    except (TypeError, ValueError):
        min_target_return_pct = float(defaults["job"]["min_target_return_pct"])

    try:
        min_signal_score = float(merged_job.get("min_signal_score"))
    except (TypeError, ValueError):
        min_signal_score = float(defaults["job"]["min_signal_score"])

    try:
        traditional_min_signal_score = float(merged_job.get("traditional_min_signal_score"))
    except (TypeError, ValueError):
        traditional_min_signal_score = float(defaults["job"].get("traditional_min_signal_score", 85.0))

    risk_level_job_value = merged_job.get("risk_level")
    if isinstance(risk_level_job_value, list):
        risk_level_job = [
            str(item).strip().upper()
            for item in risk_level_job_value
            if str(item).strip().upper() in {"LOW", "MEDIUM", "HIGH"}
        ]
    elif isinstance(risk_level_job_value, str):
        risk_level_job = [
            item.strip().upper()
            for item in risk_level_job_value.split(",")
            if item.strip().upper() in {"LOW", "MEDIUM", "HIGH"}
        ]
    else:
        risk_level_job = list(defaults["job"].get("risk_level") or [])

    traditional_risk_level_value = merged_job.get("traditional_risk_level")
    if isinstance(traditional_risk_level_value, list):
        traditional_risk_level = [
            str(item).strip().upper()
            for item in traditional_risk_level_value
            if str(item).strip().upper() in {"LOW", "MEDIUM", "HIGH"}
        ]
    elif isinstance(traditional_risk_level_value, str):
        traditional_risk_level = [
            item.strip().upper()
            for item in traditional_risk_level_value.split(",")
            if item.strip().upper() in {"LOW", "MEDIUM", "HIGH"}
        ]
    else:
        traditional_risk_level = list(defaults["job"].get("traditional_risk_level") or [])

    quick_profiles_payload = incoming.get("quick_profiles") if isinstance(incoming.get("quick_profiles"), dict) else {}
    normalized_quick_profiles = {}
    for key in ["traditional", "predictive"]:
        profile_default = defaults["quick_profiles"][key]
        profile_incoming = quick_profiles_payload.get(key) if isinstance(quick_profiles_payload.get(key), dict) else {}
        merged_profile = {**profile_default, **profile_incoming}

        risk_level_value = merged_profile.get("risk_level")
        if isinstance(risk_level_value, list):
            risk_level = [
                str(item).strip().upper()
                for item in risk_level_value
                if str(item).strip().upper() in {"LOW", "MEDIUM", "HIGH"}
            ]
        elif isinstance(risk_level_value, str):
            risk_level = [
                item.strip().upper()
                for item in risk_level_value.split(",")
                if item.strip().upper() in {"LOW", "MEDIUM", "HIGH"}
            ]
        else:
            risk_level = list(profile_default.get("risk_level") or [])

        normalized_quick_profiles[key] = {
            "picking_mode": str(merged_profile.get("picking_mode") or profile_default["picking_mode"]),
            "earnings_report_type": str(merged_profile.get("earnings_report_type") or profile_default["earnings_report_type"]),
            "valuation_method": str(merged_profile.get("valuation_method") or profile_default["valuation_method"]),
            "valuation_status": str(merged_profile.get("valuation_status") or profile_default["valuation_status"]),
            "valuation_band_pct": str(merged_profile.get("valuation_band_pct") or profile_default["valuation_band_pct"]),
            "valuation_pick_strategy": str(merged_profile.get("valuation_pick_strategy") or profile_default["valuation_pick_strategy"]),
            "buy_candidate_only": str(merged_profile.get("buy_candidate_only") or profile_default["buy_candidate_only"]),
            "risk_level": risk_level,
            "netprofit_growth": str(merged_profile.get("netprofit_growth") or profile_default["netprofit_growth"]),
            "min_signal_score": str(merged_profile.get("min_signal_score") or profile_default["min_signal_score"]),
            "signal_action": str(merged_profile.get("signal_action") or profile_default["signal_action"]),
            "min_target_return_pct": str(merged_profile.get("min_target_return_pct") or profile_default["min_target_return_pct"]),
            "feature_data_source": str(merged_profile.get("feature_data_source") or profile_default["feature_data_source"]),
            "fiscal_year": str(merged_profile.get("fiscal_year") or profile_default["fiscal_year"]),
        }

    normalized = {
        "job": {
            "scope": scope,
            "freq": freq,
            "valuation_band_pct": round(float(valuation_band_pct), 4),
            "pick_strategy": pick_strategy,
            "min_target_return_pct": round(float(min_target_return_pct), 4),
            "min_signal_score": round(float(min_signal_score), 4),
            "predictive_buy_signal_only": str(merged_job.get("predictive_buy_signal_only") or defaults["job"]["predictive_buy_signal_only"]),
            "buy_candidate_only": str(merged_job.get("buy_candidate_only") or defaults["job"]["buy_candidate_only"]),
            "risk_level": risk_level_job,
            "traditional_min_signal_score": round(float(traditional_min_signal_score), 4),
            "traditional_risk_level": traditional_risk_level,
        },
        "quick_profiles": normalized_quick_profiles,
        "market_style": _normalize_weekly_market_style(incoming.get("market_style")),
        "weekly_style_strategies": {
            style_key: _normalize_weekly_style_entry(
                (incoming.get("weekly_style_strategies") or {}).get(style_key)
                if isinstance(incoming.get("weekly_style_strategies"), dict)
                else None
            )
            for style_key in WEEKLY_STRATEGY_STYLE_KEYS
        },
    }
    return normalized


def _resolve_effective_weekly_job_config(config_payload, requested_style=None):
    normalized = _normalize_weekly_undervalued_job_config(config_payload)
    market_style = normalized.get("market_style") if isinstance(normalized.get("market_style"), dict) else {}
    default_style = _normalize_weekly_strategy_style(market_style.get("default_style"), "BALANCED")
    selected_style = _normalize_weekly_strategy_style(
        requested_style if requested_style not in (None, "") else market_style.get("current_style"),
        default_style,
    )

    style_map = normalized.get("weekly_style_strategies") if isinstance(normalized.get("weekly_style_strategies"), dict) else {}
    style_entry = style_map.get(selected_style) if isinstance(style_map.get(selected_style), dict) else None

    source_payload = {
        "job": style_entry.get("job") if isinstance(style_entry, dict) else normalized.get("job"),
        "quick_profiles": style_entry.get("quick_profiles") if isinstance(style_entry, dict) else normalized.get("quick_profiles"),
    }
    effective = _normalize_weekly_undervalued_job_config(source_payload)
    return {
        "style": selected_style,
        "job": effective.get("job") or {},
        "quick_profiles": effective.get("quick_profiles") or {},
        "style_strategy": style_entry,
        "config": normalized,
    }


def _load_weekly_undervalued_job_config():
    path = _resolve_weekly_undervalued_job_config_path()
    if not path.exists():
        normalized = _save_weekly_undervalued_job_config({})
        return normalized

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _normalize_weekly_undervalued_job_config({})

    return _normalize_weekly_undervalued_job_config(raw)


def _save_weekly_undervalued_job_config(payload):
    normalized = _normalize_weekly_undervalued_job_config(payload)
    path = _resolve_weekly_undervalued_job_config_path()
    wrapped = {
        **normalized,
        "updated_at_utc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    path.write_text(json.dumps(wrapped, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def _resolve_weekly_undervalued_output_dir():
    return Path(settings.BASE_DIR) / "output" / "weekly_undervalued"


def _get_latest_weekly_undervalued_file(kind, style=None):
    prefix = _resolve_weekly_undervalued_file_stem(kind, style)
    if not prefix:
        return None

    base_dir = _resolve_weekly_undervalued_output_dir()
    if not base_dir.exists():
        return None

    candidates = [
        path for path in base_dir.glob(f"{prefix}*.csv")
        if path.is_file()
    ]
    if not candidates:
        return None

    if style is None or str(style or "").strip() == "":
        dated_pattern = re.compile(rf"^{re.escape(prefix)}\d{{4}}-\d{{2}}-\d{{2}}\.csv$", re.IGNORECASE)
    else:
        dated_pattern = re.compile(rf"^{re.escape(prefix)}_\d{{4}}-\d{{2}}-\d{{2}}\.csv$", re.IGNORECASE)
    dated_candidates = [path for path in candidates if dated_pattern.match(path.name)]
    if dated_candidates:
        return max(dated_candidates, key=lambda item: item.stat().st_mtime)

    if not candidates and style is not None and str(style or "").strip() != "":
        return _get_latest_weekly_undervalued_file(kind, style=None)

    return max(candidates, key=lambda item: item.stat().st_mtime)


def _list_weekly_undervalued_dates(kind, style=None):
    prefix = _resolve_weekly_undervalued_file_stem(kind, style)
    if not prefix:
        return []

    base_dir = _resolve_weekly_undervalued_output_dir()
    if not base_dir.exists():
        return []

    candidates = [
        path for path in base_dir.glob(f"{prefix}*.csv")
        if path.is_file()
    ]
    if not candidates:
        if style is not None and str(style or "").strip() != "":
            return _list_weekly_undervalued_dates(kind, style=None)
        return []

    if style is None or str(style or "").strip() == "":
        pattern = re.compile(rf"^{re.escape(prefix)}(\d{{4}}-\d{{2}}-\d{{2}})\.csv$", re.IGNORECASE)
    else:
        pattern = re.compile(rf"^{re.escape(prefix)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$", re.IGNORECASE)
    dated = []
    for path in candidates:
        match = pattern.match(path.name)
        if match:
            dated.append(match.group(1))
    return sorted(set(dated), reverse=True)


def _resolve_weekly_undervalued_file_by_date(kind, pick_date=None, style=None):
    prefix = _resolve_weekly_undervalued_file_stem(kind, style)
    if not prefix:
        return None

    if pick_date:
        parsed = _parse_date_like(pick_date)
        if parsed is not None:
            if style is None or str(style or "").strip() == "":
                candidate_name = f"{prefix}{parsed.strftime('%Y-%m-%d')}.csv"
            else:
                candidate_name = f"{prefix}_{parsed.strftime('%Y-%m-%d')}.csv"
            candidate = _resolve_weekly_undervalued_output_dir() / candidate_name
            if candidate.exists() and candidate.is_file():
                return candidate

            if style is not None and str(style or "").strip() != "":
                return _get_latest_weekly_undervalued_file(kind, style=style)

    return _get_latest_weekly_undervalued_file(kind, style=style)


def _load_weekly_undervalued_rows(kind, pick_date=None, style=None):
    file_path = _resolve_weekly_undervalued_file_by_date(kind, pick_date, style=style)
    if file_path is None:
        return [], None

    rows = []
    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts_code = str(row.get("tscode") or "").strip().upper()
                if not ts_code:
                    continue
                rows.append(
                    {
                        "ts_code": ts_code,
                        "name": str(row.get("stock_name") or "").strip(),
                        "close_qfq": _to_float_or_none(row.get("close_price")),
                        "conservative_valuation": _to_float_or_none(row.get("conservative_valuation")),
                        "composite_valuation": _to_float_or_none(row.get("composite_valuation")),
                        "undervalue_score": _to_float_or_none(row.get("undervalue_score") or row.get("valuation_score")),
                        "valuation_score": _to_float_or_none(row.get("valuation_score") or row.get("undervalue_score")),
                        "source_kind": str(kind or "").strip().lower() or "traditional",
                        "report_end_date": str(row.get("report_end_date") or "").strip(),
                        "trade_date": str(row.get("trade_date") or "").strip(),
                        "target_return_pct": _to_float_or_none(row.get("target_return_pct")),
                        "is_express": int(_to_float_or_none(row.get("is_express")) or 0),
                        "profit_data_source": str(row.get("profit_data_source") or "").strip(),
                    }
                )
    except Exception:
        return [], None

    return rows, file_path


LIVE_VALUATION_BUSINESS_MATCH_TOPN = int(getattr(settings, "LIVE_VALUATION_BUSINESS_MATCH_TOPN", 0) or 0)
LIVE_VALUATION_PICK_STRATEGY = str(getattr(settings, "LIVE_VALUATION_PICK_STRATEGY", "baseline") or "baseline").strip().lower()
MAX_VALUATION_CANDIDATES_IN_RESPONSE = int(getattr(settings, "MAX_VALUATION_CANDIDATES_IN_RESPONSE", 3) or 3)
LIVE_VALUATION_RISK_USE_PERSISTED_FIRST = bool(
    getattr(settings, "LIVE_VALUATION_RISK_USE_PERSISTED_FIRST", True)
)
LIVE_VALUATION_SUMMARY_USE_PERSISTED_FIRST = bool(
    getattr(settings, "LIVE_VALUATION_SUMMARY_USE_PERSISTED_FIRST", True)
)
PREDICTIVE_UNDERVALUED_MIN_SIGNAL_SCORE_DEFAULT = float(
    getattr(settings, "PREDICTIVE_UNDERVALUED_MIN_SIGNAL_SCORE_DEFAULT", 100) or 100
)
RECENT_FINANCIAL_ANNOUNCEMENT_DAYS = int(
    getattr(settings, "RECENT_FINANCIAL_ANNOUNCEMENT_DAYS", 45) or 45
)
VALUATION_SHARE_CHANGE_IMPACT_THRESHOLD = float(
    getattr(settings, "VALUATION_SHARE_CHANGE_IMPACT_THRESHOLD", 0.1) or 0.1
)
PREDICTIVE_RETURN_OPTIMIZATION_ENABLED = str(
    getattr(settings, "PREDICTIVE_RETURN_OPTIMIZATION_ENABLED", "1")
).strip().lower() in {"1", "true", "yes", "on"}
PREDICTIVE_RETURN_ROBUSTNESS_ENABLED = str(
    getattr(settings, "PREDICTIVE_RETURN_ROBUSTNESS_ENABLED", "1")
).strip().lower() in {"1", "true", "yes", "on"}
PREDICTIVE_RETURN_CALIBRATION_ENABLED = str(
    getattr(settings, "PREDICTIVE_RETURN_CALIBRATION_ENABLED", "1")
).strip().lower() in {"1", "true", "yes", "on"}
PREDICTIVE_RETURN_MIN_PCT = float(getattr(settings, "PREDICTIVE_RETURN_MIN_PCT", -40.0) or -40.0)
PREDICTIVE_RETURN_MAX_PCT = float(getattr(settings, "PREDICTIVE_RETURN_MAX_PCT", 120.0) or 120.0)
PREDICTIVE_RETURN_DIVERGENCE_CAP_PCT = float(
    getattr(settings, "PREDICTIVE_RETURN_DIVERGENCE_CAP_PCT", 35.0) or 35.0
)
PREDICTIVE_RETURN_SHRINK_WEIGHT_MIN = float(
    getattr(settings, "PREDICTIVE_RETURN_SHRINK_WEIGHT_MIN", 0.35) or 0.35
)
PREDICTIVE_RETURN_SHRINK_WEIGHT_MAX = float(
    getattr(settings, "PREDICTIVE_RETURN_SHRINK_WEIGHT_MAX", 0.85) or 0.85
)
PREDICTIVE_RETURN_STALE_HALF_LIFE_DAYS = float(
    getattr(settings, "PREDICTIVE_RETURN_STALE_HALF_LIFE_DAYS", 180.0) or 180.0
)
PREDICTIVE_RETURN_CALIBRATION_BIAS = float(
    getattr(settings, "PREDICTIVE_RETURN_CALIBRATION_BIAS", 0.0) or 0.0
)
PREDICTIVE_RETURN_CALIBRATION_SLOPE = float(
    getattr(settings, "PREDICTIVE_RETURN_CALIBRATION_SLOPE", 0.85) or 0.85
)
TRADITIONAL_RETURN_OPTIMIZATION_ENABLED = str(
    getattr(settings, "TRADITIONAL_RETURN_OPTIMIZATION_ENABLED", "1")
).strip().lower() in {"1", "true", "yes", "on"}
TRADITIONAL_RETURN_CALIBRATION_ENABLED = str(
    getattr(settings, "TRADITIONAL_RETURN_CALIBRATION_ENABLED", "1")
).strip().lower() in {"1", "true", "yes", "on"}
TRADITIONAL_RETURN_MIN_PCT = float(getattr(settings, "TRADITIONAL_RETURN_MIN_PCT", -50.0) or -50.0)
TRADITIONAL_RETURN_MAX_PCT = float(getattr(settings, "TRADITIONAL_RETURN_MAX_PCT", 150.0) or 150.0)
TRADITIONAL_RETURN_DISPERSION_REF = float(
    getattr(settings, "TRADITIONAL_RETURN_DISPERSION_REF", 0.35) or 0.35
)
TRADITIONAL_RETURN_SHRINK_WEIGHT_MIN = float(
    getattr(settings, "TRADITIONAL_RETURN_SHRINK_WEIGHT_MIN", 0.35) or 0.35
)
TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX = float(
    getattr(settings, "TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX", 0.85) or 0.85
)
TRADITIONAL_RETURN_CALIBRATION_BIAS = float(
    getattr(settings, "TRADITIONAL_RETURN_CALIBRATION_BIAS", 0.0) or 0.0
)
TRADITIONAL_RETURN_CALIBRATION_SLOPE = float(
    getattr(settings, "TRADITIONAL_RETURN_CALIBRATION_SLOPE", 0.9) or 0.9
)


def _parse_optional_float(value, default=None):
    if value in (None, ""):
        return default
    return float(value)


def _parse_optional_float_list(value):
    if value in (None, ""):
        return None
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _sanitize_non_finite_numbers(payload):
    if isinstance(payload, dict):
        return {key: _sanitize_non_finite_numbers(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_sanitize_non_finite_numbers(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_sanitize_non_finite_numbers(item) for item in payload)
    if isinstance(payload, float) and (math.isnan(payload) or math.isinf(payload)):
        return None
    return payload


def _normalize_report_dates(report_end_date, report_ann_date):
    end_dt = _parse_date_like(report_end_date)
    ann_dt = _parse_date_like(report_ann_date)
    if end_dt is not None and ann_dt is not None and ann_dt < end_dt:
        # Announcement date cannot be earlier than period end; drop inconsistent value.
        ann_dt = None
    return end_dt, ann_dt


def _load_persisted_valuation_risk_payload(
    *,
    ts_code,
    market,
    valuation_variant,
    profit_report_type=None,
    trade_date=None,
):
    qs = ValuationRiskSnapshot.objects.filter(
        ts_code=ts_code,
        market=market,
        valuation_variant=valuation_variant or "default",
    )

    normalized_report_type = str(profit_report_type or "").strip().upper()
    if normalized_report_type:
        qs = qs.filter(profit_report_type=normalized_report_type)

    snapshot = None
    if trade_date is not None:
        snapshot = qs.filter(trade_date=trade_date).order_by("-updated_at").first()
    if snapshot is None:
        snapshot = qs.order_by("-trade_date", "-updated_at").first()
    if snapshot is None:
        return None

    factor_rows = list(
        snapshot.factors.order_by("sort_order", "id").values(
            "dimension",
            "factor_code",
            "factor_name",
            "severity",
            "factor_score",
            "factor_value",
            "threshold",
            "reason",
            "is_triggered",
            "payload",
        )
    )

    return {
        "ts_code": snapshot.ts_code,
        "market": snapshot.market,
        "trade_date": snapshot.trade_date,
        "valuation_variant": snapshot.valuation_variant,
        "profit_report_type": snapshot.profit_report_type,
        "profit_report_end_date": snapshot.profit_report_end_date,
        "profit_report_ann_date": snapshot.profit_report_ann_date,
        "profit_data_source": snapshot.profit_data_source,
        "risk_score": float(snapshot.risk_score) if snapshot.risk_score is not None else None,
        "risk_level": snapshot.risk_level,
        "confidence": float(snapshot.confidence) if snapshot.confidence is not None else None,
        "summary": snapshot.summary,
        "engine_version": snapshot.engine_version,
        "status": snapshot.status,
        "metadata": snapshot.metadata or {},
        "factors": factor_rows,
    }


def _load_persisted_variant_summary_payload(
    *,
    ts_code,
    market,
    valuation_variant,
    trade_date=None,
    profit_report_type=None,
    profit_report_end_date=None,
):
    qs = StockValuationVariantSummaryLatest.objects.filter(
        ts_code=ts_code,
        market=market,
        valuation_variant=valuation_variant or "default",
    )

    normalized_report_type = str(profit_report_type or "").strip().upper()
    if normalized_report_type == "FY":
        normalized_report_type = "ANNUAL"
    if normalized_report_type:
        qs = qs.filter(profit_report_type=normalized_report_type)

    report_end_dt = _parse_date_like(profit_report_end_date)
    if report_end_dt is not None:
        qs = qs.filter(profit_report_end_date=report_end_dt)

    snapshot = None
    if trade_date is not None:
        trade_dt = _parse_date_like(trade_date)
        if trade_dt is not None:
            snapshot = qs.filter(latest_trade_date=trade_dt).order_by("-updated_at").first()
    if snapshot is None:
        snapshot = qs.order_by("-latest_trade_date", "-updated_at").first()
    if snapshot is None:
        return None

    return {
        "composite_valuation_price": float(snapshot.composite_valuation_price)
        if snapshot.composite_valuation_price is not None
        else None,
        "conservative_valuation_price": float(snapshot.conservative_valuation_price)
        if snapshot.conservative_valuation_price is not None
        else None,
        "undervalue_score": float(snapshot.undervalue_score) if snapshot.undervalue_score is not None else None,
        "buy_candidate": bool(snapshot.buy_candidate),
        "buy_candidate_reason": snapshot.buy_candidate_reason or "",
        "buy_candidate_rule_version": snapshot.buy_candidate_rule_version or "",
        "valuation_valid_methods": list(snapshot.valuation_valid_methods or []),
        "valuation_under_methods": list(snapshot.valuation_under_methods or []),
        "valuation_core_methods": list(snapshot.valuation_core_methods or []),
        "summary_source": "persisted_variant_summary_latest",
    }


def _build_valuation_pick_job_cache_key(job_id):
    return f"valuation_pick_job:v1:{str(job_id or '').strip()}"


def _build_valuation_pick_active_job_cache_key(owner_key):
    return f"valuation_pick_job_active:v1:{str(owner_key or '').strip()}"


def _get_valuation_pick_job_state(job_id):
    cache_key = _build_valuation_pick_job_cache_key(job_id)
    try:
        cached = cache.get(cache_key)
    except Exception as cache_err:
        logger.debug("valuation pick job cache get failed: %s", cache_err)
        cached = None
    return cached if isinstance(cached, dict) else None


def _set_valuation_pick_job_state(job_id, payload):
    cache_key = _build_valuation_pick_job_cache_key(job_id)
    data = dict(payload or {})
    data["job_id"] = str(job_id or "")
    data["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        cache.set(cache_key, data, timeout=VALUATION_PICK_JOB_CACHE_TTL_SECONDS)
    except Exception as cache_err:
        logger.debug("valuation pick job cache set failed: %s", cache_err)
    return data


def _resolve_valuation_pick_job_owner(request):
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return f"user:{getattr(user, 'id', '')}"

    fallback_user = User.get_admin_user()
    if fallback_user is not None and getattr(fallback_user, "id", None) is not None:
        return f"user:{fallback_user.id}"
    return "user:anonymous"


def _get_valuation_pick_active_job_id(owner_key):
    cache_key = _build_valuation_pick_active_job_cache_key(owner_key)
    try:
        value = cache.get(cache_key)
    except Exception as cache_err:
        logger.debug("valuation pick active job cache get failed: %s", cache_err)
        value = None
    return str(value).strip() if value else ""


def _set_valuation_pick_active_job_id(owner_key, job_id):
    cache_key = _build_valuation_pick_active_job_cache_key(owner_key)
    try:
        cache.set(cache_key, str(job_id or "").strip(), timeout=VALUATION_PICK_JOB_CACHE_TTL_SECONDS)
    except Exception as cache_err:
        logger.debug("valuation pick active job cache set failed: %s", cache_err)


def _clear_valuation_pick_active_job_id(owner_key, job_id):
    cache_key = _build_valuation_pick_active_job_cache_key(owner_key)
    try:
        active_job_id = cache.get(cache_key)
    except Exception as cache_err:
        logger.debug("valuation pick active job cache clear read failed: %s", cache_err)
        active_job_id = None

    if str(active_job_id or "").strip() != str(job_id or "").strip():
        return

    try:
        cache.delete(cache_key)
    except Exception as cache_err:
        logger.debug("valuation pick active job cache clear delete failed: %s", cache_err)


def _is_valuation_pick_job_canceled(job_id):
    state = _get_valuation_pick_job_state(job_id)
    return isinstance(state, dict) and str(state.get("status") or "").strip().lower() == "canceled"


def _cancel_valuation_pick_job(job_id, message):
    state = _get_valuation_pick_job_state(job_id)
    if not isinstance(state, dict):
        return None

    status = str(state.get("status") or "").strip().lower()
    if status in {"done", "failed", "canceled"}:
        return state

    canceled_payload = dict(state)
    canceled_payload.update(
        {
            "status": "canceled",
            "has_more": False,
            "message": str(message or "任务已取消"),
            "poll_interval_seconds": VALUATION_PICK_JOB_POLL_INTERVAL_SECONDS,
        }
    )
    return _set_valuation_pick_job_state(job_id, canceled_payload)


def _resolve_active_variant_from_method_map(method_map, requested_variant=""):
    grouped_rows = {}
    variant_meta = {}
    for method, payload in (method_map or {}).items():
        normalized_method = _normalize_valuation_method_name(method)
        if not normalized_method:
            continue
        variant = _normalize_valuation_variant(
            (payload or {}).get("valuation_variant"),
            fallback="default",
        )
        row = {
            "valuation_method": normalized_method,
            "valuation_variant": variant,
            "valuation_price": (payload or {}).get("valuation_price"),
            "latest_trade_date": (payload or {}).get("latest_trade_date"),
            "profit_report_end_date": (payload or {}).get("profit_report_end_date"),
            "profit_report_type": (payload or {}).get("profit_report_type"),
            "profit_report_ann_date": (payload or {}).get("profit_report_ann_date"),
            "profit_data_source": (payload or {}).get("profit_data_source"),
            "compare_group": (payload or {}).get("compare_group"),
            "match_score": (payload or {}).get("match_score"),
            "industry_level": (payload or {}).get("industry_level"),
            "industry_code": (payload or {}).get("industry_code"),
            "industry_name": (payload or {}).get("industry_name"),
        }
        grouped_rows.setdefault(variant, []).append(row)
        meta = variant_meta.setdefault(
            variant,
            {
                "valuation_variant": variant,
                "compare_group": (payload or {}).get("compare_group"),
                "industry_level": (payload or {}).get("industry_level"),
                "industry_code": (payload or {}).get("industry_code"),
                "industry_name": (payload or {}).get("industry_name"),
                "max_match_score": None,
            },
        )
        score = _to_float_or_none((payload or {}).get("match_score"))
        if score is not None and (meta.get("max_match_score") is None or score > meta.get("max_match_score")):
            meta["max_match_score"] = score

    normalized_requested_variant = _normalize_valuation_variant(requested_variant, fallback="")
    if normalized_requested_variant and normalized_requested_variant in grouped_rows:
        return normalized_requested_variant, grouped_rows, variant_meta

    def _variant_sort_key(meta):
        variant = str(meta.get("valuation_variant") or "")
        compare_group = str(meta.get("compare_group") or "")
        score = meta.get("max_match_score")
        if score is None:
            score = -1e9
        if compare_group == "sw_l3_baseline":
            group_rank = 0
        elif compare_group == "business_match":
            group_rank = 1
        elif variant == "default":
            group_rank = 2
        else:
            group_rank = 3
        return (group_rank, -float(score), variant)

    if not variant_meta:
        return "default", grouped_rows, variant_meta
    active_variant = sorted(variant_meta.values(), key=_variant_sort_key)[0].get("valuation_variant") or "default"
    return active_variant, grouped_rows, variant_meta


def _build_strict_summary_from_method_map(
    *,
    ts_code,
    market,
    current_price,
    method_map,
    band_pct,
    trade_date=None,
    requested_variant="",
    requested_report_type=None,
):
    active_variant, grouped_rows, _variant_meta = _resolve_active_variant_from_method_map(
        method_map,
        requested_variant=requested_variant,
    )
    variant_rows = list(grouped_rows.get(active_variant) or [])
    if not variant_rows:
        return None

    normalized_report_type = _normalize_valuation_profit_report_type(requested_report_type)
    filtered_rows = []
    for row in variant_rows:
        row_report_type = _normalize_valuation_profit_report_type(row.get("profit_report_type"))
        if normalized_report_type and row_report_type != normalized_report_type:
            continue
        filtered_rows.append(row)
    if not filtered_rows:
        filtered_rows = variant_rows

    report_end_dates = [
        _parse_date_like((row or {}).get("profit_report_end_date"))
        for row in filtered_rows
        if _parse_date_like((row or {}).get("profit_report_end_date")) is not None
    ]
    selected_report_end_date = max(report_end_dates) if report_end_dates else None
    if selected_report_end_date is not None:
        filtered_rows = [
            row for row in filtered_rows
            if _parse_date_like((row or {}).get("profit_report_end_date")) == selected_report_end_date
        ]

    persisted_summary_payload = _load_persisted_variant_summary_payload(
        ts_code=ts_code,
        market=market,
        valuation_variant=active_variant,
        trade_date=trade_date,
        profit_report_type=normalized_report_type,
        profit_report_end_date=selected_report_end_date,
    )
    summary_payload = persisted_summary_payload or _build_valuation_summary_payload(
        current_price,
        filtered_rows,
        band_pct,
        ts_code=ts_code,
    )
    summary_payload = dict(summary_payload or {})
    summary_payload["summary_mode"] = "single_variant_strict"
    summary_payload["summary_variant"] = active_variant
    summary_payload["summary_report_end_date"] = (
        selected_report_end_date.strftime("%Y-%m-%d")
        if selected_report_end_date is not None
        else None
    )
    if not summary_payload.get("summary_source"):
        summary_payload["summary_source"] = "strict_method_map"
    return summary_payload


def _build_valuation_pick_job_request(query_params):
    request = RequestFactory().get("/internal/stock-pick-valuation/job-run/", query_params)
    # Internal job runner uses a Django request; expose query_params for DRF-style readers.
    if not hasattr(request, "query_params"):
        request.query_params = request.GET
    return request


def _run_valuation_pick_job(job_id, payload):
    raw_payload = payload if isinstance(payload, dict) else {}
    trade_date = str(raw_payload.get("trade_date") or "").strip()
    scope = str(raw_payload.get("scope") or "").strip()
    query = raw_payload.get("query") if isinstance(raw_payload.get("query"), dict) else {}
    freq = str(query.get("freq") or raw_payload.get("freq") or "D").strip().upper() or "D"
    base_query = {str(key): str(value) for key, value in query.items() if value not in (None, "")}
    base_query["freq"] = freq
    base_query["from_index"] = "0"
    base_query["to_index"] = "25"

    owner_key = str(raw_payload.get("owner_key") or "").strip()

    try:
        if _is_valuation_pick_job_canceled(job_id):
            return

        _set_valuation_pick_job_state(
            job_id,
            {
                "status": "running",
                "progress_pct": 1,
                "processed_count": 0,
                "matched_count": 0,
                "total_candidates": None,
                "message": "任务已启动，正在生成预览结果",
                "data": [],
                "has_more": True,
                "poll_interval_seconds": VALUATION_PICK_JOB_POLL_INTERVAL_SECONDS,
            },
        )

        step_limits = list(VALUATION_PICK_JOB_PREVIEW_SCAN_STEPS) + [None]
        final_rows = []
        final_total = 0
        total_candidates = None
        for index, scan_limit in enumerate(step_limits):
            if _is_valuation_pick_job_canceled(job_id):
                return

            step_query = dict(base_query)
            if scan_limit is not None:
                step_query["scan_limit"] = str(scan_limit)
            elif "scan_limit" in step_query:
                step_query.pop("scan_limit", None)

            step_request = _build_valuation_pick_job_request(step_query)
            response = _pick_stocks_by_valuation_fast(
                request=step_request,
                trade_date=trade_date,
                scope=scope,
                freq=freq,
                from_index=0,
                to_index=25,
            )
            response_data = response.data if hasattr(response, "data") else {}
            rows = response_data.get("data") or []
            meta = response_data.get("meta") or {}
            final_rows = rows
            final_total = int(meta.get("total_filtered") or len(rows))
            total_candidates = meta.get("total_candidates")

            if _is_valuation_pick_job_canceled(job_id):
                return

            is_final_step = scan_limit is None
            progress_pct = 100 if is_final_step else min(95, int(((index + 1) / len(step_limits)) * 100))
            _set_valuation_pick_job_state(
                job_id,
                {
                    "status": "done" if is_final_step else "running",
                    "progress_pct": progress_pct,
                    "processed_count": int(scan_limit or total_candidates or final_total or len(rows)),
                    "matched_count": final_total,
                    "total_candidates": total_candidates,
                    "message": "结果已生成" if is_final_step else "正在扩展选股结果范围",
                    "data": final_rows,
                    "has_more": not is_final_step,
                    "poll_interval_seconds": VALUATION_PICK_JOB_POLL_INTERVAL_SECONDS,
                    "meta": meta,
                    "valuation_filter": response_data.get("valuation_filter") or {},
                    "trade_date": response_data.get("trade_date"),
                    "freq": response_data.get("freq"),
                },
            )
    except Exception as err:
        if _is_valuation_pick_job_canceled(job_id):
            return
        logger.exception("valuation pick job failed: %s", err)
        _set_valuation_pick_job_state(
            job_id,
            {
                "status": "failed",
                "progress_pct": 100,
                "processed_count": 0,
                "matched_count": 0,
                "total_candidates": None,
                "message": str(err),
                "data": [],
                "has_more": False,
                "poll_interval_seconds": VALUATION_PICK_JOB_POLL_INTERVAL_SECONDS,
            },
        )
    finally:
        if owner_key:
            _clear_valuation_pick_active_job_id(owner_key, job_id)


def _load_latest_indicator_profile(ts_code):
    try:
        df = fetch_tushare_data(ts_code, "INDICATOR")
    except Exception:
        return {}
    if df is None or df.empty:
        return {}

    profile = {}
    latest_row = None
    if "end_date" in df.columns:
        try:
            ranked = df.copy()
            ranked["_end_date"] = pd.to_datetime(ranked["end_date"], errors="coerce")
            ranked = ranked.sort_values(["_end_date"], ascending=[False])
            latest_row = ranked.iloc[0]
        except Exception:
            latest_row = df.iloc[0]
    else:
        latest_row = df.iloc[0]

    for field in [
        "debt_to_assets",
        "ca_to_assets",
        "ar_turn",
        "netprofit_margin",
        "roe",
        "roe_dt",
    ]:
        if field in df.columns:
            value = latest_row.get(field)
            if value is not None and not pd.isna(value):
                profile[field] = float(value)

    grossprofit_margin = None
    if "grossprofit_margin" in df.columns:
        value = latest_row.get("grossprofit_margin")
        if value is not None and not pd.isna(value):
            grossprofit_margin = float(value)
    if grossprofit_margin is None and "gross_margin" in df.columns:
        # Some data sources expose gross_margin as absolute amount instead of percentage.
        value = latest_row.get("gross_margin")
        if value is not None and not pd.isna(value):
            value = float(value)
            if -100.0 <= value <= 100.0:
                grossprofit_margin = value
    if grossprofit_margin is not None:
        profile["gross_margin"] = grossprofit_margin

    if "end_date" in df.columns:
        end_date = latest_row.get("end_date")
        if end_date is not None and not pd.isna(end_date):
            profile["indicator_end_date"] = str(end_date)

    history_map = {}
    if "end_date" in df.columns and "ebit" in df.columns:
        for _, history_row in df.iterrows():
            end_date = _parse_date_like(history_row.get("end_date"))
            ebit_value = _to_float_or_none(history_row.get("ebit"))
            if end_date is None or ebit_value is None:
                continue
            history_map[end_date] = ebit_value

    latest_ebit = None
    if "ebit" in df.columns:
        value = latest_row.get("ebit")
        if value is not None and not pd.isna(value):
            latest_ebit = float(value)
            profile["financial_ebit"] = latest_ebit

    if latest_ebit is not None and "end_date" in df.columns:
        latest_end_date = _parse_date_like(latest_row.get("end_date"))
        if latest_end_date is not None:
            compare_end_date = datetime.date(latest_end_date.year - 1, latest_end_date.month, latest_end_date.day)
            compare_ebit = history_map.get(compare_end_date)
            if compare_ebit is not None:
                profile["financial_prev_ebit"] = float(compare_ebit)
                if abs(float(compare_ebit)) > 1e-9:
                    profile["financial_ebit_yoy"] = (float(latest_ebit) - float(compare_ebit)) / abs(float(compare_ebit))
            profile["financial_ebit_end_date"] = str(latest_end_date)

    try:
        today = datetime.date.today()
        long_ago = today - datetime.timedelta(days=3650)
        bs_df = fetch_tushare_data(
            ts_code,
            "BALANCESHEET",
            start_date=long_ago,
            end_date=today,
        )
    except Exception:
        bs_df = None

    if bs_df is not None and not bs_df.empty:
        bs_latest = None
        if "end_date" in bs_df.columns:
            try:
                ranked = bs_df.copy()
                ranked["_end_date"] = pd.to_datetime(ranked["end_date"], errors="coerce")
                ranked = ranked.sort_values(["_end_date"], ascending=[False])
                bs_latest = ranked.iloc[0]
            except Exception:
                bs_latest = bs_df.iloc[0]
        else:
            bs_latest = bs_df.iloc[0]

        def _pick_float(series, field, default=0.0):
            if field not in bs_df.columns:
                return default
            value = series.get(field)
            if value is None or pd.isna(value):
                return default
            return float(value)

        total_assets = _pick_float(bs_latest, "total_assets", default=0.0)
        accounts_receiv = _pick_float(bs_latest, "accounts_receiv", default=0.0)
        notes_receiv = _pick_float(bs_latest, "notes_receiv", default=0.0)
        oth_receiv = _pick_float(bs_latest, "oth_receiv", default=0.0)
        inventories = _pick_float(bs_latest, "inventories", default=0.0)
        goodwill = _pick_float(bs_latest, "goodwill", default=0.0)

        if total_assets > 0:
            profile["ar_to_assets"] = ((accounts_receiv + notes_receiv + oth_receiv) / total_assets) * 100.0
            profile["inventory_to_assets"] = (inventories / total_assets) * 100.0
            profile["goodwill_to_assets"] = (goodwill / total_assets) * 100.0

        if "end_date" in bs_df.columns:
            bs_end_date = bs_latest.get("end_date")
            if bs_end_date is not None and not pd.isna(bs_end_date):
                profile["balance_end_date"] = str(bs_end_date)
    return profile


def _json_safe_records(df):
    if df is None:
        return None
    safe_df = df.copy()
    safe_df = safe_df.where(pd.notnull(safe_df), None)
    return safe_df.to_dict(orient="records")


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


VALUATION_METHOD_ALIAS_MAP = {
    "pe": {"pe"},
    "ps": {"ps"},
    "pb": {"pb"},
    "sw_history": {"sw_history", "sw_hist", "industry_history"},
    "peg": {"peg"},
    "fcff_dcf": {"fcff_dcf", "fcff"},
    "ddm": {"ddm"},
    "ev_ebitda": {"ev_ebitda"},
    "market_cap": {"market_cap"},
}


def _resolve_method_candidates(selected_method):
    normalized_selected = _normalize_valuation_method_name(selected_method)
    return normalized_selected, VALUATION_METHOD_ALIAS_MAP.get(
        normalized_selected,
        {normalized_selected},
    )


def _normalize_valuation_variant(value, fallback="default"):
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return fallback
    return text


def _extract_method_valuation(valuation_df, selected_method):
    if valuation_df is None or valuation_df.empty:
        return None, None, None

    normalized_selected, candidates = _resolve_method_candidates(selected_method)

    for _, row in valuation_df.iterrows():
        method = _normalize_valuation_method_name(row.get("method"))
        row_variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
        if normalized_selected != "sw_history" and row_variant != "default":
            continue
        if method in candidates:
            implied_price = row.get("implied_price")
            if implied_price is None or pd.isna(implied_price):
                return row.get("method"), None, None
            equity_value = row.get("equity_value")
            equity_value_float = None
            if equity_value is not None and not pd.isna(equity_value):
                equity_value_float = float(equity_value)
            return row.get("method"), float(implied_price), equity_value_float
    return None, None, None


def _build_valuation_variant(row):
    explicit_variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="")
    if explicit_variant:
        return explicit_variant[:128]

    compare_group = str(row.get("compare_group") or "").strip()
    industry_level = str(row.get("industry_level") or row.get("level") or "").strip()
    industry_code = str(row.get("industry_code") or "").strip()
    industry_name = str(row.get("industry_name") or "").strip()

    parts = [part for part in [compare_group, industry_level, industry_code, industry_name] if part]
    if not parts:
        return "default"

    variant = "|".join(parts)
    return variant[:128]


def _extract_method_valuation_rows(valuation_df, selected_method):
    if valuation_df is None or valuation_df.empty:
        return []

    normalized_selected, candidates = _resolve_method_candidates(selected_method)
    rows = []
    for _, row in valuation_df.iterrows():
        method = _normalize_valuation_method_name(row.get("method"))
        if method not in candidates:
            continue
        row_variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
        if normalized_selected != "sw_history" and row_variant != "default":
            continue

        implied_price = row.get("implied_price")
        if implied_price is None or pd.isna(implied_price):
            continue

        try:
            implied_price_float = float(implied_price)
        except (TypeError, ValueError):
            continue

        equity_value = row.get("equity_value")
        equity_value_float = None
        if equity_value is not None and not pd.isna(equity_value):
            try:
                equity_value_float = float(equity_value)
            except (TypeError, ValueError):
                equity_value_float = None

        match_score = row.get("match_score")
        if pd.isna(match_score):
            match_score = None

        rows.append(
            {
                "method": row.get("method"),
                "implied_price": implied_price_float,
                "equity_value": equity_value_float,
                "valuation_variant": _build_valuation_variant(row),
                "industry_level": row.get("industry_level") or row.get("level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
                "compare_group": row.get("compare_group"),
                "match_score": match_score,
            }
        )

    return rows


def _normalize_pick_strategy(strategy):
    normalized = str(strategy or LIVE_VALUATION_PICK_STRATEGY).strip().lower()
    allowed = {"baseline", "first", "best_score", "median", "min", "max"}
    if normalized not in allowed:
        return LIVE_VALUATION_PICK_STRATEGY if LIVE_VALUATION_PICK_STRATEGY in allowed else "baseline"
    return normalized


def _candidate_anchor_date(candidate):
    if not isinstance(candidate, dict):
        return None
    for field in [
        "profit_report_ann_date",
        "express_ann_date",
        "profit_report_end_date",
        "trade_date",
        "latest_trade_date",
    ]:
        value = _parse_date_like(candidate.get(field))
        if value is not None:
            return value
    return None


def _compute_candidate_staleness_days(candidate, asof_date=None):
    normalized_asof_date = _parse_date_like(asof_date)
    anchor_date = _candidate_anchor_date(candidate)
    if normalized_asof_date is None or anchor_date is None:
        return None
    return max(0, (normalized_asof_date - anchor_date).days)


def _compute_candidate_dispersion_pct(candidates):
    prices = []
    for row in candidates or []:
        price = _to_float_or_none((row or {}).get("valuation_price") or (row or {}).get("implied_price"))
        if price is not None and price > 0:
            prices.append(float(price))
    if len(prices) < 2:
        return 0.0
    median_price = float(pd.Series(prices, dtype="float64").median())
    if median_price <= 0:
        return 0.0
    return max(0.0, (max(prices) - min(prices)) / median_price)


def _score_valuation_candidate(candidate, candidates, asof_date=None):
    price = _to_float_or_none((candidate or {}).get("valuation_price") or (candidate or {}).get("implied_price"))
    if price is None or price <= 0:
        return -999999.0

    candidate_count = max(1, len(candidates or []))
    match_score = _to_float_or_none((candidate or {}).get("match_score"))
    compare_group = str((candidate or {}).get("compare_group") or "").strip().lower()
    staleness_days = _compute_candidate_staleness_days(candidate, asof_date=asof_date)
    dispersion_pct = _compute_candidate_dispersion_pct(candidates)

    valid_prices = [
        _to_float_or_none((row or {}).get("valuation_price") or (row or {}).get("implied_price"))
        for row in (candidates or [])
    ]
    valid_prices = [float(item) for item in valid_prices if item is not None and item > 0]
    median_price = float(pd.Series(valid_prices, dtype="float64").median()) if valid_prices else price
    relative_deviation = abs(price - median_price) / median_price if median_price and median_price > 0 else 0.0

    score = 0.0
    if compare_group == "sw_l3_baseline":
        score += 0.22
    elif compare_group == "business_match":
        score += 0.12

    if match_score is not None:
        score += max(0.0, min(0.28, float(match_score) / 100.0 * 0.28))

    if staleness_days is None:
        score += 0.03
    elif staleness_days <= 45:
        score += 0.22
    elif staleness_days <= 90:
        score += 0.15
    elif staleness_days <= 180:
        score += 0.05
    elif staleness_days <= 270:
        score -= 0.08
    else:
        score -= 0.18

    score += max(0.0, 0.18 * (1.0 - min(relative_deviation, 1.0)))
    score -= min(0.18, dispersion_pct * 0.16)
    score += min(0.1, candidate_count * 0.03)
    return score


def _build_candidate_quality_payload(selected_candidate, candidates, asof_date=None):
    if not isinstance(selected_candidate, dict):
        return {
            "valuation_staleness_days": None,
            "valuation_candidate_spread_pct": None,
            "valuation_confidence": None,
        }

    dispersion_pct = _compute_candidate_dispersion_pct(candidates)
    staleness_days = _compute_candidate_staleness_days(selected_candidate, asof_date=asof_date)
    match_score = _to_float_or_none(selected_candidate.get("match_score"))
    candidate_count = max(1, len(candidates or []))
    confidence = 62.0
    confidence += min(12.0, candidate_count * 3.0)
    confidence -= min(24.0, dispersion_pct * 30.0)
    if staleness_days is not None:
        confidence -= min(24.0, max(0.0, staleness_days - 45) / 8.0)
    if match_score is not None:
        confidence += min(12.0, max(0.0, match_score) / 10.0)
    if str(selected_candidate.get("compare_group") or "").strip().lower() == "sw_l3_baseline":
        confidence += 5.0

    return {
        "valuation_staleness_days": staleness_days,
        "valuation_candidate_spread_pct": round(dispersion_pct * 100.0, 2) if dispersion_pct is not None else None,
        "valuation_confidence": int(max(20, min(95, round(confidence)))),
    }


def _select_valuation_candidate(candidates, pick_strategy, asof_date=None):
    if not candidates:
        return None

    strategy = _normalize_pick_strategy(pick_strategy)
    if strategy == "first":
        return candidates[0]
    if strategy == "best_score":
        scored = [row for row in candidates if row.get("match_score") is not None]
        return max(scored, key=lambda row: float(row.get("match_score", 0))) if scored else candidates[0]
    if strategy == "min":
        return min(candidates, key=lambda row: float(row.get("valuation_price") or 0))
    if strategy == "max":
        return max(candidates, key=lambda row: float(row.get("valuation_price") or 0))
    if strategy == "median":
        sorted_rows = sorted(candidates, key=lambda row: float(row.get("valuation_price") or 0))
        return sorted_rows[len(sorted_rows) // 2]

    return max(candidates, key=lambda row: _score_valuation_candidate(row, candidates, asof_date=asof_date))


def _build_live_valuation_contexts(ts_code, market="CN", business_match_topn=0):
    if business_match_topn <= 0:
        return [{"params": {}, "context": {}}]

    base_dir = Path(settings.BASE_DIR) / "static"
    contexts = []

    try:
        cfg = ValuationConfig(base_dir, market=market)
        sw_info = cfg.get_sw_params_by_tscode(ts_code)
        contexts.append(
            {
                "params": sw_info.get("params") or {},
                "context": {
                    "compare_group": "sw_l3_baseline",
                    "industry_level": sw_info.get("level"),
                    "industry_code": sw_info.get("industry_code"),
                    "industry_name": sw_info.get("industry_name"),
                    "match_score": None,
                },
            }
        )
    except Exception:
        pass

    try:
        matcher = BusinessIndustryMatcher(base_dir, market=market)
        matched_payload = matcher.match_by_tscode(ts_code=ts_code, top_n=business_match_topn, level="L2")
        cfg = ValuationConfig(base_dir, market=market)
        for match in (matched_payload or {}).get("matches", []):
            try:
                sw_info = cfg.get_sw_params_by_industry(
                    industry=match.get("industry_code"),
                    level=match.get("level"),
                    fuzzy=False,
                )
            except Exception:
                continue

            contexts.append(
                {
                    "params": sw_info.get("params") or {},
                    "context": {
                        "compare_group": "business_match",
                        "industry_level": match.get("level") or sw_info.get("level"),
                        "industry_code": match.get("industry_code") or sw_info.get("industry_code"),
                        "industry_name": match.get("industry_name") or sw_info.get("industry_name"),
                        "match_score": match.get("score"),
                    },
                }
            )
    except Exception:
        pass

    if not contexts:
        return [{"params": {}, "context": {}}]

    deduped = []
    seen_variants = set()
    for item in contexts:
        variant = _build_valuation_variant(item.get("context") or {})
        if variant in seen_variants:
            continue
        seen_variants.add(variant)
        item_context = item.get("context") or {}
        item_context["valuation_variant"] = variant
        deduped.append({"params": item.get("params") or {}, "context": item_context})
    return deduped


def _get_cached_method_price(ts_code, trade_date, selected_method, market="CN", pick_strategy="baseline"):
    normalized_selected, candidates = _resolve_method_candidates(selected_method)
    if not normalized_selected:
        return None, None, None, 0, []

    snapshots = StockValuationSnapshot.objects.filter(
        ts_code=ts_code,
        trade_date=trade_date,
        market=market,
    ).order_by("-updated_at")

    method_candidates = []
    for snapshot in snapshots:
        method = _normalize_valuation_method_name(snapshot.valuation_method)
        if method not in candidates or snapshot.valuation_price is None:
            continue
        method_candidates.append(
            {
                "method": method,
                "valuation_price": float(snapshot.valuation_price),
                "valuation_market_cap": (
                    float(snapshot.valuation_market_cap)
                    if snapshot.valuation_market_cap is not None
                    else None
                ),
                "valuation_variant": snapshot.valuation_variant,
                "industry_level": snapshot.industry_level,
                "industry_code": snapshot.industry_code,
                "industry_name": snapshot.industry_name,
                "compare_group": snapshot.compare_group,
                "match_score": float(snapshot.match_score) if snapshot.match_score is not None else None,
            }
        )

    selected = _select_valuation_candidate(method_candidates, pick_strategy, asof_date=trade_date)
    if selected is None:
        return None, None, None, 0, []
    return (
        selected.get("method"),
        selected.get("valuation_price"),
        selected.get("valuation_market_cap"),
        len(method_candidates),
        method_candidates[:MAX_VALUATION_CANDIDATES_IN_RESPONSE],
    )


def _build_snapshot_method_map(ts_codes, trade_date, market="CN", pick_strategy="baseline"):
    if not ts_codes:
        return {}

    snapshots = (
        StockValuationSnapshot.objects.filter(
            ts_code__in=ts_codes,
            trade_date=trade_date,
            market=market,
        )
        .order_by("ts_code", "valuation_method", "-updated_at")
        .values(
            "ts_code",
            "valuation_method",
            "valuation_price",
            "valuation_market_cap",
            "source",
            "valuation_variant",
            "industry_level",
            "industry_code",
            "industry_name",
            "compare_group",
            "match_score",
        )
    )

    grouped = {}
    for row in snapshots:
        ts_code = row["ts_code"]
        method = _normalize_valuation_method_name(row["valuation_method"])
        if not method:
            continue
        valuation_price = row.get("valuation_price")
        if valuation_price is None:
            continue
        grouped.setdefault(ts_code, {}).setdefault(method, []).append(
            {
                "method": method,
                "valuation_price": float(valuation_price),
                "valuation_market_cap": float(row.get("valuation_market_cap")) if row.get("valuation_market_cap") is not None else None,
                "source": row.get("source"),
                "valuation_variant": row.get("valuation_variant"),
                "industry_level": row.get("industry_level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
                "compare_group": row.get("compare_group"),
                "match_score": float(row.get("match_score")) if row.get("match_score") is not None else None,
            }
        )

    snapshot_map = {}
    for ts_code, method_groups in grouped.items():
        method_map = snapshot_map.setdefault(ts_code, {})
        for method, candidates in method_groups.items():
            selected = _select_valuation_candidate(candidates, pick_strategy, asof_date=trade_date)
            if selected is None:
                continue
            quality_payload = _build_candidate_quality_payload(selected, candidates, asof_date=trade_date)
            method_map[method] = {
                "valuation_price": selected.get("valuation_price"),
                "valuation_market_cap": selected.get("valuation_market_cap"),
                "source": selected.get("source"),
                "valuation_variant": _normalize_valuation_variant(selected.get("valuation_variant"), fallback="default"),
                "candidate_count": len(candidates),
                "compare_group": selected.get("compare_group"),
                "match_score": selected.get("match_score"),
                **quality_payload,
            }
    return snapshot_map


def _build_latest_snapshot_method_map(
    ts_codes,
    market="CN",
    pick_strategy="baseline",
    max_trade_date=None,
    express_only=False,
    profit_report_type=None,
    profit_report_end_date=None,
):
    if not ts_codes:
        return {}

    snapshots = StockValuationSnapshotLatest.objects.filter(
        ts_code__in=ts_codes,
        market=market,
    )
    if max_trade_date:
        snapshots = snapshots.filter(latest_trade_date__lte=max_trade_date)
    if express_only:
        snapshots = snapshots.filter(profit_data_source__startswith="express")
    normalized_profit_report_type = _normalize_valuation_profit_report_type(profit_report_type)
    if normalized_profit_report_type:
        snapshots = snapshots.filter(profit_report_type=normalized_profit_report_type)
    report_end_dt = _parse_date_like(profit_report_end_date)
    if report_end_dt is not None:
        snapshots = snapshots.filter(profit_report_end_date=report_end_dt)

    snapshots = snapshots.values(
        "ts_code",
        "valuation_method",
        "valuation_price",
        "valuation_market_cap",
        "source",
        "profit_data_source",
        "profit_report_end_date",
        "profit_report_ann_date",
        "profit_report_type",
        "express_ann_date",
        "valuation_variant",
        "industry_level",
        "industry_code",
        "industry_name",
        "compare_group",
        "match_score",
        "latest_trade_date",
        "updated_at",
    )

    grouped = {}
    for row in snapshots:
        ts_code = row["ts_code"]
        method = _normalize_valuation_method_name(row["valuation_method"])
        if not method:
            continue
        valuation_price = row.get("valuation_price")
        if valuation_price is None:
            continue
        grouped.setdefault(ts_code, {}).setdefault(method, []).append(
            {
                "method": method,
                "valuation_price": float(valuation_price),
                "valuation_market_cap": float(row.get("valuation_market_cap")) if row.get("valuation_market_cap") is not None else None,
                "source": row.get("source") or "snapshot_latest",
                "profit_data_source": row.get("profit_data_source"),
                "profit_report_end_date": row.get("profit_report_end_date"),
                "profit_report_ann_date": row.get("profit_report_ann_date"),
                "profit_report_type": row.get("profit_report_type"),
                "express_ann_date": row.get("express_ann_date"),
                "valuation_variant": row.get("valuation_variant"),
                "industry_level": row.get("industry_level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
                "compare_group": row.get("compare_group"),
                "match_score": float(row.get("match_score")) if row.get("match_score") is not None else None,
                "latest_trade_date": row.get("latest_trade_date"),
                "snapshot_updated_at": row.get("updated_at"),
            }
        )

    snapshot_map = {}
    for ts_code, method_groups in grouped.items():
        method_map = snapshot_map.setdefault(ts_code, {})
        for method, candidates in method_groups.items():
            selected = _select_valuation_candidate(candidates, pick_strategy, asof_date=max_trade_date)
            if selected is None:
                continue
            quality_payload = _build_candidate_quality_payload(selected, candidates, asof_date=max_trade_date)
            method_map[method] = {
                "valuation_price": selected.get("valuation_price"),
                "valuation_market_cap": selected.get("valuation_market_cap"),
                "source": selected.get("source") or "snapshot_latest",
                "profit_data_source": selected.get("profit_data_source"),
                "profit_report_end_date": selected.get("profit_report_end_date"),
                "profit_report_ann_date": selected.get("profit_report_ann_date"),
                "profit_report_type": selected.get("profit_report_type"),
                "express_ann_date": selected.get("express_ann_date"),
                "valuation_variant": _normalize_valuation_variant(selected.get("valuation_variant"), fallback="default"),
                "latest_trade_date": selected.get("latest_trade_date"),
                "snapshot_updated_at": selected.get("snapshot_updated_at"),
                "candidate_count": len(candidates),
                "compare_group": selected.get("compare_group"),
                "match_score": selected.get("match_score"),
                **quality_payload,
            }
    return snapshot_map


def _pick_latest_predictive_snapshot_anchor(method_map):
    if not isinstance(method_map, dict) or not method_map:
        return None

    method_priority = {
        "sw_history": 0,
        "pe": 1,
        "pb": 2,
        "ps": 3,
        "peg": 4,
        "fcff_dcf": 5,
        "ddm": 6,
        "scarcity_overlay": 7,
        "market_cap": 99,
    }

    candidates = []
    for method, payload in method_map.items():
        report_type = _normalize_valuation_profit_report_type(payload.get("profit_report_type"))
        if report_type == "ANNUAL":
            report_type = "FY"
        report_end_date = _parse_date_like(payload.get("profit_report_end_date"))
        if report_type not in {"Q1", "H1", "Q3", "FY"} or report_end_date is None:
            continue

        candidates.append(
            {
                "method": method,
                "report_type": report_type,
                "report_end_date": report_end_date,
                "report_ann_date": _parse_date_like(payload.get("profit_report_ann_date")),
                "latest_trade_date": _parse_date_like(payload.get("latest_trade_date")),
                "priority": method_priority.get(method, 50),
            }
        )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: (
            item.get("report_end_date") or datetime.date.min,
            item.get("latest_trade_date") or datetime.date.min,
            item.get("report_ann_date") or datetime.date.min,
            -int(item.get("priority", 50)),
        ),
    )


def _build_industry_context_map(ts_codes, market="CN"):
    context_map = {}
    if not ts_codes:
        return context_map
    try:
        cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
    except Exception:
        return context_map

    corp_map = {
        corp.ts_code: corp
        for corp in Corporation.objects.filter(ts_code__in=ts_codes)
        .select_related("industry")
        .only("ts_code", "sw_l3_code", "sw_l3_name", "industry__name")
    }

    for ts_code in ts_codes:
        corp = corp_map.get(ts_code)
        corp_sw_l3_code = str(getattr(corp, "sw_l3_code", "") or "").strip()
        corp_sw_l3_name = str(getattr(corp, "sw_l3_name", "") or "").strip()
        corp_industry_name = str(getattr(getattr(corp, "industry", None), "name", "") or "").strip()

        if corp_sw_l3_code or corp_sw_l3_name:
            matched_entry = None
            l3_items = (cfg.sw_mapping.get("levels", {}) or {}).get("L3", {})
            if corp_sw_l3_code:
                matched_entry = l3_items.get(corp_sw_l3_code)
            if matched_entry is None and corp_sw_l3_name:
                for entry in l3_items.values():
                    if str(entry.get("industry_name") or "").strip() == corp_sw_l3_name:
                        matched_entry = entry
                        break

            hierarchy = cfg.get_sw_hierarchy_from_entry("L3", matched_entry) if matched_entry else {}
            context_map[ts_code] = {
                "industry_name": corp_sw_l3_name or hierarchy.get("l3_name") or "",
                "industry_code": corp_sw_l3_code or hierarchy.get("l3_code") or "",
                "industry_level": "L3",
                "sw_l1_code": hierarchy.get("l1_code") or "",
                "sw_l1_name": hierarchy.get("l1_name") or "",
                "sw_l2_code": hierarchy.get("l2_code") or "",
                "sw_l2_name": hierarchy.get("l2_name") or "",
                "sw_l3_code": corp_sw_l3_code or hierarchy.get("l3_code") or "",
                "sw_l3_name": corp_sw_l3_name or hierarchy.get("l3_name") or "",
                "corp_industry_name": corp_industry_name,
                "industry_source": "corporation_sw_l3",
            }
            continue

        try:
            sw_info = cfg.get_sw_params_by_tscode(ts_code)
            hierarchy = sw_info.get("hierarchy") or {}
            context_map[ts_code] = {
                "industry_name": sw_info.get("industry_name") or hierarchy.get("l3_name") or "",
                "industry_code": sw_info.get("industry_code") or hierarchy.get("l3_code") or "",
                "industry_level": sw_info.get("level") or "L3",
                "sw_l1_code": hierarchy.get("l1_code") or "",
                "sw_l1_name": hierarchy.get("l1_name") or "",
                "sw_l2_code": hierarchy.get("l2_code") or "",
                "sw_l2_name": hierarchy.get("l2_name") or "",
                "sw_l3_code": hierarchy.get("l3_code") or "",
                "sw_l3_name": hierarchy.get("l3_name") or "",
                "corp_industry_name": corp_industry_name,
                "industry_source": "sw_mapping_by_tscode",
            }
        except Exception:
            context_map[ts_code] = {
                "industry_name": "",
                "industry_code": "",
                "industry_level": "",
                "sw_l1_code": "",
                "sw_l1_name": "",
                "sw_l2_code": "",
                "sw_l2_name": "",
                "sw_l3_code": "",
                "sw_l3_name": "",
                "corp_industry_name": corp_industry_name,
                "industry_source": "missing",
            }
    return context_map


def _match_sw_industry_filter(industry_context, sw_industry_query):
    if not sw_industry_query:
        return True

    normalized_query = str(sw_industry_query).strip().lower()
    if not normalized_query:
        return True

    if not isinstance(industry_context, dict):
        return False

    code_candidates = [
        industry_context.get("industry_code"),
        industry_context.get("sw_l1_code"),
        industry_context.get("sw_l2_code"),
        industry_context.get("sw_l3_code"),
    ]
    name_candidates = [
        industry_context.get("industry_name"),
        industry_context.get("sw_l1_name"),
        industry_context.get("sw_l2_name"),
        industry_context.get("sw_l3_name"),
    ]

    for code in code_candidates:
        normalized_code = str(code or "").strip().lower()
        if not normalized_code:
            continue
        if normalized_query == normalized_code:
            return True

    for name in name_candidates:
        normalized_name = str(name or "").strip().lower()
        if not normalized_name:
            continue
        if normalized_query in normalized_name:
            return True

    return False


def _industry_prior_scores(industry_name):
    name = str(industry_name or "").lower()
    # Default balanced priors for general sectors.
    priors = {
        "pb": 0.62,
        "pe": 0.72,
        "ps": 0.58,
        "peg": 0.48,
        "fcff_dcf": 0.40,
        "ddm": 0.30,
    }

    if any(k in name for k in ["Θô╢Φíî", "Σ┐¥ΘÖ⌐", "Φ»üσê╕", "σñÜσàâΘçæΦ₧ì"]):
        priors.update({"pb": 0.90, "pe": 0.45, "ps": 0.20, "ddm": 0.40})
    elif any(k in name for k in ["σà¼τö¿", "σ£░Σ║º", "σ╗║µ¥É", "ΘÆóΘôü", "τàñτé¡", "Σ║ñΘÇÜΦ┐ÉΦ╛ô"]):
        priors.update({"pb": 0.78, "pe": 0.55, "ps": 0.35, "fcff_dcf": 0.52})
    elif any(k in name for k in ["σìèσ»╝Σ╜ô", "Φ╜»Σ╗╢", "Σ║ÆΦüöτ╜æ", "Σ╝áσ¬Æ", "τöƒτë⌐", "σî╗Φì»", "τö╡σ¡É"]):
        priors.update({"ps": 0.86, "pe": 0.73, "peg": 0.68, "pb": 0.36})
    elif any(k in name for k in ["Θúƒσôü", "ΘÑ«µûÖ", "σ«╢τö╡", "Φ╜╗σ╖Ñ", "τ║║τ╗ç", "µ▒╜Φ╜ª", "µ£║µó░"]):
        priors.update({"pe": 0.82, "pb": 0.60, "ps": 0.52, "peg": 0.56})

    return priors


def _build_recommendation_profile(ts_code, method_map, industry_context):
    priors = _industry_prior_scores((industry_context or {}).get("industry_name"))
    all_methods = ["pb", "pe", "ps", "peg", "fcff_dcf", "ddm"]
    scored = []

    for method in all_methods:
        prior_score = float(priors.get(method, 0.5))
        payload = (method_map or {}).get(method) or {}
        price = payload.get("valuation_price")
        candidate_count = int(payload.get("candidate_count") or 0)
        valuation_confidence = _to_float_or_none(payload.get("valuation_confidence"))
        valuation_staleness_days = _to_float_or_none(payload.get("valuation_staleness_days"))
        valuation_candidate_spread_pct = _to_float_or_none(payload.get("valuation_candidate_spread_pct"))
        match_score = _to_float_or_none(payload.get("match_score"))
        has_value = price is not None and float(price) > 0
        availability_score = 1.0 if has_value else 0.0
        stability_bonus = min(candidate_count, 3) * 0.06

        confidence_score = max(0.0, min(1.0, (valuation_confidence or 0.0) / 100.0))
        freshness_score = 0.5
        if valuation_staleness_days is not None:
            freshness_score = max(0.0, min(1.0, 1.0 - max(0.0, valuation_staleness_days - 30.0) / 270.0))
        dispersion_score = 0.5
        if valuation_candidate_spread_pct is not None:
            dispersion_score = max(0.0, min(1.0, 1.0 - valuation_candidate_spread_pct / 80.0))
        match_quality_score = max(0.0, min(1.0, (match_score or 0.0) / 100.0))

        final_score = (
            (prior_score * 0.38)
            + (availability_score * 0.2)
            + (confidence_score * 0.18)
            + (freshness_score * 0.1)
            + (dispersion_score * 0.08)
            + (match_quality_score * 0.06)
            + stability_bonus
        )
        scored.append(
            {
                "method": method,
                "score": final_score,
                "available": has_value,
                "candidate_count": candidate_count,
            }
        )

    available_rank = [item for item in sorted(scored, key=lambda item: item["score"], reverse=True) if item["available"]]
    fallback_rank = sorted(scored, key=lambda item: item["score"], reverse=True)
    final_rank = available_rank or fallback_rank

    recommended_methods = [item["method"] for item in final_rank]
    top_score = final_rank[0]["score"] if final_rank else 0.0
    second_score = final_rank[1]["score"] if len(final_rank) > 1 else 0.0
    confidence = int(max(35, min(95, 55 + (top_score - second_score) * 80 + len(available_rank) * 2)))

    reasons = []
    industry_name = (industry_context or {}).get("industry_name") or "µ£¬τƒÑΦíîΣ╕Ü"
    reasons.append(f"industry={industry_name}")
    reasons.append(f"available_methods={len(available_rank)}")
    if final_rank:
        reasons.append(f"top_method={final_rank[0]['method']}")

    return {
        "methods": recommended_methods,
        "scores": {item["method"]: round(item["score"], 4) for item in final_rank},
        "confidence": confidence,
        "reason": "; ".join(reasons),
    }


def _resolve_effective_method(requested_method, method_map, recommendation_profile=None):
    normalized_requested = _normalize_valuation_method_name(requested_method)
    if normalized_requested in {"recommended", "auto"}:
        for method in (recommendation_profile or {}).get("methods", []):
            if method in (method_map or {}):
                return method
        for method in ["pb", "pe", "ps", "fcff_dcf", "ddm", "peg"]:
            if method in (method_map or {}):
                return method
        return "pe"
    return normalized_requested or "pe"


def _summarize_buy_candidate(current_price, method_map, band_pct):
    return summarize_buy_candidate(
        current_price=current_price,
        method_map=method_map,
        band_pct=band_pct,
    )


def _build_valuation_summary_payload(current_price, rows, band_pct, price_key="valuation_price", ts_code=None, freq="D"):
    anchor_row = next(
        (row for row in (rows or []) if _parse_date_like(row.get("latest_trade_date")) is not None),
        (rows or [{}])[0] if rows else {},
    )
    anchor_trade_date = _parse_date_like((anchor_row or {}).get("latest_trade_date"))
    anchor_ts_code = str(ts_code or (anchor_row or {}).get("ts_code") or "").strip().upper()
    anchor_close_price = None
    if anchor_ts_code and anchor_trade_date is not None:
        anchor_trade_row = (
            StockTradingHistory.objects.filter(ts_code=anchor_ts_code, freq=freq, trade_date=anchor_trade_date)
            .values("close_qfq", "close")
            .first()
        )
        anchor_close_price = _to_float_or_none((anchor_trade_row or {}).get("close_qfq"))
        if anchor_close_price is None:
            anchor_close_price = _to_float_or_none((anchor_trade_row or {}).get("close"))

    anchor_basis_price = anchor_close_price
    if price_key == "valuation_price_normalized_to_latest_share" and anchor_close_price is not None:
        snapshot_total_share = _parse_optional_float((anchor_row or {}).get("snapshot_total_share"), default=None)
        current_total_share = _parse_optional_float((anchor_row or {}).get("current_total_share"), default=None)
        if snapshot_total_share not in (None, 0) and current_total_share not in (None, 0):
            anchor_basis_price = float(anchor_close_price) * float(snapshot_total_share) / float(current_total_share)

    method_map_for_summary = {}
    for row in rows or []:
        method = _normalize_valuation_method_name(row.get("valuation_method"))
        valuation_price = row.get(price_key)
        if not method or valuation_price is None:
            continue
        method_map_for_summary[method] = {
            "valuation_price": valuation_price,
            "candidate_count": 1,
        }

    summary = _summarize_buy_candidate(current_price, method_map_for_summary, band_pct)
    composite_status, composite_gap_pct = _classify_valuation(
        current_price,
        summary.get("composite_valuation_price"),
        band_pct,
    )
    conservative_status, conservative_gap_pct = _classify_valuation(
        current_price,
        summary.get("conservative_valuation_price"),
        band_pct,
    )
    return {
        "anchor_trade_date": anchor_trade_date.strftime("%Y-%m-%d") if anchor_trade_date is not None else None,
        "anchor_basis_price": round(float(anchor_basis_price), 4) if anchor_basis_price is not None else None,
        "undervalue_score": summary.get("undervalue_score"),
        "buy_candidate": bool(summary.get("buy_candidate")),
        "valuation_under_methods": summary.get("valuation_under_methods") or [],
        "valuation_valid_methods": summary.get("valuation_valid_methods") or [],
        "composite_valuation_price": summary.get("composite_valuation_price"),
        "composite_valuation_status": composite_status,
        "composite_valuation_gap_pct": round(composite_gap_pct * 100, 2) if composite_gap_pct is not None else None,
        "composite_valuation_anchor_gap_pct": _calc_return_pct_simple(anchor_basis_price, summary.get("composite_valuation_price")),
        "conservative_valuation_price": summary.get("conservative_valuation_price"),
        "conservative_valuation_status": conservative_status,
        "conservative_valuation_gap_pct": round(conservative_gap_pct * 100, 2) if conservative_gap_pct is not None else None,
        "conservative_valuation_anchor_gap_pct": _calc_return_pct_simple(anchor_basis_price, summary.get("conservative_valuation_price")),
    }


def _hydrate_summary_gap_fields(summary_payload, *, current_price, rows, band_pct, ts_code=None, freq="D"):
    """Backfill gap/anchor fields when persisted summary only contains prices."""
    summary = dict(summary_payload or {})
    if not summary:
        return summary

    computed = _build_valuation_summary_payload(
        current_price,
        rows,
        band_pct,
        ts_code=ts_code,
        freq=freq,
    )
    if not computed:
        return summary

    for key in [
        "anchor_trade_date",
        "anchor_basis_price",
        "composite_valuation_status",
        "composite_valuation_gap_pct",
        "composite_valuation_anchor_gap_pct",
        "conservative_valuation_status",
        "conservative_valuation_gap_pct",
        "conservative_valuation_anchor_gap_pct",
    ]:
        if summary.get(key) is None:
            summary[key] = computed.get(key)

    return summary


def _load_market_style_price_series(ts_code, freq="D", trade_date=None, lookback=130):
    if trade_date is None:
        return []

    rows = list(
        StockTradingHistory.objects.filter(
            ts_code=ts_code,
            freq=freq,
            trade_date__lte=trade_date,
        )
        .order_by("-trade_date")
        .values("trade_date", "close_qfq", "close")[:lookback]
    )
    rows.reverse()

    price_series = []
    for row in rows:
        price = _parse_optional_float(row.get("close_qfq"), default=None)
        if price is None:
            price = _parse_optional_float(row.get("close"), default=None)
        if price is None:
            continue
        price_series.append((row.get("trade_date"), float(price)))
    return price_series


def _build_market_style_payload_for_variant(
    variant,
    variant_rows,
    current_price,
    band_pct,
    stock_snapshot,
    price_series,
    allow_fallback=True,
    price_key="valuation_price",
):
    existing_row = next(
        (
            row for row in (variant_rows or [])
            if _normalize_valuation_method_name(row.get("valuation_method")) == "market_style"
            and row.get(price_key) is not None
        ),
        None,
    )
    if existing_row is not None:
        valuation_price = _parse_optional_float(existing_row.get(price_key), default=None)
        status, gap_pct = _classify_valuation(current_price, valuation_price, band_pct)
        return {
            "market_style_valuation_price": round(float(valuation_price), 4) if valuation_price is not None else None,
            "market_style_valuation_status": status,
            "market_style_valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
        }

    base_rows = [
        row for row in (variant_rows or [])
        if _normalize_valuation_method_name(row.get("valuation_method")) != "market_style"
    ]
    if not allow_fallback:
        return {
            "market_style_valuation_price": None,
            "market_style_valuation_status": "unknown",
            "market_style_valuation_gap_pct": None,
        }
    if current_price in (None, 0) or not base_rows or not price_series:
        return {
            "market_style_valuation_price": None,
            "market_style_valuation_status": "unknown",
            "market_style_valuation_gap_pct": None,
        }

    from prediction.management.commands.backtestmarketstyleadjustment import (
        _apply_market_style_adjustment,
        _build_regime_features,
        _resolve_style_params,
    )
    from prediction.management.commands.backtestmarketstylebatch import _resolve_industry_group

    base_summary = _build_valuation_summary_payload(
        current_price,
        base_rows,
        band_pct,
        price_key=price_key,
    )
    composite_price = _parse_optional_float(base_summary.get("composite_valuation_price"), default=None)
    conservative_price = _parse_optional_float(base_summary.get("conservative_valuation_price"), default=None)
    if composite_price is None:
        return {
            "market_style_valuation_price": None,
            "market_style_valuation_status": "unknown",
            "market_style_valuation_gap_pct": None,
        }

    anchor_row = (base_rows or [{}])[0] if base_rows else {}
    industry_name = anchor_row.get("industry_name")
    style_group = _resolve_industry_group(industry_name, variant)
    style_params, resolved_profile, resolved_group = _resolve_style_params("adaptive", style_group)
    regime = _build_regime_features(price_series, len(price_series) - 1)
    adjusted_price, _adjust_meta = _apply_market_style_adjustment(
        composite_price,
        conservative_price,
        stock_snapshot or {},
        regime,
        style_params,
        resolved_profile,
        resolved_group,
    )
    status, gap_pct = _classify_valuation(current_price, adjusted_price, band_pct)
    return {
        "market_style_valuation_price": round(float(adjusted_price), 4) if adjusted_price is not None else None,
        "market_style_valuation_status": status,
        "market_style_valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
    }


def _merge_summary_with_market_style(summary_payload, market_style_payload):
    merged = dict(summary_payload or {})
    merged.update(market_style_payload or {})
    return merged


def _load_latest_total_share_shares(ts_code, freq="D", max_trade_date=None):
    queryset = StockFundamentalHistory.objects.filter(ts_code=ts_code, freq=freq)
    if max_trade_date is not None:
        queryset = queryset.filter(trade_date__lte=max_trade_date)

    row = queryset.order_by("-trade_date").values("trade_date", "total_share").first()
    total_share = _parse_optional_float((row or {}).get("total_share"), default=None)
    if total_share is None or total_share <= 0:
        return None, (row or {}).get("trade_date")
    return total_share * 10000.0, row.get("trade_date")


def _infer_snapshot_total_share_shares(row):
    valuation_market_cap = _parse_optional_float((row or {}).get("valuation_market_cap"), default=None)
    valuation_price = _parse_optional_float((row or {}).get("valuation_price"), default=None)
    if valuation_market_cap is None or valuation_price is None or valuation_price <= 0:
        return None
    snapshot_total_share = valuation_market_cap / valuation_price
    if snapshot_total_share <= 0:
        return None
    return snapshot_total_share


def _load_dividend_events(ts_code, start_date=None, end_date=None):
    try:
        df = query_local_financial_df(
            """
            SELECT *
            FROM earnings_fin_dividend
            WHERE ts_code = %s
            ORDER BY end_date DESC, ann_date DESC
            LIMIT 32
            """,
            [ts_code],
        )
    except Exception:
        return []

    if df is None or df.empty:
        return []

    start_dt = _parse_date_like(start_date)
    end_dt = _parse_date_like(end_date)
    events = []
    for _, row in df.iterrows():
        event = row.to_dict()
        event_date = (
            _parse_date_like(event.get("ex_date"))
            or _parse_date_like(event.get("record_date"))
            or _parse_date_like(event.get("pay_date"))
            or _parse_date_like(event.get("ann_date"))
        )
        if event_date is None:
            continue
        if start_dt is not None and event_date <= start_dt:
            continue
        if end_dt is not None and event_date > end_dt:
            continue

        stock_bonus = _parse_optional_float(event.get("stk_div"), default=0.0) or 0.0
        stock_boost = _parse_optional_float(event.get("stk_bo_rate"), default=0.0) or 0.0
        stock_convert = _parse_optional_float(event.get("stk_co_rate"), default=0.0) or 0.0
        stock_bonus = stock_bonus if math.isfinite(stock_bonus) else 0.0
        stock_boost = stock_boost if math.isfinite(stock_boost) else 0.0
        stock_convert = stock_convert if math.isfinite(stock_convert) else 0.0
        if stock_bonus <= 0 and stock_boost <= 0 and stock_convert <= 0:
            continue

        event["event_date"] = event_date
        event["stock_distribution_ratio"] = round(stock_bonus + stock_boost + stock_convert, 6)
        events.append(event)

    events.sort(key=lambda item: item.get("event_date") or datetime.date.min, reverse=True)
    return events


def _build_corporate_action_impact_payload(ts_code, current_trade_date, current_total_share_shares, row):
    snapshot_trade_date = _parse_date_like((row or {}).get("latest_trade_date"))
    snapshot_total_share_shares = _infer_snapshot_total_share_shares(row)
    if (
        snapshot_trade_date is None
        or current_trade_date is None
        or snapshot_total_share_shares is None
        or current_total_share_shares is None
        or current_total_share_shares <= snapshot_total_share_shares
    ):
        return None

    share_change_ratio = current_total_share_shares / snapshot_total_share_shares - 1.0
    if share_change_ratio < VALUATION_SHARE_CHANGE_IMPACT_THRESHOLD:
        return None

    dividend_events = _load_dividend_events(
        ts_code,
        start_date=snapshot_trade_date,
        end_date=current_trade_date,
    )
    if not dividend_events:
        return None

    latest_event = dividend_events[0]
    return {
        "impact_type": "share_dilution_from_dividend",
        "impact_detected": True,
        "snapshot_trade_date": snapshot_trade_date,
        "current_trade_date": current_trade_date,
        "snapshot_total_share": round(snapshot_total_share_shares / 10000.0, 4),
        "current_total_share": round(current_total_share_shares / 10000.0, 4),
        "share_change_ratio_pct": round(share_change_ratio * 100, 2),
        "latest_dividend_event": {
            "end_date": _parse_date_like(latest_event.get("end_date")),
            "ann_date": _parse_date_like(latest_event.get("ann_date")),
            "record_date": _parse_date_like(latest_event.get("record_date")),
            "ex_date": _parse_date_like(latest_event.get("ex_date")),
            "pay_date": _parse_date_like(latest_event.get("pay_date")),
            "stock_distribution_ratio": latest_event.get("stock_distribution_ratio"),
            "cash_div_tax": _parse_optional_float(latest_event.get("cash_div_tax"), default=None),
            "div_proc": latest_event.get("div_proc"),
        },
        "message": "检测到除权摊薄影响：当前总股本相较估值快照基准股本已显著增加。为避免除权导致的估值失真，系统已提供按最新股本归一化的估值参考。",
    }


def _enrich_rows_with_share_basis(ts_code, current_trade_date, current_total_share_shares, current_price, band_pct, rows):
    normalized_rows = []
    for row in rows or []:
        valuation_market_cap = _parse_optional_float(row.get("valuation_market_cap"), default=None)
        snapshot_total_share_shares = _infer_snapshot_total_share_shares(row)
        normalized_price = None
        if valuation_market_cap is not None and current_total_share_shares is not None and current_total_share_shares > 0:
            normalized_price = valuation_market_cap / current_total_share_shares

        normalized_status, normalized_gap_pct = _classify_valuation(current_price, normalized_price, band_pct)
        row["snapshot_total_share"] = round(snapshot_total_share_shares / 10000.0, 4) if snapshot_total_share_shares else None
        row["current_total_share"] = round(current_total_share_shares / 10000.0, 4) if current_total_share_shares else None
        row["valuation_price_normalized_to_latest_share"] = round(normalized_price, 4) if normalized_price is not None else None
        row["valuation_status_normalized_to_latest_share"] = normalized_status if normalized_price is not None else "unknown"
        row["valuation_gap_pct_normalized_to_latest_share"] = round(normalized_gap_pct * 100, 2) if normalized_gap_pct is not None else None
        row["corporate_action_impact"] = _build_corporate_action_impact_payload(
            ts_code=ts_code,
            current_trade_date=current_trade_date,
            current_total_share_shares=current_total_share_shares,
            row=row,
        )
        normalized_rows.append(row)
    return normalized_rows


def _save_valuation_snapshot(
    ts_code,
    trade_date,
    market,
    method,
    valuation_price,
    valuation_market_cap=None,
    source="live_compute",
    corporation=None,
    valuation_snapshot=None,
    valuation_variant="default",
    industry_level=None,
    industry_code=None,
    industry_name=None,
    compare_group=None,
    match_score=None,
):
    normalized_method = _normalize_valuation_method_name(method)
    if not normalized_method:
        return

    valuation_snapshot = valuation_snapshot or {}

    def _parse_snapshot_date(value):
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        text = str(value).strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) < 8:
            return None
        try:
            return datetime.datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None

    def _resolve_report_type(report_end_date):
        if report_end_date is None:
            return None
        md = report_end_date.strftime("%m%d")
        if md == "0331":
            return "Q1"
        if md == "0630":
            return "H1"
        if md == "0930":
            return "Q3"
        if md == "1231":
            return "ANNUAL"
        return "OTHER"

    profit_source = valuation_snapshot.get("profit_data_source")
    express_end_date = _parse_snapshot_date(valuation_snapshot.get("express_end_date"))
    express_ann_date = _parse_snapshot_date(valuation_snapshot.get("express_ann_date"))
    base_end_date = _parse_snapshot_date(valuation_snapshot.get("end_date"))
    raw_frames = (valuation_snapshot or {}).get("raw_frames") or {}
    base_ann_candidates = []
    for frame_name in ["income", "fina_indicator", "balancesheet", "cashflow", "dividend"]:
        frame = raw_frames.get(frame_name)
        if frame is None or getattr(frame, "empty", True):
            continue
        if "ann_date" not in frame.columns:
            continue
        try:
            values = frame["ann_date"].tolist()
        except Exception:
            values = []
        for value in values:
            parsed = _parse_snapshot_date(value)
            if parsed is not None:
                base_ann_candidates.append(parsed)
    base_ann_date = max(base_ann_candidates) if base_ann_candidates else None
    effective_end_date = base_end_date
    if profit_source and str(profit_source).startswith("express_vip") and express_end_date is not None:
        effective_end_date = express_end_date
    effective_ann_date = base_ann_date
    if profit_source and str(profit_source).startswith("express_vip") and express_ann_date is not None:
        effective_ann_date = express_ann_date
    if effective_end_date is not None and effective_ann_date is not None and effective_ann_date < effective_end_date:
        effective_ann_date = None

    normalized_variant = (str(valuation_variant).strip() or "default")[:128]
    normalized_profit_source = (str(profit_source).strip() or None) if profit_source is not None else None
    normalized_profit_report_type = _resolve_report_type(effective_end_date)
    snapshot_defaults = {
        "valuation_price": valuation_price,
        "valuation_market_cap": valuation_market_cap,
        "source": source,
        "corporation": corporation,
        "industry_level": (str(industry_level).strip() or None) if industry_level is not None else None,
        "industry_code": (str(industry_code).strip() or None) if industry_code is not None else None,
        "industry_name": (str(industry_name).strip() or None) if industry_name is not None else None,
        "compare_group": (str(compare_group).strip() or None) if compare_group is not None else None,
        "match_score": match_score,
        "profit_data_source": normalized_profit_source,
        "profit_report_end_date": effective_end_date,
        "profit_report_ann_date": effective_ann_date,
        "profit_report_type": normalized_profit_report_type,
        "express_end_date": express_end_date,
        "express_ann_date": express_ann_date,
        "express_apply_reason": valuation_snapshot.get("express_apply_reason"),
        "express_block_reason": valuation_snapshot.get("express_block_reason"),
        "strict_express_match": valuation_snapshot.get("strict_express_match"),
        "express_max_age_days": valuation_snapshot.get("express_max_age_days"),
    }

    StockValuationSnapshot.objects.update_or_create(
        ts_code=ts_code,
        trade_date=trade_date,
        market=market,
        valuation_method=normalized_method,
        valuation_variant=normalized_variant,
        profit_report_type=normalized_profit_report_type,
        profit_report_end_date=effective_end_date,
        profit_data_source=normalized_profit_source,
        defaults=snapshot_defaults,
    )

    StockValuationSnapshotLatest.objects.update_or_create(
        ts_code=ts_code,
        market=market,
        valuation_method=normalized_method,
        valuation_variant=normalized_variant,
        profit_report_type=normalized_profit_report_type,
        profit_data_source=normalized_profit_source,
        defaults={
            **snapshot_defaults,
            "latest_trade_date": trade_date,
        },
    )


def _classify_valuation(current_price, implied_price, band_pct):
    if current_price in (None, 0) or implied_price is None:
        return "unknown", None
    gap_pct = (float(implied_price) - float(current_price)) / float(current_price)
    if float(current_price) <= float(implied_price) * (1 - band_pct):
        return "under", gap_pct
    if float(current_price) >= float(implied_price) * (1 + band_pct):
        return "over", gap_pct
    return "fair", gap_pct


def _evaluate_stock_valuation(
    ts_code,
    trade_date,
    selected_method,
    current_price,
    band_pct,
    market="CN",
    corporation=None,
    business_match_topn=0,
    pick_strategy="baseline",
    strict_snapshot_only=False,
):
    try:
        cached_method, cached_price, cached_market_cap, cached_candidate_count, cached_candidates = _get_cached_method_price(
            ts_code=ts_code,
            trade_date=trade_date,
            selected_method=selected_method,
            market=market,
            pick_strategy=pick_strategy,
        )
        if cached_price is not None:
            status, gap_pct = _classify_valuation(current_price, cached_price, band_pct)
            return {
                "valuation_method": cached_method,
                "valuation_price": round(cached_price, 4),
                "valuation_market_cap": round(cached_market_cap, 2) if cached_market_cap is not None else None,
                "valuation_status": status,
                "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
                "valuation_source": "snapshot_cache",
                "valuation_pick_strategy": _normalize_pick_strategy(pick_strategy),
                "valuation_candidate_count": cached_candidate_count,
                "valuation_candidates": cached_candidates,
            }

        if strict_snapshot_only:
            return {
                "valuation_method": _normalize_valuation_method_name(selected_method),
                "valuation_price": None,
                "valuation_market_cap": None,
                "valuation_status": "unknown",
                "valuation_gap_pct": None,
                "valuation_source": "snapshot_only_miss",
                "valuation_pick_strategy": _normalize_pick_strategy(pick_strategy),
                "valuation_candidate_count": 0,
                "valuation_candidates": [],
            }

        matched_rows = []
        resolved_method = None
        implied_price = None
        equity_value = None
        valuation_snapshot_payload = {}

        contexts = _build_live_valuation_contexts(
            ts_code=ts_code,
            market=market,
            business_match_topn=max(0, int(business_match_topn or 0)),
        )

        for context_item in contexts:
            valuation_result = test_valuation(
                ts_code=ts_code,
                trade_date=trade_date,
                **(context_item.get("params") or {}),
            )
            valuation_df = valuation_result.get("valuations")
            context = context_item.get("context") or {}
            rows = _extract_method_valuation_rows(valuation_df, selected_method)
            if rows:
                for row in rows:
                    row["valuation_variant"] = context.get("valuation_variant") or _build_valuation_variant(context)
                    row["industry_level"] = context.get("industry_level")
                    row["industry_code"] = context.get("industry_code")
                    row["industry_name"] = context.get("industry_name")
                    row["compare_group"] = context.get("compare_group")
                    row["match_score"] = context.get("match_score")
                matched_rows.extend(rows)

            if implied_price is None:
                resolved_method, implied_price, equity_value = _extract_method_valuation(
                    valuation_df,
                    selected_method,
                )
                valuation_snapshot_payload = valuation_result.get("snapshot") or {}

        deduped_rows = []
        seen_variants = set()
        for row in matched_rows:
            variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
            if variant in seen_variants:
                continue
            seen_variants.add(variant)
            deduped_rows.append(row)
        matched_rows = deduped_rows

        selected_row = _select_valuation_candidate(
            [
                {
                    "method": _normalize_valuation_method_name(row.get("method")),
                    "valuation_price": row.get("implied_price"),
                    "valuation_market_cap": row.get("equity_value"),
                    "valuation_variant": row.get("valuation_variant"),
                    "industry_level": row.get("industry_level"),
                    "industry_code": row.get("industry_code"),
                    "industry_name": row.get("industry_name"),
                    "compare_group": row.get("compare_group"),
                    "match_score": row.get("match_score"),
                }
                for row in matched_rows
            ],
            pick_strategy,
            asof_date=trade_date,
        )
        if selected_row is not None:
            resolved_method = selected_row.get("method")
            implied_price = selected_row.get("valuation_price")
            equity_value = selected_row.get("valuation_market_cap")

        status, gap_pct = _classify_valuation(current_price, implied_price, band_pct)
        if matched_rows:
            for row in matched_rows:
                _save_valuation_snapshot(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    market=market,
                    method=row.get("method"),
                    valuation_price=row.get("implied_price"),
                    valuation_market_cap=row.get("equity_value"),
                    source="live_compute",
                    corporation=corporation,
                    valuation_snapshot=valuation_snapshot_payload,
                    valuation_variant=row.get("valuation_variant"),
                    industry_level=row.get("industry_level"),
                    industry_code=row.get("industry_code"),
                    industry_name=row.get("industry_name"),
                    compare_group=row.get("compare_group"),
                    match_score=row.get("match_score"),
                )
        elif implied_price is not None and resolved_method:
            _save_valuation_snapshot(
                ts_code=ts_code,
                trade_date=trade_date,
                market=market,
                method=resolved_method,
                valuation_price=implied_price,
                valuation_market_cap=equity_value,
                source="live_compute",
                corporation=corporation,
                valuation_snapshot=valuation_snapshot_payload,
            )
        return {
            "valuation_method": _normalize_valuation_method_name(resolved_method),
            "valuation_price": round(implied_price, 4) if implied_price is not None else None,
            "valuation_market_cap": round(equity_value, 2) if equity_value is not None else None,
            "valuation_status": status,
            "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
            "valuation_source": "live_compute",
            "valuation_pick_strategy": _normalize_pick_strategy(pick_strategy),
            "valuation_candidate_count": len(matched_rows),
            "valuation_candidates": [
                {
                    "valuation_variant": row.get("valuation_variant"),
                    "industry_level": row.get("industry_level"),
                    "industry_code": row.get("industry_code"),
                    "industry_name": row.get("industry_name"),
                    "compare_group": row.get("compare_group"),
                    "match_score": row.get("match_score"),
                    "valuation_price": row.get("implied_price"),
                    "valuation_market_cap": row.get("equity_value"),
                }
                for row in matched_rows[:MAX_VALUATION_CANDIDATES_IN_RESPONSE]
            ],
        }
    except Exception:
        return {
            "valuation_method": None,
            "valuation_price": None,
            "valuation_market_cap": None,
            "valuation_status": "unknown",
            "valuation_gap_pct": None,
            "valuation_source": "error",
            "valuation_pick_strategy": _normalize_pick_strategy(pick_strategy),
            "valuation_candidate_count": 0,
            "valuation_candidates": [],
        }


# Create your views here.
@api_view(["GET"])
def get_stock_trading_history(request, ts_code, freq, adj="qfq", count=None):
    # Dummy response, replace with actual logic
    try:
        # Get the latest N working days (trading days) up to today
        count = int(count) if count is not None else settings.DEFAULT_HISTORY_COUNT
        all_dates = (
            StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .distinct()
        )
        latest_dates = list(all_dates[:count])
        if not latest_dates:
            records = []
        else:
            records = StockTradingHistory.objects.filter(
                ts_code=ts_code, freq=freq, trade_date__in=latest_dates
            ).order_by("trade_date")

        # records = records.order_by("trade_date")
        adj = (adj or "qfq").lower()
        field_map = {
            "qfq": (
                "open_qfq",
                "high_qfq",
                "low_qfq",
                "close_qfq",
                "vol",
                "amount",
                "pct_change",
            ),
            "hfq": (
                "open_hfq",
                "high_hfq",
                "low_hfq",
                "close_hfq",
                "vol",
                "amount",
                "pct_change",
            ),
            "bfq": ("open", "high", "low", "close", "vol", "amount", "pct_change"),
        }

        df = pd.DataFrame([r.__dict__ for r in records])
        df = calculate_atr(
            df=df,
            period=20,
            high_col="high_qfq",
            low_col="low_qfq",
            close_col="close_qfq",
        )
        for idx, r in enumerate(records):
            atr = df.at[idx, "atr"] if "atr" in df.columns and idx < len(df) else None
            close_qfq = (
                df.at[idx, "close_qfq"]
                if "close_qfq" in df.columns and idx < len(df)
                else None
            )
            if atr is not None and pd.notnull(atr) and close_qfq is not None:
                atr = round(atr, 2)
                setattr(r, "stoploss_1", close_qfq - atr)
                setattr(r, "stoploss_2", close_qfq - 2 * atr)
                setattr(r, "takeprofit_1", close_qfq + atr)
                setattr(r, "takeprofit_2", close_qfq + 2 * atr)
            else:
                setattr(r, "stoploss_1", None)
                setattr(r, "stoploss_2", None)
                setattr(r, "takeprofit_1", None)
                setattr(r, "takeprofit_2", None)

        def get_indicator_value(record):
            indicator_fields = {
                "macd": ["macd", "macd_dif", "macd_dea"],
                "rsi": ["rsi_6", "rsi_12", "rsi_24"],
                "kdj": ["kdj_k", "kdj_d", "kdj_j"],
                "boll": ["boll_mid", "boll_upper", "boll_lower"],
                "cci": ["cci"],
                # Add more indicators here as needed
            }
            indicator_values = {}
            for ind_name, fields in indicator_fields.items():
                indicator_values[ind_name] = {
                    f: getattr(record, f, None) for f in fields
                }
            return indicator_values

        fields = field_map.get(adj, field_map["qfq"])
        data = [
            {
                "ts_code": r.ts_code,
                "trade_date": r.trade_date,
                "open": getattr(r, fields[0], None),
                "high": getattr(r, fields[1], None),
                "low": getattr(r, fields[2], None),
                "close": getattr(r, fields[3], None),
                "sl1": getattr(r, "stoploss_1", None),
                "sl2": getattr(r, "stoploss_2", None),
                "tp1": getattr(r, "takeprofit_1", None),
                "tp2": getattr(r, "takeprofit_2", None),
                "vol": getattr(r, fields[4], None),
                "amount": getattr(r, fields[5], None),
                "pct_chg": getattr(r, fields[6], None),
                "freq": r.freq,
                "indicator": get_indicator_value(r),
            }
            for r in records
        ]

        if not data:
            return Response(
                {"error": "No trading history found for given ts_code and freq."},
                status=404,
            )
        return Response({"data": data, "ts_code": ts_code, "freq": freq})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_fundamental_history(request, ts_code, freq, count):
    # Dummy response, replace with actual logic
    try:
        # Get the latest N working days (trading days) up to today
        count = int(count) if count is not None else settings.DEFAULT_HISTORY_COUNT
        all_dates = (
            StockFundamentalHistory.objects.filter(ts_code=ts_code, freq=freq)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .distinct()
        )
        latest_dates = list(all_dates[:count])
        if not latest_dates:
            records = []
        else:
            records = StockFundamentalHistory.objects.filter(
                ts_code=ts_code, freq=freq, trade_date__in=latest_dates
            ).order_by("trade_date")
        data = [{**r.to_dict()} for r in records]
        if not data:
            return Response(
                {"error": "No fundamental history found for given ts_code and freq."},
                status=404,
            )
        return Response({"data": data, "ts_code": ts_code, "freq": freq})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_corporation(request, input_text):
    # Dummy response, replace with actual logic
    try:
        # Perform a fuzzy search on multiple fields
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        # Fuzzy search by text
        corp_q = (
            Q(ts_code__icontains=input_text)
            | Q(name__icontains=input_text)
            | Q(fullname__icontains=input_text)
            | Q(enname__icontains=input_text)
            | Q(cnspell__icontains=input_text)
        )
        corp_list = list(Corporation.objects.filter(corp_q)[:10])
        # Add corporations by tag
        tag_corp_ids = set(
            UserStockTag.objects.filter(
                user=user, tag__icontains=input_text, is_enabled=True
            ).values_list("corporation", flat=True)
        )
        for corp in Corporation.objects.filter(id__in=tag_corp_ids):
            if corp not in corp_list:
                corp_list.append(corp)
        # Attach tags
        tags_map = {}
        for tag in UserStockTag.objects.filter(
            user=user, corporation__in=corp_list, is_enabled=True
        ):
            tags_map.setdefault(tag.corporation.ts_code, []).append(tag.tag)
        data = [
            {
                "ts_code": corp.ts_code,
                "name": corp.name,
                "fullname": corp.fullname,
                "enname": corp.enname,
                "listdate": corp.list_date,
                "cnspell": corp.cnspell,
                "tags": tags_map.get(corp.ts_code, []),
            }
            for corp in corp_list
        ]
        if not data:
            return Response({"error": "No matching corporations found."}, status=404)

        return Response({"data": data, "input_text": input_text}, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_watch_list(request, from_index, to_index):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        market = str(request.query_params.get("market", "HO") or "HO").strip().upper()
        from_index = int(from_index)
        to_index = int(to_index)

        def _market_prefixes(code):
            if code in {"ALL", "A"}:
                return []
            if code == "0":
                return ["00", "30"]
            if code == "6":
                return ["60", "68"]
            if code == "688":
                return ["68"]
            return [code]

        def _watchlist_market_prefixes(code):
            normalized = str(code or "ALL").strip().upper()
            if normalized in {"", "ALL", "A"}:
                return []
            if normalized in {"SH", "SSE", "60"}:
                return ["60"]
            if normalized in {"SZ", "SZSE", "00"}:
                return ["00"]
            if normalized in {"CYB", "GEM", "30"}:
                return ["30"]
            if normalized in {"STAR", "KCB", "688", "KC", "68"}:
                return ["688"]
            return []

        records = []
        record_mode = "watchlist"
        result_file_date = None
        result_available_dates = []
        result_kind = "traditional"
        traditional_return_pct_map = {}
        predictive_optimistic_return_pct_map = {}
        predictive_conservative_return_pct_map = {}
        latest_report_end_date_map = {}

        def _calc_return_pct(current_price, target_price):
            current_price = _to_float_or_none(current_price)
            target_price = _to_float_or_none(target_price)
            if current_price in (None, 0) or target_price is None:
                return None
            return round((float(target_price) / float(current_price) - 1.0) * 100.0, 2)

        def _filter_method_map_to_latest_report(method_map):
            anchor = _pick_latest_predictive_snapshot_anchor(method_map)
            if not anchor:
                return method_map or {}, None

            anchor_end_date = _parse_date_like(anchor.get("report_end_date"))
            if anchor_end_date is None:
                return method_map or {}, None

            filtered = {}
            for method, payload in (method_map or {}).items():
                payload_end_date = _parse_date_like((payload or {}).get("profit_report_end_date"))
                if payload_end_date == anchor_end_date:
                    filtered[method] = payload

            if not filtered:
                return method_map or {}, anchor
            return filtered, anchor

        def _filter_method_map_to_report_end_date(method_map, report_end_date):
            normalized_end_date = _parse_date_like(report_end_date)
            if normalized_end_date is None:
                return method_map or {}

            filtered = {}
            for method, payload in (method_map or {}).items():
                payload_end_date = _parse_date_like(
                    (payload or {}).get("profit_report_end_date")
                    or (payload or {}).get("report_end_date")
                )
                if payload_end_date == normalized_end_date:
                    filtered[method] = payload
            return filtered
        if market == "HO":
            queryset = UserWatchlist.objects.filter(
                user=user, is_enabled=True, hold_a_position=True,
            ).select_related("corporation").order_by("ts_code")
            total = queryset.count()
            records = list(queryset[from_index:to_index])
        elif market == "WL":
            wl_market_filter = str(request.query_params.get("wl_market", "ALL") or "ALL").strip().upper()
            queryset = UserWatchlist.objects.filter(
                user=user, is_enabled=True
            ).select_related("corporation").order_by("ts_code")
            wl_prefixes = _watchlist_market_prefixes(wl_market_filter)
            if wl_prefixes:
                wl_q = Q()
                for prefix in wl_prefixes:
                    wl_q |= Q(ts_code__startswith=prefix)
                queryset = queryset.filter(wl_q)
            total = queryset.count()
            records = list(queryset[from_index:to_index])
        elif market == "OBS":
            obs_market_filter = str(request.query_params.get("wl_market", "ALL") or "ALL").strip().upper()
            queryset = UserWatchlist.objects.filter(
                user=user, is_enabled=True, observe_only=True
            ).select_related("corporation").order_by("ts_code")
            obs_prefixes = _watchlist_market_prefixes(obs_market_filter)
            if obs_prefixes:
                obs_q = Q()
                for prefix in obs_prefixes:
                    obs_q |= Q(ts_code__startswith=prefix)
                queryset = queryset.filter(obs_q)
            total = queryset.count()
            records = list(queryset[from_index:to_index])
        elif market == "RESULT":
            record_mode = "result"
            result_kind = str(request.query_params.get("pick_kind", "traditional") or "traditional").strip().lower()
            if result_kind not in WEEKLY_UNDERVALUED_FILE_PREFIX:
                result_kind = "traditional"
            pick_date = str(request.query_params.get("pick_date", "") or "").strip()
            result_market_filter = str(request.query_params.get("result_market", "ALL") or "ALL").strip().upper()
            result_season_filter = str(request.query_params.get("result_season", "ALL") or "ALL").strip().upper()

            def _match_result_market(ts_code, market_filter):
                code = str(ts_code or "").strip().upper()
                if market_filter in {"", "ALL", "A"}:
                    return True
                if market_filter in {"SH", "SSE", "60"}:
                    return code.startswith("60")
                if market_filter in {"SZ", "SZSE", "00"}:
                    return code.startswith("00")
                if market_filter in {"CYB", "GEM", "30"}:
                    return code.startswith("30")
                if market_filter in {"STAR", "KCB", "688", "KC"}:
                    return code.startswith("68")
                return True

            def _resolve_report_season(report_end_date):
                end_dt = _parse_date_like(report_end_date)
                if end_dt is None:
                    return ""
                md = end_dt.strftime("%m%d")
                if md == "0331":
                    return "Q1"
                if md == "0630":
                    return "H1"
                if md == "0930":
                    return "Q3"
                if md == "1231":
                    return "FY"
                return ""

            season_alias_map = {
                "Q1": "Q1",
                "H1": "H1",
                "HY": "H1",
                "S1": "H1",
                "Q3": "Q3",
                "FY": "FY",
                "ANNUAL": "FY",
                "Y": "FY",
            }
            normalized_result_season_filter = season_alias_map.get(result_season_filter, result_season_filter)
            result_style = _normalize_weekly_strategy_style(request.query_params.get("result_style"), "BALANCED")
            result_available_dates = _list_weekly_undervalued_dates(result_kind, result_style)
            all_rows, used_file = _load_weekly_undervalued_rows(result_kind, pick_date=pick_date, style=result_style)

            if result_market_filter not in {"", "ALL", "A"}:
                all_rows = [
                    row for row in all_rows
                    if _match_result_market(row.get("ts_code"), result_market_filter)
                ]

            if normalized_result_season_filter not in {"", "ALL"}:
                all_rows = [
                    row for row in all_rows
                    if _resolve_report_season(row.get("report_end_date")) == normalized_result_season_filter
                ]

            total = len(all_rows)
            records = all_rows[from_index:to_index]
            resolved_pick_date = pick_date
            if used_file is not None:
                match = re.search(r"(\d{4}-\d{2}-\d{2})", used_file.name)
                result_file_date = match.group(1) if match else None
                if not resolved_pick_date and result_file_date:
                    resolved_pick_date = result_file_date
        else:
            record_mode = "market"
            corp_qs = Corporation.objects.all().order_by("ts_code")
            prefixes = _market_prefixes(market)
            if prefixes:
                q_filter = Q()
                for prefix in prefixes:
                    q_filter |= Q(ts_code__startswith=prefix)
                corp_qs = corp_qs.filter(q_filter)
            total = corp_qs.count()
            records = list(corp_qs[from_index:to_index])

        if record_mode == "watchlist":
            ts_codes = [item.ts_code for item in records]
        elif record_mode == "market":
            ts_codes = [item.ts_code for item in records]
        else:
            ts_codes = [str(item.get("ts_code") or "").strip().upper() for item in records if item.get("ts_code")]
        corp_name_map = {}

        latest_trade_map = {}
        if ts_codes:
            trading_rows = (
                StockTradingHistory.objects.filter(ts_code__in=ts_codes, freq="D")
                .order_by("ts_code", "-trade_date")
                .values("ts_code", "trade_date", "close_qfq", "close")
            )
            for row in trading_rows:
                code = row.get("ts_code")
                if code in latest_trade_map:
                    continue
                latest_trade_map[code] = {
                    "trade_date": row.get("trade_date"),
                    "close": row.get("close_qfq") or row.get("close"),
                }

        latest_trade_dates = [
            _parse_date_like(payload.get("trade_date"))
            for payload in latest_trade_map.values()
            if payload.get("trade_date") is not None
        ]
        signal_end_date = max(latest_trade_dates) if latest_trade_dates else None

        requested_earnings_report_type = str(
            request.query_params.get("earnings_report_type", "") or ""
        ).strip().upper()
        report_type_alias_map = {
            "ANNUAL": "FY",
            "YEAR": "FY",
            "YEARLY": "FY",
            "S1": "H1",
            "HY": "H1",
        }
        requested_earnings_report_type = report_type_alias_map.get(
            requested_earnings_report_type,
            requested_earnings_report_type,
        )
        if requested_earnings_report_type not in {"Q1", "H1", "Q3", "FY"}:
            requested_earnings_report_type = ""

        method_map_by_code = {}
        if ts_codes:
            method_map_by_code = _build_latest_snapshot_method_map(
                ts_codes=ts_codes,
                market="CN",
                pick_strategy=LIVE_VALUATION_PICK_STRATEGY,
                max_trade_date=signal_end_date,
            )

        preferred_report_type_method_map_by_code = {}
        if ts_codes and record_mode != "result" and requested_earnings_report_type:
            preferred_report_type_method_map_by_code = _build_latest_snapshot_method_map(
                ts_codes=ts_codes,
                market="CN",
                pick_strategy=LIVE_VALUATION_PICK_STRATEGY,
                max_trade_date=signal_end_date,
                profit_report_type=requested_earnings_report_type,
            )

        anchored_method_map_by_code = {}
        earnings_report_type_map = {}
        earnings_end_date_map = {}
        for ts_code in ts_codes:
            current_payload = latest_trade_map.get(ts_code) or {}
            current_price = current_payload.get("close")
            raw_method_map = method_map_by_code.get(ts_code) or {}
            if record_mode != "result":
                preferred_method_map = preferred_report_type_method_map_by_code.get(ts_code) or {}
                if preferred_method_map:
                    raw_method_map = preferred_method_map
            filtered_method_map, anchor = _filter_method_map_to_latest_report(raw_method_map)

            anchor_end_date = _parse_date_like((anchor or {}).get("report_end_date"))
            anchor_report_type = str((anchor or {}).get("report_type") or "").strip().upper()
            selected_report_end_date = anchor_end_date
            selected_report_type = anchor_report_type if anchor_report_type in {"Q1", "H1", "Q3", "FY"} else ""
            if not selected_report_type and selected_report_end_date is not None:
                selected_report_type = _infer_report_type_from_end_date(selected_report_end_date)

            if record_mode == "result" or (record_mode != "result" and not requested_earnings_report_type):
                # Keep list/report period aligned with the latest published formal report.
                latest_panel_report_type, latest_panel_end_date = _resolve_latest_report_meta_from_feature_panel(
                    ts_code,
                    asof_date=signal_end_date,
                )
                if latest_panel_end_date is not None:
                    should_override_anchor = (
                        selected_report_end_date is None
                        or latest_panel_end_date > selected_report_end_date
                    )
                    if should_override_anchor:
                        selected_report_end_date = latest_panel_end_date
                        selected_report_type = latest_panel_report_type

            if selected_report_end_date is not None:
                latest_report_end_date_map[ts_code] = selected_report_end_date.strftime("%Y-%m-%d")
                earnings_end_date_map[ts_code] = selected_report_end_date

            if selected_report_type not in {"Q1", "H1", "Q3", "FY"}:
                selected_report_type = _infer_report_type_from_end_date(selected_report_end_date)
            if selected_report_type in {"Q1", "H1", "Q3", "FY"}:
                earnings_report_type_map[ts_code] = selected_report_type

            strict_method_map = filtered_method_map
            if selected_report_end_date is not None:
                strict_method_map = _filter_method_map_to_report_end_date(
                    raw_method_map,
                    selected_report_end_date,
                )

            anchored_method_map_by_code[ts_code] = strict_method_map
            summary = _summarize_buy_candidate(current_price, strict_method_map, 0.1)
            traditional_return_pct = _calc_return_pct(current_price, summary.get("composite_valuation_price"))
            if traditional_return_pct is None and selected_report_end_date is not None:
                selected_report_type_for_calc = selected_report_type
                if selected_report_type_for_calc not in {"Q1", "H1", "Q3", "FY"}:
                    selected_report_type_for_calc = _infer_report_type_from_end_date(selected_report_end_date)
                if selected_report_type_for_calc in {"Q1", "H1", "Q3", "FY"}:
                    try:
                        aligned_payload = _load_internal_stock_valuation_methods_payload(
                            ts_code,
                            freq="D",
                            earnings_report_type=selected_report_type_for_calc,
                            valuation_report_end_date=selected_report_end_date.strftime("%Y-%m-%d"),
                            valuation_band_pct=0.1,
                        ) or {}
                    except Exception:
                        aligned_payload = {}
                    aligned_summary = aligned_payload.get("summary") or {}
                    aligned_gap_pct = _to_float_or_none(aligned_summary.get("composite_valuation_gap_pct"))
                    if aligned_gap_pct is not None:
                        traditional_return_pct = round(float(aligned_gap_pct), 2)
            traditional_return_pct_map[ts_code] = traditional_return_pct

        if ts_codes and earnings_end_date_map:
            predictive_codes = [code for code in ts_codes if code in earnings_end_date_map]
            earnings_map = {}
            grouped_codes_by_report_type = {}
            grouped_end_date_map = {}
            for code in predictive_codes:
                grouped_rt = earnings_report_type_map.get(code) or "ALL"
                grouped_codes_by_report_type.setdefault(grouped_rt, []).append(code)
                grouped_end_date_map.setdefault(grouped_rt, {})[code] = earnings_end_date_map[code]

            for grouped_rt, grouped_codes in grouped_codes_by_report_type.items():
                unique_codes = list(dict.fromkeys(grouped_codes))
                if not unique_codes:
                    continue
                group_result, _group_stats = _fetch_earnings_signal_batch(
                    unique_codes,
                    report_type=grouped_rt,
                    return_stats=True,
                    financial_end_date_map=grouped_end_date_map.get(grouped_rt) or None,
                )
                earnings_map.update(group_result)

            for code in predictive_codes:
                earnings_payload = earnings_map.get(code) or {}
                current_price = _to_float_or_none((latest_trade_map.get(code) or {}).get("close"))
                target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_low_pct"))
                target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_high_pct"))
                target_price_low = _to_float_or_none(earnings_payload.get("target_price_low"))
                target_price_high = _to_float_or_none(earnings_payload.get("target_price_high"))
                target_price = _to_float_or_none(earnings_payload.get("target_price"))
                predictive_optimistic_target_price = target_price_high if target_price_high is not None else target_price
                predictive_conservative_target_price = target_price_low if target_price_low is not None else target_price

                optimistic_pct_recalc = _calc_return_pct(current_price, predictive_optimistic_target_price)
                conservative_pct_recalc = _calc_return_pct(current_price, predictive_conservative_target_price)

                predictive_optimistic_return_pct_map[code] = (
                    optimistic_pct_recalc
                    if optimistic_pct_recalc is not None
                    else (round(float(target_return_high_pct), 2) if target_return_high_pct is not None else None)
                )
                predictive_conservative_return_pct_map[code] = (
                    conservative_pct_recalc
                    if conservative_pct_recalc is not None
                    else (round(float(target_return_low_pct), 2) if target_return_low_pct is not None else None)
                )

        basic_info_map = {}
        prediction_map = {}
        if ts_codes:
            corp_rows = Corporation.objects.filter(ts_code__in=ts_codes).values("ts_code", "name")
            corp_name_map = {row["ts_code"]: row.get("name") for row in corp_rows}

            # Keep watchlist payload light; full prediction/detail payload is only needed for RESULT mode.
            if record_mode == "result":
                corp_basic_rows = CorporationBasic.objects.filter(ts_code__in=ts_codes)
                for basic in corp_basic_rows:
                    basic_info = (
                        basic.to_dict_short() if hasattr(basic, "to_dict_short") else {}
                    )
                    basic_info["website_url"] = _normalize_company_website_url(
                        basic_info.get("website")
                    )
                    basic_info_map[basic.ts_code] = basic_info

                prediction_rows = (
                    StockPrediction.objects.filter(ts_code__in=ts_codes)
                    .order_by("ts_code", "-trade_date")
                )
                for pred in prediction_rows:
                    if pred.ts_code in prediction_map:
                        continue
                    prediction_map[pred.ts_code] = pred.to_dict() if hasattr(pred, "to_dict") else {}
            else:
                corp_basic_rows = CorporationBasic.objects.filter(ts_code__in=ts_codes).values(
                    "ts_code", "website", "main_business"
                )
                for basic in corp_basic_rows:
                    basic_info_map[basic["ts_code"]] = {
                        "website": basic.get("website"),
                        "website_url": _normalize_company_website_url(basic.get("website")),
                        "main_business": basic.get("main_business"),
                    }

        data = []
        for item in records:
            if record_mode == "watchlist":
                item_dict = item.to_dict() if hasattr(item, "to_dict") else {}
                corp = getattr(item, "corporation", None)
                ts_code = item.ts_code
                # Prefer canonical corporation name so stale watchlist snapshots don't leak to UI.
                canonical_name = (getattr(corp, "name", "") or corp_name_map.get(ts_code, "") or "").strip()
                if canonical_name:
                    item_dict["name"] = canonical_name
            elif record_mode == "market":
                ts_code = item.ts_code
                item_dict = {
                    "ts_code": ts_code,
                    "name": getattr(item, "name", ""),
                    "is_enabled": False,
                    "hold_a_position": False,
                }
            else:
                ts_code = str(item.get("ts_code") or "").strip().upper()
                csv_undervalue_score = _to_float_or_none(item.get("undervalue_score") or item.get("valuation_score"))
                item_dict = {
                    "ts_code": ts_code,
                    "name": str(item.get("name") or corp_name_map.get(ts_code) or "").strip(),
                    "is_enabled": False,
                    "hold_a_position": False,
                    "screened_trade_date": item.get("trade_date"),
                    "undervalue_score": csv_undervalue_score,
                    "result_meta": {
                        "source_kind": str(item.get("source_kind") or "traditional"),
                        "report_end_date": item.get("report_end_date"),
                        "trade_date": item.get("trade_date"),
                        "undervalue_score": csv_undervalue_score,
                        "target_return_pct": item.get("target_return_pct"),
                        "traditional_return_pct": traditional_return_pct_map.get(ts_code),
                        "predictive_optimistic_return_pct": predictive_optimistic_return_pct_map.get(ts_code),
                        "predictive_conservative_return_pct": predictive_conservative_return_pct_map.get(ts_code),
                        "is_express": item.get("is_express"),
                        "profit_data_source": item.get("profit_data_source"),
                    },
                }

            result_meta = item_dict.get("result_meta") if isinstance(item_dict.get("result_meta"), dict) else {}
            result_meta["traditional_return_pct"] = traditional_return_pct_map.get(ts_code)
            result_meta["predictive_optimistic_return_pct"] = predictive_optimistic_return_pct_map.get(ts_code)
            result_meta["predictive_conservative_return_pct"] = predictive_conservative_return_pct_map.get(ts_code)
            result_meta["valuation_report_end_date"] = latest_report_end_date_map.get(ts_code)
            live_traditional_signal = None
            result_meta["traditional_signal_live"] = live_traditional_signal
            source_kind_text = str(result_meta.get("source_kind") or "").strip().lower()
            if record_mode == "result" and source_kind_text == "traditional":
                result_meta["traditional_signal"] = "BUY"
            else:
                result_meta["traditional_signal"] = live_traditional_signal
            item_dict["result_meta"] = result_meta

            item_dict["basic_info"] = basic_info_map.get(ts_code, {})
            if ts_code in prediction_map:
                item_dict["prediction"] = prediction_map.get(ts_code)

            current_payload = latest_trade_map.get(ts_code) or {}
            current_price = current_payload.get("close")
            method_map = anchored_method_map_by_code.get(ts_code) or {}
            summary = _summarize_buy_candidate(current_price, method_map, 0.1)
            composite_price = summary.get("composite_valuation_price")
            composite_status, composite_gap_pct = _classify_valuation(
                current_price,
                composite_price,
                0.1,
            )
            if record_mode == "result":
                aligned_payload = {}
                aligned_rows = []

                result_report_end_date = _parse_date_like(result_meta.get("report_end_date"))
                result_report_type = _infer_report_type_from_end_date(result_report_end_date)
                if result_report_type in {"Q1", "H1", "Q3", "FY"} and result_report_end_date is not None:
                    result_aligned_payload = _load_internal_stock_valuation_methods_payload(
                        ts_code,
                        freq="D",
                        earnings_report_type=result_report_type,
                        valuation_report_end_date=result_report_end_date.strftime("%Y-%m-%d"),
                        valuation_band_pct=0.1,
                    ) or {}
                    if result_aligned_payload.get("summary"):
                        aligned_payload = result_aligned_payload
                        aligned_rows = result_aligned_payload.get("data") or []
                        aligned_variant = str(result_aligned_payload.get("active_valuation_variant") or "").strip()
                        if aligned_variant:
                            result_meta["valuation_variant"] = aligned_variant

                aligned_summary = aligned_payload.get("summary") or {}
                aligned_price = _to_float_or_none(aligned_summary.get("composite_valuation_price"))
                aligned_status = str(aligned_summary.get("composite_valuation_status") or "unknown")
                aligned_gap_pct = _to_float_or_none(aligned_summary.get("composite_valuation_gap_pct"))
                if aligned_price is not None:
                    composite_price = round(float(aligned_price), 4)
                    composite_status = aligned_status
                    composite_gap_pct = aligned_gap_pct / 100.0 if aligned_gap_pct is not None else None
                    result_meta["traditional_return_pct"] = aligned_gap_pct
                    aligned_report_row = next(
                        (
                            row for row in aligned_rows
                            if row.get("profit_report_end_date") or row.get("profit_report_type")
                        ),
                        {},
                    )
                    result_meta["valuation_report_end_date"] = (
                        aligned_report_row.get("profit_report_end_date")
                        or result_meta.get("valuation_report_end_date")
                    )
            item_dict["valuation"] = {
                "current_price": round(float(current_price), 4) if current_price is not None else None,
                "latest_trade_date": current_payload.get("trade_date"),
                "composite_valuation_price": composite_price,
                "composite_valuation_status": composite_status,
                "composite_valuation_gap_pct": round(composite_gap_pct * 100, 2) if composite_gap_pct is not None else None,
            }
            data.append(item_dict)
        _attach_recent_financial_report_badge(data, market="CN")
        _attach_recent_forecast_badge(data, asof_date=signal_end_date or datetime.date.today(), window_days=60)
        if market == "RESULT":
            _attach_signal_window_returns(
                data,
                trade_date_for_query=signal_end_date or datetime.date.today(),
                freq="D",
                signal_end_date=signal_end_date,
            )
        if market == "RESULT":
            for item_dict in data:
                result_meta = item_dict.get("result_meta") if isinstance(item_dict.get("result_meta"), dict) else {}
                result_meta["since_pick_current_return_pct"] = item_dict.get("signal_current_return_pct")
                result_meta["since_pick_peak_return_pct"] = item_dict.get("signal_peak_return_pct")
                result_meta["since_pick_trough_return_pct"] = item_dict.get("signal_trough_return_pct")
                item_dict["result_meta"] = result_meta
        return Response(
            {
                "data": data,
                "from": from_index,
                "to": to_index,
                "total": total,
                "result_kind": result_kind if market == "RESULT" else None,
                "result_style": result_style if market == "RESULT" else None,
                "result_file_date": result_file_date if market == "RESULT" else None,
                "result_available_dates": result_available_dates if market == "RESULT" else [],
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_gain_loss_statistic(request, ts_code, freq, period):
    """
    Get stock gain/loss statistics for a specific stock.
    """
    try:
        records = StockGainLossQuantile.objects.filter(
            ts_code=ts_code, quantile=0.5, freq=freq, period=period
        ).order_by("-top_or_bottom")

        data = [
            {
                k: v
                for k, v in (
                    r.to_dict()
                    if hasattr(r, "to_dict")
                    else {
                        "top_or_bottom": getattr(r, "top_or_bottom", None),
                        "gain_loss": getattr(r, "gain_loss", None),
                        # Add other relevant fields as needed
                    }
                ).items()
                if k not in ["period", "ts_code", "quantile", "freq"]
            }
            for r in records
        ]
        if not data:
            return Response(
                {"error": "No gain/loss statistics found for given ts_code."},
                status=404,
            )
        return Response({"data": data, "ts_code": ts_code})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_recent_financial_updates(request):
    """Return stocks with financial/express announcements updated in recent N days."""
    try:
        try:
            days = int(request.query_params.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(days, 60))

        try:
            limit = int(request.query_params.get("limit", 5000))
        except (TypeError, ValueError):
            limit = 5000
        limit = max(1, min(limit, 20000))

        market = str(request.query_params.get("market", "CN") or "CN").strip().upper()
        scope = str(request.query_params.get("scope", "ALL") or "ALL").strip().upper()
        report_filter_raw = str(request.query_params.get("report", "ALL") or "ALL").strip().upper()

        if report_filter_raw in {"", "ALL", "A", "*"}:
            report_filter = "ALL"
        elif report_filter_raw in {"Q1", "H1", "Q3", "FY"}:
            report_filter = report_filter_raw
        elif report_filter_raw in {"快", "EXP", "EXPRESS"}:
            report_filter = "快"
        elif report_filter_raw in {"ANNUAL", "YEAR", "YEARLY"}:
            report_filter = "FY"
        else:
            report_filter = "ALL"

        asof_date = datetime.date.today()
        cutoff_date = asof_date - datetime.timedelta(days=days)

        report_suffix_map = {
            "Q1": {"0331"},
            "H1": {"0630"},
            "Q3": {"0930"},
            "FY": {"1231"},
            "ALL": {"0331", "0630", "0930", "1231"},
        }

        def _scope_match(ts_code):
            normalized_code = str(ts_code or "").strip().upper()
            if not normalized_code or scope in {"ALL", "A"}:
                return True
            if scope == "0":
                return normalized_code.startswith("00") or normalized_code.startswith("30")
            if scope == "6":
                return normalized_code.startswith("60") or normalized_code.startswith("68")
            return normalized_code.startswith(scope)

        def _build_daily_sync_summary():
            if report_filter == "快":
                return {
                    "daily": [],
                    "expected_total": 0,
                    "synced_total": 0,
                    "missing_total": 0,
                    "today_expected": 0,
                    "today_synced": 0,
                    "today_missing": 0,
                    "note": "快报仅统计 income 库中的快报更新",
                }

            suffix_allow = report_suffix_map.get(report_filter, report_suffix_map["ALL"])
            start_text = cutoff_date.strftime("%Y%m%d")
            end_text = asof_date.strftime("%Y%m%d")

            disclosure_sql = """
                SELECT ts_code, end_date, actual_date
                FROM earnings_fin_disclosure_date
                WHERE actual_date >= %s
                  AND actual_date <= %s
                  AND COALESCE(actual_date, '') <> ''
                  AND COALESCE(end_date, '') <> ''
            """
            disclosure_df = query_local_financial_df(disclosure_sql, [start_text, end_text])
            if disclosure_df is None or disclosure_df.empty:
                return {
                    "daily": [],
                    "expected_total": 0,
                    "synced_total": 0,
                    "missing_total": 0,
                    "today_expected": 0,
                    "today_synced": 0,
                    "today_missing": 0,
                    "note": "",
                }

            rows = []
            for row in disclosure_df.to_dict(orient="records"):
                ts_code = str(row.get("ts_code") or "").strip().upper()
                end_date_text = "".join(ch for ch in str(row.get("end_date") or "") if ch.isdigit())[:8]
                actual_date_value = _parse_date_like(row.get("actual_date"))
                if not ts_code or not end_date_text or actual_date_value is None:
                    continue
                if not _scope_match(ts_code):
                    continue
                if len(end_date_text) != 8:
                    continue
                if end_date_text[-4:] not in suffix_allow:
                    continue
                rows.append(
                    {
                        "ts_code": ts_code,
                        "end_date": end_date_text,
                        "actual_date": actual_date_value,
                    }
                )

            if not rows:
                return {
                    "daily": [],
                    "expected_total": 0,
                    "synced_total": 0,
                    "missing_total": 0,
                    "today_expected": 0,
                    "today_synced": 0,
                    "today_missing": 0,
                    "note": "",
                }

            unique_end_dates = sorted({item["end_date"] for item in rows})
            placeholders = ",".join(["%s"] * len(unique_end_dates))
            income_sql = f"""
                SELECT DISTINCT ts_code, end_date
                FROM earnings_fin_income
                WHERE end_date IN ({placeholders})
            """
            income_df = query_local_financial_df(income_sql, unique_end_dates)
            income_pair_set = set()
            if income_df is not None and not income_df.empty:
                for row in income_df.to_dict(orient="records"):
                    ts_code = str(row.get("ts_code") or "").strip().upper()
                    end_date_text = "".join(ch for ch in str(row.get("end_date") or "") if ch.isdigit())[:8]
                    if ts_code and len(end_date_text) == 8:
                        income_pair_set.add((ts_code, end_date_text))

            daily_counter = {}
            for item in rows:
                day_key = item["actual_date"].isoformat()
                payload = daily_counter.setdefault(
                    day_key,
                    {
                        "date": day_key,
                        "expected": 0,
                        "synced": 0,
                        "missing": 0,
                    },
                )
                payload["expected"] += 1
                if (item["ts_code"], item["end_date"]) in income_pair_set:
                    payload["synced"] += 1
                else:
                    payload["missing"] += 1

            cursor = cutoff_date
            daily_payload = []
            while cursor <= asof_date:
                key = cursor.isoformat()
                payload = daily_counter.get(
                    key,
                    {
                        "date": key,
                        "expected": 0,
                        "synced": 0,
                        "missing": 0,
                    },
                )
                expected_value = int(payload.get("expected") or 0)
                synced_value = int(payload.get("synced") or 0)
                missing_value = int(payload.get("missing") or 0)
                payload["sync_rate_pct"] = round((synced_value * 100.0 / expected_value), 2) if expected_value > 0 else None
                payload["missing_rate_pct"] = round((missing_value * 100.0 / expected_value), 2) if expected_value > 0 else None
                daily_payload.append(payload)
                cursor = cursor + datetime.timedelta(days=1)

            daily_payload.sort(key=lambda x: x.get("date", ""), reverse=True)

            expected_total = sum(int(item.get("expected") or 0) for item in daily_payload)
            synced_total = sum(int(item.get("synced") or 0) for item in daily_payload)
            missing_total = sum(int(item.get("missing") or 0) for item in daily_payload)

            today_key = asof_date.isoformat()
            today_payload = next((x for x in daily_payload if x.get("date") == today_key), None) or {}

            return {
                "daily": daily_payload,
                "expected_total": expected_total,
                "synced_total": synced_total,
                "missing_total": missing_total,
                "today_expected": int(today_payload.get("expected") or 0),
                "today_synced": int(today_payload.get("synced") or 0),
                "today_missing": int(today_payload.get("missing") or 0),
                "note": "",
            }

        def _matches_scope(ts_code):
            normalized_code = str(ts_code or "").strip().upper()
            if not normalized_code or scope in {"ALL", "A"}:
                return True
            if scope == "0":
                return normalized_code.startswith("00") or normalized_code.startswith("30")
            if scope == "6":
                return normalized_code.startswith("60") or normalized_code.startswith("68")
            return normalized_code.startswith(scope)

        snapshot_rows = (
            StockValuationSnapshotLatest.objects.filter(market=market)
            .filter(
                Q(profit_report_ann_date__gte=cutoff_date)
                | Q(express_ann_date__gte=cutoff_date)
            )
            .values(
                "ts_code",
                "latest_trade_date",
                "profit_report_ann_date",
                "profit_report_type",
                "profit_data_source",
                "express_ann_date",
            )
        )

        latest_map = {}
        for row in snapshot_rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if not ts_code or not _matches_scope(ts_code):
                continue

            latest_trade_date = _parse_date_like(row.get("latest_trade_date"))
            candidates = []

            profit_ann_date = _parse_date_like(row.get("profit_report_ann_date"))
            if profit_ann_date is not None:
                label = _normalize_recent_report_label(
                    report_type=row.get("profit_report_type"),
                    profit_source=row.get("profit_data_source"),
                    ann_date=profit_ann_date,
                    express_ann_date=_parse_date_like(row.get("express_ann_date")),
                )
                candidates.append((profit_ann_date, label))

            express_ann_date = _parse_date_like(row.get("express_ann_date"))
            if express_ann_date is not None:
                candidates.append((express_ann_date, "快"))

            if latest_trade_date is not None:
                candidates = [item for item in candidates if item[0] <= latest_trade_date]

            candidates = [item for item in candidates if cutoff_date <= item[0] <= asof_date]
            if not candidates:
                continue

            ann_date, label = max(candidates, key=_recent_report_candidate_sort_key)
            if report_filter != "ALL" and str(label or "") != report_filter:
                continue
            existing = latest_map.get(ts_code)
            if existing is None or _recent_report_candidate_sort_key((ann_date, label)) > _recent_report_candidate_sort_key((existing["ann_date"], existing["label"])):
                latest_map[ts_code] = {
                    "ann_date": ann_date,
                    "label": label,
                    "days": (asof_date - ann_date).days,
                }

        if not latest_map:
            sync_summary = _build_daily_sync_summary()
            return Response(
                {
                    "data": [],
                    "total": 0,
                    "days": days,
                    "scope": scope,
                    "report": report_filter,
                    "asof_date": asof_date.isoformat(),
                    "market": market,
                    "summary": {
                        "updates_total": 0,
                        "label_counts": {},
                        "sync": sync_summary,
                    },
                }
            )

        sorted_codes = sorted(
            latest_map.keys(),
            key=lambda code: _recent_report_candidate_sort_key((latest_map[code]["ann_date"], latest_map[code]["label"])),
            reverse=True,
        )
        selected_codes = sorted_codes[:limit]

        corp_rows = Corporation.objects.filter(ts_code__in=selected_codes).values("ts_code", "name")
        corp_name_map = {row["ts_code"]: (row.get("name") or "") for row in corp_rows}

        basic_info_map = {}
        for basic in CorporationBasic.objects.filter(ts_code__in=selected_codes):
            basic_info_map[basic.ts_code] = basic.to_dict_short() if hasattr(basic, "to_dict_short") else {}

        data = []
        label_counts = {}
        for ts_code in selected_codes:
            payload = latest_map.get(ts_code)
            if payload is None:
                continue
            label_text = str(payload.get("label") or "")
            if label_text:
                label_counts[label_text] = int(label_counts.get(label_text) or 0) + 1
            data.append(
                {
                    "ts_code": ts_code,
                    "name": corp_name_map.get(ts_code, ""),
                    "basic_info": basic_info_map.get(ts_code, {}),
                    "latest_financial_ann_date": payload["ann_date"].isoformat(),
                    "recent_report_days": payload["days"],
                    "recent_report_label": payload.get("label"),
                    "recent_report_badge": True,
                }
            )

        sync_summary = _build_daily_sync_summary()

        return Response(
            {
                "data": data,
                "total": len(data),
                "days": days,
                "scope": scope,
                "report": report_filter,
                "asof_date": asof_date.isoformat(),
                "market": market,
                "summary": {
                    "updates_total": len(data),
                    "label_counts": label_counts,
                    "sync": sync_summary,
                },
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_list(request, from_index, to_index):
    # Dummy response, replace with actual logic
    try:
        from_index = int(from_index)
        to_index = int(to_index)
        queryset = Corporation.objects.all().order_by("ts_code")
        total = queryset.count()
        records = queryset[from_index:to_index]
        data = [
            {
                "ts_code": corp.ts_code,
                "name": corp.name,
                "fullname": corp.fullname,
                "enname": corp.enname,
                "listdate": corp.list_date,
                "cnspell": corp.cnspell,
            }
            for corp in records
        ]
        return Response(
            {"data": data, "from": from_index, "to": to_index, "total": total}
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_basic(request, ts_code):
    # Dummy response, replace with actual logic
    try:
        corp_basic = CorporationBasic.objects.filter(ts_code=ts_code).first()
        if not corp_basic:
            return Response(
                {"error": "No basic information found for given ts_code."}, status=404
            )
        data = (
            corp_basic.to_dict()
            if hasattr(corp_basic, "to_dict")
            else {
                "ts_code": corp_basic.ts_code,
                "name": corp_basic.basic_info.name,
                "industry": getattr(corp_basic, "industry", None),
                "market": getattr(corp_basic, "market", None),
                "list_date": getattr(corp_basic, "list_date", None),
                # Add other fields as needed
            }
        )
        data["website_url"] = _normalize_company_website_url(data.get("website"))
        return Response({"data": data, "ts_code": ts_code})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_prediction_result(
    request, ts_code, model, volatility, period, freq, version
):
    # Dummy response, replace with actual logic
    try:
        filters = {}
        excludes = [
            "id",
            "created_at",
            "corporation",
            "freq",
            "applied_model",
            "model_version",
            "volatility",
        ]

        if ts_code:
            filters["ts_code"] = ts_code
        if model:
            filters["applied_model"] = model
        if volatility:
            filters["volatility"] = volatility
        if period:
            try:
                period_days = int(period)
                today = datetime.date.today()
                start_date = today - datetime.timedelta(days=period_days)
                filters["trade_date__gte"] = start_date
                filters["trade_date__lte"] = today
                del filters["prediction_date"]
            except Exception:
                pass
        if freq:
            filters["freq"] = freq
        if version:
            filters["model_version"] = version

        records = StockPrediction.objects.filter(
            **filters, top_or_bottom__in=["B", "T"]
        ).order_by("-trade_date")
        data = [
            {k: v for k, v in r.to_dict().items() if k not in excludes} for r in records
        ]
        if not data:
            return Response(
                {"error": "No prediction results found for given parameters."},
                status=404,
            )
        return Response({"data": data, **filters})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_all_stocks_prediction_result(request):
    ts_code = request.GET.get("ts_code")
    model_name = request.GET.get("model_name")
    volatility = request.GET.get("volatility")
    trade_date = request.GET.get("trade_date")
    freq = request.GET.get("freq")
    from_index = int(request.GET.get("from", 0))
    to_index = int(request.GET.get("to", from_index + 50))

    try:
        filters = {}
        excludes = [
            "id",
            "created_at",
            "corporation",
            "freq",
            "applied_model",
            "model_version",
            "volatility",
        ]
        if ts_code:
            filters["ts_code"] = ts_code
        if model_name:
            filters["model_name"] = model_name
        if volatility:
            filters["volatility"] = volatility
        if trade_date:
            filters["prediction_date"] = trade_date
        if freq:
            filters["freq"] = freq

        queryset = StockPrediction.objects.filter(**filters).order_by("-trade_date")
        total_count = queryset.count()
        records = queryset[from_index:to_index]
        data = [
            {k: v for k, v in r.to_dict().items() if k not in excludes} for r in records
        ]
        if not data:
            return Response(
                {"error": "No prediction results found for given parameters."},
                status=404,
            )
        return Response(
            {
                "data": data,
                "from": from_index,
                "to": to_index,
                "total": total_count,
                **filters,
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


from django.db.models import Value, CharField


@api_view(["GET"])
def get_latest_trade_date(request, freq):
    try:
        normalized_freq = str(freq or "D").strip().upper()
        latest_trade_date = StockTradingHistory.objects.filter(
            freq=normalized_freq
        ).aggregate(latest_date=Max("trade_date"))["latest_date"]
        return Response(
            {
                "freq": normalized_freq,
                "latest_trade_date": latest_trade_date.strftime("%Y-%m-%d") if latest_trade_date else None,
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def pick_stocks_by_params(
    request,
    trade_date,
    scope,
    model,
    model_version,
    top_bottom,
    freq,
    period,
    params,
    from_index,
    to_index,
    forced_valuation_method=None,
    forced_valuation_band_pct=None,
    forced_valuation_pick_strategy=None,
    force_need_valuation=False,
    strict_snapshot_only=False,
):
    try:
        latest_trade_date_for_freq = StockTradingHistory.objects.filter(
            freq=freq
        ).aggregate(latest_date=Max("trade_date"))["latest_date"]
        requested_trade_date_has_data = StockTradingHistory.objects.filter(
            trade_date=trade_date,
            freq=freq,
        ).exists()

        valuation_method = (
            request.query_params.get("valuation_method", "") if hasattr(request, "query_params") else ""
        )
        valuation_status = (
            request.query_params.get("valuation_status", "") if hasattr(request, "query_params") else ""
        )
        valuation_band_pct_raw = (
            request.query_params.get("valuation_band_pct", "0.1") if hasattr(request, "query_params") else "0.1"
        )
        valuation_pick_strategy_raw = (
            request.query_params.get("valuation_pick_strategy", LIVE_VALUATION_PICK_STRATEGY)
            if hasattr(request, "query_params")
            else LIVE_VALUATION_PICK_STRATEGY
        )
        buy_candidate_only_raw = (
            request.query_params.get("buy_candidate_only", "") if hasattr(request, "query_params") else ""
        )
        if forced_valuation_method is not None:
            valuation_method = forced_valuation_method
        if forced_valuation_band_pct is not None:
            valuation_band_pct_raw = forced_valuation_band_pct
        if forced_valuation_pick_strategy is not None:
            valuation_pick_strategy_raw = forced_valuation_pick_strategy

        try:
            valuation_band_pct = max(0.01, float(valuation_band_pct_raw))
        except (TypeError, ValueError):
            valuation_band_pct = 0.1

        buy_candidate_only = str(buy_candidate_only_raw).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }
        valuation_business_topn_raw = (
            request.query_params.get(
                "valuation_business_topn",
                str(LIVE_VALUATION_BUSINESS_MATCH_TOPN),
            )
            if hasattr(request, "query_params")
            else str(LIVE_VALUATION_BUSINESS_MATCH_TOPN)
        )
        try:
            valuation_business_topn = max(0, int(valuation_business_topn_raw))
        except (TypeError, ValueError):
            valuation_business_topn = LIVE_VALUATION_BUSINESS_MATCH_TOPN
        valuation_pick_strategy = _normalize_pick_strategy(valuation_pick_strategy_raw)

        valuation_status = str(valuation_status).strip().lower()
        valuation_method = str(valuation_method).strip().lower()
        selected_valuation_method = valuation_method or ("pe" if valuation_status else "")
        if force_need_valuation and not selected_valuation_method:
            selected_valuation_method = "pe"
        need_valuation = bool(selected_valuation_method or valuation_status or force_need_valuation)

        # Step 1: Filter predictions according to scope
        if top_bottom == "B,T":
            prediction_qs = StockTradingHistory.objects.filter(
                trade_date=trade_date,
                freq=freq,
            ).values(
                "ts_code",
                "trade_date",
                top_or_bottom=Value("", output_field=CharField()),
            )

        else:
            prediction_qs = StockPrediction.objects.filter(
                trade_date=trade_date,
                applied_model=model,
                model_version=model_version,
                freq=freq,
                top_or_bottom__in=[top_bottom],
            )
        if not prediction_qs.exists():
            return Response(
                {
                    "data": [],
                    "trade_date": trade_date,
                    "model_name": model,
                    "freq": freq,
                    "params": params,
                    "meta": {
                        "latest_trade_date_for_freq": latest_trade_date_for_freq,
                        "requested_trade_date_has_data": requested_trade_date_has_data,
                    },
                },
                status=200,
            )
        if scope.isdigit():
            prediction_qs = prediction_qs.filter(ts_code__startswith=scope)
        elif scope == "WATCHLIST":
            hold_codes = list(
                UserWatchlist.objects.filter(is_enabled=True).values_list(
                    "ts_code", flat=True
                )
            )
            prediction_qs = prediction_qs.filter(ts_code__in=hold_codes)
        screened_stocks = list(prediction_qs.values_list("ts_code", "top_or_bottom"))

        param_list = [p for p in params.split("|") if p.strip()]
        freq_days_map = {"D": 1, "W": 7, "M": 30}
        base_days = freq_days_map.get(freq, 1)
        period_days = base_days * int(period) if period else base_days
        end_date = datetime.datetime.strptime(trade_date, "%Y-%m-%d").date()
        start_date = end_date - datetime.timedelta(days=period_days - 1)

        ts_codes = [ts_code for ts_code, _ in screened_stocks]
        valuation_snapshot_map = _build_snapshot_method_map(
            ts_codes=ts_codes,
            trade_date=trade_date,
            market="CN",
            pick_strategy=valuation_pick_strategy,
        )
        (
            trading_fields,
            fundamental_fields,
            feature_fields,
            feature_diff_fields,
            stat_params,
            feature_params,
            feature_diff_params,
        ) = (
            set(),
            set(),
            set(),
            set(),
            [],
            [],
            [],
        )
        for param in param_list:
            key_param = param.split(":")
            if len(key_param) < 2:
                continue
            field_name = key_param[1][1:].lower()
            if key_param[1].startswith("T"):
                trading_fields.add(field_name)
            elif key_param[1].startswith("F"):
                fundamental_fields.add(field_name)
            if key_param[0] == "STAT":
                stat_params.append((key_param[0], key_param[1], field_name))
            if key_param[0] == "COST":
                winner_rate = int(key_param[1])
                cost_qs = StockCostHistory.objects.filter(
                    ts_code__in=ts_codes,
                    winner_rate__gte=winner_rate,
                    trade_date__gte=start_date.strftime("%Y-%m-%d"),
                    trade_date=trade_date,
                )
                ts_codes = list(cost_qs.values_list("ts_code", flat=True))
                stat_params.append((key_param[0], key_param[1], key_param[1]))
            if key_param[0] == "FEAT":
                feature_param = key_param[1]
                feature_fields.add(feature_param.lower())
                feature_params.append(feature_param.lower())
        
        diff_param = params.split(":")
        chg_pct = None     
        if diff_param[0] == "FEAT_DIFF":
            parts = diff_param[1].split("|")
            if len(parts) >= 4:
                chg_pct = float(parts[-1])
                period = parts[-2] if len(parts) >= 2 else None
                for raw_field in parts[:2]:
                    field_name = f"{raw_field.replace('X', period)}_DIFF".lower()
                    feature_diff_fields.add(field_name)
                    feature_diff_params.append(field_name)
                

        def fetch_data(model_cls, ts_code, freq, start_date, end_date, fields):
            if not fields:
                return []
            qs = model_cls.objects.filter(
                ts_code=ts_code,
                freq=freq,
                trade_date__gte=start_date.strftime("%Y-%m-%d"),
                trade_date__lte=end_date.strftime("%Y-%m-%d"),
            ).values("ts_code", "trade_date", *fields)
            return list(qs)

        def get_latest_record(model_cls, ts_code, freq, end_date):
            latest_date = model_cls.objects.filter(
                ts_code=ts_code,
                freq=freq,
                trade_date__lte=end_date.strftime("%Y-%m-%d"),
            ).aggregate(latest_date=Max("trade_date"))["latest_date"]
            if latest_date:
                rec = model_cls.objects.filter(
                    ts_code=ts_code, freq=freq, trade_date=latest_date
                ).first()
                return rec.to_dict() if rec and hasattr(rec, "to_dict") else {}
            return {}

        result = []
        count = 0
        for ts_code, top_or_bottom in screened_stocks:
            if ts_code not in ts_codes or count >= to_index:
                continue
            passed = True
            quantile_value = None
            for filter_type, param_type, field_name in stat_params:
                df = pd.DataFrame()
                if filter_type == "STAT":
                    if param_type.startswith("T"):
                        df = pd.DataFrame(
                            fetch_data(
                                StockTradingHistory,
                                ts_code,
                                freq,
                                start_date,
                                end_date,
                                trading_fields,
                            )
                        )
                    elif param_type.startswith("F"):
                        df = pd.DataFrame(
                            fetch_data(
                                StockFundamentalHistory,
                                ts_code,
                                freq,
                                start_date,
                                end_date,
                                fundamental_fields,
                            )
                        )
                    if not df.empty:
                        result_value, _, quantile_value = (
                            is_last_row_value_below_quantile(
                                df, field_name, quantile=0.1
                            )
                        )
                        if not result_value:
                            passed = False
                            break

            for filter_type in feature_params:
                df = pd.DataFrame(
                    fetch_data(
                        StockCombinedFeature,
                        ts_code,
                        freq,
                        end_date,
                        end_date,
                        feature_fields,
                    )
                )
                if not df.empty:
                    for field in feature_fields:
                        if df[field].iloc[0] != "1":
                            passed = False
                            break
                        
            for filter_type in feature_diff_params: 
                df = pd.DataFrame(
                    fetch_data(
                        StockCombinedFeature,
                        ts_code,
                        freq,
                        end_date,
                        end_date,
                        feature_diff_fields,
                    )
                )  
                
                if not df.empty:
                    # close price in low price
                    if df[feature_diff_params[0]].iloc[0] > 0.0:                            
                        passed = False
                        break
                    if df[feature_diff_params[1]].iloc[0] < chg_pct:
                        passed = False
                        break
                        
                        
            if passed:
                corp_obj = Corporation.objects.filter(ts_code=ts_code).first()
                corp_basic_obj = getattr(corp_obj, "basic_info", None)
                corp_basic = {}

                if corp_basic_obj and hasattr(corp_basic_obj, "first"):
                    basic = corp_basic_obj.first()
                    corp_basic = (
                        basic.to_dict_short()
                        if basic and hasattr(basic, "to_dict_short")
                        else {}
                    )
                latest_trading = get_latest_record(
                    StockTradingHistory, ts_code, freq, end_date
                )
                latest_fundamental = get_latest_record(
                    StockFundamentalHistory, ts_code, freq, end_date
                )
                valuation_payload = {
                    "valuation_method": None,
                    "valuation_price": None,
                    "valuation_market_cap": None,
                    "valuation_status": "unknown",
                    "valuation_gap_pct": None,
                    "valuation_source": "none",
                }
                current_price = latest_trading.get("close_qfq") or latest_trading.get("close")
                buy_candidate_payload = _summarize_buy_candidate(
                    current_price=current_price,
                    method_map=valuation_snapshot_map.get(ts_code, {}),
                    band_pct=valuation_band_pct,
                )
                if buy_candidate_only and not buy_candidate_payload.get("buy_candidate"):
                    continue
                if need_valuation:
                    valuation_payload = _evaluate_stock_valuation(
                        ts_code=ts_code,
                        trade_date=trade_date,
                        selected_method=selected_valuation_method,
                        current_price=current_price,
                        band_pct=valuation_band_pct,
                        market="CN",
                        corporation=corp_obj,
                        business_match_topn=valuation_business_topn,
                        pick_strategy=valuation_pick_strategy,
                        strict_snapshot_only=strict_snapshot_only,
                    )
                    if valuation_status and valuation_payload.get("valuation_status") != valuation_status:
                        continue

                result.append(
                    {
                        "ts_code": ts_code,
                        "name": getattr(corp_obj, "name", None),
                        "top_or_bottom": top_or_bottom,
                        **{
                            k: v
                            for k, v in (corp_basic or {}).items()
                            if k
                            not in [
                                "id",
                                "ts_code",
                                "trade_date",
                                "area",
                                "city",
                                "corporation",
                            ]
                        },
                        "website_url": _normalize_company_website_url(corp_basic.get("website")),
                        **latest_trading,
                        **latest_fundamental,
                        **valuation_payload,
                        **buy_candidate_payload,
                        "quantile_param": (
                            round(quantile_value, 2)
                            if quantile_value is not None
                            else None
                        ),
                    }
                )
                count += 1

        paged_result = result[from_index:to_index]
        _attach_recent_financial_report_badge(paged_result, asof_date=trade_date, market="CN")
        return Response(
            {
                "data": paged_result,
                "trade_date": trade_date,
                "model_name": model,
                "freq": freq,
                "params": params,
                "valuation_filter": {
                    "method": selected_valuation_method,
                    "status": valuation_status,
                    "band_pct": valuation_band_pct,
                    "buy_candidate_only": buy_candidate_only,
                    "business_topn": valuation_business_topn,
                    "pick_strategy": valuation_pick_strategy,
                    "strict_snapshot_only": strict_snapshot_only,
                },
                "meta": {
                    "latest_trade_date_for_freq": latest_trade_date_for_freq,
                    "requested_trade_date_has_data": requested_trade_date_has_data,
                },
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def pick_stocks_by_valuation(
    request,
    trade_date,
    scope,
    model,
    model_version,
    top_bottom,
    freq,
    period,
    params,
    from_index,
    to_index,
):
    normalized_freq = str(freq or "D").strip().upper()
    try:
        from_index_int = int(from_index)
    except (TypeError, ValueError):
        from_index_int = 0
    try:
        to_index_int = int(to_index)
    except (TypeError, ValueError):
        to_index_int = from_index_int + 25
    return _pick_stocks_by_valuation_fast(
        request=request,
        trade_date=trade_date,
        scope=scope,
        freq=normalized_freq,
        from_index=from_index_int,
        to_index=to_index_int,
    )


def _parse_date_like(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        text = text[:10]
        try:
            return datetime.datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        try:
            return datetime.datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _resolve_report_type_from_end_date(report_end_date):
    end_dt = _parse_date_like(report_end_date)
    if end_dt is None:
        return None
    md = end_dt.strftime("%m%d")
    if md == "0331":
        return "Q1"
    if md == "0630":
        return "H1"
    if md == "0930":
        return "Q3"
    if md == "1231":
        return "FY"
    return None


def _recent_report_candidate_sort_key(candidate):
    ann_date, label = candidate
    return (ann_date, 0 if str(label or "") == "快" else 1)


def _build_latest_official_financial_ann_date_map(ts_codes, max_trade_date=None):
    if not ts_codes:
        return {}

    ann_map = {}
    for ts_code in ts_codes:
        normalized_ts_code = str(ts_code or "").strip().upper()
        if not normalized_ts_code:
            continue
        try:
            df = fetch_tushare_data(normalized_ts_code, "INDICATOR")
        except Exception:
            continue
        if df is None or df.empty or "ann_date" not in df.columns or "end_date" not in df.columns:
            continue

        latest_payload = None
        for _, source_row in df.iterrows():
            end_date = _parse_date_like(source_row.get("end_date"))
            ann_date = _parse_date_like(source_row.get("ann_date"))
            end_date, ann_date = _normalize_report_dates(end_date, ann_date)
            label = _resolve_report_type_from_end_date(end_date)
            if ann_date is None or label is None:
                continue
            if max_trade_date is not None and ann_date > max_trade_date:
                continue
            payload = {"ann_date": ann_date, "label": label}
            if latest_payload is None or _recent_report_candidate_sort_key((ann_date, label)) > _recent_report_candidate_sort_key((latest_payload["ann_date"], latest_payload["label"])):
                latest_payload = payload

        if latest_payload is not None:
            ann_map[normalized_ts_code] = latest_payload
    return ann_map


def _build_latest_financial_ann_date_map(ts_codes, market="CN", max_trade_date=None):
    if not ts_codes:
        return {}

    queryset = StockValuationSnapshotLatest.objects.filter(
        ts_code__in=ts_codes,
        market=market,
    )
    if max_trade_date is not None:
        queryset = queryset.filter(latest_trade_date__lte=max_trade_date)

    rows = queryset.values(
        "ts_code",
        "latest_trade_date",
        "profit_report_end_date",
        "profit_report_ann_date",
        "profit_report_type",
        "profit_data_source",
        "express_ann_date",
    )

    ann_map = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code:
            continue
        snapshot_trade_date = _parse_date_like(row.get("latest_trade_date"))
        report_end_date = _parse_date_like(row.get("profit_report_end_date"))
        profit_ann_date = _parse_date_like(row.get("profit_report_ann_date"))
        _, normalized_profit_ann_date = _normalize_report_dates(report_end_date, profit_ann_date)
        express_ann_date = _parse_date_like(row.get("express_ann_date"))
        report_type = row.get("profit_report_type")
        profit_source = row.get("profit_data_source")

        candidates = []
        for candidate, label in [
            (
                normalized_profit_ann_date,
                _normalize_recent_report_label(
                    report_type=report_type,
                    profit_source=profit_source,
                    ann_date=normalized_profit_ann_date,
                    express_ann_date=express_ann_date,
                ),
            ),
            (express_ann_date, "快"),
        ]:
            if candidate is None:
                continue
            if snapshot_trade_date is not None and candidate > snapshot_trade_date:
                continue
            candidates.append((candidate, label))
        if not candidates:
            continue

        latest_ann_date, latest_label = max(candidates, key=_recent_report_candidate_sort_key)
        previous = ann_map.get(ts_code)
        if previous is None or _recent_report_candidate_sort_key((latest_ann_date, latest_label)) > _recent_report_candidate_sort_key((previous.get("ann_date"), previous.get("label"))):
            ann_map[ts_code] = {
                "ann_date": latest_ann_date,
                "label": latest_label,
            }
    return ann_map


def _normalize_recent_report_label(*, report_type=None, profit_source=None, ann_date=None, express_ann_date=None):
    source_text = str(profit_source or "").strip().lower()
    if source_text.startswith("express"):
        return "快"

    if ann_date is not None and express_ann_date is not None and ann_date == express_ann_date:
        return "快"

    normalized_type = str(report_type or "").strip().upper()
    if not normalized_type:
        return None

    if normalized_type in {"ANNUAL", "YEAR", "YEARLY", "FY"}:
        return "FY"
    if normalized_type in {"Q1", "FIRST_QUARTER"}:
        return "Q1"
    if normalized_type in {"Q3", "THIRD_QUARTER"}:
        return "Q3"
    if normalized_type in {"S1", "H1", "SEMI", "SEMIANNUAL", "SEMI_ANNUAL", "HALF_YEAR", "HY"}:
        return "H1"
    if normalized_type in {"H2", "SECOND_HALF"}:
        return "H2"
    return None


def _attach_recent_financial_report_badge(
    rows,
    *,
    asof_date=None,
    market="CN",
    include_official_ann_lookup=True,
):
    if not rows:
        return

    normalized_asof_date = _parse_date_like(asof_date)
    missing_codes = []
    for row in rows:
        row["latest_financial_ann_date"] = None
        row["recent_report_badge"] = False
        row["recent_report_days"] = None
        row["recent_report_label"] = None

        ann_date = None
        for candidate in [
            _parse_date_like(row.get("financial_ann_date")),
            _parse_date_like(row.get("valuation_profit_report_ann_date")),
            _parse_date_like(row.get("profit_report_ann_date")),
            _parse_date_like(row.get("valuation_express_ann_date")),
            _parse_date_like(row.get("express_ann_date")),
        ]:
            if candidate is not None and (ann_date is None or candidate > ann_date):
                ann_date = candidate
        if ann_date is None:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if ts_code:
                missing_codes.append(ts_code)

    fallback_ann_map = _build_latest_financial_ann_date_map(
        sorted(set(missing_codes)),
        market=market,
        max_trade_date=normalized_asof_date,
    )

    official_ann_map = {}
    if include_official_ann_lookup:
        official_override_codes = []
        for row in rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if not ts_code:
                continue
            fallback_payload = fallback_ann_map.get(ts_code) or {}
            if (
                _parse_date_like(row.get("valuation_express_ann_date")) is not None
                or _parse_date_like(row.get("express_ann_date")) is not None
                or fallback_payload.get("label") == "快"
            ):
                official_override_codes.append(ts_code)

        official_ann_map = _build_latest_official_financial_ann_date_map(
            sorted(set(official_override_codes)),
            max_trade_date=normalized_asof_date,
        )

    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        effective_asof_date = (
            _parse_date_like(row.get("earnings_asof_date"))
            or _parse_date_like(row.get("trade_date"))
            or _parse_date_like(row.get("latest_trade_date"))
            or _parse_date_like((row.get("valuation") or {}).get("latest_trade_date"))
            or normalized_asof_date
        )

        valuation_report_type = row.get("valuation_profit_report_type")
        base_report_type = row.get("profit_report_type")
        earnings_report_type = row.get("earnings_report_type")

        valuation_profit_ann = _parse_date_like(row.get("valuation_profit_report_ann_date"))
        base_profit_ann = _parse_date_like(row.get("profit_report_ann_date"))
        financial_ann = _parse_date_like(row.get("financial_ann_date"))
        valuation_express_ann = _parse_date_like(row.get("valuation_express_ann_date"))
        base_express_ann = _parse_date_like(row.get("express_ann_date"))

        candidates = []

        if financial_ann is not None:
            candidates.append(
                (
                    financial_ann,
                    _normalize_recent_report_label(report_type=earnings_report_type),
                )
            )
        if valuation_profit_ann is not None:
            candidates.append(
                (
                    valuation_profit_ann,
                    _normalize_recent_report_label(
                        report_type=valuation_report_type,
                        profit_source=row.get("valuation_profit_data_source"),
                        ann_date=valuation_profit_ann,
                        express_ann_date=valuation_express_ann,
                    ),
                )
            )
        if base_profit_ann is not None:
            candidates.append(
                (
                    base_profit_ann,
                    _normalize_recent_report_label(
                        report_type=base_report_type,
                        profit_source=row.get("profit_data_source"),
                        ann_date=base_profit_ann,
                        express_ann_date=base_express_ann,
                    ),
                )
            )
        if valuation_express_ann is not None:
            candidates.append((valuation_express_ann, "快"))
        if base_express_ann is not None:
            candidates.append((base_express_ann, "快"))

        fallback_payload = fallback_ann_map.get(ts_code) or {}
        fallback_ann = fallback_payload.get("ann_date")
        fallback_label = fallback_payload.get("label")
        if fallback_ann is not None:
            candidates.append((fallback_ann, fallback_label))

        official_payload = official_ann_map.get(ts_code) or {}
        official_ann = official_payload.get("ann_date")
        official_label = official_payload.get("label")
        if official_ann is not None:
            candidates.append((official_ann, official_label))

        if effective_asof_date is not None:
            candidates = [item for item in candidates if item[0] <= effective_asof_date]

        ann_date = None
        label = None
        if candidates:
            ann_date, label = max(candidates, key=_recent_report_candidate_sort_key)

        if ann_date is None:
            continue

        row["latest_financial_ann_date"] = ann_date.isoformat()
        row["recent_report_label"] = label
        if effective_asof_date is None or ann_date > effective_asof_date:
            continue

        delta_days = (effective_asof_date - ann_date).days
        if 0 <= delta_days <= RECENT_FINANCIAL_ANNOUNCEMENT_DAYS:
            row["recent_report_badge"] = True
            row["recent_report_days"] = delta_days


def _format_forecast_amount_yi_from_wan(value):
    amount_wan = _to_float_or_none(value)
    if amount_wan is None:
        return None
    return round(amount_wan / 10000.0, 2)


def _format_forecast_pct(value):
    pct = _to_float_or_none(value)
    if pct is None:
        return None
    return round(pct, 2)


def _build_forecast_narrative(payload):
    ann_date = str(payload.get("ann_date") or "-")
    end_date = str(payload.get("end_date") or "-")
    forecast_type = str(payload.get("type") or "").strip() or "预告"
    summary = str(payload.get("summary") or "").strip()
    reason = str(payload.get("change_reason") or "").strip()

    net_profit_min_yi = _format_forecast_amount_yi_from_wan(payload.get("net_profit_min"))
    net_profit_max_yi = _format_forecast_amount_yi_from_wan(payload.get("net_profit_max"))
    p_change_min = _format_forecast_pct(payload.get("p_change_min"))
    p_change_max = _format_forecast_pct(payload.get("p_change_max"))

    parts = [f"{ann_date} 发布 {end_date} 业绩预告，类型 {forecast_type}。"]

    if net_profit_min_yi is not None or net_profit_max_yi is not None:
        if net_profit_min_yi is not None and net_profit_max_yi is not None:
            parts.append(f"预计归母净利润 {net_profit_min_yi:.2f}-{net_profit_max_yi:.2f} 亿元。")
        else:
            single = net_profit_min_yi if net_profit_min_yi is not None else net_profit_max_yi
            parts.append(f"预计归母净利润约 {single:.2f} 亿元。")

    if p_change_min is not None or p_change_max is not None:
        if p_change_min is not None and p_change_max is not None:
            parts.append(f"预计同比变动 {p_change_min:.2f}% 至 {p_change_max:.2f}%。")
        else:
            single = p_change_min if p_change_min is not None else p_change_max
            parts.append(f"预计同比变动约 {single:.2f}%。")

    if summary:
        parts.append(f"摘要：{summary}")
    if reason:
        parts.append(f"原因：{reason[:160]}")

    return " ".join(parts).strip()


def _build_forecast_lite_estimate(payload, current_price=None):
    p_change_min = _to_float_or_none(payload.get("p_change_min"))
    p_change_max = _to_float_or_none(payload.get("p_change_max"))
    net_profit_min = _to_float_or_none(payload.get("net_profit_min"))
    net_profit_max = _to_float_or_none(payload.get("net_profit_max"))

    yoy_mid = None
    if p_change_min is not None and p_change_max is not None:
        yoy_mid = (p_change_min + p_change_max) / 2.0
    elif p_change_min is not None:
        yoy_mid = p_change_min
    elif p_change_max is not None:
        yoy_mid = p_change_max

    implied_return_pct = None
    if yoy_mid is not None:
        # Piecewise scaling: keep low-growth conservative while improving sensitivity for strong forecasts.
        abs_yoy_mid = abs(yoy_mid)
        if abs_yoy_mid <= 20:
            scale = 0.20
        elif abs_yoy_mid <= 50:
            scale = 0.30
        else:
            scale = 0.40
        implied_return_pct = max(-25.0, min(25.0, yoy_mid * scale))

    signal = "中性"
    if implied_return_pct is not None:
        if implied_return_pct >= 8:
            signal = "看多"
        elif implied_return_pct <= -8:
            signal = "看空"
        elif implied_return_pct > 2:
            signal = "偏多"
        elif implied_return_pct < -2:
            signal = "偏空"

    confidence = "LOW"
    if p_change_min is not None and p_change_max is not None and net_profit_min is not None and net_profit_max is not None:
        confidence = "MEDIUM"

    return {
        "enabled": True,
        "basis": "预告同比区间中枢 + 分段缩放(0.20/0.30/0.40) + 最新交易截面（极轻量提示）",
        "implied_signal": signal,
        "implied_return_pct": round(implied_return_pct, 2) if implied_return_pct is not None else None,
        "confidence": confidence,
        "latest_price": _to_float_or_none(current_price),
        "note": "仅用于快速筛查，不替代正式估值结论。",
    }


def _extract_row_current_price(row):
    valuation = row.get("valuation") if isinstance(row.get("valuation"), dict) else {}
    for candidate in [
        row.get("current_price"),
        valuation.get("current_price"),
        row.get("close"),
        row.get("close_qfq"),
    ]:
        value = _to_float_or_none(candidate)
        if value is not None:
            return value
    return None


def _attach_recent_forecast_badge(rows, *, asof_date=None, window_days=60):
    if not rows:
        return

    normalized_asof_date = _parse_date_like(asof_date) or datetime.date.today()
    normalized_window_days = max(1, min(int(window_days or 60), 180))
    cutoff_date = normalized_asof_date - datetime.timedelta(days=normalized_window_days)

    ts_codes = sorted(
        {
            str(row.get("ts_code") or "").strip().upper()
            for row in rows
            if str(row.get("ts_code") or "").strip()
        }
    )

    for row in rows:
        row["forecast_badge"] = False
        row["forecast_days"] = None
        row["forecast_payload"] = None
        row["forecast_narrative"] = None
        row["forecast_lite_estimate"] = None

    if not ts_codes:
        return

    placeholders = ",".join(["%s"] * len(ts_codes))
    sql = f"""
        SELECT ts_code, ann_date, end_date, type,
               p_change_min, p_change_max,
               net_profit_min, net_profit_max,
               summary, change_reason
        FROM earnings_fin_forecast_vip
        WHERE ts_code IN ({placeholders})
          AND ann_date >= %s
          AND ann_date <= %s
    """
    params = list(ts_codes) + [
        cutoff_date.strftime("%Y%m%d"),
        normalized_asof_date.strftime("%Y%m%d"),
    ]
    forecast_df = query_local_financial_df(sql, params)
    if forecast_df is None or forecast_df.empty:
        return

    latest_map = {}
    for raw in forecast_df.to_dict(orient="records"):
        ts_code = str(raw.get("ts_code") or "").strip().upper()
        ann_date = _parse_date_like(raw.get("ann_date"))
        end_date = _parse_date_like(raw.get("end_date"))
        if not ts_code or ann_date is None:
            continue
        if ann_date < cutoff_date or ann_date > normalized_asof_date:
            continue
        key = (ann_date, end_date or datetime.date.min)
        prev = latest_map.get(ts_code)
        if prev is None or key > prev.get("key"):
            latest_map[ts_code] = {
                "key": key,
                "ann_date": ann_date,
                "end_date": end_date,
                "raw": raw,
            }

    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        candidate = latest_map.get(ts_code)
        if candidate is None:
            continue

        effective_asof_date = (
            _parse_date_like(row.get("earnings_asof_date"))
            or _parse_date_like(row.get("trade_date"))
            or _parse_date_like(row.get("latest_trade_date"))
            or _parse_date_like((row.get("valuation") or {}).get("latest_trade_date"))
            or normalized_asof_date
        )
        ann_date = candidate.get("ann_date")
        if ann_date is None or effective_asof_date is None or ann_date > effective_asof_date:
            continue

        days = (effective_asof_date - ann_date).days
        if days < 0 or days > normalized_window_days:
            continue

        raw = candidate.get("raw") or {}
        end_date = candidate.get("end_date")
        payload = {
            "ann_date": ann_date.isoformat(),
            "end_date": end_date.isoformat() if end_date is not None else str(raw.get("end_date") or ""),
            "type": str(raw.get("type") or "").strip(),
            "p_change_min": _to_float_or_none(raw.get("p_change_min")),
            "p_change_max": _to_float_or_none(raw.get("p_change_max")),
            "net_profit_min": _to_float_or_none(raw.get("net_profit_min")),
            "net_profit_max": _to_float_or_none(raw.get("net_profit_max")),
            "summary": str(raw.get("summary") or "").strip(),
            "change_reason": str(raw.get("change_reason") or "").strip(),
        }

        row["forecast_badge"] = True
        row["forecast_days"] = days
        row["forecast_payload"] = payload
        row["forecast_narrative"] = _build_forecast_narrative(payload)
        row["forecast_lite_estimate"] = _build_forecast_lite_estimate(
            payload,
            current_price=_extract_row_current_price(row),
        )


def _attach_signal_window_returns(rows, trade_date_for_query, freq="D", signal_end_date=None):
    if not rows:
        return

    end_date = _parse_date_like(signal_end_date) or _parse_date_like(trade_date_for_query)
    if end_date is None:
        return

    for row in rows:
        row["signal_current_return_pct"] = None
        row["signal_peak_return_pct"] = None
        row["signal_trough_return_pct"] = None

    def _row_signal_anchor_date(row):
        # Prefer the latest known announcement date across all announcement sources.
        ann_dates = [
            _parse_date_like(row.get("valuation_profit_report_ann_date")),
            _parse_date_like(row.get("profit_report_ann_date")),
            _parse_date_like(row.get("financial_ann_date")),
            _parse_date_like(row.get("valuation_express_ann_date")),
            _parse_date_like(row.get("express_ann_date")),
            _parse_date_like(row.get("latest_financial_ann_date")),
        ]
        ann_dates = [item for item in ann_dates if item is not None]
        if ann_dates:
            return max(ann_dates)

        return (
            _parse_date_like(row.get("earnings_asof_date"))
            or _parse_date_like(row.get("screened_trade_date"))
            or _parse_date_like(row.get("result_trade_date"))
            or _parse_date_like(row.get("trade_date"))
            or _parse_date_like(row.get("valuation_profit_report_end_date"))
            or _parse_date_like(row.get("profit_report_end_date"))
        )

    code_min_start = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        asof_date = _row_signal_anchor_date(row)
        if not ts_code or asof_date is None or asof_date > end_date:
            continue
        prev = code_min_start.get(ts_code)
        if prev is None or asof_date < prev:
            code_min_start[ts_code] = asof_date

    if not code_min_start:
        return

    min_start = min(code_min_start.values())
    history_rows = (
        StockTradingHistory.objects.filter(
            ts_code__in=list(code_min_start.keys()),
            freq=str(freq or "D").strip().upper(),
            trade_date__gte=min_start,
            trade_date__lte=end_date,
        )
        .order_by("ts_code", "trade_date")
        .values("ts_code", "trade_date", "close_qfq", "high_qfq", "low_qfq")
    )

    by_code = {}
    for item in history_rows:
        ts_code = str(item.get("ts_code") or "").strip().upper()
        by_code.setdefault(ts_code, []).append(
            {
                "trade_date": item.get("trade_date"),
                "close_qfq": _to_float_or_none(item.get("close_qfq")),
                "high_qfq": _to_float_or_none(item.get("high_qfq")),
                "low_qfq": _to_float_or_none(item.get("low_qfq")),
            }
        )

    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        asof_date = _row_signal_anchor_date(row)
        series = by_code.get(ts_code) or []
        if not ts_code or asof_date is None or not series:
            continue

        start_idx = None
        start_close = None
        for idx, item in enumerate(series):
            trade_date = item.get("trade_date")
            close_price = item.get("close_qfq")
            if trade_date is None or close_price in (None, 0):
                continue
            if trade_date >= asof_date:
                start_idx = idx
                start_close = close_price
                break

        if start_idx is None or start_close in (None, 0):
            continue

        # Baseline uses the screened-day close, but performance window starts from next trading day.
        window = [item for item in series[start_idx + 1:] if item.get("trade_date") is not None and item.get("trade_date") > asof_date]
        if not window:
            continue
        peak_price = None
        trough_price = None
        last_close = None
        for item in window:
            close_price = item.get("close_qfq")
            high_price = item.get("high_qfq") if item.get("high_qfq") is not None else close_price
            low_price = item.get("low_qfq") if item.get("low_qfq") is not None else close_price

            if close_price is not None:
                last_close = close_price
            if high_price is not None:
                peak_price = high_price if peak_price is None else max(peak_price, high_price)
            if low_price is not None:
                trough_price = low_price if trough_price is None else min(trough_price, low_price)

        current_close = _to_float_or_none(row.get("close_qfq") or row.get("close"))
        if current_close is None:
            current_close = last_close

        if current_close is not None:
            row["signal_current_return_pct"] = round((current_close / start_close - 1.0) * 100.0, 2)
        if peak_price is not None:
            row["signal_peak_return_pct"] = round((peak_price / start_close - 1.0) * 100.0, 2)
        if trough_price is not None:
            row["signal_trough_return_pct"] = round((trough_price / start_close - 1.0) * 100.0, 2)


def _pick_stocks_by_valuation_fast(request, trade_date, scope, freq="D", from_index=0, to_index=25):
    perf_t0 = time.perf_counter()
    recommendation_desc = "ΦíîΣ╕ÜµÄ¿ΦìÉ=µîëΦéíτÑ¿µëÇσ▒₧ΦíîΣ╕ÜσàêΘ¬î + Σ╝░σÇ╝µû╣µ│òσÅ»τö¿µÇºΦ┐¢ΦíîµëôσêåµÄÆσ║Å∩╝îΣ╝ÿσàêΦ┐öσ¢₧σ╜ôσëìΦéíτÑ¿µ£ëσÅ»τö¿σ┐½τàºτÜäµû╣µ│ò∩╝îσ╣╢τ╗Öσç║τ╜«Σ┐íσ║ªΣ╕ÄµÄ¿ΦìÉτÉåτö▒πÇé"
    normalized_freq = str(freq or "D").strip().upper()
    latest_trade_date = StockTradingHistory.objects.filter(
        freq=normalized_freq
    ).aggregate(latest_date=Max("trade_date"))["latest_date"]

    auto_latest_raw = (
        request.query_params.get("auto_latest", "1")
        if hasattr(request, "query_params")
        else "1"
    )
    auto_latest = str(auto_latest_raw).strip().lower() not in {"0", "false", "off", "no"}

    normalized_trade_date = str(trade_date or "").strip()
    requested_date_has_data = StockTradingHistory.objects.filter(
        trade_date=normalized_trade_date,
        freq=normalized_freq,
    ).exists()

    trade_date_for_query = normalized_trade_date
    if latest_trade_date is not None and (
        normalized_trade_date.upper() in {"LATEST", "AUTO"}
        or (auto_latest and not requested_date_has_data)
    ):
        trade_date_for_query = latest_trade_date.strftime("%Y-%m-%d")

    valuation_method = (
        request.query_params.get("valuation_method", "pe") if hasattr(request, "query_params") else "pe"
    )
    valuation_status = (
        request.query_params.get("valuation_status", "") if hasattr(request, "query_params") else ""
    )
    valuation_band_pct_raw = (
        request.query_params.get("valuation_band_pct", "0.1") if hasattr(request, "query_params") else "0.1"
    )
    valuation_pick_strategy_raw = (
        request.query_params.get("valuation_pick_strategy", LIVE_VALUATION_PICK_STRATEGY)
        if hasattr(request, "query_params")
        else LIVE_VALUATION_PICK_STRATEGY
    )
    summary_mode_raw = (
        request.query_params.get("summary_mode", "single_variant_strict")
        if hasattr(request, "query_params")
        else "single_variant_strict"
    )
    requested_valuation_variant_raw = (
        request.query_params.get("valuation_variant", "")
        if hasattr(request, "query_params")
        else ""
    )
    buy_candidate_only_raw = (
        request.query_params.get("buy_candidate_only", "") if hasattr(request, "query_params") else ""
    )
    sw_industry_raw = (
        request.query_params.get("sw_industry", "") if hasattr(request, "query_params") else ""
    )
    picking_mode_raw = (
        request.query_params.get("picking_mode", "baseline") if hasattr(request, "query_params") else "baseline"
    )
    earnings_report_type_raw = (
        request.query_params.get("earnings_report_type", "ALL") if hasattr(request, "query_params") else "ALL"
    )
    signal_action_raw = (
        request.query_params.get("signal_action", "") if hasattr(request, "query_params") else ""
    )
    risk_level_raw = (
        request.query_params.get("risk_level", "") if hasattr(request, "query_params") else ""
    )
    min_signal_score_raw = (
        request.query_params.get("min_signal_score", "") if hasattr(request, "query_params") else ""
    )
    min_target_return_pct_raw = (
        request.query_params.get("min_target_return_pct", "") if hasattr(request, "query_params") else ""
    )
    feature_data_source_raw = (
        request.query_params.get("feature_data_source", "") if hasattr(request, "query_params") else ""
    )
    netprofit_growth_raw = (
        request.query_params.get("netprofit_growth", "ALL") if hasattr(request, "query_params") else "ALL"
    )
    valuation_score_raw = (
        request.query_params.get("valuation_score", "ALL") if hasattr(request, "query_params") else "ALL"
    )
    min_valuation_score_raw = (
        request.query_params.get("min_valuation_score", "") if hasattr(request, "query_params") else ""
    )
    min_netprofit_yoy_raw = (
        request.query_params.get("min_netprofit_yoy", "") if hasattr(request, "query_params") else ""
    )
    min_ebit_yoy_raw = (
        request.query_params.get("min_ebit_yoy", "") if hasattr(request, "query_params") else ""
    )
    require_positive_prev_netprofit_raw = (
        request.query_params.get("require_positive_prev_netprofit", "1")
        if hasattr(request, "query_params")
        else "1"
    )
    require_positive_prev_ebit_raw = (
        request.query_params.get("require_positive_prev_ebit", "1")
        if hasattr(request, "query_params")
        else "1"
    )
    apply_financial_filters_raw = (
        request.query_params.get("apply_financial_filters", "0")
        if hasattr(request, "query_params")
        else "0"
    )
    apply_moneyflow_filters_raw = (
        request.query_params.get("apply_moneyflow_filters", "0")
        if hasattr(request, "query_params")
        else "0"
    )
    moneyflow_window_raw = (
        request.query_params.get("moneyflow_net_inflow_days_window", THS_STOCK_MONEYFLOW_DEFAULT_WINDOW)
        if hasattr(request, "query_params")
        else THS_STOCK_MONEYFLOW_DEFAULT_WINDOW
    )
    priority_policy_raw = (
        request.query_params.get("priority_policy", "score_desc")
        if hasattr(request, "query_params")
        else "score_desc"
    )
    scan_limit_raw = (
        request.query_params.get("scan_limit", "")
        if hasattr(request, "query_params")
        else ""
    )

    try:
        valuation_band_pct = max(0.01, float(valuation_band_pct_raw))
    except (TypeError, ValueError):
        valuation_band_pct = 0.1

    valuation_status = str(valuation_status).strip().lower()
    selected_valuation_method = str(valuation_method or "pe").strip().lower() or "pe"
    valuation_pick_strategy = _normalize_pick_strategy(valuation_pick_strategy_raw)
    summary_mode = str(summary_mode_raw or "single_variant_strict").strip().lower()
    if summary_mode not in {"single_variant_strict", "mixed_method"}:
        summary_mode = "single_variant_strict"
    requested_valuation_variant = _normalize_valuation_variant(
        requested_valuation_variant_raw,
        fallback="",
    )
    buy_candidate_only = str(buy_candidate_only_raw).strip().lower() in {
        "1", "true", "yes", "y", "on",
    }
    sw_industry = str(sw_industry_raw).strip()
    picking_mode = _normalize_predictive_mode(picking_mode_raw)
    valuation_report_type_text = str(earnings_report_type_raw or "").strip().upper()
    valuation_express_only = valuation_report_type_text in {"EXP", "EXPRESS", "σ┐½"}
    earnings_report_type = _normalize_earnings_report_type_with_all(earnings_report_type_raw)
    valuation_profit_report_type = _normalize_valuation_profit_report_type(earnings_report_type)
    valuation_fiscal_year = (
        str(
            request.query_params.get("valuation_fiscal_year")
            or request.query_params.get("target_fiscal_year")
            or ""
        ).strip()
        if hasattr(request, "query_params")
        else ""
    )
    valuation_report_end_date = _resolve_valuation_report_end_date(
        valuation_profit_report_type,
        fiscal_year_value=valuation_fiscal_year,
    )
    signal_action = _normalize_optional_choice(signal_action_raw, {"BUY", "HOLD", "SELL_PART", "SELL"})
    risk_level_set = _normalize_risk_level_filters(risk_level_raw)
    risk_level = ",".join(sorted(risk_level_set)) if risk_level_set else ""
    feature_data_source = str(feature_data_source_raw or "").strip().lower()
    try:
        min_signal_score = _to_float_or_none(min_signal_score_raw)
    except (TypeError, ValueError):
        min_signal_score = None
    if picking_mode == "predictive" and min_signal_score is None:
        min_signal_score = PREDICTIVE_UNDERVALUED_MIN_SIGNAL_SCORE_DEFAULT
    try:
        min_target_return_pct = _to_float_or_none(min_target_return_pct_raw)
    except (TypeError, ValueError):
        min_target_return_pct = None
    netprofit_growth = str(netprofit_growth_raw or "ALL").strip().upper()
    if netprofit_growth not in {"ALL", "MEDIUM", "HIGH"}:
        netprofit_growth = "ALL"
    # pred_earnings_growth is stored as ratio (e.g. 0.2 == 20%).
    min_netprofit_growth = 0.2 if netprofit_growth == "HIGH" else (0.1 if netprofit_growth == "MEDIUM" else None)
    valuation_score_level = ""
    min_valuation_score = _to_float_or_none(min_valuation_score_raw)
    if min_valuation_score is None:
        valuation_score_text = str(valuation_score_raw or "ALL").strip().upper()
        if valuation_score_text in {"HIGH", "MEDIUM", "LOW"}:
            valuation_score_level = valuation_score_text
            min_valuation_score = {
                "HIGH": 75.0,
                "MEDIUM": 55.0,
                "LOW": 35.0,
            }.get(valuation_score_level)
        elif valuation_score_text in {"ALL", ""}:
            valuation_score_level = "ALL"
            min_valuation_score = None
        else:
            # Backward-compatible numeric support via valuation_score.
            min_valuation_score = _to_float_or_none(valuation_score_raw)
            valuation_score_level = "CUSTOM" if min_valuation_score is not None else "ALL"

    min_netprofit_yoy = _to_float_or_none(min_netprofit_yoy_raw)
    min_ebit_yoy = _to_float_or_none(min_ebit_yoy_raw)

    def _normalize_yoy_threshold(value):
        numeric = _to_float_or_none(value)
        if numeric is None:
            return None
        # Dual-input compatibility:
        # 1) "3" means 3% -> 0.03 ratio.
        # 2) "0.03" is already ratio.
        if abs(float(numeric)) > 1.0:
            return float(numeric) / 100.0
        return float(numeric)

    def _parse_bool_flag(raw_value, default=True):
        if raw_value is None:
            return default
        text_value = str(raw_value).strip().lower()
        if text_value == "":
            return default
        return text_value in {"1", "true", "yes", "y", "on"}

    require_positive_prev_netprofit = _parse_bool_flag(require_positive_prev_netprofit_raw, True)
    require_positive_prev_ebit = _parse_bool_flag(require_positive_prev_ebit_raw, True)
    apply_financial_filters = _parse_bool_flag(apply_financial_filters_raw, False)
    apply_moneyflow_filters = _parse_bool_flag(apply_moneyflow_filters_raw, False)
    moneyflow_window_days = _normalize_stock_moneyflow_window(moneyflow_window_raw)
    priority_policy = str(priority_policy_raw or "score_desc").strip().lower()
    allowed_priority_policies = {
        "score_desc",
        "deep_discount_first",
        "target_discount_first",
        "high_price_first",
        "low_price_first",
        "low_risk_high_score",
    }
    if priority_policy not in allowed_priority_policies:
        priority_policy = "score_desc"
    try:
        scan_limit = int(str(scan_limit_raw).strip()) if str(scan_limit_raw).strip() else None
    except (TypeError, ValueError):
        scan_limit = None
    if scan_limit is not None and scan_limit <= 0:
        scan_limit = None
    netprofit_growth_floor = 0.2 if netprofit_growth == "HIGH" else (0.1 if netprofit_growth == "MEDIUM" else None)
    min_netprofit_yoy_ratio = _normalize_yoy_threshold(min_netprofit_yoy)
    min_ebit_yoy_ratio = _normalize_yoy_threshold(min_ebit_yoy)
    effective_netprofit_yoy_floor = (
        min_netprofit_yoy_ratio if min_netprofit_yoy_ratio is not None else netprofit_growth_floor
    )

    cache_key = _build_valuation_pick_cache_key(
        {
            "trade_date": trade_date_for_query,
            "freq": normalized_freq,
            "scope": str(scope or ""),
            "valuation_method": selected_valuation_method,
            "valuation_status": valuation_status,
            "valuation_band_pct": valuation_band_pct,
            "valuation_pick_strategy": valuation_pick_strategy,
            "summary_mode": summary_mode,
            "valuation_variant": requested_valuation_variant,
            "buy_candidate_only": buy_candidate_only,
            "sw_industry": sw_industry,
            "picking_mode": picking_mode,
            "earnings_report_type": earnings_report_type,
            "valuation_fiscal_year": valuation_fiscal_year,
            "valuation_report_end_date": valuation_report_end_date.isoformat() if valuation_report_end_date is not None else "",
            "valuation_express_only": valuation_express_only,
            "signal_action": signal_action,
            "risk_level": risk_level,
            "feature_data_source": feature_data_source,
            "min_signal_score": min_signal_score,
            "min_target_return_pct": min_target_return_pct,
            "netprofit_growth": netprofit_growth,
            "min_valuation_score": min_valuation_score,
            "priority_policy": priority_policy,
            "scan_limit": scan_limit,
            "apply_financial_filters": apply_financial_filters,
            "effective_netprofit_yoy_floor": effective_netprofit_yoy_floor,
            "min_ebit_yoy_ratio": min_ebit_yoy_ratio,
            "require_positive_prev_netprofit": require_positive_prev_netprofit,
            "require_positive_prev_ebit": require_positive_prev_ebit,
            "apply_moneyflow_filters": apply_moneyflow_filters,
            "moneyflow_window_days": moneyflow_window_days,
        }
    )

    def _ms(start, end):
        return round((end - start) * 1000.0, 2)

    def _build_pick_response(
        *,
        paged_result,
        total_filtered,
        total_candidates=None,
        strategy_effective_stocks,
        predictive_stats,
        moneyflow_stats=None,
        timing_ms,
        cache_hit,
    ):
        return Response(
            {
                "data": paged_result,
                "trade_date": trade_date_for_query,
                "freq": normalized_freq,
                "valuation_filter": {
                    "method": selected_valuation_method,
                    "status": valuation_status,
                    "band_pct": valuation_band_pct,
                    "buy_candidate_only": buy_candidate_only,
                    "pick_strategy": valuation_pick_strategy,
                    "summary_mode": summary_mode,
                    "valuation_variant": requested_valuation_variant or None,
                    "sw_industry": sw_industry,
                    "strict_snapshot_only": True,
                    "picking_mode": picking_mode,
                    "earnings_report_type": "σ┐½" if valuation_express_only else earnings_report_type,
                    "valuation_fiscal_year": valuation_fiscal_year or None,
                    "valuation_report_end_date": valuation_report_end_date.isoformat() if valuation_report_end_date is not None else None,
                    "signal_action": signal_action,
                    "risk_level": risk_level,
                    "min_signal_score": min_signal_score,
                    "min_target_return_pct": min_target_return_pct,
                    "feature_data_source": feature_data_source,
                    "netprofit_growth": netprofit_growth,
                    "valuation_score": valuation_score_level,
                    "min_valuation_score": min_valuation_score,
                    "priority_policy": priority_policy,
                    "effective_financial_filters": {
                        "apply_financial_filters": bool(apply_financial_filters),
                        "min_netprofit_yoy": min_netprofit_yoy,
                        "min_ebit_yoy": min_ebit_yoy,
                        "min_netprofit_yoy_ratio": min_netprofit_yoy_ratio,
                        "min_ebit_yoy_ratio": min_ebit_yoy_ratio,
                        "require_positive_prev_netprofit": require_positive_prev_netprofit,
                        "require_positive_prev_ebit": require_positive_prev_ebit,
                        "netprofit_growth_floor": effective_netprofit_yoy_floor,
                    },
                    "effective_moneyflow_filters": {
                        "apply_moneyflow_filters": bool(apply_moneyflow_filters),
                        "moneyflow_net_inflow_days_window": int(moneyflow_window_days),
                        "mode": "sum_positive",
                        "matched_count_before": int((moneyflow_stats or {}).get("before") or 0),
                        "matched_count_after": int((moneyflow_stats or {}).get("after") or 0),
                    },
                },
                "meta": {
                    "latest_trade_date_for_freq": latest_trade_date,
                    "requested_trade_date_has_data": requested_date_has_data,
                    "requested_trade_date": normalized_trade_date,
                    "resolved_trade_date": trade_date_for_query,
                    "auto_latest": auto_latest,
                    "total_candidates": total_candidates,
                    "total_filtered": total_filtered,
                    "strategy_effective_stocks": strategy_effective_stocks,
                    "page_from_index": from_index,
                    "page_to_index": to_index,
                    "current_page_size": len(paged_result),
                    "valuation_method_recommendation_desc": recommendation_desc,
                    "sw_industry": sw_industry,
                    "predictive_mode_enabled": picking_mode == "predictive",
                    "cache_hit": bool(cache_hit),
                    "timing_ms": timing_ms,
                    "predictive_earnings_stats": predictive_stats,
                },
            }
        )

    cached_bundle = None
    try:
        cached_bundle = cache.get(cache_key)
    except Exception as cache_err:
        logger.debug("valuation pick cache get failed: %s", cache_err)

    if isinstance(cached_bundle, dict) and isinstance(cached_bundle.get("result"), list):
        cached_result = cached_bundle.get("result") or []
        paged_result = [
            (row.copy() if isinstance(row, dict) else row)
            for row in cached_result[from_index:to_index]
        ]
        if picking_mode != "predictive":
            _attach_traditional_quick_metrics(paged_result, market="CN")
        _attach_recent_financial_report_badge(
            paged_result,
            asof_date=trade_date_for_query,
            market="CN",
            include_official_ann_lookup=bool(apply_financial_filters),
        )
        _attach_signal_window_returns(
            paged_result,
            trade_date_for_query=trade_date_for_query,
            freq=normalized_freq,
            signal_end_date=latest_trade_date,
        )

        perf_after_all = time.perf_counter()
        cached_total_ms = _ms(perf_t0, perf_after_all)
        return _build_pick_response(
            paged_result=paged_result,
            total_filtered=len(cached_result),
            total_candidates=cached_bundle.get("total_candidates"),
            strategy_effective_stocks=int(cached_bundle.get("multi_candidate_rows") or 0),
            predictive_stats=(cached_bundle.get("predictive_earnings_stats") or {}),
            moneyflow_stats=(cached_bundle.get("moneyflow_filter_stats") or {}),
            timing_ms={
                "total": cached_total_ms,
                "load_trading_rows": 0.0,
                "build_valuation_snapshot": 0.0,
                "predictive_earnings_enrich": 0.0,
                "post_process_and_page": cached_total_ms,
            },
            cache_hit=True,
        )

    trading_qs = StockTradingHistory.objects.filter(
        trade_date=trade_date_for_query,
        freq=normalized_freq,
    )
    if scope.isdigit():
        trading_qs = trading_qs.filter(ts_code__startswith=scope)
    elif scope == "WATCHLIST":
        watchlist_codes = list(
            UserWatchlist.objects.filter(is_enabled=True).values_list("ts_code", flat=True)
        )
        trading_qs = trading_qs.filter(ts_code__in=watchlist_codes)

    trading_rows = list(
        trading_qs.order_by("ts_code").values(
            "ts_code",
            "close_qfq",
            "close",
            "pct_change_qfq",
        )
    )
    perf_after_trading = time.perf_counter()
    total_candidates_count = len(trading_rows)
    if scan_limit is not None:
        trading_rows = trading_rows[:scan_limit]
    ts_codes = [row["ts_code"] for row in trading_rows]

    valuation_snapshot_map = _build_latest_snapshot_method_map(
        ts_codes=ts_codes,
        market="CN",
        pick_strategy=valuation_pick_strategy,
        max_trade_date=trade_date_for_query,
        express_only=valuation_express_only,
        profit_report_type=(None if valuation_express_only else valuation_profit_report_type),
        profit_report_end_date=(None if valuation_express_only else valuation_report_end_date),
    )
    predictive_anchor_snapshot_map = {}
    if picking_mode == "predictive" and valuation_express_only:
        predictive_anchor_snapshot_map = _build_latest_snapshot_method_map(
            ts_codes=ts_codes,
            market="CN",
            pick_strategy=valuation_pick_strategy,
            max_trade_date=trade_date_for_query,
            express_only=False,
            profit_report_end_date=valuation_report_end_date,
        )
    industry_context_map = _build_industry_context_map(ts_codes=ts_codes, market="CN")

    traditional_risk_map = {}
    if picking_mode != "predictive":
        traditional_risk_map = _build_latest_risk_snapshot_map(ts_codes, market="CN")

    perf_after_snapshot = time.perf_counter()

    corp_map = {
        corp.ts_code: corp
        for corp in Corporation.objects.filter(ts_code__in=ts_codes).prefetch_related("basic_info")
    }

    result = []
    multi_candidate_rows = 0
    for row in trading_rows:
        ts_code = row.get("ts_code")
        current_price = row.get("close_qfq") or row.get("close")
        industry_context = industry_context_map.get(ts_code, {})

        if sw_industry and not _match_sw_industry_filter(industry_context, sw_industry):
            continue

        method_map = valuation_snapshot_map.get(ts_code, {})
        recommendation_profile = _build_recommendation_profile(
            ts_code=ts_code,
            method_map=method_map,
            industry_context=industry_context,
        )

        effective_method = _resolve_effective_method(
            requested_method=selected_valuation_method,
            method_map=method_map,
            recommendation_profile=recommendation_profile,
        )
        selected_method_payload = method_map.get(effective_method, {})
        selected_price = selected_method_payload.get("valuation_price")
        selected_market_cap = selected_method_payload.get("valuation_market_cap")
        selected_source = selected_method_payload.get("source") or "snapshot_only_miss"
        selected_profit_data_source = selected_method_payload.get("profit_data_source")
        selected_profit_report_end_date = selected_method_payload.get("profit_report_end_date")
        selected_profit_report_ann_date = selected_method_payload.get("profit_report_ann_date")
        selected_profit_report_type = _normalize_valuation_profit_report_type(
            selected_method_payload.get("profit_report_type")
        )
        selected_snapshot_updated_at = selected_method_payload.get("snapshot_updated_at")
        selected_valuation_variant = _normalize_valuation_variant(
            selected_method_payload.get("valuation_variant"),
            fallback="",
        )
        selected_candidate_count = selected_method_payload.get("candidate_count", 0)
        selected_confidence = selected_method_payload.get("valuation_confidence")
        selected_staleness_days = selected_method_payload.get("valuation_staleness_days")
        selected_candidate_spread_pct = selected_method_payload.get("valuation_candidate_spread_pct")
        if selected_candidate_count and int(selected_candidate_count) > 1:
            multi_candidate_rows += 1

        if picking_mode != "predictive":
            if valuation_express_only:
                if not str(selected_profit_data_source or "").strip().lower().startswith("express"):
                    continue
            elif valuation_profit_report_type and selected_profit_report_type != valuation_profit_report_type:
                continue

        valuation_state, valuation_gap = _classify_valuation(current_price, selected_price, valuation_band_pct)
        valuation_payload = {
            "valuation_method": effective_method,
            "valuation_method_requested": _normalize_valuation_method_name(selected_valuation_method),
            "valuation_method_recommended": recommendation_profile.get("methods", []),
            "valuation_method_recommendation_scores": recommendation_profile.get("scores", {}),
            "valuation_recommendation_confidence": recommendation_profile.get("confidence"),
            "valuation_recommendation_reason": recommendation_profile.get("reason"),
            "valuation_method_recommendation_desc": recommendation_desc,
            "valuation_price": round(float(selected_price), 4) if selected_price is not None else None,
            "valuation_market_cap": round(float(selected_market_cap), 2) if selected_market_cap is not None else None,
            "valuation_status": valuation_state,
            "valuation_gap_pct": round(valuation_gap * 100, 2) if valuation_gap is not None else None,
            "valuation_source": selected_source,
            "valuation_profit_data_source": selected_profit_data_source,
            "valuation_profit_report_end_date": selected_profit_report_end_date,
            "valuation_profit_report_ann_date": selected_profit_report_ann_date,
            "valuation_profit_report_type": selected_profit_report_type,
            "valuation_express_ann_date": selected_method_payload.get("express_ann_date"),
            "earnings_asof_date": selected_profit_report_ann_date or selected_profit_report_end_date,
            "valuation_snapshot_updated_at": selected_snapshot_updated_at,
            "valuation_variant": selected_valuation_variant or None,
            "valuation_pick_strategy": valuation_pick_strategy,
            "valuation_candidate_count": selected_candidate_count,
            "valuation_confidence": selected_confidence,
            "valuation_staleness_days": selected_staleness_days,
            "valuation_candidate_spread_pct": selected_candidate_spread_pct,
            "valuation_candidates": [],
        }

        if selected_price is None:
            valuation_payload["valuation_source"] = "snapshot_only_miss"

        # Predictive seasonal filter (Q1/H1/Q3/FY) should use formal report-season
        # snapshots by default. Express-driven snapshots are allowed only in
        # explicit express/fusion flows.
        if (
            picking_mode == "predictive"
            and not valuation_express_only
            and earnings_report_type in {"Q1", "H1", "Q3", "FY"}
            and str(selected_profit_data_source or "").strip().lower().startswith("express")
        ):
            continue

        buy_candidate_payload = None
        if summary_mode == "single_variant_strict":
            strict_report_type = None
            if valuation_express_only:
                strict_report_type = "EXP"
            elif earnings_report_type in {"Q1", "H1", "Q3", "FY"}:
                strict_report_type = earnings_report_type

            strict_payload = _build_strict_summary_from_method_map(
                ts_code=ts_code,
                market="CN",
                current_price=current_price,
                method_map=method_map,
                band_pct=valuation_band_pct,
                trade_date=trade_date_for_query,
                requested_variant=requested_valuation_variant or "",
                requested_report_type=strict_report_type,
            )
            if strict_payload:
                buy_candidate_payload = dict(strict_payload)

        if buy_candidate_payload is None:
            buy_candidate_payload = _summarize_buy_candidate(
                current_price=current_price,
                method_map=method_map,
                band_pct=valuation_band_pct,
            )
            buy_candidate_payload["summary_mode"] = "mixed_method"
            buy_candidate_payload.setdefault("summary_variant", None)
            buy_candidate_payload.setdefault("summary_report_end_date", None)
        valuation_score = _to_float_or_none(buy_candidate_payload.get("undervalue_score"))
        if valuation_score is None:
            # Prefer composite gap fallback for traditional mode when selected-method gap is missing.
            composite_price = _to_float_or_none(buy_candidate_payload.get("composite_valuation_price"))
            current_price_num = _to_float_or_none(current_price)
            gap_pct = None
            if composite_price is not None and current_price_num not in (None, 0):
                gap_pct = (float(composite_price) / float(current_price_num) - 1.0) * 100.0
            if gap_pct is None:
                gap_pct = _to_float_or_none(valuation_payload.get("valuation_gap_pct"))
            if gap_pct is not None:
                valuation_score = max(0.0, min(100.0, 50.0 + float(gap_pct)))
        if valuation_score is not None:
            valuation_score = round(float(valuation_score), 2)

        buy_candidate_payload["valuation_score"] = valuation_score
        if buy_candidate_payload.get("undervalue_score") is None:
            buy_candidate_payload["undervalue_score"] = valuation_score

        conservative_price_num = _to_float_or_none(
            buy_candidate_payload.get("conservative_valuation_price")
        )
        current_price_num = _to_float_or_none(current_price)
        backtest_aligned = (
            current_price_num is not None
            and conservative_price_num is not None
            and current_price_num <= conservative_price_num
        )
        if current_price_num is None:
            backtest_align_reason = "missing_current_price"
        elif conservative_price_num is None:
            backtest_align_reason = "missing_conservative_price"
        elif backtest_aligned:
            backtest_align_reason = "price_lte_conservative"
        else:
            backtest_align_reason = "price_gt_conservative"
        buy_candidate_payload["buy_candidate_backtest_aligned"] = bool(backtest_aligned)
        buy_candidate_payload["buy_candidate_backtest_align_reason"] = backtest_align_reason

        if min_valuation_score is not None and (valuation_score is None or float(valuation_score) < float(min_valuation_score)):
            continue

        if picking_mode != "predictive":
            if valuation_status and valuation_payload.get("valuation_status") != valuation_status:
                continue
            if buy_candidate_only and (
                (not buy_candidate_payload.get("buy_candidate"))
                or (not buy_candidate_payload.get("buy_candidate_backtest_aligned"))
            ):
                continue

        traditional_metric_payload = {}
        if picking_mode != "predictive":
            risk_payload = traditional_risk_map.get(ts_code) or {}
            traditional_metric_payload = {**risk_payload}

            row_risk_level = str(risk_payload.get("valuation_risk_level") or "").strip().upper()
            if risk_level_set and row_risk_level not in risk_level_set:
                continue

        corp_obj = corp_map.get(ts_code)
        corp_basic = {}
        corp_basic_obj = getattr(corp_obj, "basic_info", None)
        if corp_basic_obj is not None:
            basic = corp_basic_obj.first()
            if basic is not None and hasattr(basic, "to_dict_short"):
                corp_basic = basic.to_dict_short()

        result.append(
            {
                "ts_code": ts_code,
                "name": getattr(corp_obj, "name", None),
                "top_or_bottom": "",
                **{
                    k: v
                    for k, v in (corp_basic or {}).items()
                    if k not in ["id", "ts_code", "trade_date", "area", "city", "corporation"]
                },
                **row,
                **industry_context,
                **valuation_payload,
                **buy_candidate_payload,
                **traditional_metric_payload,
            }
        )

    if picking_mode != "predictive" and result:
        financial_filters_enabled = bool(apply_financial_filters)
        financial_filters_active = financial_filters_enabled and (
            effective_netprofit_yoy_floor is not None
            or min_ebit_yoy_ratio is not None
            or bool(require_positive_prev_netprofit)
            or bool(require_positive_prev_ebit)
        )
        if financial_filters_enabled:
            candidate_codes = [
                str(item.get("ts_code") or "").strip().upper()
                for item in result
                if item.get("ts_code")
            ]
            candidate_codes = list(dict.fromkeys([code for code in candidate_codes if code]))

            netprofit_map = _build_latest_income_netprofit_map(candidate_codes)
            indicator_map = {
                code: _load_latest_indicator_profile(code)
                for code in candidate_codes
            }

            filtered_rows = []
            for item in result:
                ts_code = str(item.get("ts_code") or "").strip().upper()
                netprofit_payload = netprofit_map.get(ts_code) or {}
                indicator_payload = indicator_map.get(ts_code) or {}

                row_netprofit = _to_float_or_none(netprofit_payload.get("financial_netprofit"))
                row_netprofit_yoy = _to_float_or_none(netprofit_payload.get("financial_netprofit_yoy"))
                row_prev_netprofit = _to_float_or_none(netprofit_payload.get("financial_prev_netprofit"))
                if row_prev_netprofit is None and row_netprofit is not None and row_netprofit_yoy is not None:
                    yoy_base = 1.0 + float(row_netprofit_yoy)
                    if abs(yoy_base) > 1e-9:
                        row_prev_netprofit = float(row_netprofit) / yoy_base

                row_ebit = _to_float_or_none(indicator_payload.get("financial_ebit"))
                row_ebit_yoy = _to_float_or_none(indicator_payload.get("financial_ebit_yoy"))
                row_prev_ebit = _to_float_or_none(indicator_payload.get("financial_prev_ebit"))
                if row_prev_ebit is None and row_ebit is not None and row_ebit_yoy is not None:
                    yoy_base = 1.0 + float(row_ebit_yoy)
                    if abs(yoy_base) > 1e-9:
                        row_prev_ebit = float(row_ebit) / yoy_base

                # Keep financial columns populated whenever financial mode is enabled.
                item.update(netprofit_payload)
                item.update(indicator_payload)
                item["financial_netprofit"] = row_netprofit
                item["financial_netprofit_yoy"] = row_netprofit_yoy
                item["financial_prev_netprofit"] = row_prev_netprofit
                item["financial_ebit"] = row_ebit
                item["financial_ebit_yoy"] = row_ebit_yoy
                item["financial_prev_ebit"] = row_prev_ebit

                if not financial_filters_active:
                    filtered_rows.append(item)
                    continue

                if effective_netprofit_yoy_floor is not None:
                    if row_netprofit_yoy is not None:
                        if row_netprofit_yoy < effective_netprofit_yoy_floor:
                            continue
                    elif row_netprofit is None or row_netprofit <= 0:
                        continue

                if min_ebit_yoy_ratio is not None:
                    if row_ebit_yoy is not None:
                        if row_ebit_yoy < min_ebit_yoy_ratio:
                            continue
                    elif row_ebit is None or row_ebit <= 0:
                        continue

                if require_positive_prev_netprofit and (row_prev_netprofit is None or row_prev_netprofit < 0):
                    continue
                if require_positive_prev_ebit and (row_prev_ebit is None or row_prev_ebit < 0):
                    continue

                filtered_rows.append(item)

            result = filtered_rows

    moneyflow_filter_stats = {
        "before": len(result),
        "after": len(result),
    }
    if apply_moneyflow_filters and result:
        moneyflow_filter_stats["before"] = len(result)
        candidate_codes = [
            _normalize_ts_code(item.get("ts_code"))
            for item in result
            if item.get("ts_code")
        ]
        candidate_codes = [code for code in list(dict.fromkeys(candidate_codes)) if code]
        moneyflow_sum_map = _build_stock_moneyflow_sum_map(
            candidate_codes,
            asof_date=trade_date_for_query,
            window_days=moneyflow_window_days,
        )

        filtered_rows = []
        for item in result:
            ts_code = _normalize_ts_code(item.get("ts_code"))
            sum_payload = moneyflow_sum_map.get(ts_code) or {}
            net_inflow_sum = _to_float_or_none(sum_payload.get("net_inflow_sum"))
            observed_days = int(sum_payload.get("observed_days") or 0)
            item["moneyflow_net_inflow_sum"] = (
                round(float(net_inflow_sum), 4) if net_inflow_sum is not None else None
            )
            item["moneyflow_window_days_observed"] = observed_days
            item["moneyflow_window_days_requested"] = int(moneyflow_window_days)

            if net_inflow_sum is not None and float(net_inflow_sum) > 0.0:
                filtered_rows.append(item)

        result = filtered_rows
        moneyflow_filter_stats["after"] = len(result)

    if picking_mode == "predictive" and result:
        predictive_ts_codes = [row.get("ts_code") for row in result if row.get("ts_code")]
        predictive_ts_codes = list(
            dict.fromkeys(
                [str(code or "").strip().upper() for code in predictive_ts_codes if code]
            )
        )
        predictive_report_window_strict = (
            bool(valuation_fiscal_year)
            and valuation_report_end_date is not None
            and earnings_report_type in {"Q1", "H1", "Q3", "FY"}
        )
        try:
            requested_fiscal_year_num = int(str(valuation_fiscal_year).strip()) if str(valuation_fiscal_year).strip() else None
        except (TypeError, ValueError):
            requested_fiscal_year_num = None
        earnings_end_date_map = {}
        if earnings_report_type in {"Q1", "H1", "Q3", "FY"}:
            for row in result:
                ts_code = str(row.get("ts_code") or "").strip().upper()
                if not ts_code:
                    continue
                report_end_date = _parse_date_like(row.get("valuation_profit_report_end_date"))
                if report_end_date is None:
                    continue
                earnings_end_date_map[ts_code] = report_end_date
        earnings_map = {}
        predictive_earnings_stats = {}
        try:
            if valuation_express_only:
                grouped_codes_by_report_type = {}
                grouped_end_date_map = {}

                for row in result:
                    ts_code = str(row.get("ts_code") or "").strip().upper()
                    if not ts_code:
                        continue

                    anchor_source = predictive_anchor_snapshot_map.get(ts_code) or {}
                    anchor = _pick_latest_predictive_snapshot_anchor(anchor_source)
                    if anchor is None:
                        anchor = _pick_latest_predictive_snapshot_anchor(
                            valuation_snapshot_map.get(ts_code) or {}
                        )
                    if anchor is None:
                        continue

                    normalized_rt = anchor.get("report_type")
                    grouped_codes_by_report_type.setdefault(normalized_rt, []).append(ts_code)

                    report_end_date = anchor.get("report_end_date")
                    if report_end_date is not None:
                        grouped_end_date_map.setdefault(normalized_rt, {})[ts_code] = report_end_date

                grouped_stats = {}
                for grouped_rt, grouped_codes in grouped_codes_by_report_type.items():
                    unique_codes = list(dict.fromkeys(grouped_codes))
                    if not unique_codes:
                        continue
                    group_result, group_stats = _fetch_earnings_signal_batch(
                        unique_codes,
                        report_type=grouped_rt,
                        return_stats=True,
                        financial_end_date_map=grouped_end_date_map.get(grouped_rt) or None,
                    )
                    earnings_map.update(group_result)
                    grouped_stats[grouped_rt] = group_stats

                unresolved_codes = [code for code in predictive_ts_codes if code not in earnings_map]
                fallback_stats = None
                if unresolved_codes:
                    fallback_result, fallback_stats = _fetch_earnings_signal_batch(
                        unresolved_codes,
                        report_type="ALL",
                        return_stats=True,
                    )
                    earnings_map.update(fallback_result)

                predictive_earnings_stats = {
                    "mode": "express_latest_snapshot",
                    "grouped_report_type_stats": grouped_stats,
                    "unresolved_fallback_stats": fallback_stats or {},
                    "unresolved_code_count": len(unresolved_codes),
                }
            else:
                earnings_map, predictive_earnings_stats = _fetch_earnings_signal_batch(
                    predictive_ts_codes,
                    report_type=earnings_report_type,
                    return_stats=True,
                    financial_end_date_map=earnings_end_date_map,
                )
        except Exception as err:
            logger.warning("predictive valuation pick degraded: %s", err)
        perf_after_earnings = time.perf_counter()

        predictive_financial_maps_enabled = bool(apply_financial_filters)
        predictive_netprofit_map = {}
        predictive_indicator_map = {}
        if predictive_financial_maps_enabled:
            predictive_netprofit_map = _build_latest_income_netprofit_map(predictive_ts_codes)
            predictive_indicator_map = {
                code: _load_latest_indicator_profile(code)
                for code in predictive_ts_codes
            }

        predictive_rows = []
        for row in result:
            ts_code = row.get("ts_code")
            ts_code_norm = str(ts_code or "").strip().upper()
            netprofit_payload = predictive_netprofit_map.get(ts_code_norm) or {}
            indicator_payload = predictive_indicator_map.get(ts_code_norm) or {}

            financial_netprofit = None
            financial_netprofit_yoy = None
            financial_prev_netprofit = None
            financial_ebit = None
            financial_ebit_yoy = None
            financial_prev_ebit = None
            if predictive_financial_maps_enabled:
                financial_netprofit = _to_float_or_none(netprofit_payload.get("financial_netprofit"))
                financial_netprofit_yoy = _to_float_or_none(netprofit_payload.get("financial_netprofit_yoy"))
                financial_prev_netprofit = _to_float_or_none(netprofit_payload.get("financial_prev_netprofit"))
                if financial_prev_netprofit is None and financial_netprofit is not None and financial_netprofit_yoy is not None:
                    yoy_base = 1.0 + float(financial_netprofit_yoy)
                    if abs(yoy_base) > 1e-9:
                        financial_prev_netprofit = float(financial_netprofit) / yoy_base

                financial_ebit = _to_float_or_none(indicator_payload.get("financial_ebit"))
                financial_ebit_yoy = _to_float_or_none(indicator_payload.get("financial_ebit_yoy"))
                financial_prev_ebit = _to_float_or_none(indicator_payload.get("financial_prev_ebit"))
                if financial_prev_ebit is None and financial_ebit is not None and financial_ebit_yoy is not None:
                    yoy_base = 1.0 + float(financial_ebit_yoy)
                    if abs(yoy_base) > 1e-9:
                        financial_prev_ebit = float(financial_ebit) / yoy_base

            earnings_payload = earnings_map.get(ts_code) or _build_earnings_default_data(
                ts_code,
                earnings_report_type if earnings_report_type != "ALL" else "",
            )

            earnings_report_type_value = str(earnings_payload.get("report_type") or "UNKNOWN").upper()
            earnings_action_value = str(earnings_payload.get("action") or "HOLD").upper()
            earnings_risk_value = _canonicalize_risk_level(earnings_payload.get("risk_level")) or "MEDIUM"
            earnings_source_value = str(earnings_payload.get("feature_data_source") or "").strip().lower()
            earnings_fiscal_year = earnings_payload.get("financial_fiscal_year")
            earnings_report_end_date = _parse_date_like(
                earnings_payload.get("report_end_date") or earnings_payload.get("profit_report_end_date")
            )
            valuation_report_end_date_row = _parse_date_like(row.get("valuation_profit_report_end_date"))
            earnings_report_type_from_end_date = _infer_report_type_from_end_date(earnings_report_end_date)
            pred_earnings_growth = _to_float_or_none(earnings_payload.get("pred_earnings_growth"))
            prev_year_netprofit_non_negative = earnings_payload.get("prev_year_netprofit_non_negative")
            earnings_signal_score = _to_float_or_none(earnings_payload.get("signal_score"))
            earnings_target_return_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))

            if predictive_report_window_strict:
                # Enforce report window deterministically:
                # 1) If valuation snapshot has report_end_date, it must equal requested end_date.
                # 2) Only when valuation report_end_date is missing, fallback to earnings payload checks.
                if valuation_report_end_date_row is not None:
                    if valuation_report_end_date_row != valuation_report_end_date:
                        continue
                else:
                    matches_end_date = (
                        earnings_report_end_date is not None
                        and earnings_report_end_date == valuation_report_end_date
                    )
                    matches_year_and_type = (
                        requested_fiscal_year_num is not None
                        and str(earnings_fiscal_year or "").strip() == str(requested_fiscal_year_num)
                        and (
                            (earnings_report_type_from_end_date or "").upper() == earnings_report_type
                            or earnings_report_type_value == earnings_report_type
                        )
                    )
                    if not (matches_end_date and matches_year_and_type):
                        continue

            if signal_action and earnings_action_value != signal_action:
                continue
            if risk_level_set and earnings_risk_value not in risk_level_set:
                continue
            if min_signal_score is not None and (earnings_signal_score is None or earnings_signal_score < min_signal_score):
                continue
            if min_target_return_pct is not None and (
                earnings_target_return_pct is None or earnings_target_return_pct < min_target_return_pct
            ):
                continue
            if feature_data_source and earnings_source_value != feature_data_source:
                continue
            if bool(apply_financial_filters) and min_netprofit_growth is not None and (
                pred_earnings_growth is None or pred_earnings_growth < min_netprofit_growth
            ):
                continue
            if bool(apply_financial_filters) and min_netprofit_growth is not None and prev_year_netprofit_non_negative is not True:
                continue

            predictive_valuation_status = _classify_predictive_valuation_status(
                earnings_target_return_pct,
                band_pct=valuation_band_pct,
            )
            predictive_buy_candidate = _is_predictive_buy_candidate(
                action=earnings_action_value,
                signal_score=earnings_signal_score,
                risk_level=earnings_risk_value,
                target_return_pct=earnings_target_return_pct,
            )

            if valuation_status and predictive_valuation_status != valuation_status:
                continue
            if buy_candidate_only and not predictive_buy_candidate:
                continue

            merged_row = {
                **row,
                "traditional_valuation_status": row.get("valuation_status"),
                "traditional_buy_candidate": bool(row.get("buy_candidate")),
                "traditional_buy_candidate_backtest_aligned": bool(row.get("buy_candidate_backtest_aligned")),
                "predictive_valuation_status": predictive_valuation_status,
                "predictive_buy_candidate": bool(predictive_buy_candidate),
                "valuation_status": predictive_valuation_status,
                "buy_candidate": bool(predictive_buy_candidate),
                "earnings_report_type": earnings_report_type_value,
                "pred_earnings_growth": pred_earnings_growth,
                "prev_year_netprofit_non_negative": prev_year_netprofit_non_negative,
                "signal_score": earnings_signal_score,
                "target_return_pct": earnings_target_return_pct,
                "target_price": _to_float_or_none(earnings_payload.get("target_price")),
                "target_market_cap": _to_float_or_none(earnings_payload.get("target_market_cap")),
                "target_return_low_pct": _to_float_or_none(earnings_payload.get("target_return_low_pct")),
                "target_return_high_pct": _to_float_or_none(earnings_payload.get("target_return_high_pct")),
                "target_price_low": _to_float_or_none(earnings_payload.get("target_price_low")),
                "target_price_high": _to_float_or_none(earnings_payload.get("target_price_high")),
                "target_market_cap_low": _to_float_or_none(earnings_payload.get("target_market_cap_low")),
                "target_market_cap_high": _to_float_or_none(earnings_payload.get("target_market_cap_high")),
                "action": earnings_action_value,
                "risk_level": earnings_risk_value,
                "earnings_model_version": earnings_payload.get("model_version"),
                "earnings_asof_date": earnings_payload.get("asof_date"),
                "feature_data_source": earnings_payload.get("feature_data_source"),
                "financial_fiscal_year": earnings_fiscal_year,
                "financial_ann_date": earnings_payload.get("financial_ann_date"),
                "financial_netprofit_yoy": financial_netprofit_yoy,
                "financial_ebit_yoy": financial_ebit_yoy,
                "financial_prev_netprofit": financial_prev_netprofit,
                "financial_prev_ebit": financial_prev_ebit,
                "predictive_explain": earnings_payload.get("explain") or {},
            }
            merged_row["predictive_pick_score"] = _compute_predictive_pick_score(merged_row)
            predictive_rows.append(merged_row)

        predictive_rows.sort(
            key=lambda item: (
                -(item.get("predictive_pick_score") or -999999.0),
                -(_to_float_or_none(item.get("target_return_pct")) or -999999.0),
                -(_to_float_or_none(item.get("valuation_gap_pct")) or -999999.0),
                0 if item.get("buy_candidate") else 1,
                str(item.get("ts_code") or ""),
            )
        )
        result = predictive_rows
    else:
        perf_after_earnings = time.perf_counter()
        predictive_earnings_stats = {}

    def _row_primary_score(item):
        if picking_mode == "predictive":
            score = _to_float_or_none(item.get("predictive_pick_score"))
            if score is not None:
                return score
            return _to_float_or_none(item.get("signal_score"))
        score = _to_float_or_none(item.get("valuation_score"))
        if score is not None:
            return score
        return _to_float_or_none(item.get("undervalue_score"))

    def _row_close_price(item):
        price = _to_float_or_none(item.get("close_qfq"))
        if price is not None:
            return price
        return _to_float_or_none(item.get("close"))

    def _row_risk_rank(item):
        risk_text = _canonicalize_risk_level(
            item.get("risk_level") or item.get("valuation_risk_level")
        )
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(risk_text, 9)

    def _sort_result_key(item):
        score = _row_primary_score(item)
        valuation_gap = _to_float_or_none(item.get("valuation_gap_pct"))
        target_return = _to_float_or_none(item.get("target_return_pct"))
        close_price = _row_close_price(item)
        ts_code_key = str(item.get("ts_code") or "")

        if priority_policy == "deep_discount_first":
            return (
                valuation_gap is None,
                -(valuation_gap if valuation_gap is not None else -999999.0),
                score is None,
                -(score if score is not None else -999999.0),
                ts_code_key,
            )
        if priority_policy == "target_discount_first":
            return (
                target_return is None,
                -(target_return if target_return is not None else -999999.0),
                score is None,
                -(score if score is not None else -999999.0),
                ts_code_key,
            )
        if priority_policy == "high_price_first":
            return (
                close_price is None,
                -(close_price if close_price is not None else -999999.0),
                score is None,
                -(score if score is not None else -999999.0),
                ts_code_key,
            )
        if priority_policy == "low_price_first":
            return (
                close_price is None,
                close_price if close_price is not None else 999999.0,
                score is None,
                -(score if score is not None else -999999.0),
                ts_code_key,
            )
        if priority_policy == "low_risk_high_score":
            return (
                _row_risk_rank(item),
                score is None,
                -(score if score is not None else -999999.0),
                target_return is None,
                -(target_return if target_return is not None else -999999.0),
                ts_code_key,
            )
        return (
            score is None,
            -(score if score is not None else -999999.0),
            target_return is None,
            -(target_return if target_return is not None else -999999.0),
            valuation_gap is None,
            -(valuation_gap if valuation_gap is not None else -999999.0),
            ts_code_key,
        )

    result = sorted(result, key=_sort_result_key)

    paged_result = result[from_index:to_index]
    if picking_mode != "predictive":
        _attach_traditional_quick_metrics(paged_result, market="CN")
    _attach_recent_financial_report_badge(
        paged_result,
        asof_date=trade_date_for_query,
        market="CN",
        include_official_ann_lookup=bool(apply_financial_filters),
    )
    _attach_signal_window_returns(
        paged_result,
        trade_date_for_query=trade_date_for_query,
        freq=normalized_freq,
        signal_end_date=latest_trade_date,
    )
    perf_after_all = time.perf_counter()

    try:
        cache.set(
            cache_key,
            {
                "result": result,
                "total_candidates": total_candidates_count,
                "multi_candidate_rows": multi_candidate_rows,
                "predictive_earnings_stats": predictive_earnings_stats,
                "moneyflow_filter_stats": moneyflow_filter_stats,
            },
            VALUATION_PICK_CACHE_TTL_SECONDS,
        )
    except Exception as cache_err:
        logger.debug("valuation pick cache set failed: %s", cache_err)

    return _build_pick_response(
        paged_result=paged_result,
        total_filtered=len(result),
        total_candidates=total_candidates_count,
        strategy_effective_stocks=multi_candidate_rows,
        predictive_stats=predictive_earnings_stats,
        moneyflow_stats=moneyflow_filter_stats,
        timing_ms={
            "total": _ms(perf_t0, perf_after_all),
            "load_trading_rows": _ms(perf_t0, perf_after_trading),
            "build_valuation_snapshot": _ms(perf_after_trading, perf_after_snapshot),
            "predictive_earnings_enrich": _ms(perf_after_snapshot, perf_after_earnings),
            "post_process_and_page": _ms(perf_after_earnings, perf_after_all),
        },
        cache_hit=False,
    )


@api_view(["GET"])
def get_sw_industry_options(request):
    market = str(request.query_params.get("market", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"
    level = str(request.query_params.get("level", "L3") if hasattr(request, "query_params") else "L3").strip().upper() or "L3"
    if level not in {"L1", "L2", "L3"}:
        level = "L3"

    try:
        cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
        level_items = (cfg.sw_mapping.get("levels", {}) or {}).get(level, {})
        options = []
        for code, entry in level_items.items():
            industry_code = entry.get("index_code") or code
            industry_name = entry.get("industry_name") or ""
            if not industry_code:
                continue
            options.append(
                {
                    "industry_code": industry_code,
                    "industry_name": industry_name,
                    "level": level,
                }
            )
        options = sorted(options, key=lambda item: (str(item.get("industry_code") or ""), str(item.get("industry_name") or "")))
        return Response(
            {
                "data": options,
                "meta": {
                    "market": market,
                    "level": level,
                    "total": len(options),
                },
            }
        )
    except Exception as exc:
        return Response(
            {
                "data": [],
                "meta": {
                    "market": market,
                    "level": level,
                    "total": 0,
                },
                "error": str(exc),
            }
        )


def _resolve_sw_l3_entry(cfg: ValuationConfig, industry_code: str):
    token = str(industry_code or "").strip()
    if not token:
        return None, None

    levels = cfg.sw_mapping.get("levels", {}) if isinstance(cfg.sw_mapping, dict) else {}
    l3_items = levels.get("L3", {}) if isinstance(levels, dict) else {}
    if not isinstance(l3_items, dict):
        return None, None

    if token in l3_items:
        return token, l3_items.get(token) or {}

    token_upper = token.upper()
    for code, entry in l3_items.items():
        if not isinstance(entry, dict):
            continue
        index_code = str(entry.get("index_code") or "").strip()
        industry_code_value = str(entry.get("industry_code") or "").strip()
        industry_name = str(entry.get("industry_name") or "").strip()
        if token_upper == index_code.upper() or token_upper == industry_code_value.upper() or token == industry_name:
            return code, entry

    return None, None


def _parse_sw_period(period_text: str):
    normalized = str(period_text or "5Y").strip().upper() or "5Y"
    if normalized == "ALL":
        return normalized, None
    if normalized in {"30D", "60D", "90D"}:
        return normalized, datetime.timedelta(days=int(normalized[:-1]))
    if normalized in {"1Y", "3Y", "5Y", "10Y"}:
        years = int(normalized[:-1])
        return normalized, datetime.timedelta(days=years * 365)
    return "5Y", datetime.timedelta(days=5 * 365)


def _as_float_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _compute_quantile(values, quantile):
    cleaned = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v))
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return float(cleaned[0])
    position = (len(cleaned) - 1) * float(quantile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(cleaned[lower])
    lower_weight = upper - position
    upper_weight = position - lower
    return float(cleaned[lower] * lower_weight + cleaned[upper] * upper_weight)


SW_ROTATION_OUTPUT_SUBDIR = "output/sw_rotation"
SW_ROTATION_LATEST_FILE = "sw_industry_rotation_latest.json"
SW_ROTATION_RUNS_FILE = "sw_industry_rotation_runs.json"
SW_ROTATION_RETURN_WINDOWS = (5, 20, 60)
THS_INDUSTRY_OUTPUT_SUBDIR = "output/industry_universe"
THS_INDUSTRY_SNAPSHOT_FILE = "ths_industry_index_snapshot.json"
THS_INDUSTRY_HISTORY_CACHE_TTL_SECONDS = int(
    getattr(settings, "THS_INDUSTRY_HISTORY_CACHE_TTL_SECONDS", 600) or 600
)
THS_MONEYFLOW_DAILY_FILE = "ths_moneyflow_daily.json"
THS_MONEYFLOW_SCORE_LATEST_FILE = "ths_moneyflow_score_latest.json"
THS_MONEYFLOW_TOPN_DEFAULT = int(getattr(settings, "THS_MONEYFLOW_TOPN_DEFAULT", 20) or 20)
THS_MONEYFLOW_LOOKBACK_DAYS = int(getattr(settings, "THS_MONEYFLOW_LOOKBACK_DAYS", 30) or 30)
THS_STOCK_MONEYFLOW_WINDOW_OPTIONS = (5, 10, 15, 30, 60)
THS_STOCK_MONEYFLOW_DEFAULT_WINDOW = int(
    getattr(settings, "THS_STOCK_MONEYFLOW_DEFAULT_WINDOW", 10) or 10
)
THS_MONEYFLOW_SCORE_WEIGHT_MONEYFLOW = 0.50
THS_MONEYFLOW_SCORE_WEIGHT_POSITION = 0.30
THS_MONEYFLOW_SCORE_WEIGHT_VOLATILITY = 0.20
THS_MONEYFLOW_ACCUMULATION_BONUS_MAP = {
    "NONE": 0.0,
    "EARLY": 2.0,
    "SUSTAINING": 5.0,
    "STRONG": 8.0,
}
THS_MONEYFLOW_ACCUMULATION_RULE_VERSION = "v1_10_30_60"
THS_INDEX_TYPE_LABEL_MAP = {
    "N": "概念指数",
    "I": "行业指数",
    "R": "地域指数",
    "S": "特色指数",
    "ST": "风格指数",
    "TH": "主题指数",
    "BB": "宽基指数",
}


def _resolve_sw_rotation_snapshot_path():
    output_dir = Path(settings.BASE_DIR) / SW_ROTATION_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / SW_ROTATION_LATEST_FILE


def _resolve_sw_rotation_runs_path():
    output_dir = Path(settings.BASE_DIR) / SW_ROTATION_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / SW_ROTATION_RUNS_FILE


def _normalize_rotation_ths_index_type(value):
    token = str(value or "ALL").strip().upper() or "ALL"
    if token == "ALL":
        return "ALL"
    normalized = _normalize_ths_index_type(token)
    return normalized if normalized else "ALL"


def _rotation_file_suffix(industry_type, ths_index_type="ALL"):
    normalized = _normalize_industry_universe_type(industry_type)
    if normalized == "sw":
        return ""
    if normalized == "ths":
        ths_token = _normalize_rotation_ths_index_type(ths_index_type).lower()
        return f"_{normalized}_{ths_token}"
    return f"_{normalized}"


def _resolve_rotation_snapshot_path(industry_type="sw", ths_index_type="ALL"):
    output_dir = Path(settings.BASE_DIR) / SW_ROTATION_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _rotation_file_suffix(industry_type, ths_index_type)
    if not suffix:
        return output_dir / SW_ROTATION_LATEST_FILE
    return output_dir / f"sw_industry_rotation_latest{suffix}.json"


def _resolve_rotation_runs_path(industry_type="sw", ths_index_type="ALL"):
    output_dir = Path(settings.BASE_DIR) / SW_ROTATION_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _rotation_file_suffix(industry_type, ths_index_type)
    if not suffix:
        return output_dir / SW_ROTATION_RUNS_FILE
    return output_dir / f"sw_industry_rotation_runs{suffix}.json"


def _resolve_ths_industry_snapshot_path():
    output_dir = Path(settings.BASE_DIR) / THS_INDUSTRY_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / THS_INDUSTRY_SNAPSHOT_FILE


def _resolve_ths_moneyflow_daily_path():
    output_dir = Path(settings.BASE_DIR) / THS_INDUSTRY_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / THS_MONEYFLOW_DAILY_FILE


def _resolve_ths_moneyflow_score_latest_path():
    output_dir = Path(settings.BASE_DIR) / THS_INDUSTRY_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / THS_MONEYFLOW_SCORE_LATEST_FILE


def _normalize_moneyflow_trade_date(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    return ""


def _normalize_ths_industry_code(value):
    token = str(value or "").strip().upper()
    if not token:
        return ""
    if "." not in token:
        token = f"{token}.TI"
    return token


def _read_ths_moneyflow_daily_payload():
    path = _resolve_ths_moneyflow_daily_path()
    if not path.exists():
        return {"rows": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"rows": []}
    if not isinstance(payload, dict):
        return {"rows": []}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        payload["rows"] = []
    return payload


def _write_ths_moneyflow_daily_payload(payload):
    path = _resolve_ths_moneyflow_daily_path()
    normalized = payload if isinstance(payload, dict) else {"rows": []}
    rows = normalized.get("rows") if isinstance(normalized.get("rows"), list) else []

    serializable = []
    for row in rows:
        item = row if isinstance(row, dict) else {}
        trade_date = _normalize_moneyflow_trade_date(item.get("trade_date"))
        industry_code = _normalize_ths_industry_code(item.get("industry_code"))
        if not trade_date or not industry_code:
            continue
        index_type = _normalize_ths_index_type(item.get("index_type"))
        serializable.append(
            {
                "trade_date": trade_date,
                "industry_code": industry_code,
                "industry_name": str(item.get("industry_name") or "").strip(),
                "index_type": index_type,
                "index_type_label": str(item.get("index_type_label") or _get_ths_index_type_label(index_type)).strip(),
                "net_amount": _as_float_or_none(item.get("net_amount")),
                "net_pct": _as_float_or_none(item.get("net_pct")),
                "updated_at": str(item.get("updated_at") or "").strip(),
            }
        )

    serializable = sorted(
        serializable,
        key=lambda item: (str(item.get("trade_date") or ""), str(item.get("industry_code") or "")),
    )
    normalized["rows"] = serializable
    normalized["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _read_ths_moneyflow_score_latest_payload():
    path = _resolve_ths_moneyflow_score_latest_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_ths_moneyflow_score_latest_payload(payload):
    path = _resolve_ths_moneyflow_score_latest_path()
    normalized = payload if isinstance(payload, dict) else {}
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _fetch_ths_moneyflow_cnt_frame(pro, trade_date_text):
    if pro is None or not hasattr(pro, "moneyflow_cnt_ths"):
        return None

    token = str(trade_date_text or "").replace("-", "")
    if len(token) != 8 or not token.isdigit():
        return None

    for call_kwargs in (
        {
            "trade_date": token,
            "fields": "trade_date,ts_code,name,net_amount,net_pct,net_amount_rate,net_mf_amount,net_mf_rate",
        },
        {"trade_date": token},
        {
            "start_date": token,
            "end_date": token,
            "fields": "trade_date,ts_code,name,net_amount,net_pct,net_amount_rate,net_mf_amount,net_mf_rate",
        },
        {"start_date": token, "end_date": token},
    ):
        try:
            frame = pro.moneyflow_cnt_ths(**call_kwargs)
            if frame is not None:
                return frame
        except TypeError:
            continue
        except Exception:
            continue
    return None


def _upsert_ths_moneyflow_daily_rows(incoming_rows):
    payload = _read_ths_moneyflow_daily_payload()
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    row_map = {}

    for row in rows:
        item = row if isinstance(row, dict) else {}
        trade_date = _normalize_moneyflow_trade_date(item.get("trade_date"))
        industry_code = _normalize_ths_industry_code(item.get("industry_code"))
        if not trade_date or not industry_code:
            continue
        row_map[(trade_date, industry_code)] = {
            "trade_date": trade_date,
            "industry_code": industry_code,
            "industry_name": str(item.get("industry_name") or "").strip(),
            "index_type": _normalize_ths_index_type(item.get("index_type")),
            "index_type_label": str(item.get("index_type_label") or "").strip(),
            "net_amount": _as_float_or_none(item.get("net_amount")),
            "net_pct": _as_float_or_none(item.get("net_pct")),
            "updated_at": str(item.get("updated_at") or "").strip(),
        }

    upsert_count = 0
    for row in incoming_rows:
        item = row if isinstance(row, dict) else {}
        trade_date = _normalize_moneyflow_trade_date(item.get("trade_date"))
        industry_code = _normalize_ths_industry_code(item.get("industry_code"))
        if not trade_date or not industry_code:
            continue
        index_type = _normalize_ths_index_type(item.get("index_type"))
        row_map[(trade_date, industry_code)] = {
            "trade_date": trade_date,
            "industry_code": industry_code,
            "industry_name": str(item.get("industry_name") or "").strip(),
            "index_type": index_type,
            "index_type_label": str(item.get("index_type_label") or _get_ths_index_type_label(index_type)).strip(),
            "net_amount": _as_float_or_none(item.get("net_amount")),
            "net_pct": _as_float_or_none(item.get("net_pct")),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        upsert_count += 1

    payload["rows"] = list(row_map.values())
    output_path = _write_ths_moneyflow_daily_payload(payload)
    return {
        "upsert_count": upsert_count,
        "total_rows": len(payload.get("rows") or []),
        "output_path": str(output_path),
    }


def _sync_ths_moneyflow_daily(lookback_days=7):
    try:
        pro = get_tushare_pro()
    except Exception as exc:
        raise RuntimeError(f"init tushare pro failed: {exc}") from exc

    rows_to_upsert = []
    fetched_dates = []
    checked_days = max(1, int(lookback_days or 1))
    today = datetime.date.today()

    ths_index_rows = _load_ths_index_rows(pro=pro, prefer_local=True)
    ths_type_map = {
        _normalize_ths_industry_code(item.get("industry_key")): {
            "display_name": str(item.get("display_name") or "").strip(),
            "index_type": _normalize_ths_index_type(item.get("index_type")),
        }
        for item in ths_index_rows
        if isinstance(item, dict)
    }

    for offset in range(checked_days):
        trade_date = (today - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
        frame = _fetch_ths_moneyflow_cnt_frame(pro, trade_date)
        if frame is None or getattr(frame, "empty", True):
            continue

        fetched_dates.append(trade_date)
        for _, row in frame.fillna("").iterrows():
            industry_code = _normalize_ths_industry_code(row.get("ts_code") or row.get("industry_code") or row.get("code"))
            if not industry_code:
                continue

            index_meta = ths_type_map.get(industry_code) or {}
            index_type = _normalize_ths_index_type(index_meta.get("index_type") or row.get("type") or row.get("index_type"))
            industry_name = (
                str(row.get("name") or row.get("industry_name") or row.get("index_name") or index_meta.get("display_name") or "").strip()
                or industry_code
            )
            resolved_trade_date = _normalize_moneyflow_trade_date(row.get("trade_date")) or trade_date

            rows_to_upsert.append(
                {
                    "trade_date": resolved_trade_date,
                    "industry_code": industry_code,
                    "industry_name": industry_name,
                    "index_type": index_type,
                    "index_type_label": _get_ths_index_type_label(index_type),
                    "net_amount": _pick_first_numeric_metric(
                        row,
                        ["net_amount", "net_mf_amount", "net_buy_amount", "buy_amount"],
                    ),
                    "net_pct": _as_float_or_none(
                        row.get("net_pct")
                        or row.get("net_amount_rate")
                        or row.get("net_mf_rate")
                    ),
                }
            )

    upsert_result = _upsert_ths_moneyflow_daily_rows(rows_to_upsert)
    return {
        "checked_days": checked_days,
        "fetched_dates": sorted(set(fetched_dates)),
        "fetched_rows": len(rows_to_upsert),
        **upsert_result,
    }


def _normalize_stock_moneyflow_window(raw_value, default_value=None):
    try:
        candidate = int(raw_value)
    except (TypeError, ValueError):
        candidate = int(default_value or THS_STOCK_MONEYFLOW_DEFAULT_WINDOW)
    if candidate not in THS_STOCK_MONEYFLOW_WINDOW_OPTIONS:
        candidate = int(default_value or THS_STOCK_MONEYFLOW_DEFAULT_WINDOW)
    if candidate not in THS_STOCK_MONEYFLOW_WINDOW_OPTIONS:
        candidate = 10
    return candidate


def _fetch_stock_moneyflow_ths_frame(pro, trade_date_text, offset=0, limit=5000):
    if pro is None or not hasattr(pro, "moneyflow_ths"):
        return None

    token = str(trade_date_text or "").replace("-", "")
    if len(token) != 8 or not token.isdigit():
        return None

    fields = (
        "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,"
        "buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,"
        "net_amount,net_pct,net_amount_rate,net_mf_amount,net_mf_rate"
    )
    call_kwargs_list = [
        {
            "trade_date": token,
            "fields": fields,
            "offset": int(offset),
            "limit": int(limit),
        },
        {
            "trade_date": token,
            "offset": int(offset),
            "limit": int(limit),
        },
        {
            "trade_date": token,
            "fields": fields,
        },
        {"trade_date": token},
    ]

    for call_kwargs in call_kwargs_list:
        try:
            frame = pro.moneyflow_ths(**call_kwargs)
            if frame is not None:
                return frame
        except TypeError:
            continue
        except Exception:
            continue
    return None


def _upsert_stock_moneyflow_ths_rows(incoming_rows):
    row_map = {}
    for row in incoming_rows:
        item = row if isinstance(row, dict) else {}
        ts_code = _normalize_ts_code(item.get("ts_code"))
        trade_date = _parse_date_like(item.get("trade_date"))
        if not ts_code or trade_date is None:
            continue
        row_map[(ts_code, trade_date)] = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "buy_sm_amount": _as_float_or_none(item.get("buy_sm_amount")),
            "sell_sm_amount": _as_float_or_none(item.get("sell_sm_amount")),
            "buy_md_amount": _as_float_or_none(item.get("buy_md_amount")),
            "sell_md_amount": _as_float_or_none(item.get("sell_md_amount")),
            "buy_lg_amount": _as_float_or_none(item.get("buy_lg_amount")),
            "sell_lg_amount": _as_float_or_none(item.get("sell_lg_amount")),
            "buy_elg_amount": _as_float_or_none(item.get("buy_elg_amount")),
            "sell_elg_amount": _as_float_or_none(item.get("sell_elg_amount")),
            "net_amount": _as_float_or_none(item.get("net_amount")),
            "net_pct": _as_float_or_none(item.get("net_pct")),
            "net_amount_rate": _as_float_or_none(item.get("net_amount_rate")),
            "net_mf_amount": _as_float_or_none(item.get("net_mf_amount")),
            "net_mf_rate": _as_float_or_none(item.get("net_mf_rate")),
            "raw_payload": item.get("raw_payload") if isinstance(item.get("raw_payload"), dict) else {},
        }

    objects = [StockThsMoneyflowDaily(**payload) for payload in row_map.values()]
    if not objects:
        return {"upsert_count": 0, "total_rows": int(StockThsMoneyflowDaily.objects.count())}

    try:
        StockThsMoneyflowDaily.objects.bulk_create(
            objects,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["ts_code", "trade_date"],
            update_fields=[
                "buy_sm_amount",
                "sell_sm_amount",
                "buy_md_amount",
                "sell_md_amount",
                "buy_lg_amount",
                "sell_lg_amount",
                "buy_elg_amount",
                "sell_elg_amount",
                "net_amount",
                "net_pct",
                "net_amount_rate",
                "net_mf_amount",
                "net_mf_rate",
                "raw_payload",
                "updated_at",
            ],
        )
    except TypeError:
        for payload in row_map.values():
            StockThsMoneyflowDaily.objects.update_or_create(
                ts_code=payload["ts_code"],
                trade_date=payload["trade_date"],
                defaults={
                    "buy_sm_amount": payload["buy_sm_amount"],
                    "sell_sm_amount": payload["sell_sm_amount"],
                    "buy_md_amount": payload["buy_md_amount"],
                    "sell_md_amount": payload["sell_md_amount"],
                    "buy_lg_amount": payload["buy_lg_amount"],
                    "sell_lg_amount": payload["sell_lg_amount"],
                    "buy_elg_amount": payload["buy_elg_amount"],
                    "sell_elg_amount": payload["sell_elg_amount"],
                    "net_amount": payload["net_amount"],
                    "net_pct": payload["net_pct"],
                    "net_amount_rate": payload["net_amount_rate"],
                    "net_mf_amount": payload["net_mf_amount"],
                    "net_mf_rate": payload["net_mf_rate"],
                    "raw_payload": payload["raw_payload"],
                },
            )

    return {
        "upsert_count": len(objects),
        "total_rows": int(StockThsMoneyflowDaily.objects.count()),
    }


def _sync_stock_moneyflow_ths_daily(start_date=None, end_date=None, latest=False, lookback_days=365):
    try:
        pro = get_tushare_pro()
    except Exception as exc:
        raise RuntimeError(f"init tushare pro failed: {exc}") from exc

    today = datetime.date.today()
    parsed_start = _parse_date_like(start_date)
    parsed_end = _parse_date_like(end_date)

    if latest:
        start_dt = today
        end_dt = today
    else:
        end_dt = parsed_end or today
        if parsed_start is not None:
            start_dt = parsed_start
        else:
            lookback = max(1, int(lookback_days or 365))
            start_dt = end_dt - datetime.timedelta(days=lookback - 1)

    if start_dt > end_dt:
        raise ValueError("start_date should be <= end_date")

    checked_days = 0
    fetched_rows = 0
    upsert_count = 0
    fetched_dates = []

    current = start_dt
    while current <= end_dt:
        checked_days += 1
        trade_date_text = current.strftime("%Y-%m-%d")

        page_offset = 0
        page_limit = 5000
        rows_for_date = []
        while True:
            frame = _fetch_stock_moneyflow_ths_frame(
                pro,
                trade_date_text,
                offset=page_offset,
                limit=page_limit,
            )
            if frame is None or getattr(frame, "empty", True):
                break

            for _, row in frame.fillna("").iterrows():
                ts_code = _normalize_ts_code(row.get("ts_code"))
                if not ts_code:
                    continue
                rows_for_date.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": _parse_date_like(row.get("trade_date")) or current,
                        "buy_sm_amount": row.get("buy_sm_amount"),
                        "sell_sm_amount": row.get("sell_sm_amount"),
                        "buy_md_amount": row.get("buy_md_amount"),
                        "sell_md_amount": row.get("sell_md_amount"),
                        "buy_lg_amount": row.get("buy_lg_amount"),
                        "sell_lg_amount": row.get("sell_lg_amount"),
                        "buy_elg_amount": row.get("buy_elg_amount"),
                        "sell_elg_amount": row.get("sell_elg_amount"),
                        "net_amount": row.get("net_amount"),
                        "net_pct": row.get("net_pct"),
                        "net_amount_rate": row.get("net_amount_rate"),
                        "net_mf_amount": row.get("net_mf_amount"),
                        "net_mf_rate": row.get("net_mf_rate"),
                        "raw_payload": {
                            "ts_code": row.get("ts_code"),
                            "trade_date": row.get("trade_date"),
                            "buy_sm_amount": row.get("buy_sm_amount"),
                            "sell_sm_amount": row.get("sell_sm_amount"),
                            "buy_md_amount": row.get("buy_md_amount"),
                            "sell_md_amount": row.get("sell_md_amount"),
                            "buy_lg_amount": row.get("buy_lg_amount"),
                            "sell_lg_amount": row.get("sell_lg_amount"),
                            "buy_elg_amount": row.get("buy_elg_amount"),
                            "sell_elg_amount": row.get("sell_elg_amount"),
                            "net_amount": row.get("net_amount"),
                            "net_pct": row.get("net_pct"),
                            "net_amount_rate": row.get("net_amount_rate"),
                            "net_mf_amount": row.get("net_mf_amount"),
                            "net_mf_rate": row.get("net_mf_rate"),
                        },
                    }
                )

            frame_size = int(len(frame.index))
            if frame_size < page_limit:
                break
            page_offset += page_limit

        if rows_for_date:
            fetched_dates.append(trade_date_text)
            fetched_rows += len(rows_for_date)
            upsert_result = _upsert_stock_moneyflow_ths_rows(rows_for_date)
            upsert_count += int(upsert_result.get("upsert_count") or 0)

        current += datetime.timedelta(days=1)

    return {
        "checked_days": checked_days,
        "fetched_dates": fetched_dates,
        "fetched_rows": fetched_rows,
        "upsert_count": upsert_count,
        "total_rows": int(StockThsMoneyflowDaily.objects.count()),
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
    }


def _build_stock_moneyflow_sum_map(ts_codes, asof_date, window_days):
    normalized_codes = list(
        dict.fromkeys(
            [
                _normalize_ts_code(code)
                for code in (ts_codes or [])
                if _normalize_ts_code(code)
            ]
        )
    )
    if not normalized_codes:
        return {}

    end_dt = _parse_date_like(asof_date) or datetime.date.today()
    lookback_days = max(5, int(window_days or THS_STOCK_MONEYFLOW_DEFAULT_WINDOW))
    scan_start = end_dt - datetime.timedelta(days=max(lookback_days * 3, 90))

    qs = (
        StockThsMoneyflowDaily.objects.filter(
            ts_code__in=normalized_codes,
            trade_date__gte=scan_start,
            trade_date__lte=end_dt,
        )
        .order_by("ts_code", "-trade_date")
        .values("ts_code", "trade_date", "net_amount", "net_mf_amount")
    )

    sum_map = {}
    for row in qs:
        ts_code = _normalize_ts_code(row.get("ts_code"))
        if not ts_code:
            continue
        payload = sum_map.get(ts_code)
        if payload is None:
            payload = {
                "net_inflow_sum": 0.0,
                "observed_days": 0,
                "latest_trade_date": None,
            }
            sum_map[ts_code] = payload
        if payload["observed_days"] >= lookback_days:
            continue

        payload["observed_days"] += 1
        net_inflow = _as_float_or_none(row.get("net_amount"))
        if net_inflow is None:
            net_inflow = _as_float_or_none(row.get("net_mf_amount"))
        payload["net_inflow_sum"] += float(net_inflow or 0.0)
        if payload["latest_trade_date"] is None:
            payload["latest_trade_date"] = row.get("trade_date")

    return sum_map


def _compute_and_write_ths_moneyflow_score_snapshot(top_n=None, lookback_days=None, ths_index_type="ALL"):
    try:
        pro = get_tushare_pro()
    except Exception as exc:
        raise RuntimeError(f"init tushare pro failed: {exc}") from exc

    top_n_value = max(1, min(100, int(top_n or THS_MONEYFLOW_TOPN_DEFAULT)))
    lookback = max(5, min(180, int(lookback_days or THS_MONEYFLOW_LOOKBACK_DAYS)))
    requested_type = _normalize_rotation_ths_index_type(ths_index_type)

    daily_payload = _read_ths_moneyflow_daily_payload()
    daily_rows = daily_payload.get("rows") if isinstance(daily_payload.get("rows"), list) else []
    if not daily_rows:
        raise RuntimeError("ths moneyflow daily dataset is empty")

    by_code_rows = defaultdict(list)
    by_code_name = {}
    by_code_type = {}
    by_code_member_count = {}
    available_trade_dates = set()
    for row in daily_rows:
        item = row if isinstance(row, dict) else {}
        trade_date = _normalize_moneyflow_trade_date(item.get("trade_date"))
        industry_code = _normalize_ths_industry_code(item.get("industry_code"))
        if not trade_date or not industry_code:
            continue
        net_amount = _as_float_or_none(item.get("net_amount"))
        if net_amount is None:
            continue
        index_type = _normalize_ths_index_type(item.get("index_type"))
        by_code_rows[industry_code].append({"trade_date": trade_date, "net_amount": float(net_amount)})
        by_code_name[industry_code] = str(item.get("industry_name") or by_code_name.get(industry_code) or industry_code).strip()
        by_code_type[industry_code] = index_type or by_code_type.get(industry_code, "")
        available_trade_dates.add(trade_date)

    if not by_code_rows:
        raise RuntimeError("ths moneyflow daily dataset has no valid rows")

    asof_date = max(available_trade_dates) if available_trade_dates else datetime.date.today().strftime("%Y-%m-%d")
    end_date = asof_date.replace("-", "")
    start_date = (datetime.datetime.strptime(asof_date, "%Y-%m-%d").date() - datetime.timedelta(days=180)).strftime("%Y%m%d")

    ths_index_rows = _load_ths_index_rows(pro=pro, prefer_local=True)
    for item in ths_index_rows:
        if not isinstance(item, dict):
            continue
        code = _normalize_ths_industry_code(item.get("industry_key"))
        if not code:
            continue
        by_code_type[code] = _normalize_ths_index_type(item.get("index_type")) or by_code_type.get(code, "")
        if code not in by_code_name or not by_code_name.get(code):
            by_code_name[code] = str(item.get("display_name") or code).strip()
        try:
            by_code_member_count[code] = int(item.get("member_count") or 0)
        except (TypeError, ValueError):
            by_code_member_count[code] = 0

    price_metric_cache = {}
    for industry_code in by_code_rows.keys():
        frame = _fetch_ths_daily_frame(pro, industry_code, start_date, end_date)
        close_series = []
        if frame is not None and not getattr(frame, "empty", True) and "trade_date" in frame.columns:
            work = frame.fillna("").copy()
            work["trade_date"] = work["trade_date"].astype(str)
            work = work.sort_values("trade_date")
            for _, row in work.iterrows():
                close_value = _as_float_or_none(row.get("close"))
                if close_value is None or close_value <= 0:
                    continue
                close_series.append(float(close_value))

        position_value = None
        volatility_value = None
        if close_series:
            close_tail = close_series[-60:] if len(close_series) > 60 else close_series
            low_value = min(close_tail) if close_tail else None
            high_value = max(close_tail) if close_tail else None
            latest_close = close_tail[-1] if close_tail else None
            if low_value is not None and high_value is not None and latest_close is not None and high_value > low_value:
                position_value = (latest_close - low_value) / (high_value - low_value)

            daily_returns = []
            for idx in range(1, len(close_series)):
                prev_close = close_series[idx - 1]
                current_close = close_series[idx]
                if prev_close <= 0:
                    continue
                daily_returns.append((current_close / prev_close) - 1.0)
            tail_returns = daily_returns[-30:] if len(daily_returns) > 30 else daily_returns
            if tail_returns:
                mean_ret = sum(tail_returns) / len(tail_returns)
                variance = sum((sample - mean_ret) ** 2 for sample in tail_returns) / len(tail_returns)
                volatility_value = math.sqrt(variance) * math.sqrt(252.0)

        price_metric_cache[industry_code] = {
            "position": _as_float_or_none(position_value),
            "volatility": _as_float_or_none(volatility_value),
        }

    def _to_score(value, pool, invert=False, default=50.0):
        number = _as_float_or_none(value)
        if number is None:
            return float(default)
        cleaned = [float(item) for item in pool if isinstance(item, (int, float)) and math.isfinite(item)]
        if not cleaned:
            return float(default)
        minimum = min(cleaned)
        maximum = max(cleaned)
        if maximum - minimum <= 1e-12:
            return 50.0
        ratio = (float(number) - minimum) / (maximum - minimum)
        score = (1.0 - ratio) * 100.0 if invert else ratio * 100.0
        return _clamp_score_0_100(score, default=default)

    def _sum_last(values, window_size):
        tail = values[-window_size:] if len(values) > window_size else values
        return float(sum(tail))

    def _count_positive_last(values, window_size):
        tail = values[-window_size:] if len(values) > window_size else values
        return int(sum(1 for value in tail if float(value) > 0.0))

    def _linear_slope(series):
        if not series or len(series) < 2:
            return 0.0
        length = len(series)
        x_mean = (length - 1) / 2.0
        y_mean = sum(series) / length
        numerator = 0.0
        denominator = 0.0
        for idx, value in enumerate(series):
            dx = float(idx) - x_mean
            numerator += dx * (float(value) - y_mean)
            denominator += dx * dx
        if denominator <= 1e-12:
            return 0.0
        return float(numerator / denominator)

    candidates_by_type = defaultdict(list)
    for industry_code, rows in by_code_rows.items():
        current_type = _normalize_ths_index_type(by_code_type.get(industry_code))
        if requested_type != "ALL" and current_type != requested_type:
            continue
        if not current_type:
            continue
        member_count = by_code_member_count.get(industry_code)
        if member_count is None:
            member_count = _get_ths_member_count(pro, industry_code)
        try:
            member_count = int(member_count or 0)
        except (TypeError, ValueError):
            member_count = 0
        if member_count <= 0:
            continue
        ordered_rows = sorted(rows, key=lambda item: str(item.get("trade_date") or ""))
        net_amount_series = [float(item.get("net_amount") or 0.0) for item in ordered_rows]
        tail_rows = ordered_rows[-lookback:] if len(ordered_rows) > lookback else ordered_rows
        moneyflow_30d = sum(float(item.get("net_amount") or 0.0) for item in tail_rows)

        mf_10_sum = _sum_last(net_amount_series, 10)
        mf_30_sum = _sum_last(net_amount_series, 30)
        mf_60_tail = net_amount_series[-60:] if len(net_amount_series) > 60 else net_amount_series
        mf_60_sum = float(sum(mf_60_tail))
        mf_10_pos_days = _count_positive_last(net_amount_series, 10)
        mf_30_pos_days = _count_positive_last(net_amount_series, 30)

        cumulative_60 = []
        running_sum = 0.0
        for value in mf_60_tail:
            running_sum += float(value)
            cumulative_60.append(running_sum)
        mf_60_slope = _linear_slope(cumulative_60)

        start_signal = (mf_10_sum > 0.0) and (mf_10_pos_days >= 6)
        sustain_signal = (mf_30_sum > 0.0) and (mf_30_pos_days >= 16) and (mf_30_sum >= mf_10_sum * 1.2)
        trend_signal = (mf_60_sum > 0.0) and (mf_60_slope > 0.0)

        accumulation_level = "NONE"
        if start_signal and not sustain_signal:
            accumulation_level = "EARLY"
        elif sustain_signal and not trend_signal:
            accumulation_level = "SUSTAINING"
        elif sustain_signal and trend_signal:
            accumulation_level = "STRONG"

        if current_type != "N":
            accumulation_level = "NONE"

        accumulation_bonus = float(THS_MONEYFLOW_ACCUMULATION_BONUS_MAP.get(accumulation_level, 0.0))

        metric_item = price_metric_cache.get(industry_code) or {}
        candidates_by_type[current_type].append(
            {
                "industry_code": industry_code,
                "industry_name": str(by_code_name.get(industry_code) or industry_code).strip(),
                "index_type": current_type,
                "index_type_label": _get_ths_index_type_label(current_type),
                "member_count": member_count,
                "moneyflow_30d": float(moneyflow_30d),
                "position": _as_float_or_none(metric_item.get("position")),
                "volatility": _as_float_or_none(metric_item.get("volatility")),
                "accumulation_level": accumulation_level,
                "accumulation_bonus": accumulation_bonus,
                "accumulation_signals": {
                    "start_signal": bool(start_signal),
                    "sustain_signal": bool(sustain_signal),
                    "trend_signal": bool(trend_signal),
                },
                "accumulation_metrics": {
                    "mf_10_sum": round(float(mf_10_sum), 4),
                    "mf_30_sum": round(float(mf_30_sum), 4),
                    "mf_60_sum": round(float(mf_60_sum), 4),
                    "mf_10_pos_days": int(mf_10_pos_days),
                    "mf_30_pos_days": int(mf_30_pos_days),
                    "mf_60_slope": round(float(mf_60_slope), 6),
                },
            }
        )

    snapshots = {}
    for index_type, rows in candidates_by_type.items():
        if not rows:
            continue
        moneyflow_pool = [item.get("moneyflow_30d") for item in rows]
        position_pool = [item.get("position") for item in rows if item.get("position") is not None]
        volatility_pool = [item.get("volatility") for item in rows if item.get("volatility") is not None]

        scored_rows = []
        for item in rows:
            moneyflow_score = _to_score(item.get("moneyflow_30d"), moneyflow_pool, invert=False, default=50.0)
            position_score = _to_score(item.get("position"), position_pool, invert=False, default=50.0)
            volatility_score = _to_score(item.get("volatility"), volatility_pool, invert=True, default=50.0)
            score_total_v1 = (
                _clamp_score_0_100(moneyflow_score) * THS_MONEYFLOW_SCORE_WEIGHT_MONEYFLOW
                + _clamp_score_0_100(position_score) * THS_MONEYFLOW_SCORE_WEIGHT_POSITION
                + _clamp_score_0_100(volatility_score) * THS_MONEYFLOW_SCORE_WEIGHT_VOLATILITY
            )
            accumulation_bonus = float(item.get("accumulation_bonus") or 0.0)
            score_total_v2 = _clamp_score_0_100(float(score_total_v1) + accumulation_bonus, default=0.0)

            scored_rows.append(
                {
                    "industry_code": str(item.get("industry_code") or "").strip(),
                    "industry_name": str(item.get("industry_name") or "").strip(),
                    "index_type": index_type,
                    "index_type_label": _get_ths_index_type_label(index_type),
                    "member_count": int(item.get("member_count") or 0),
                    "score_total": round(float(score_total_v2), 4),
                    "score_total_v1": round(float(score_total_v1), 4),
                    "score_total_v2": round(float(score_total_v2), 4),
                    "score_breakdown": {
                        "moneyflow_30d": round(float(_clamp_score_0_100(moneyflow_score)), 4),
                        "position": round(float(_clamp_score_0_100(position_score)), 4),
                        "volatility": round(float(_clamp_score_0_100(volatility_score)), 4),
                    },
                    "metrics": {
                        "moneyflow_30d": round(float(item.get("moneyflow_30d") or 0.0), 4),
                        "position": round(float(item.get("position")), 6) if item.get("position") is not None else None,
                        "volatility": round(float(item.get("volatility")), 6) if item.get("volatility") is not None else None,
                    },
                    "accumulation_level": str(item.get("accumulation_level") or "NONE"),
                    "accumulation_bonus": round(float(accumulation_bonus), 4),
                    "accumulation_signals": item.get("accumulation_signals") if isinstance(item.get("accumulation_signals"), dict) else {},
                    "accumulation_metrics": item.get("accumulation_metrics") if isinstance(item.get("accumulation_metrics"), dict) else {},
                }
            )

        scored_rows = sorted(
            scored_rows,
            key=lambda row: (
                -float(row.get("score_total") or 0.0),
                str(row.get("industry_code") or ""),
            ),
        )
        for rank_idx, row in enumerate(scored_rows, start=1):
            row["rank"] = rank_idx

        snapshots[index_type] = {
            "ths_index_type": index_type,
            "ths_index_type_label": _get_ths_index_type_label(index_type),
            "total_candidates": len(scored_rows),
            "top_n": top_n_value,
            "data": scored_rows,
        }

    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "asof_date": asof_date,
        "scoring_version": "ths_moneyflow_v2",
        "accumulation_rule_version": THS_MONEYFLOW_ACCUMULATION_RULE_VERSION,
        "top_n_default": top_n_value,
        "lookback_days": lookback,
        "weights": {
            "moneyflow_30d": THS_MONEYFLOW_SCORE_WEIGHT_MONEYFLOW,
            "position": THS_MONEYFLOW_SCORE_WEIGHT_POSITION,
            "volatility": THS_MONEYFLOW_SCORE_WEIGHT_VOLATILITY,
        },
        "accumulation_bonus_map": THS_MONEYFLOW_ACCUMULATION_BONUS_MAP,
        "snapshots": snapshots,
    }
    output_path = _write_ths_moneyflow_score_latest_payload(payload)
    return payload, output_path


def _read_ths_index_snapshot():
    path = _resolve_ths_industry_snapshot_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []

    normalized = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        industry_key = str(item.get("industry_key") or "").strip().upper()
        display_name = str(item.get("display_name") or "").strip()
        index_type = _normalize_ths_index_type(item.get("index_type"))
        index_type_label = str(item.get("index_type_label") or _get_ths_index_type_label(index_type)).strip()
        member_count = item.get("member_count", 0)
        member_stocks_raw = item.get("member_stocks") if isinstance(item.get("member_stocks"), list) else []
        member_stocks = []
        for stock in member_stocks_raw:
            if not isinstance(stock, dict):
                continue
            ts_code = _normalize_ts_code(stock.get("ts_code"))
            name = str(stock.get("name") or "").strip()
            if not ts_code:
                continue
            member_stocks.append({"ts_code": ts_code, "name": name})

        if member_stocks and not member_count:
            member_count = len(member_stocks)
        try:
            member_count = int(member_count)
        except (TypeError, ValueError):
            member_count = 0
        if not industry_key or not display_name:
            continue
        normalized.append(
            {
                "industry_key": industry_key,
                "display_name": display_name,
                "index_type": index_type,
                "index_type_label": index_type_label,
                "member_count": max(0, member_count),
                "member_stocks": member_stocks,
            }
        )
    return normalized


def _write_ths_index_snapshot(rows):
    path = _resolve_ths_industry_snapshot_path()
    serializable_rows = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        industry_key = str(item.get("industry_key") or "").strip().upper()
        display_name = str(item.get("display_name") or "").strip()
        index_type = _normalize_ths_index_type(item.get("index_type"))
        index_type_label = str(item.get("index_type_label") or _get_ths_index_type_label(index_type)).strip()
        member_count = item.get("member_count", 0)
        member_stocks_raw = item.get("member_stocks") if isinstance(item.get("member_stocks"), list) else []
        member_stocks = []
        for stock in member_stocks_raw:
            if not isinstance(stock, dict):
                continue
            ts_code = _normalize_ts_code(stock.get("ts_code"))
            name = str(stock.get("name") or "").strip()
            if not ts_code:
                continue
            member_stocks.append({"ts_code": ts_code, "name": name})

        if member_stocks and not member_count:
            member_count = len(member_stocks)
        try:
            member_count = int(member_count)
        except (TypeError, ValueError):
            member_count = 0
        if not industry_key or not display_name:
            continue
        serializable_rows.append(
            {
                "industry_key": industry_key,
                "display_name": display_name,
                "index_type": index_type,
                "index_type_label": index_type_label,
                "member_count": max(0, member_count),
                "member_stocks": member_stocks,
            }
        )

    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(serializable_rows),
        "data": serializable_rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_ths_index_rows(pro=None, prefer_local=True):
    existing_snapshot_map = {
        str(item.get("industry_key") or "").strip().upper(): item
        for item in _read_ths_index_snapshot()
        if isinstance(item, dict)
    }

    if prefer_local:
        local_rows = _read_ths_index_snapshot()
        if local_rows:
            if pro is not None:
                needs_index_type_refresh = any(
                    not _normalize_ths_index_type(item.get("index_type"))
                    for item in local_rows
                    if isinstance(item, dict)
                )
                if needs_index_type_refresh:
                    live_rows = _fetch_ths_index_rows(pro)
                    if live_rows:
                        live_type_map = {
                            str(item.get("industry_key") or "").strip().upper(): {
                                "index_type": _normalize_ths_index_type(item.get("index_type")),
                                "index_type_label": str(item.get("index_type_label") or "").strip(),
                            }
                            for item in live_rows
                            if isinstance(item, dict)
                        }
                        merged_rows = []
                        changed = False
                        for item in local_rows:
                            if not isinstance(item, dict):
                                continue
                            industry_key = str(item.get("industry_key") or "").strip().upper()
                            live_meta = live_type_map.get(industry_key) or {}
                            index_type = _normalize_ths_index_type(item.get("index_type") or live_meta.get("index_type"))
                            index_type_label = str(
                                item.get("index_type_label")
                                or live_meta.get("index_type_label")
                                or _get_ths_index_type_label(index_type)
                            ).strip()
                            merged_item = dict(item)
                            merged_item["index_type"] = index_type
                            merged_item["index_type_label"] = index_type_label
                            if index_type != str(item.get("index_type") or "").strip().upper():
                                changed = True
                            if index_type_label != str(item.get("index_type_label") or "").strip():
                                changed = True
                            merged_rows.append(merged_item)
                        if merged_rows:
                            local_rows = merged_rows
                            if changed:
                                try:
                                    _write_ths_index_snapshot(local_rows)
                                except Exception:
                                    pass
            return local_rows

    live_rows = _fetch_ths_index_rows(pro) if pro is not None else []
    if live_rows and pro is not None:
        enriched_rows = []
        for item in live_rows:
            industry_key = str(item.get("industry_key") or "").strip().upper()
            display_name = str(item.get("display_name") or "").strip()
            index_type = _normalize_ths_index_type(item.get("index_type"))
            if not industry_key or not display_name:
                continue
            previous_entry = existing_snapshot_map.get(industry_key) or {}
            fetched_member_stocks = _fetch_ths_member_rows(pro, industry_key)
            if fetched_member_stocks:
                member_stocks = fetched_member_stocks
                member_count = len(fetched_member_stocks)
            else:
                member_stocks = previous_entry.get("member_stocks") if isinstance(previous_entry.get("member_stocks"), list) else []
                try:
                    member_count = int(previous_entry.get("member_count", 0))
                except (TypeError, ValueError):
                    member_count = len(member_stocks)
            enriched_rows.append(
                {
                    "industry_key": industry_key,
                    "display_name": display_name,
                    "index_type": index_type,
                    "index_type_label": _get_ths_index_type_label(index_type),
                    "member_count": max(0, member_count),
                    "member_stocks": member_stocks,
                }
            )
        live_rows = enriched_rows
    if live_rows:
        try:
            _write_ths_index_snapshot(live_rows)
        except Exception:
            pass
        return live_rows

    if not prefer_local:
        return _read_ths_index_snapshot()
    return []


def _upsert_ths_snapshot_entry(industry_key, display_name=None, member_stocks=None, member_count=None, index_type=None):
    token = str(industry_key or "").strip().upper()
    if not token:
        return

    rows = _read_ths_index_snapshot()
    updated = False
    normalized_member_stocks = []
    if isinstance(member_stocks, list):
        for item in member_stocks:
            if not isinstance(item, dict):
                continue
            ts_code = _normalize_ts_code(item.get("ts_code"))
            name = str(item.get("name") or "").strip()
            if not ts_code:
                continue
            normalized_member_stocks.append({"ts_code": ts_code, "name": name})

    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("industry_key") or "").strip().upper() != token:
            continue
        if display_name:
            item["display_name"] = str(display_name).strip()
        normalized_index_type = _normalize_ths_index_type(index_type)
        if normalized_index_type:
            item["index_type"] = normalized_index_type
            item["index_type_label"] = _get_ths_index_type_label(normalized_index_type)
        if member_stocks is not None:
            item["member_stocks"] = normalized_member_stocks
        if member_count is not None:
            try:
                item["member_count"] = max(0, int(member_count))
            except (TypeError, ValueError):
                item["member_count"] = len(normalized_member_stocks)
        elif member_stocks is not None:
            item["member_count"] = len(normalized_member_stocks)
        updated = True
        break

    if not updated:
        normalized_index_type = _normalize_ths_index_type(index_type)
        rows.append(
            {
                "industry_key": token,
                "display_name": str(display_name or token).strip(),
                "index_type": normalized_index_type,
                "index_type_label": _get_ths_index_type_label(normalized_index_type),
                "member_count": int(member_count) if member_count is not None else len(normalized_member_stocks),
                "member_stocks": normalized_member_stocks,
            }
        )

    _write_ths_index_snapshot(rows)


def _read_sw_rotation_snapshot(industry_type="sw", ths_index_type="ALL"):
    path = _resolve_rotation_snapshot_path(industry_type, ths_index_type)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        logger.warning("read sw rotation snapshot failed: %s", exc)
    return None


def _write_sw_rotation_snapshot(payload, industry_type="sw", ths_index_type="ALL"):
    path = _resolve_rotation_snapshot_path(industry_type, ths_index_type)
    normalized = payload if isinstance(payload, dict) else {}
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _read_sw_rotation_runs_payload(industry_type="sw", ths_index_type="ALL"):
    path = _resolve_rotation_runs_path(industry_type, ths_index_type)
    if not path.exists():
        return {"runs": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("read sw rotation runs failed: %s", exc)
        return {"runs": []}
    if not isinstance(payload, dict):
        return {"runs": []}
    runs = payload.get("runs")
    if not isinstance(runs, list):
        payload["runs"] = []
    return payload


def _write_sw_rotation_runs_payload(payload, industry_type="sw", ths_index_type="ALL"):
    path = _resolve_rotation_runs_path(industry_type, ths_index_type)
    normalized = payload if isinstance(payload, dict) else {"runs": []}
    if not isinstance(normalized.get("runs"), list):
        normalized["runs"] = []
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _new_sw_rotation_run_id():
    seed = f"{datetime.datetime.now(datetime.timezone.utc).isoformat()}|{time.time_ns()}"
    token = hashlib.md5(seed.encode("utf-8")).hexdigest()[:10]
    return f"rot_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}_{token}"


def _build_sw_rotation_run(snapshot, market, top_n, limit_count, industry_type="sw", ths_index_type="ALL"):
    normalized = snapshot if isinstance(snapshot, dict) else {}
    top_candidates = normalized.get("top_candidates") if isinstance(normalized.get("top_candidates"), list) else []
    all_candidates = normalized.get("all_candidates") if isinstance(normalized.get("all_candidates"), list) else []

    def _compact_row(row, rank_idx=None):
        item = row if isinstance(row, dict) else {}
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        return {
            "rank": int(rank_idx) if isinstance(rank_idx, int) else None,
            "industry_code": str(item.get("industry_code") or "").strip(),
            "industry_name": str(item.get("industry_name") or "").strip(),
            "regime": str(item.get("regime") or "").strip(),
            "rotation_score": _as_float_or_none(item.get("rotation_score")),
            "latest_trade_date": str(item.get("latest_trade_date") or "").strip(),
            "entry_close": _as_float_or_none(item.get("entry_close") or metrics.get("latest_close")),
            "score_breakdown": {
                "valuation": _as_float_or_none((item.get("score_breakdown") or {}).get("valuation")),
                "momentum": _as_float_or_none((item.get("score_breakdown") or {}).get("momentum")),
                "risk": _as_float_or_none((item.get("score_breakdown") or {}).get("risk")),
                "style": _as_float_or_none((item.get("score_breakdown") or {}).get("style")),
            },
        }

    return {
        "run_id": _new_sw_rotation_run_id(),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "industry_type": _normalize_industry_universe_type(industry_type),
        "ths_index_type": _normalize_rotation_ths_index_type(ths_index_type),
        "market": str(market or "CN").strip().upper() or "CN",
        "top_n": int(top_n or 10),
        "limit_count": int(limit_count or 0),
        "asof_date": str(normalized.get("asof_date") or "").strip(),
        "generated_at": str(normalized.get("generated_at") or "").strip(),
        "scoring_version": str(normalized.get("scoring_version") or "sw_rotation_v1").strip(),
        "total_candidates": int(normalized.get("total_candidates") or 0),
        "top_candidates": [_compact_row(row, idx + 1) for idx, row in enumerate(top_candidates)],
        "all_candidates": [_compact_row(row) for row in all_candidates],
    }


def _append_sw_rotation_run(snapshot, market, top_n, limit_count, industry_type="sw", ths_index_type="ALL"):
    payload = _read_sw_rotation_runs_payload(industry_type, ths_index_type)
    runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
    run_record = _build_sw_rotation_run(
        snapshot=snapshot,
        market=market,
        top_n=top_n,
        limit_count=limit_count,
        industry_type=industry_type,
        ths_index_type=ths_index_type,
    )
    runs.append(run_record)
    payload["runs"] = runs
    _write_sw_rotation_runs_payload(payload, industry_type, ths_index_type)
    return run_record


def _compute_generic_rotation_candidates(industry_type="ths", market="CN", top_n=10, limit_count=None, ths_index_type="ALL"):
    normalized_type = _normalize_industry_universe_type(industry_type)
    entries = []

    if normalized_type == "ths":
        normalized_ths_index_type = _normalize_rotation_ths_index_type(ths_index_type)
        try:
            pro = get_tushare_pro()
        except Exception:
            pro = None
        for row in _load_ths_index_rows(pro=pro, prefer_local=True):
            if not isinstance(row, dict):
                continue
            key = str(row.get("industry_key") or "").strip().upper()
            name = str(row.get("display_name") or "").strip()
            row_index_type = _normalize_ths_index_type(row.get("index_type"))
            try:
                count = int(row.get("member_count") or 0)
            except (TypeError, ValueError):
                count = 0
            if normalized_ths_index_type != "ALL" and row_index_type != normalized_ths_index_type:
                continue
            if key and name:
                entries.append({"industry_code": key, "industry_name": name, "member_count": max(0, count)})

        if isinstance(limit_count, int) and limit_count > 0:
            entries = entries[:limit_count]

        today = datetime.date.today()
        start_date = (today - datetime.timedelta(days=730)).strftime("%Y%m%d")
        end_date = today.strftime("%Y%m%d")

        def _compute_max_drawdown(close_series):
            peak = None
            max_drawdown = 0.0
            for value in close_series:
                close_value = _as_float_or_none(value)
                if close_value is None or close_value <= 0:
                    continue
                if peak is None or close_value > peak:
                    peak = close_value
                if peak is None or peak <= 0:
                    continue
                drawdown = (peak - close_value) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            return float(max_drawdown)

        def _blend_optional(weighted_values):
            valid = [(float(weight), float(value)) for weight, value in weighted_values if value is not None]
            if not valid:
                return None
            total_weight = sum(weight for weight, _ in valid)
            if total_weight <= 0:
                return None
            return sum(weight * value for weight, value in valid) / total_weight

        def _scale_to_score(value, value_pool, invert=False, default=50.0):
            number = _as_float_or_none(value)
            if number is None:
                return float(default)
            cleaned_pool = [
                float(item)
                for item in value_pool
                if isinstance(item, (int, float)) and math.isfinite(item)
            ]
            if not cleaned_pool:
                return float(default)
            min_value = min(cleaned_pool)
            max_value = max(cleaned_pool)
            if max_value - min_value <= 1e-12:
                return 50.0
            ratio = (number - min_value) / (max_value - min_value)
            score = (1.0 - ratio) * 100.0 if invert else ratio * 100.0
            return _clamp_score_0_100(score, default=default)

        raw_rows = []
        for item in entries:
            industry_code = str(item.get("industry_code") or "").strip().upper()
            industry_name = str(item.get("industry_name") or "").strip()
            member_count = int(item.get("member_count") or 0)

            if member_count <= 0:
                continue

            latest_close = None
            latest_trade_date = ""
            ret_1m = None
            ret_3m = None
            volatility = None
            max_drawdown = None
            close_series = []

            if pro is not None:
                frame = _fetch_ths_daily_frame(pro, industry_code, start_date, end_date)
                if frame is not None and not getattr(frame, "empty", True) and "trade_date" in frame.columns:
                    work = frame.fillna("").copy()
                    work["trade_date"] = work["trade_date"].astype(str)
                    work = work.sort_values("trade_date")
                    for _, row in work.iterrows():
                        close_value = _as_float_or_none(row.get("close"))
                        if close_value is None or close_value <= 0:
                            continue
                        close_series.append(float(close_value))

                    if close_series:
                        latest_close = close_series[-1]
                        latest_trade_date = _to_trade_date_text(work.iloc[-1].get("trade_date"))

                    if len(close_series) >= 21:
                        ret_1m = _safe_pct_change(close_series[-1], close_series[-21])
                    if len(close_series) >= 63:
                        ret_3m = _safe_pct_change(close_series[-1], close_series[-63])

                    if len(close_series) >= 2:
                        daily_returns = []
                        for idx in range(1, len(close_series)):
                            prev_close = close_series[idx - 1]
                            current_close = close_series[idx]
                            if prev_close <= 0:
                                continue
                            daily_returns.append((current_close / prev_close) - 1.0)
                        tail_returns = daily_returns[-60:] if len(daily_returns) > 60 else daily_returns
                        if tail_returns:
                            mean_ret = sum(tail_returns) / len(tail_returns)
                            variance = sum((sample - mean_ret) ** 2 for sample in tail_returns) / len(tail_returns)
                            volatility = math.sqrt(variance) * math.sqrt(252.0)

                    if len(close_series) >= 2:
                        max_drawdown = _compute_max_drawdown(close_series[-252:] if len(close_series) > 252 else close_series)

            if not close_series:
                continue

            momentum_raw = _blend_optional([(0.6, ret_1m), (0.4, ret_3m)])
            risk_raw = _blend_optional([(0.7, volatility), (0.3, max_drawdown)])

            raw_rows.append(
                {
                    "industry_code": industry_code,
                    "industry_name": industry_name,
                    "member_count": max(0, member_count),
                    "latest_close": latest_close,
                    "latest_trade_date": latest_trade_date or today.strftime("%Y-%m-%d"),
                    "ret_1m": ret_1m,
                    "ret_3m": ret_3m,
                    "volatility": volatility,
                    "max_drawdown": max_drawdown,
                    "momentum_raw": momentum_raw,
                    "risk_raw": risk_raw,
                }
            )

        momentum_pool = [row.get("momentum_raw") for row in raw_rows if row.get("momentum_raw") is not None]
        risk_pool = [row.get("risk_raw") for row in raw_rows if row.get("risk_raw") is not None]
        breadth_pool = [row.get("member_count") for row in raw_rows]

        candidates = []
        for row in raw_rows:
            momentum_score = _scale_to_score(row.get("momentum_raw"), momentum_pool, invert=False, default=50.0)
            risk_score = _scale_to_score(row.get("risk_raw"), risk_pool, invert=True, default=50.0)
            breadth_score = _scale_to_score(row.get("member_count"), breadth_pool, invert=False, default=50.0)
            rotation_score = (
                _clamp_score_0_100(momentum_score) * 0.55
                + _clamp_score_0_100(risk_score) * 0.35
                + _clamp_score_0_100(breadth_score) * 0.10
            )

            candidates.append(
                {
                    "industry_code": str(row.get("industry_code") or "").strip(),
                    "industry_name": str(row.get("industry_name") or "").strip(),
                    "regime": "none",
                    "rotation_score": round(float(rotation_score), 4),
                    "entry_close": round(float(row.get("latest_close")), 4) if row.get("latest_close") is not None else None,
                    "score_breakdown": {
                        "valuation": None,
                        "momentum": round(float(_clamp_score_0_100(momentum_score)), 4),
                        "risk": round(float(_clamp_score_0_100(risk_score)), 4),
                        "style": round(float(_clamp_score_0_100(breadth_score)), 4),
                    },
                    "metrics": {
                        "latest_close": round(float(row.get("latest_close")), 4) if row.get("latest_close") is not None else None,
                        "ret_1m": round(float(row.get("ret_1m")), 6) if row.get("ret_1m") is not None else None,
                        "ret_3m": round(float(row.get("ret_3m")), 6) if row.get("ret_3m") is not None else None,
                        "volatility": round(float(row.get("volatility")), 6) if row.get("volatility") is not None else None,
                        "max_drawdown": round(float(row.get("max_drawdown")), 6) if row.get("max_drawdown") is not None else None,
                        "member_count": int(row.get("member_count") or 0),
                    },
                    "latest_trade_date": str(row.get("latest_trade_date") or today.strftime("%Y-%m-%d")),
                }
            )

        candidates = sorted(
            candidates,
            key=lambda item: (
                -float(item.get("rotation_score") or 0.0),
                -int((item.get("metrics") or {}).get("member_count") or 0),
                str(item.get("industry_code") or ""),
            ),
        )
        top_n = max(1, min(100, int(top_n or 10)))
        asof_candidates = [str(item.get("latest_trade_date") or "").strip() for item in candidates if str(item.get("latest_trade_date") or "").strip()]
        asof_date = max(asof_candidates) if asof_candidates else today.strftime("%Y-%m-%d")
        return {
            "industry_type": "ths",
            "asof_date": asof_date,
            "scoring_version": "ths_rotation_v2_close_only",
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_candidates": len(candidates),
            "top_n": top_n,
            "top_candidates": candidates[:top_n],
            "all_candidates": candidates,
        }

    elif normalized_type == "valuation_variant":
        persisted_qs = IndustryVariantCache.objects.filter(market=market).order_by("-member_count", "variant_key")
        if persisted_qs.exists():
            for row in persisted_qs.values("variant_key", "display_name", "member_count"):
                key = str(row.get("variant_key") or "").strip()
                name = str(row.get("display_name") or key).strip()
                count = int(row.get("member_count") or 0)
                if key and name:
                    entries.append({"industry_code": key, "industry_name": name, "member_count": max(0, count)})
        else:
            variant_qs = (
                StockValuationSnapshotLatest.objects.filter(market=market)
                .exclude(valuation_variant__isnull=True)
                .exclude(valuation_variant="")
                .values("valuation_variant", "industry_name")
                .annotate(member_count=Count("ts_code", distinct=True))
                .order_by("-member_count", "valuation_variant")
            )
            for row in variant_qs:
                key = str(row.get("valuation_variant") or "").strip()
                name = str(row.get("industry_name") or key).strip()
                count = int(row.get("member_count") or 0)
                if key and name:
                    entries.append({"industry_code": key, "industry_name": name, "member_count": max(0, count)})

    else:
        corp_qs = (
            Corporation.objects.filter(list_status="L")
            .exclude(industry__isnull=True)
            .exclude(industry__name__isnull=True)
            .exclude(industry__name="")
            .values("industry__name")
            .annotate(member_count=Count("id"))
            .order_by("-member_count", "industry__name")
        )
        for row in corp_qs:
            name = str(row.get("industry__name") or "").strip()
            count = int(row.get("member_count") or 0)
            if name:
                entries.append({"industry_code": name, "industry_name": name, "member_count": max(0, count)})

    if isinstance(limit_count, int) and limit_count > 0:
        entries = entries[:limit_count]

    total = len(entries)
    candidates = []
    for idx, item in enumerate(entries):
        member_count = int(item.get("member_count") or 0)
        rank_score = 100.0 if total <= 1 else max(0.0, 100.0 - (idx * 100.0 / (total - 1)))
        size_score = _clamp_score_0_100(member_count / 50.0)
        rotation_score = round(float(rank_score * 0.7 + size_score * 0.3), 4)
        candidates.append(
            {
                "industry_code": str(item.get("industry_code") or "").strip(),
                "industry_name": str(item.get("industry_name") or "").strip(),
                "regime": "none",
                "rotation_score": rotation_score,
                "entry_close": None,
                "score_breakdown": {
                    "valuation": round(float(size_score), 4),
                    "momentum": round(float(rank_score), 4),
                    "risk": 50.0,
                    "style": 50.0,
                },
                "metrics": {
                    "member_count": member_count,
                },
                "latest_trade_date": datetime.date.today().strftime("%Y-%m-%d"),
            }
        )

    top_n = max(1, min(100, int(top_n or 10)))
    return {
        "industry_type": normalized_type,
        "asof_date": datetime.date.today().strftime("%Y-%m-%d"),
        "scoring_version": f"{normalized_type}_rotation_v1_heuristic",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_candidates": len(candidates),
        "top_n": top_n,
        "top_candidates": candidates[:top_n],
        "all_candidates": candidates,
    }


def _compute_industry_rotation_candidates(industry_type="sw", market="CN", top_n=10, limit_count=None, ths_index_type="ALL"):
    normalized_type = _normalize_industry_universe_type(industry_type)
    if normalized_type == "sw":
        payload = _compute_sw_rotation_candidates(market=market, top_n=top_n, limit_count=limit_count)
        payload["industry_type"] = "sw"
        return payload
    return _compute_generic_rotation_candidates(
        industry_type=normalized_type,
        market=market,
        top_n=top_n,
        limit_count=limit_count,
        ths_index_type=ths_index_type,
    )


def _parse_rotation_windows(raw_windows):
    if raw_windows is None:
        return list(SW_ROTATION_RETURN_WINDOWS)
    tokens = [item.strip() for item in str(raw_windows or "").split(",")]
    values = []
    for token in tokens:
        if not token:
            continue
        try:
            number = int(token)
        except (TypeError, ValueError):
            continue
        if number > 0:
            values.append(number)
    return sorted(set(values))[:8] if values else list(SW_ROTATION_RETURN_WINDOWS)


def _normalize_date_token(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text[0:10]


def _load_sw_close_rows(index_code, start_date, end_date):
    code = str(index_code or "").strip()
    if not code:
        return []
    pro = get_tushare_pro()
    try:
        df = pro.sw_daily(
            ts_code=code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,close",
        )
    except TypeError:
        df = pro.sw_daily(ts_code=code, start_date=start_date, end_date=end_date)
    if df is None or getattr(df, "empty", True):
        return []
    frame = df.fillna("").copy().sort_values("trade_date")
    rows = []
    for _, row in frame.iterrows():
        close_value = _as_float_or_none(row.get("close"))
        if close_value is None or close_value <= 0:
            continue
        date_text = _normalize_date_token(row.get("trade_date"))
        if not date_text:
            continue
        rows.append({"trade_date": date_text, "close": float(close_value)})
    return rows


def _evaluate_rotation_run_payload(run_payload, windows):
    run = run_payload if isinstance(run_payload, dict) else {}
    asof_date = _normalize_date_token(run.get("asof_date"))
    if not asof_date:
        return {
            "windows": windows,
            "topn_summary": {},
            "benchmark_summary": {},
            "alpha_summary": {},
            "hit_ratio_summary": {},
            "details": [],
            "computed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "error": "missing_asof_date",
        }

    start_date = asof_date.replace("-", "")
    end_date = datetime.date.today().strftime("%Y%m%d")

    def _evaluate_rows(rows):
        evaluated_rows = []
        for row in rows:
            item = row if isinstance(row, dict) else {}
            code = str(item.get("industry_code") or "").strip()
            if not code:
                continue
            try:
                series = _load_sw_close_rows(code, start_date=start_date, end_date=end_date)
            except Exception as exc:
                logger.debug("rotation evaluation sw_daily failed %s: %s", code, exc)
                series = []

            date_list = [str(point.get("trade_date") or "") for point in series]
            close_list = [_as_float_or_none(point.get("close")) for point in series]
            returns = {str(window): None for window in windows}
            base_idx = None
            for idx, date_text in enumerate(date_list):
                if date_text >= asof_date:
                    base_idx = idx
                    break
            if base_idx is not None:
                base_close = _as_float_or_none(close_list[base_idx])
                for window in windows:
                    target_idx = base_idx + int(window)
                    if base_close is None or base_close <= 0 or target_idx >= len(close_list):
                        continue
                    target_close = _as_float_or_none(close_list[target_idx])
                    if target_close is None or target_close <= 0:
                        continue
                    returns[str(window)] = round(float((target_close / base_close) - 1.0), 6)

            evaluated_rows.append(
                {
                    "industry_code": code,
                    "industry_name": str(item.get("industry_name") or "").strip(),
                    "returns": returns,
                }
            )
        return evaluated_rows

    top_rows = _evaluate_rows(run.get("top_candidates") if isinstance(run.get("top_candidates"), list) else [])
    benchmark_rows = _evaluate_rows(run.get("all_candidates") if isinstance(run.get("all_candidates"), list) else [])

    def _avg_for_window(rows, window):
        key = str(window)
        values = [_as_float_or_none((row.get("returns") or {}).get(key)) for row in rows]
        cleaned = [float(v) for v in values if v is not None]
        return round(float(sum(cleaned) / len(cleaned)), 6) if cleaned else None

    topn_summary = {}
    benchmark_summary = {}
    alpha_summary = {}
    hit_ratio_summary = {}
    for window in windows:
        top_value = _avg_for_window(top_rows, window)
        benchmark_value = _avg_for_window(benchmark_rows, window)
        topn_summary[str(window)] = top_value
        benchmark_summary[str(window)] = benchmark_value
        alpha_summary[str(window)] = round(float(top_value - benchmark_value), 6) if top_value is not None and benchmark_value is not None else None
        hit_values = [_as_float_or_none((row.get("returns") or {}).get(str(window))) for row in top_rows]
        hit_cleaned = [float(v) for v in hit_values if v is not None]
        hit_ratio_summary[str(window)] = round(float(sum(1 for v in hit_cleaned if v > 0) / len(hit_cleaned)), 6) if hit_cleaned else None

    return {
        "windows": windows,
        "topn_summary": topn_summary,
        "benchmark_summary": benchmark_summary,
        "alpha_summary": alpha_summary,
        "hit_ratio_summary": hit_ratio_summary,
        "details": top_rows,
        "computed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _safe_pct_change(current_value, past_value):
    current = _as_float_or_none(current_value)
    past = _as_float_or_none(past_value)
    if current is None or past is None or past <= 0:
        return None
    return (current / past) - 1.0


def _clamp_score_0_100(value, default=50.0):
    number = _as_float_or_none(value)
    if number is None:
        return float(default)
    return float(max(0.0, min(100.0, number)))


def _compute_sw_rotation_candidates(market="CN", top_n=10, limit_count=None):
    cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
    l3_items = (cfg.sw_mapping.get("levels", {}) or {}).get("L3", {})
    if not isinstance(l3_items, dict):
        l3_items = {}

    industry_entries = []
    for raw_code, entry in l3_items.items():
        if not isinstance(entry, dict):
            continue
        index_code = str(entry.get("index_code") or raw_code or "").strip()
        industry_name = str(entry.get("industry_name") or "").strip()
        if not index_code or not industry_name:
            continue
        industry_entries.append(
            {
                "index_code": index_code,
                "industry_name": industry_name,
            }
        )

    corp_count_map = {
        str(item.get("sw_l3_code") or "").strip(): int(item.get("count") or 0)
        for item in (
            Corporation.objects.exclude(sw_l3_code__isnull=True)
            .exclude(sw_l3_code="")
            .values("sw_l3_code")
            .annotate(count=Count("id"))
        )
    }

    if isinstance(limit_count, int) and limit_count > 0:
        industry_entries = sorted(
            industry_entries,
            key=lambda item: corp_count_map.get(str(item.get("index_code") or "").strip(), 0),
            reverse=True,
        )[:limit_count]

    pro = get_tushare_pro()
    candidates = []
    asof_date = datetime.date.today().strftime("%Y-%m-%d")

    for item in industry_entries:
        index_code = str(item.get("index_code") or "").strip()
        industry_name = str(item.get("industry_name") or "").strip()
        if not index_code:
            continue
        try:
            df = pro.sw_daily(
                ts_code=index_code,
                start_date=(datetime.date.today() - datetime.timedelta(days=730)).strftime("%Y%m%d"),
                end_date=datetime.date.today().strftime("%Y%m%d"),
                fields="ts_code,trade_date,close,pe,pb",
            )
        except TypeError:
            df = pro.sw_daily(
                ts_code=index_code,
                start_date=(datetime.date.today() - datetime.timedelta(days=730)).strftime("%Y%m%d"),
                end_date=datetime.date.today().strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.debug("sw rotation sw_daily failed for %s: %s", index_code, exc)
            continue

        if df is None or getattr(df, "empty", True):
            continue

        frame = df.fillna("").copy()
        frame["trade_date"] = frame["trade_date"].astype(str)
        frame = frame.sort_values("trade_date")

        closes = []
        pe_values = []
        pb_values = []
        for _, row in frame.iterrows():
            close_value = _as_float_or_none(row.get("close"))
            pe_value = _as_float_or_none(row.get("pe"))
            pb_value = _as_float_or_none(row.get("pb"))
            closes.append(close_value)
            if pe_value is not None and pe_value > 0:
                pe_values.append(pe_value)
            if pb_value is not None and pb_value > 0:
                pb_values.append(pb_value)

        valid_closes = [v for v in closes if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]
        if len(valid_closes) < 65:
            continue

        latest_close = valid_closes[-1]
        close_1m = valid_closes[-21] if len(valid_closes) >= 21 else None
        close_3m = valid_closes[-63] if len(valid_closes) >= 63 else None
        ret_1m = _safe_pct_change(latest_close, close_1m)
        ret_3m = _safe_pct_change(latest_close, close_3m)

        close_return_samples = []
        for idx in range(1, len(valid_closes)):
            prev_close = valid_closes[idx - 1]
            current_close = valid_closes[idx]
            if prev_close <= 0:
                continue
            close_return_samples.append((current_close / prev_close) - 1.0)
        tail_samples = close_return_samples[-60:] if len(close_return_samples) > 60 else close_return_samples
        volatility = None
        if tail_samples:
            mean_ret = sum(tail_samples) / len(tail_samples)
            variance = sum((sample - mean_ret) ** 2 for sample in tail_samples) / len(tail_samples)
            volatility = math.sqrt(variance) * math.sqrt(252.0)

        latest_pe = pe_values[-1] if pe_values else None
        latest_pb = pb_values[-1] if pb_values else None
        pe_percentile = None
        pb_percentile = None
        if latest_pe is not None and pe_values:
            less_equal_count = sum(1 for value in pe_values if value <= latest_pe)
            pe_percentile = less_equal_count / len(pe_values)
        if latest_pb is not None and pb_values:
            less_equal_count = sum(1 for value in pb_values if value <= latest_pb)
            pb_percentile = less_equal_count / len(pb_values)

        valuation_percentiles = [p for p in [pe_percentile, pb_percentile] if p is not None]
        valuation_score = 50.0
        if valuation_percentiles:
            valuation_score = (1.0 - (sum(valuation_percentiles) / len(valuation_percentiles))) * 100.0

        momentum_raw = 0.0
        if ret_1m is not None:
            momentum_raw += ret_1m * 0.6
        if ret_3m is not None:
            momentum_raw += ret_3m * 0.4
        momentum_score = _clamp_score_0_100(50.0 + momentum_raw * 200.0)

        risk_score = _clamp_score_0_100(100.0 - ((volatility or 0.0) * 200.0))
        regime_value, _regime_reason = _resolve_regime_by_industry_code(index_code, industry_name)
        style_score_map = {
            "high_growth": 70.0,
            "balanced": 62.0,
            "cyclical": 58.0,
            "defensive": 66.0,
            "none": 50.0,
        }
        style_score = _clamp_score_0_100(style_score_map.get(regime_value, 55.0), default=55.0)

        rotation_score = (
            _clamp_score_0_100(valuation_score) * 0.35
            + _clamp_score_0_100(momentum_score) * 0.35
            + _clamp_score_0_100(risk_score) * 0.20
            + _clamp_score_0_100(style_score) * 0.10
        )

        latest_trade_date = str(frame.iloc[-1].get("trade_date") or "").strip()
        if len(latest_trade_date) == 8 and latest_trade_date.isdigit():
            latest_trade_date = f"{latest_trade_date[0:4]}-{latest_trade_date[4:6]}-{latest_trade_date[6:8]}"
            asof_date = latest_trade_date

        candidates.append(
            {
                "industry_code": index_code,
                "industry_name": industry_name,
                "regime": regime_value,
                "rotation_score": round(float(rotation_score), 4),
                "entry_close": round(float(latest_close), 4),
                "score_breakdown": {
                    "valuation": round(float(_clamp_score_0_100(valuation_score)), 4),
                    "momentum": round(float(_clamp_score_0_100(momentum_score)), 4),
                    "risk": round(float(_clamp_score_0_100(risk_score)), 4),
                    "style": round(float(_clamp_score_0_100(style_score)), 4),
                },
                "metrics": {
                    "latest_close": round(float(latest_close), 4),
                    "ret_1m": round(float(ret_1m), 6) if ret_1m is not None else None,
                    "ret_3m": round(float(ret_3m), 6) if ret_3m is not None else None,
                    "volatility": round(float(volatility), 6) if volatility is not None else None,
                    "latest_pe": round(float(latest_pe), 4) if latest_pe is not None else None,
                    "latest_pb": round(float(latest_pb), 4) if latest_pb is not None else None,
                    "pe_percentile": round(float(pe_percentile), 6) if pe_percentile is not None else None,
                    "pb_percentile": round(float(pb_percentile), 6) if pb_percentile is not None else None,
                    "member_count": int(corp_count_map.get(index_code, 0)),
                },
                "latest_trade_date": latest_trade_date,
            }
        )

    candidates = sorted(
        candidates,
        key=lambda row: (
            -float(row.get("rotation_score") or 0.0),
            -int((row.get("metrics") or {}).get("member_count") or 0),
            str(row.get("industry_code") or ""),
        ),
    )
    top_n = max(1, min(100, int(top_n or 10)))
    return {
        "asof_date": asof_date,
        "scoring_version": "sw_rotation_v1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_candidates": len(candidates),
        "top_n": top_n,
        "top_candidates": candidates[:top_n],
        "all_candidates": candidates,
    }


@api_view(["GET"])
def get_industry_universe_rotation_latest(request):
    market = str(request.query_params.get("market", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "sw") if hasattr(request, "query_params") else "sw"
    )
    ths_index_type = _normalize_rotation_ths_index_type(
        request.query_params.get("ths_index_type", "ALL") if hasattr(request, "query_params") else "ALL"
    )
    if industry_type != "ths":
        ths_index_type = "ALL"
    try:
        top_n = int(request.query_params.get("top_n", "10") if hasattr(request, "query_params") else 10)
    except (TypeError, ValueError):
        top_n = 10
    top_n = max(1, min(100, top_n))

    snapshot = _read_sw_rotation_snapshot(industry_type, ths_index_type)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("all_candidates"), list):
        snapshot = _compute_industry_rotation_candidates(
            industry_type=industry_type,
            market=market,
            top_n=top_n,
            limit_count=120,
            ths_index_type=ths_index_type,
        )
        _write_sw_rotation_snapshot(snapshot, industry_type, ths_index_type)

    all_candidates = snapshot.get("all_candidates") if isinstance(snapshot.get("all_candidates"), list) else []

    latest_run_id = ""
    latest_run_record = None
    fallback_candidates = []
    fallback_meta = {}
    runs_payload = _read_sw_rotation_runs_payload(industry_type, ths_index_type)
    runs = runs_payload.get("runs") if isinstance(runs_payload.get("runs"), list) else []
    if runs:
        ordered_runs = sorted(
            runs,
            key=lambda row: str((row or {}).get("created_at") or ""),
            reverse=True,
        )
        latest_run_record = ordered_runs[0] if isinstance(ordered_runs[0], dict) else None
        latest_run_id = str((latest_run_record or {}).get("run_id") or "").strip()

        for candidate_run in ordered_runs:
            run_item = candidate_run if isinstance(candidate_run, dict) else {}
            run_all = run_item.get("all_candidates") if isinstance(run_item.get("all_candidates"), list) else []
            run_top = run_item.get("top_candidates") if isinstance(run_item.get("top_candidates"), list) else []
            chosen = run_all if run_all else run_top
            if chosen:
                fallback_candidates = chosen
                fallback_meta = {
                    "asof_date": run_item.get("asof_date"),
                    "generated_at": run_item.get("generated_at") or run_item.get("created_at"),
                    "scoring_version": run_item.get("scoring_version") or "sw_rotation_v1",
                    "run_id": str(run_item.get("run_id") or "").strip(),
                }
                break

    # Snapshot may be stale or empty; fallback to latest run to keep UI usable.
    if (not all_candidates) and fallback_candidates:
        all_candidates = fallback_candidates
        if fallback_meta.get("run_id"):
            latest_run_id = str(fallback_meta.get("run_id") or "").strip()
            snapshot = {
                **snapshot,
                "asof_date": fallback_meta.get("asof_date") or snapshot.get("asof_date"),
                "generated_at": fallback_meta.get("generated_at") or snapshot.get("generated_at"),
                "scoring_version": fallback_meta.get("scoring_version") or snapshot.get("scoring_version") or "sw_rotation_v1",
                "total_candidates": len(fallback_candidates),
            }

    top_candidates = sorted(
        all_candidates,
        key=lambda row: -float((row or {}).get("rotation_score") or 0.0),
    )[:top_n]

    return Response(
        {
            "data": top_candidates,
            "meta": {
                "market": market,
                "industry_type": industry_type,
                "ths_index_type": ths_index_type,
                "top_n": top_n,
                "total": len(all_candidates),
                "asof_date": snapshot.get("asof_date"),
                "generated_at": snapshot.get("generated_at"),
                "scoring_version": snapshot.get("scoring_version") or "sw_rotation_v1",
                "run_id": latest_run_id,
                "source": "snapshot" if isinstance(snapshot.get("all_candidates"), list) and snapshot.get("all_candidates") else "snapshot_fallback_run",
            },
        }
    )


@api_view(["GET"])
def get_industry_universe_moneyflow_latest(request):
    market = str(request.query_params.get("market", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "ths") if hasattr(request, "query_params") else "ths"
    )
    requested_ths_index_type = _normalize_rotation_ths_index_type(
        request.query_params.get("ths_index_type", "N") if hasattr(request, "query_params") else "N"
    )
    # Current TuShare moneyflow_cnt_ths coverage is effectively N-only.
    # Keep API contract-compatible but force the scoring view to N.
    ths_index_type = "N"
    if industry_type != "ths":
        return Response({"error": "moneyflow ranking only supports THS industry_type"}, status=400)

    try:
        top_n = int(request.query_params.get("top_n", THS_MONEYFLOW_TOPN_DEFAULT) if hasattr(request, "query_params") else THS_MONEYFLOW_TOPN_DEFAULT)
    except (TypeError, ValueError):
        top_n = THS_MONEYFLOW_TOPN_DEFAULT
    top_n = max(1, min(100, top_n))

    snapshot = _read_ths_moneyflow_score_latest_payload()
    if not isinstance(snapshot, dict):
        snapshot, _path = _compute_and_write_ths_moneyflow_score_snapshot(
            top_n=top_n,
            lookback_days=THS_MONEYFLOW_LOOKBACK_DAYS,
            ths_index_type="N",
        )

    snapshots = snapshot.get("snapshots") if isinstance(snapshot.get("snapshots"), dict) else {}
    rows = []
    total_candidates = 0

    chosen = snapshots.get(ths_index_type)
    if isinstance(chosen, dict):
        data_rows = chosen.get("data") if isinstance(chosen.get("data"), list) else []
        filtered_rows = [
            row
            for row in data_rows
            if int((row or {}).get("member_count") or 0) > 0
        ]
        total_candidates = len(filtered_rows)
        rows = [dict(row if isinstance(row, dict) else {}) for row in filtered_rows]

    return Response(
        {
            "data": rows[:top_n],
            "meta": {
                "market": market,
                "industry_type": "ths",
                "ths_index_type": ths_index_type,
                "requested_ths_index_type": requested_ths_index_type,
                "top_n": top_n,
                "total_candidates": total_candidates,
                "asof_date": str(snapshot.get("asof_date") or ""),
                "generated_at": str(snapshot.get("generated_at") or ""),
                "scoring_version": str(snapshot.get("scoring_version") or "ths_moneyflow_v2"),
                "accumulation_rule_version": str(snapshot.get("accumulation_rule_version") or ""),
                "lookback_days": int(snapshot.get("lookback_days") or THS_MONEYFLOW_LOOKBACK_DAYS),
                "weights": snapshot.get("weights") if isinstance(snapshot.get("weights"), dict) else {},
                "source": "snapshot",
            },
        }
    )


@api_view(["POST"])
def recompute_industry_universe_rotation(request):
    payload = request.data if isinstance(request.data, dict) else {}
    market = str(payload.get("market") or "CN").strip().upper() or "CN"
    industry_type = _normalize_industry_universe_type(payload.get("industry_type") or "sw")
    ths_index_type = _normalize_rotation_ths_index_type(payload.get("ths_index_type") or "ALL")
    if industry_type != "ths":
        ths_index_type = "ALL"
    try:
        top_n = int(payload.get("top_n") or 10)
    except (TypeError, ValueError):
        top_n = 10
    try:
        limit_count = int(payload.get("limit_count") or 120)
    except (TypeError, ValueError):
        limit_count = 120

    top_n = max(1, min(100, top_n))
    limit_count = max(top_n, min(500, max(1, limit_count)))

    snapshot = _compute_industry_rotation_candidates(
        industry_type=industry_type,
        market=market,
        top_n=top_n,
        limit_count=limit_count,
        ths_index_type=ths_index_type,
    )
    output_path = _write_sw_rotation_snapshot(snapshot, industry_type, ths_index_type)
    run_record = _append_sw_rotation_run(
        snapshot=snapshot,
        market=market,
        top_n=top_n,
        limit_count=limit_count,
        industry_type=industry_type,
        ths_index_type=ths_index_type,
    )

    return Response(
        {
            "data": snapshot.get("top_candidates") or [],
            "meta": {
                "market": market,
                "industry_type": industry_type,
                "ths_index_type": ths_index_type,
                "top_n": top_n,
                "total": int(snapshot.get("total_candidates") or 0),
                "asof_date": snapshot.get("asof_date"),
                "generated_at": snapshot.get("generated_at"),
                "scoring_version": snapshot.get("scoring_version") or "sw_rotation_v1",
                "output_path": str(output_path),
                "runs_path": str(_resolve_rotation_runs_path(industry_type, ths_index_type)),
                "source": "recomputed",
                "run_created": True,
                "run_id": run_record.get("run_id"),
            },
        }
    )


@never_cache
@api_view(["GET"])
def get_industry_universe_rotation_runs(request):
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "sw") if hasattr(request, "query_params") else "sw"
    )
    ths_index_type = _normalize_rotation_ths_index_type(
        request.query_params.get("ths_index_type", "ALL") if hasattr(request, "query_params") else "ALL"
    )
    if industry_type != "ths":
        ths_index_type = "ALL"
    try:
        limit = int(request.query_params.get("limit", "20") if hasattr(request, "query_params") else 20)
    except (TypeError, ValueError):
        limit = 20
    try:
        from_index = int(request.query_params.get("from_index", "0") if hasattr(request, "query_params") else 0)
    except (TypeError, ValueError):
        from_index = 0
    limit = max(1, min(200, limit))
    from_index = max(0, from_index)

    payload = _read_sw_rotation_runs_payload(industry_type, ths_index_type)
    runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
    ordered = sorted(runs, key=lambda row: str((row or {}).get("created_at") or ""), reverse=True)
    sliced = ordered[from_index:from_index + limit]

    rows = []
    for item in sliced:
        row = item if isinstance(item, dict) else {}
        cached_eval = row.get("last_evaluation") if isinstance(row.get("last_evaluation"), dict) else {}
        top_candidates = row.get("top_candidates") if isinstance(row.get("top_candidates"), list) else []
        rows.append(
            {
                "run_id": str(row.get("run_id") or "").strip(),
                "created_at": str(row.get("created_at") or "").strip(),
                "asof_date": str(row.get("asof_date") or "").strip(),
                "industry_type": str(row.get("industry_type") or industry_type).strip() or industry_type,
                "ths_index_type": str(row.get("ths_index_type") or ths_index_type).strip().upper() or ths_index_type,
                "market": str(row.get("market") or "").strip(),
                "top_n": int(row.get("top_n") or len(top_candidates) or 0),
                "scoring_version": str(row.get("scoring_version") or "").strip(),
                "total_candidates": int(row.get("total_candidates") or 0),
                "performance": {
                    "topn_summary": cached_eval.get("topn_summary") or {},
                    "benchmark_summary": cached_eval.get("benchmark_summary") or {},
                    "alpha_summary": cached_eval.get("alpha_summary") or {},
                    "hit_ratio_summary": cached_eval.get("hit_ratio_summary") or {},
                },
            }
        )

    response = Response(
        {
            "data": rows,
            "meta": {
                "total": len(ordered),
                "industry_type": industry_type,
                "ths_index_type": ths_index_type,
                "from_index": from_index,
                "limit": limit,
            },
        }
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@never_cache
@api_view(["GET"])
def get_industry_universe_rotation_run_detail(request, run_id):
    normalized_run_id = str(run_id or "").strip()
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "sw") if hasattr(request, "query_params") else "sw"
    )
    ths_index_type = _normalize_rotation_ths_index_type(
        request.query_params.get("ths_index_type", "ALL") if hasattr(request, "query_params") else "ALL"
    )
    if industry_type != "ths":
        ths_index_type = "ALL"
    windows = _parse_rotation_windows(request.query_params.get("windows") if hasattr(request, "query_params") else None)

    payload = _read_sw_rotation_runs_payload(industry_type, ths_index_type)
    runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
    matched_index = None
    matched_run = None
    for idx, item in enumerate(runs):
        row = item if isinstance(item, dict) else {}
        if str(row.get("run_id") or "").strip() == normalized_run_id:
            matched_index = idx
            matched_run = row
            break

    if matched_run is None:
        return Response({"error": f"rotation run not found: {normalized_run_id}"}, status=404)

    cached_last = matched_run.get("last_evaluation") if isinstance(matched_run.get("last_evaluation"), dict) else {}
    cached_daily = matched_run.get("evaluation_daily") if isinstance(matched_run.get("evaluation_daily"), dict) else {}

    cached_windows = cached_last.get("windows") if isinstance(cached_last.get("windows"), list) else []
    cached_series = cached_daily.get("series") if isinstance(cached_daily.get("series"), list) else []
    has_cached = bool(cached_last) and list(cached_windows) == list(windows) and bool(cached_series)

    if has_cached:
        evaluation = {
            "windows": windows,
            "topn_summary": cached_last.get("topn_summary") or {},
            "benchmark_summary": cached_last.get("benchmark_summary") or {},
            "alpha_summary": cached_last.get("alpha_summary") or {},
            "hit_ratio_summary": cached_last.get("hit_ratio_summary") or {},
            "computed_at": cached_last.get("computed_at") or cached_daily.get("computed_at"),
            "daily_series": cached_series,
            "source": "precomputed",
        }
    else:
        run_industry_type = _normalize_industry_universe_type(matched_run.get("industry_type") or industry_type)
        if run_industry_type == "sw":
            try:
                from prediction.management.commands.refresh_sw_rotation_run_evaluation_daily import _build_run_evaluation

                evaluated = _build_run_evaluation(matched_run, windows=windows)
                matched_run["last_evaluation"] = evaluated.get("last_evaluation") or {}
                matched_run["evaluation_daily"] = evaluated.get("evaluation_daily") or {}
                evaluation = {
                    "windows": windows,
                    "topn_summary": (evaluated.get("last_evaluation") or {}).get("topn_summary") or {},
                    "benchmark_summary": (evaluated.get("last_evaluation") or {}).get("benchmark_summary") or {},
                    "alpha_summary": (evaluated.get("last_evaluation") or {}).get("alpha_summary") or {},
                    "hit_ratio_summary": (evaluated.get("last_evaluation") or {}).get("hit_ratio_summary") or {},
                    "computed_at": (evaluated.get("last_evaluation") or {}).get("computed_at"),
                    "daily_series": (evaluated.get("evaluation_daily") or {}).get("series") if isinstance((evaluated.get("evaluation_daily") or {}).get("series"), list) else [],
                    "source": "realtime_backfill",
                }
            except Exception:
                evaluation = _evaluate_rotation_run_payload(matched_run, windows=windows)
                evaluation["daily_series"] = cached_series
                evaluation["source"] = "realtime"
                matched_run["last_evaluation"] = {
                    "windows": windows,
                    "computed_at": evaluation.get("computed_at"),
                    "topn_summary": evaluation.get("topn_summary") or {},
                    "benchmark_summary": evaluation.get("benchmark_summary") or {},
                    "alpha_summary": evaluation.get("alpha_summary") or {},
                    "hit_ratio_summary": evaluation.get("hit_ratio_summary") or {},
                }
        else:
            evaluation = {
                "windows": windows,
                "topn_summary": {},
                "benchmark_summary": {},
                "alpha_summary": {},
                "hit_ratio_summary": {},
                "computed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "daily_series": [],
                "source": "not_supported_for_type",
            }
    if matched_index is not None:
        runs[matched_index] = matched_run
        payload["runs"] = runs
        _write_sw_rotation_runs_payload(payload, industry_type, ths_index_type)

    response = Response(
        {
            "data": {
                "run": {
                    "run_id": str(matched_run.get("run_id") or "").strip(),
                    "created_at": str(matched_run.get("created_at") or "").strip(),
                    "asof_date": str(matched_run.get("asof_date") or "").strip(),
                    "industry_type": str(matched_run.get("industry_type") or industry_type).strip() or industry_type,
                    "ths_index_type": str(matched_run.get("ths_index_type") or ths_index_type).strip().upper() or ths_index_type,
                    "market": str(matched_run.get("market") or "").strip(),
                    "top_n": int(matched_run.get("top_n") or 0),
                    "scoring_version": str(matched_run.get("scoring_version") or "").strip(),
                },
                "top_candidates": matched_run.get("top_candidates") if isinstance(matched_run.get("top_candidates"), list) else [],
                "evaluation": evaluation,
            },
            "meta": {
                "run_id": normalized_run_id,
                "industry_type": industry_type,
                "ths_index_type": ths_index_type,
                "windows": windows,
            },
        }
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@api_view(["DELETE"])
def delete_industry_universe_rotation_run(request, run_id):
    normalized_run_id = str(run_id or "").strip()
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "sw") if hasattr(request, "query_params") else "sw"
    )
    ths_index_type = _normalize_rotation_ths_index_type(
        request.query_params.get("ths_index_type", "ALL") if hasattr(request, "query_params") else "ALL"
    )
    if industry_type != "ths":
        ths_index_type = "ALL"
    if not normalized_run_id:
        return Response({"error": "missing run_id"}, status=400)

    payload = _read_sw_rotation_runs_payload(industry_type, ths_index_type)
    runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
    next_runs = []
    deleted = False
    for item in runs:
        row = item if isinstance(item, dict) else {}
        current_run_id = str(row.get("run_id") or "").strip()
        if current_run_id == normalized_run_id:
            deleted = True
            continue
        next_runs.append(row)

    if not deleted:
        return Response({"error": f"rotation run not found: {normalized_run_id}"}, status=404)

    payload["runs"] = next_runs
    _write_sw_rotation_runs_payload(payload, industry_type, ths_index_type)

    return Response(
        {
            "data": {
                "run_id": normalized_run_id,
                "deleted": True,
                "remaining": len(next_runs),
            }
        }
    )


@api_view(["GET"])
def get_sw_industry_list(request):
    market = str(request.query_params.get("market", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"
    level = str(request.query_params.get("level", "L3") if hasattr(request, "query_params") else "L3").strip().upper() or "L3"
    if level not in {"L1", "L2", "L3"}:
        level = "L3"

    try:
        cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
        level_items = (cfg.sw_mapping.get("levels", {}) or {}).get(level, {})
        l3_member_map = (cfg.sw_mapping.get("level_members", {}) or {}).get("L3", {})

        corp_count_map = {
            str(item.get("sw_l3_code") or "").strip(): int(item.get("count") or 0)
            for item in (
                Corporation.objects.exclude(sw_l3_code__isnull=True)
                .exclude(sw_l3_code="")
                .values("sw_l3_code")
                .annotate(count=Count("id"))
            )
        }

        options = []
        for code, entry in (level_items or {}).items():
            if not isinstance(entry, dict):
                continue
            index_code = str(entry.get("index_code") or code or "").strip()
            industry_code = str(entry.get("industry_code") or "").strip()
            industry_name = str(entry.get("industry_name") or "").strip()
            if not index_code or not industry_name:
                continue

            configured_members = l3_member_map.get(code) if isinstance(l3_member_map, dict) else []
            configured_member_count = len(configured_members) if isinstance(configured_members, list) else 0
            db_member_count = corp_count_map.get(index_code)

            options.append(
                {
                    "industry_code": index_code,
                    "industry_name": industry_name,
                    "industry_code_raw": industry_code,
                    "level": str(entry.get("level") or level),
                    "parent_index_code": str(entry.get("parent_index_code") or ""),
                    "parent_name": str(entry.get("parent_name") or ""),
                    "member_count": int(db_member_count if db_member_count is not None else configured_member_count),
                }
            )

        options = sorted(options, key=lambda item: (str(item.get("industry_name") or ""), str(item.get("industry_code") or "")))
        return Response(
            {
                "data": options,
                "meta": {
                    "market": market,
                    "level": level,
                    "total": len(options),
                },
            }
        )
    except Exception as exc:
        return Response(
            {
                "data": [],
                "meta": {
                    "market": market,
                    "level": level,
                    "total": 0,
                },
                "error": str(exc),
            }
        )


@api_view(["GET"])
def get_sw_industry_history(request, industry_code):
    metric = str(request.query_params.get("metric", "pe") if hasattr(request, "query_params") else "pe").strip().lower() or "pe"
    if metric not in {"close", "pe", "pb"}:
        metric = "pe"
    period, lookback_delta = _parse_sw_period(
        request.query_params.get("period", "5Y") if hasattr(request, "query_params") else "5Y"
    )
    market = str(request.query_params.get("market", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"

    try:
        cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
        _code, l3_entry = _resolve_sw_l3_entry(cfg, industry_code)
        if not l3_entry:
            return Response({"error": f"SWΦíîΣ╕ÜΣ╕ìσ¡ÿσ£¿: {industry_code}"}, status=404)

        index_code = str(l3_entry.get("index_code") or industry_code or "").strip()
        if not index_code:
            return Response({"error": f"SWΦíîΣ╕Üτ╝ûτáüµùáµòê: {industry_code}"}, status=400)

        today = datetime.date.today()
        start_date = (today - lookback_delta).strftime("%Y%m%d") if lookback_delta is not None else "19900101"
        end_date = today.strftime("%Y%m%d")
        cache_key = f"sw_history:{market}:{index_code}:{period}:{metric}"
        cached_payload = cache.get(cache_key)
        if cached_payload:
            return Response(cached_payload)

        pro = get_tushare_pro()
        try:
            df = pro.sw_daily(
                ts_code=index_code,
                start_date=start_date,
                end_date=end_date,
                fields="ts_code,trade_date,close,pe,pb",
            )
        except TypeError:
            df = pro.sw_daily(ts_code=index_code, start_date=start_date, end_date=end_date)

        if df is None or getattr(df, "empty", True):
            payload = {
                "data": [],
                "meta": {
                    "industry_code": index_code,
                    "industry_name": str(l3_entry.get("industry_name") or ""),
                    "metric": metric,
                    "period": period,
                    "q10": None,
                    "q50": None,
                    "q90": None,
                    "latest_value": None,
                    "latest_trade_date": None,
                },
            }
            cache.set(cache_key, payload, timeout=120)
            return Response(payload)

        frame = df.fillna("").copy()
        frame["trade_date"] = frame["trade_date"].astype(str)
        frame = frame.sort_values("trade_date")
        values = []
        rows = []
        for _, row in frame.iterrows():
            trade_date_raw = str(row.get("trade_date") or "").strip()
            if len(trade_date_raw) == 8 and trade_date_raw.isdigit():
                trade_date_text = f"{trade_date_raw[0:4]}-{trade_date_raw[4:6]}-{trade_date_raw[6:8]}"
            else:
                trade_date_text = trade_date_raw

            value = _as_float_or_none(row.get(metric))
            if value is None or value <= 0:
                continue
            rows.append(
                {
                    "trade_date": trade_date_text,
                    "value": round(float(value), 4),
                }
            )
            values.append(float(value))

        latest_row = rows[-1] if rows else None
        payload = {
            "data": rows,
            "meta": {
                "industry_code": index_code,
                "industry_name": str(l3_entry.get("industry_name") or ""),
                "metric": metric,
                "period": period,
                "q10": round(_compute_quantile(values, 0.1), 4) if values else None,
                "q50": round(_compute_quantile(values, 0.5), 4) if values else None,
                "q90": round(_compute_quantile(values, 0.9), 4) if values else None,
                "latest_value": latest_row.get("value") if latest_row else None,
                "latest_trade_date": latest_row.get("trade_date") if latest_row else None,
                "count": len(rows),
            },
        }
        cache.set(cache_key, payload, timeout=120)
        return Response(payload)
    except Exception as exc:
        return Response(
            {
                "data": [],
                "meta": {
                    "industry_code": str(industry_code or ""),
                    "metric": metric,
                    "period": period,
                },
                "error": str(exc),
            },
            status=500,
        )


@api_view(["GET"])
def get_sw_industry_constituents(request, industry_code, from_index, to_index):
    market_filter = str(request.query_params.get("market", "ALL") if hasattr(request, "query_params") else "ALL").strip().upper() or "ALL"
    keyword = str(request.query_params.get("keyword", "") if hasattr(request, "query_params") else "").strip()
    market = str(request.query_params.get("market_scope", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"

    try:
        cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
        _code, l3_entry = _resolve_sw_l3_entry(cfg, industry_code)
        if not l3_entry:
            return Response({"error": f"SWΦíîΣ╕ÜΣ╕ìσ¡ÿσ£¿: {industry_code}"}, status=404)

        index_code = str(l3_entry.get("index_code") or industry_code or "").strip()
        industry_code_raw = str(l3_entry.get("industry_code") or "").strip()

        from_index = max(0, int(from_index))
        to_index = max(from_index + 1, int(to_index))

        qs = Corporation.objects.filter(list_status="L").filter(Q(sw_l3_code=index_code) | Q(sw_l3_code=industry_code_raw))
        if not qs.exists():
            qs = Corporation.objects.filter(list_status="L", sw_l3_name=str(l3_entry.get("industry_name") or "").strip())

        if market_filter in {"SH", "SSE"}:
            qs = qs.filter(ts_code__startswith="6")
        elif market_filter in {"SZ", "SZSE"}:
            qs = qs.filter(ts_code__startswith="0")
        elif market_filter in {"CYB", "GEM"}:
            qs = qs.filter(ts_code__startswith="3")
        elif market_filter in {"STAR", "KCB"}:
            qs = qs.filter(ts_code__startswith="688")

        if keyword:
            qs = qs.filter(Q(ts_code__icontains=keyword) | Q(name__icontains=keyword))

        total_count = qs.count()
        corporations = list(qs.order_by("ts_code")[from_index:to_index])
        ts_codes = [str(c.ts_code or "").strip().upper() for c in corporations if str(c.ts_code or "").strip()]

        user = request.user if request.user.is_authenticated else User.get_admin_user()
        watchlist_map = {}
        if user and ts_codes:
            watch_qs = UserWatchlist.objects.filter(user=user, ts_code__in=ts_codes, is_enabled=True)
            for item in watch_qs:
                code = str(item.ts_code or "").strip().upper()
                watchlist_map[code] = {
                    "in_watchlist": True,
                    "hold_position": bool(getattr(item, "hold_position", False)),
                    "observe_only": bool(getattr(item, "observe_only", False)),
                }

        basic_info_map = {}
        if ts_codes:
            for row in CorporationBasic.objects.filter(ts_code__in=ts_codes):
                website = str(getattr(row, "website", "") or "")
                basic_info_map[str(row.ts_code or "").strip().upper()] = {
                    "website": website,
                    "website_url": _normalize_company_website_url(website),
                    "main_business": str(getattr(row, "main_business", "") or ""),
                }

        rows = []
        for corp in corporations:
            ts_code_value = str(corp.ts_code or "").strip().upper()
            watch_info = watchlist_map.get(ts_code_value) or {
                "in_watchlist": False,
                "hold_position": False,
                "observe_only": False,
            }
            rows.append(
                {
                    "ts_code": ts_code_value,
                    "name": str(corp.name or ""),
                    "industry_name": str(corp.sw_l3_name or ""),
                    "website": str(getattr(corp, "website", "") or ""),
                    "website_url": _normalize_company_website_url(getattr(corp, "website", "")),
                    "basic_info": basic_info_map.get(ts_code_value) or {"website": "", "website_url": None, "main_business": ""},
                    "in_watchlist": watch_info["in_watchlist"],
                    "hold_position": watch_info["hold_position"],
                    "observe_only": watch_info["observe_only"],
                }
            )

        return Response(
            {
                "data": rows,
                "meta": {
                    "industry_code": index_code,
                    "industry_name": str(l3_entry.get("industry_name") or ""),
                    "total": total_count,
                    "from_index": from_index,
                    "to_index": to_index,
                    "market": market_filter,
                    "keyword": keyword,
                },
            }
        )
    except Exception as exc:
        return Response(
            {
                "data": [],
                "meta": {
                    "industry_code": str(industry_code or ""),
                    "from_index": int(from_index),
                    "to_index": int(to_index),
                    "market": market_filter,
                },
                "error": str(exc),
            },
            status=500,
        )


def _normalize_industry_universe_type(value):
    normalized = str(value or "sw").strip().lower() or "sw"
    if normalized in {"sw", "ths", "valuation_variant", "corp_industry"}:
        return normalized
    return "sw"


def _to_trade_date_text(raw_value):
    trade_date_raw = str(raw_value or "").strip()
    if len(trade_date_raw) == 8 and trade_date_raw.isdigit():
        return f"{trade_date_raw[0:4]}-{trade_date_raw[4:6]}-{trade_date_raw[6:8]}"
    return trade_date_raw


def _pick_first_positive_metric(row, field_candidates):
    for field_name in field_candidates:
        value = _as_float_or_none(row.get(field_name))
        if value is not None and value > 0:
            return float(value)
    return None


def _pick_first_numeric_metric(row, field_candidates):
    for field_name in field_candidates:
        value = _as_float_or_none(row.get(field_name))
        if value is not None:
            return float(value)
    return None


def _normalize_ths_index_type(value):
    token = str(value or "").strip().upper()
    if token in THS_INDEX_TYPE_LABEL_MAP:
        return token
    return ""


def _get_ths_index_type_label(index_type):
    token = _normalize_ths_index_type(index_type)
    return str(THS_INDEX_TYPE_LABEL_MAP.get(token) or "")


def _fetch_ths_index_rows(pro):
    if pro is None or not hasattr(pro, "ths_index"):
        return []

    frame = None
    for call_kwargs in (
        {"fields": "ts_code,name,type"},
        {"fields": "ts_code,name"},
        {},
    ):
        try:
            frame = pro.ths_index(**call_kwargs)
            break
        except TypeError:
            continue
        except Exception:
            frame = None
            break

    if frame is None or getattr(frame, "empty", True):
        return []
    rows = []
    for _, row in frame.fillna("").iterrows():
        index_code = str(row.get("ts_code") or "").strip().upper()
        display_name = str(row.get("name") or "").strip()
        index_type = _normalize_ths_index_type(row.get("type") or row.get("index_type"))
        if not index_code or not display_name:
            continue
        rows.append(
            {
                "industry_key": index_code,
                "display_name": display_name,
                "index_type": index_type,
                "index_type_label": _get_ths_index_type_label(index_type),
            }
        )
    return rows


def _normalize_ts_code(raw_code):
    text = str(raw_code or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        return text
    if text.startswith(("6", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "3")):
        return f"{text}.SZ"
    if text.startswith(("4", "8")):
        return f"{text}.BJ"
    return text


def _extract_ths_member_code(row):
    # Different tushare client versions may expose different member code columns.
    for field_name in ("con_code", "code", "symbol", "member_code"):
        normalized = _normalize_ts_code(row.get(field_name))
        if normalized and "." in normalized:
            return normalized

    # Fallback: some payloads only provide ts_code; ignore THS index code (*.TI).
    ts_value = _normalize_ts_code(row.get("ts_code"))
    if ts_value and "." in ts_value and not ts_value.endswith(".TI"):
        return ts_value
    return ""


def _extract_ths_member_name(row):
    for field_name in ("name", "con_name", "stock_name", "security_name"):
        text = str(row.get(field_name) or "").strip()
        if text:
            return text
    return ""


def _fetch_ths_member_rows(pro, industry_key):
    key = str(industry_key or "").strip().upper()
    if not key or pro is None or not hasattr(pro, "ths_member"):
        return []

    candidates = [key]
    if key.endswith(".TI"):
        candidates.append(key.split(".", 1)[0])
    elif "." not in key:
        candidates.append(f"{key}.TI")

    for candidate in candidates:
        frame = None
        for call_kwargs in (
            {"ts_code": candidate, "fields": "ts_code,con_code,code,symbol,name,con_name,stock_name"},
            {"ts_code": candidate},
        ):
            try:
                frame = pro.ths_member(**call_kwargs)
                break
            except TypeError:
                continue
            except Exception:
                frame = None
                break

        if frame is None or getattr(frame, "empty", True):
            continue

        items = []
        for _, row in frame.fillna("").iterrows():
            ts_code = _extract_ths_member_code(row)
            if not ts_code:
                continue
            items.append({"ts_code": ts_code, "name": _extract_ths_member_name(row)})

        dedup_map = {}
        for item in items:
            code = str(item.get("ts_code") or "").strip().upper()
            if not code:
                continue
            existing = dedup_map.get(code)
            if existing is None:
                dedup_map[code] = {"ts_code": code, "name": str(item.get("name") or "").strip()}
                continue
            if not existing.get("name"):
                existing["name"] = str(item.get("name") or "").strip()

        deduped = sorted(dedup_map.values(), key=lambda item: str(item.get("ts_code") or ""))
        if deduped:
            return deduped
    return []


def _fetch_ths_member_codes(pro, industry_key):
    rows = _fetch_ths_member_rows(pro, industry_key)
    return [str(item.get("ts_code") or "").strip().upper() for item in rows if str(item.get("ts_code") or "").strip()]


def _get_ths_member_count(pro, industry_key):
    normalized_key = str(industry_key or "").strip().upper()
    if not normalized_key:
        return 0
    cache_key = f"ths_member_count:{normalized_key}"
    cached = cache.get(cache_key)
    if isinstance(cached, int):
        return max(0, cached)
    count = len(_fetch_ths_member_rows(pro, normalized_key))
    cache.set(cache_key, int(count), timeout=900)
    return int(count)


def _get_ths_snapshot_entry(industry_key):
    token = str(industry_key or "").strip().upper()
    if not token:
        return None
    for item in _read_ths_index_snapshot():
        if str(item.get("industry_key") or "").strip().upper() == token:
            return item if isinstance(item, dict) else None
    return None


def _get_ths_snapshot_member_rows(industry_key):
    entry = _get_ths_snapshot_entry(industry_key)
    rows = entry.get("member_stocks") if isinstance(entry, dict) and isinstance(entry.get("member_stocks"), list) else []
    normalized_rows = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        ts_code = _normalize_ts_code(item.get("ts_code"))
        name = str(item.get("name") or "").strip()
        if not ts_code:
            continue
        normalized_rows.append({"ts_code": ts_code, "name": name})
    return normalized_rows


def _fetch_ths_daily_frame(pro, industry_code, start_date, end_date):
    if pro is None or not hasattr(pro, "ths_daily"):
        return None

    for call_kwargs in (
        {
            "ts_code": industry_code,
            "start_date": start_date,
            "end_date": end_date,
            "fields": "ts_code,trade_date,close,pe_ttm,pb_mrq,pe,pb",
        },
        {
            "ts_code": industry_code,
            "start_date": start_date,
            "end_date": end_date,
            "fields": "ts_code,trade_date,close",
        },
        {
            "ts_code": industry_code,
            "start_date": start_date,
            "end_date": end_date,
        },
    ):
        try:
            frame = pro.ths_daily(**call_kwargs)
            if frame is not None:
                return frame
        except TypeError:
            continue
        except Exception:
            continue
    return None


def _apply_constituent_market_filter(qs, market_filter):
    if market_filter in {"SH", "SSE"}:
        return qs.filter(ts_code__startswith="6")
    if market_filter in {"SZ", "SZSE"}:
        return qs.filter(ts_code__startswith="0")
    if market_filter in {"CYB", "GEM"}:
        return qs.filter(ts_code__startswith="3")
    if market_filter in {"STAR", "KCB"}:
        return qs.filter(ts_code__startswith="688")
    return qs


def _resolve_corporation_queryset_by_industry_universe(industry_type, industry_key, market_scope="CN"):
    normalized_type = _normalize_industry_universe_type(industry_type)
    token = str(industry_key or "").strip()
    if not token:
        return Corporation.objects.none(), ""

    if normalized_type == "sw":
        cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market_scope)
        _code, l3_entry = _resolve_sw_l3_entry(cfg, token)
        if not l3_entry:
            return Corporation.objects.none(), ""

        index_code = str(l3_entry.get("index_code") or token or "").strip()
        industry_code_raw = str(l3_entry.get("industry_code") or "").strip()
        industry_name = str(l3_entry.get("industry_name") or "").strip()
        qs = Corporation.objects.filter(list_status="L").filter(
            Q(sw_l3_code=index_code) | Q(sw_l3_code=industry_code_raw)
        )
        if not qs.exists() and industry_name:
            qs = Corporation.objects.filter(list_status="L", sw_l3_name=industry_name)
        return qs, industry_name

    if normalized_type == "valuation_variant":
        snapshot_qs = StockValuationSnapshotLatest.objects.filter(
            market=market_scope,
            valuation_variant=token,
        )
        ts_codes = list(snapshot_qs.values_list("ts_code", flat=True).distinct())
        display_name = str(
            snapshot_qs.exclude(industry_name__isnull=True)
            .exclude(industry_name="")
            .values_list("industry_name", flat=True)
            .first()
            or token
        )
        if not ts_codes:
            return Corporation.objects.none(), display_name
        return Corporation.objects.filter(list_status="L", ts_code__in=ts_codes), display_name

    if normalized_type == "ths":
        token = str(industry_key or "").strip().upper()
        if not token:
            return Corporation.objects.none(), ""

        display_name = token
        try:
            pro = get_tushare_pro()
            for item in _load_ths_index_rows(pro=pro, prefer_local=True):
                if str(item.get("industry_key") or "").strip().upper() == token:
                    display_name = str(item.get("display_name") or token)
                    break
            snapshot_rows = _get_ths_snapshot_member_rows(token)
            member_codes = [str(row.get("ts_code") or "").strip().upper() for row in snapshot_rows if str(row.get("ts_code") or "").strip()]
            if not member_codes:
                member_codes = _fetch_ths_member_codes(pro, token)
        except Exception:
            member_codes = []

        if not member_codes:
            fuzzy_name = str(display_name or "").strip()
            if fuzzy_name:
                fallback_qs = Corporation.objects.filter(list_status="L").filter(
                    Q(sw_l3_name=fuzzy_name) | Q(industry__name=fuzzy_name)
                )
                if fallback_qs.exists():
                    return fallback_qs, display_name
            return Corporation.objects.none(), display_name
        return Corporation.objects.filter(list_status="L", ts_code__in=member_codes), display_name

    industry_name = token
    return Corporation.objects.filter(list_status="L", industry__name=industry_name), industry_name


def _build_watchlist_map(user, ts_codes):
    if not user or not ts_codes:
        return {}
    requested_codes = [str(code or "").strip().upper() for code in ts_codes if str(code or "").strip()]
    if not requested_codes:
        return {}

    def _base_code(code):
        normalized = str(code or "").strip().upper()
        return normalized.split(".", 1)[0] if "." in normalized else normalized

    code_candidates = set(requested_codes)
    code_candidates.update(_base_code(code) for code in requested_codes)

    watchlist_map = {
        code: {
            "in_watchlist": False,
            "hold_position": False,
            "observe_only": False,
        }
        for code in requested_codes
    }
    watch_qs = UserWatchlist.objects.filter(user=user, ts_code__in=code_candidates, is_enabled=True)
    for item in watch_qs:
        entry_code = str(item.ts_code or "").strip().upper()
        if not entry_code:
            continue
        entry_base = _base_code(entry_code)
        for requested in requested_codes:
            if requested != entry_code and _base_code(requested) != entry_base:
                continue
            state = watchlist_map[requested]
            state["in_watchlist"] = True
            state["hold_position"] = state["hold_position"] or bool(getattr(item, "hold_a_position", False))
            state["observe_only"] = state["observe_only"] or bool(getattr(item, "observe_only", False))
    return watchlist_map


def _build_basic_info_map(ts_codes):
    if not ts_codes:
        return {}
    basic_info_map = {}
    for row in CorporationBasic.objects.filter(ts_code__in=ts_codes):
        website = str(getattr(row, "website", "") or "")
        basic_info_map[str(row.ts_code or "").strip().upper()] = {
            "website": website,
            "website_url": _normalize_company_website_url(website),
            "main_business": str(getattr(row, "main_business", "") or ""),
        }
    return basic_info_map


def _median(values):
    return _compute_quantile(values, 0.5)


def _build_industry_universe_median_history(ts_codes, period_delta=None, metric="pe"):
    if not ts_codes:
        return [], {
            "q10": None,
            "q50": None,
            "q90": None,
            "latest_value": None,
            "latest_trade_date": None,
        }

    trade_filter = Q(ts_code__in=ts_codes, freq="D")
    if period_delta is not None:
        start_date = datetime.date.today() - period_delta
        trade_filter &= Q(trade_date__gte=start_date)

    by_date = {}

    if metric == "close":
        trading_rows = StockTradingHistory.objects.filter(trade_filter).values("trade_date", "close_qfq", "close")
        for row in trading_rows:
            trade_date = row.get("trade_date")
            if trade_date is None:
                continue
            payload = by_date.setdefault(trade_date, [])
            close_value = _as_float_or_none(row.get("close_qfq"))
            if close_value is None:
                close_value = _as_float_or_none(row.get("close"))
            if close_value is not None and close_value > 0:
                payload.append(float(close_value))
    else:
        fundamental_rows = StockFundamentalHistory.objects.filter(trade_filter).values("trade_date", metric)
        for row in fundamental_rows:
            trade_date = row.get("trade_date")
            if trade_date is None:
                continue
            payload = by_date.setdefault(trade_date, [])
            metric_value = _as_float_or_none(row.get(metric))
            if metric_value is not None and metric_value > 0:
                payload.append(float(metric_value))

    rows = []
    selected_values = []
    for trade_date in sorted(by_date.keys()):
        values = by_date.get(trade_date) or []
        selected_value = _median(values)
        if selected_value is not None:
            selected_values.append(float(selected_value))

        rows.append(
            {
                "trade_date": trade_date.strftime("%Y-%m-%d") if hasattr(trade_date, "strftime") else str(trade_date),
                "value": round(float(selected_value), 4) if selected_value is not None else None,
            }
        )

    latest_row = rows[-1] if rows else None
    meta = {
        "q10": round(float(_compute_quantile(selected_values, 0.1)), 4) if selected_values else None,
        "q50": round(float(_compute_quantile(selected_values, 0.5)), 4) if selected_values else None,
        "q90": round(float(_compute_quantile(selected_values, 0.9)), 4) if selected_values else None,
        "latest_value": latest_row.get("value") if latest_row else None,
        "latest_trade_date": latest_row.get("trade_date") if latest_row else None,
        "count": len(rows),
    }
    return rows, meta


def _load_variant_metric_history_from_cache(market, variant_key, metric, period_delta=None):
    query = IndustryVariantMetricDaily.objects.filter(
        market=market,
        variant_key=variant_key,
        metric=metric,
    )
    if period_delta is not None:
        start_date = datetime.date.today() - period_delta
        query = query.filter(trade_date__gte=start_date)

    rows = []
    values = []
    for item in query.order_by("trade_date").values("trade_date", "median_value"):
        trade_date = item.get("trade_date")
        value = _as_float_or_none(item.get("median_value"))
        if trade_date is None or value is None:
            continue
        rows.append(
            {
                "trade_date": trade_date.strftime("%Y-%m-%d") if hasattr(trade_date, "strftime") else str(trade_date),
                "value": round(float(value), 4),
            }
        )
        values.append(float(value))

    latest_row = rows[-1] if rows else None
    meta = {
        "q10": round(float(_compute_quantile(values, 0.1)), 4) if values else None,
        "q50": round(float(_compute_quantile(values, 0.5)), 4) if values else None,
        "q90": round(float(_compute_quantile(values, 0.9)), 4) if values else None,
        "latest_value": latest_row.get("value") if latest_row else None,
        "latest_trade_date": latest_row.get("trade_date") if latest_row else None,
        "count": len(rows),
    }
    return rows, meta


@api_view(["GET"])
def get_industry_universe_types(request):
    return Response(
        {
            "data": [
                {"industry_type": "sw", "label": "SW行业", "enabled": True},
                {"industry_type": "ths", "label": "THS行业", "enabled": True},
                {"industry_type": "valuation_variant", "label": "行业变体", "enabled": True},
                {"industry_type": "corp_industry", "label": "基本信息行业", "enabled": True},
            ],
            "meta": {"total": 4},
        }
    )


@api_view(["GET"])
def get_industry_universe_list(request):
    market = str(request.query_params.get("market", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"
    level = str(request.query_params.get("level", "L3") if hasattr(request, "query_params") else "L3").strip().upper() or "L3"
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "sw") if hasattr(request, "query_params") else "sw"
    )
    keyword = str(request.query_params.get("keyword", "") if hasattr(request, "query_params") else "").strip().lower()
    ths_index_type = _normalize_ths_index_type(
        request.query_params.get("ths_index_type", "") if hasattr(request, "query_params") else ""
    )

    try:
        if industry_type == "sw":
            cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
            level_items = (cfg.sw_mapping.get("levels", {}) or {}).get(level, {})
            l3_member_map = (cfg.sw_mapping.get("level_members", {}) or {}).get("L3", {})
            corp_count_map = {
                str(item.get("sw_l3_code") or "").strip(): int(item.get("count") or 0)
                for item in (
                    Corporation.objects.exclude(sw_l3_code__isnull=True)
                    .exclude(sw_l3_code="")
                    .values("sw_l3_code")
                    .annotate(count=Count("id"))
                )
            }

            data = []
            for code, entry in (level_items or {}).items():
                if not isinstance(entry, dict):
                    continue
                index_code = str(entry.get("index_code") or code or "").strip()
                name = str(entry.get("industry_name") or "").strip()
                configured_members = l3_member_map.get(code) if isinstance(l3_member_map, dict) else []
                configured_member_count = len(configured_members) if isinstance(configured_members, list) else 0
                db_member_count = corp_count_map.get(index_code)
                if not code or not name:
                    continue
                if keyword and keyword not in index_code.lower() and keyword not in name.lower():
                    continue
                data.append(
                    {
                        "industry_type": "sw",
                        "industry_key": index_code,
                        "display_name": name,
                        "member_count": int(db_member_count if db_member_count is not None else configured_member_count),
                        "extra_label": str(entry.get("level") or level),
                    }
                )
            return Response({"data": data, "meta": {"industry_type": industry_type, "total": len(data), "market": market, "level": level}})

        if industry_type == "ths":
            try:
                pro = get_tushare_pro()
                ths_rows = _load_ths_index_rows(pro=pro, prefer_local=True)
            except Exception:
                pro = None
                ths_rows = _load_ths_index_rows(pro=None, prefer_local=True)

            if pro is not None and ths_rows:
                needs_snapshot_refresh = any(
                    (
                        "member_count" not in row
                        or "member_stocks" not in row
                        or not _normalize_ths_index_type(row.get("index_type"))
                    )
                    for row in ths_rows
                    if isinstance(row, dict)
                )
                if needs_snapshot_refresh:
                    refreshed_rows = []
                    for row in ths_rows:
                        if not isinstance(row, dict):
                            continue
                        industry_key = str(row.get("industry_key") or "").strip().upper()
                        display_name = str(row.get("display_name") or "").strip()
                        if not industry_key or not display_name:
                            continue
                        fetched_member_stocks = _fetch_ths_member_rows(pro, industry_key)
                        previous_member_stocks = row.get("member_stocks") if isinstance(row.get("member_stocks"), list) else []
                        if fetched_member_stocks:
                            member_stocks = fetched_member_stocks
                            member_count = len(fetched_member_stocks)
                        else:
                            member_stocks = previous_member_stocks
                            try:
                                member_count = int(row.get("member_count", 0))
                            except (TypeError, ValueError):
                                member_count = len(member_stocks)
                        refreshed_rows.append(
                            {
                                "industry_key": industry_key,
                                "display_name": display_name,
                                "index_type": _normalize_ths_index_type(row.get("index_type")),
                                "index_type_label": str(
                                    row.get("index_type_label") or _get_ths_index_type_label(row.get("index_type"))
                                ).strip(),
                                "member_count": max(0, member_count),
                                "member_stocks": member_stocks,
                            }
                        )
                    if refreshed_rows:
                        ths_rows = refreshed_rows
                        try:
                            _write_ths_index_snapshot(ths_rows)
                        except Exception:
                            pass

            member_count_map = {}
            try:
                Corporation._meta.get_field("ths_code")
                member_count_map = {
                    str(item.get("ths_code") or "").strip().upper(): int(item.get("count") or 0)
                    for item in (
                        Corporation.objects.exclude(ths_code__isnull=True)
                        .exclude(ths_code="")
                        .values("ths_code")
                        .annotate(count=Count("id"))
                    )
                }
            except Exception:
                member_count_map = {}
            data = []
            for row in ths_rows:
                industry_key = str(row.get("industry_key") or "").strip().upper()
                display_name = str(row.get("display_name") or "").strip()
                index_type = _normalize_ths_index_type(row.get("index_type"))
                index_type_label = str(row.get("index_type_label") or _get_ths_index_type_label(index_type)).strip()
                snapshot_member_count = row.get("member_count")
                try:
                    snapshot_member_count = int(snapshot_member_count)
                except (TypeError, ValueError):
                    snapshot_member_count = None
                if not industry_key or not display_name:
                    continue
                if ths_index_type and index_type != ths_index_type:
                    continue
                if keyword and keyword not in industry_key.lower() and keyword not in display_name.lower():
                    continue
                data.append(
                    {
                        "industry_type": "ths",
                        "industry_key": industry_key,
                        "display_name": display_name,
                        "index_type": index_type,
                        "index_type_label": index_type_label,
                        "member_count": int(
                            member_count_map.get(
                                industry_key,
                                snapshot_member_count if snapshot_member_count is not None else _get_ths_member_count(pro, industry_key),
                            )
                        ),
                        "extra_label": f"THS {index_type_label}".strip(),
                    }
                )
            return Response(
                {
                    "data": data,
                    "meta": {
                        "industry_type": industry_type,
                        "total": len(data),
                        "market": market,
                        "ths_index_type": ths_index_type or "ALL",
                    },
                }
            )

        if industry_type == "valuation_variant":
            data = []
            persisted_qs = IndustryVariantCache.objects.filter(market=market).order_by("-member_count", "-max_match_score", "variant_key")
            if persisted_qs.exists():
                for row in persisted_qs.values("variant_key", "display_name", "industry_code", "industry_level", "compare_group", "member_count"):
                    variant = str(row.get("variant_key") or "").strip()
                    industry_name = str(row.get("display_name") or "").strip()
                    display_name = industry_name or variant
                    if not variant or not display_name:
                        continue
                    haystack = f"{variant} {display_name} {row.get('industry_code') or ''}".lower()
                    if keyword and keyword not in haystack:
                        continue
                    compare_group = str(row.get("compare_group") or "").strip()
                    data.append(
                        {
                            "industry_type": "valuation_variant",
                            "industry_key": variant,
                            "display_name": display_name,
                            "member_count": int(row.get("member_count") or 0),
                            "extra_label": compare_group or str(row.get("industry_level") or ""),
                        }
                    )
                return Response({"data": data, "meta": {"industry_type": industry_type, "total": len(data), "market": market, "source": "persisted"}})

            variant_qs = (
                StockValuationSnapshotLatest.objects.filter(market=market)
                .exclude(valuation_variant__isnull=True)
                .exclude(valuation_variant="")
                .values("valuation_variant", "industry_name", "industry_code", "industry_level", "compare_group")
                .annotate(member_count=Count("ts_code", distinct=True), max_match_score=Max("match_score"))
                .order_by("-member_count", "-max_match_score", "valuation_variant")
            )
            for row in variant_qs:
                variant = str(row.get("valuation_variant") or "").strip()
                industry_name = str(row.get("industry_name") or "").strip()
                display_name = industry_name or variant
                if not variant or not display_name:
                    continue
                haystack = f"{variant} {display_name} {row.get('industry_code') or ''}".lower()
                if keyword and keyword not in haystack:
                    continue
                compare_group = str(row.get("compare_group") or "").strip()
                data.append(
                    {
                        "industry_type": "valuation_variant",
                        "industry_key": variant,
                        "display_name": display_name,
                        "member_count": int(row.get("member_count") or 0),
                        "extra_label": compare_group or str(row.get("industry_level") or ""),
                    }
                )
            return Response({"data": data, "meta": {"industry_type": industry_type, "total": len(data), "market": market}})

        corp_qs = (
            Corporation.objects.filter(list_status="L")
            .exclude(industry__isnull=True)
            .exclude(industry__name__isnull=True)
            .exclude(industry__name="")
            .values("industry__name")
            .annotate(member_count=Count("id"))
            .order_by("industry__name")
        )
        data = []
        for row in corp_qs:
            industry_name = str(row.get("industry__name") or "").strip()
            if not industry_name:
                continue
            if keyword and keyword not in industry_name.lower():
                continue
            data.append(
                {
                    "industry_type": "corp_industry",
                    "industry_key": industry_name,
                    "display_name": industry_name,
                    "member_count": int(row.get("member_count") or 0),
                    "extra_label": "σƒ║τíÇΦíîΣ╕Ü",
                }
            )
        return Response({"data": data, "meta": {"industry_type": industry_type, "total": len(data), "market": market}})
    except Exception as exc:
        return Response(
            {
                "data": [],
                "meta": {
                    "industry_type": industry_type,
                    "total": 0,
                    "market": market,
                },
                "error": str(exc),
            },
            status=500,
        )


@api_view(["GET"])
def get_industry_universe_history(request):
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "sw") if hasattr(request, "query_params") else "sw"
    )
    industry_key = str(request.query_params.get("industry_key", "") if hasattr(request, "query_params") else "").strip()
    metric = str(request.query_params.get("metric", "pe") if hasattr(request, "query_params") else "pe").strip().lower() or "pe"
    if metric not in {"close", "pe", "pb"}:
        metric = "pe"
    period_text = request.query_params.get("period", "5Y") if hasattr(request, "query_params") else "5Y"
    period, lookback_delta = _parse_sw_period(period_text)
    market = str(request.query_params.get("market", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"

    if not industry_key:
        return Response({"error": "industry_key is required"}, status=400)

    try:
        if industry_type == "sw":
            cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market=market)
            _code, l3_entry = _resolve_sw_l3_entry(cfg, industry_key)
            if not l3_entry:
                return Response({"error": f"SWΦíîΣ╕ÜΣ╕ìσ¡ÿσ£¿: {industry_key}"}, status=404)

            index_code = str(l3_entry.get("index_code") or industry_key or "").strip()
            if not index_code:
                return Response({"error": f"SWΦíîΣ╕Üτ╝ûτáüµùáµòê: {industry_key}"}, status=400)

            today = datetime.date.today()
            start_date = (today - lookback_delta).strftime("%Y%m%d") if lookback_delta is not None else "19900101"
            end_date = today.strftime("%Y%m%d")
            cache_key = f"sw_history:universe:{market}:{index_code}:{period}:{metric}"
            cached_payload = cache.get(cache_key)
            if cached_payload:
                return Response(cached_payload)

            pro = get_tushare_pro()
            try:
                df = pro.sw_daily(
                    ts_code=index_code,
                    start_date=start_date,
                    end_date=end_date,
                    fields="ts_code,trade_date,close,pe,pb",
                )
            except TypeError:
                df = pro.sw_daily(ts_code=index_code, start_date=start_date, end_date=end_date)

            if df is None or getattr(df, "empty", True):
                payload = {
                    "data": [],
                    "meta": {
                        "industry_type": "sw",
                        "industry_key": industry_key,
                        "industry_code": index_code,
                        "industry_name": str(l3_entry.get("industry_name") or ""),
                        "metric": metric,
                        "period": period,
                        "q10": None,
                        "q50": None,
                        "q90": None,
                        "latest_value": None,
                        "latest_trade_date": None,
                    },
                }
                cache.set(cache_key, payload, timeout=THS_INDUSTRY_HISTORY_CACHE_TTL_SECONDS)
                return Response(payload)

            frame = df.fillna("").copy()
            frame["trade_date"] = frame["trade_date"].astype(str)
            frame = frame.sort_values("trade_date")
            values = []
            rows = []
            for _, row in frame.iterrows():
                trade_date_raw = str(row.get("trade_date") or "").strip()
                if len(trade_date_raw) == 8 and trade_date_raw.isdigit():
                    trade_date_text = f"{trade_date_raw[0:4]}-{trade_date_raw[4:6]}-{trade_date_raw[6:8]}"
                else:
                    trade_date_text = trade_date_raw

                value = _as_float_or_none(row.get(metric))
                if value is None or value <= 0:
                    continue
                rows.append(
                    {
                        "trade_date": trade_date_text,
                        "value": round(float(value), 4),
                    }
                )
                values.append(float(value))

            latest_row = rows[-1] if rows else None
            payload = {
                "data": rows,
                "meta": {
                    "industry_type": "sw",
                    "industry_key": industry_key,
                    "industry_code": index_code,
                    "industry_name": str(l3_entry.get("industry_name") or ""),
                    "metric": metric,
                    "period": period,
                    "q10": round(_compute_quantile(values, 0.1), 4) if values else None,
                    "q50": round(_compute_quantile(values, 0.5), 4) if values else None,
                    "q90": round(_compute_quantile(values, 0.9), 4) if values else None,
                    "latest_value": latest_row.get("value") if latest_row else None,
                    "latest_trade_date": latest_row.get("trade_date") if latest_row else None,
                    "count": len(rows),
                },
            }
            cache.set(cache_key, payload, timeout=120)
            return Response(payload)

        if industry_type == "ths":
            industry_code = str(industry_key or "").strip().upper()
            industry_name = industry_code
            today = datetime.date.today()
            start_date = (today - lookback_delta).strftime("%Y%m%d") if lookback_delta is not None else "19900101"
            end_date = today.strftime("%Y%m%d")
            cache_key = f"ths_history:universe:{market}:{industry_code}:{period}:{metric}"
            cached_payload = cache.get(cache_key)
            if cached_payload:
                return Response(cached_payload)

            pro = get_tushare_pro()
            for item in _load_ths_index_rows(pro=pro, prefer_local=True):
                if str(item.get("industry_key") or "").strip().upper() == industry_code:
                    industry_name = str(item.get("display_name") or industry_code)
                    break
            ths_df = _fetch_ths_daily_frame(pro, industry_code, start_date, end_date)

            if ths_df is None or getattr(ths_df, "empty", True):
                snapshot_rows = _get_ths_snapshot_member_rows(industry_code)
                member_codes = [str(row.get("ts_code") or "").strip().upper() for row in snapshot_rows if str(row.get("ts_code") or "").strip()]
                if not member_codes:
                    member_codes = _fetch_ths_member_codes(pro, industry_code)
                rows, history_meta = _build_industry_universe_median_history(
                    member_codes,
                    period_delta=lookback_delta,
                    metric=metric,
                )
                payload = {
                    "data": rows,
                    "meta": {
                        "industry_type": "ths",
                        "industry_key": industry_key,
                        "industry_code": industry_code,
                        "industry_name": industry_name,
                        "metric": metric,
                        "period": period,
                        "source": "member_median",
                        **history_meta,
                    },
                }
                cache.set(cache_key, payload, timeout=THS_INDUSTRY_HISTORY_CACHE_TTL_SECONDS)
                return Response(payload)

            frame = ths_df.fillna("").copy()
            if "trade_date" not in frame.columns:
                snapshot_rows = _get_ths_snapshot_member_rows(industry_code)
                member_codes = [str(row.get("ts_code") or "").strip().upper() for row in snapshot_rows if str(row.get("ts_code") or "").strip()]
                if not member_codes:
                    member_codes = _fetch_ths_member_codes(pro, industry_code)
                rows, history_meta = _build_industry_universe_median_history(
                    member_codes,
                    period_delta=lookback_delta,
                    metric=metric,
                )
                payload = {
                    "data": rows,
                    "meta": {
                        "industry_type": "ths",
                        "industry_key": industry_key,
                        "industry_code": industry_code,
                        "industry_name": industry_name,
                        "metric": metric,
                        "period": period,
                        "source": "member_median",
                        **history_meta,
                    },
                }
                cache.set(cache_key, payload, timeout=120)
                return Response(payload)

            frame["trade_date"] = frame["trade_date"].astype(str)
            frame = frame.sort_values("trade_date")
            metric_fields = {
                "close": ("close",),
                "pe": ("pe_ttm", "pe"),
                "pb": ("pb_mrq", "pb"),
            }

            values = []
            rows = []
            for _, row in frame.iterrows():
                trade_date_text = _to_trade_date_text(row.get("trade_date"))
                value = _pick_first_positive_metric(row, metric_fields.get(metric, (metric,)))
                if value is None:
                    continue
                rows.append({"trade_date": trade_date_text, "value": round(value, 4)})
                values.append(value)

            latest_row = rows[-1] if rows else None
            payload = {
                "data": rows,
                "meta": {
                    "industry_type": "ths",
                    "industry_key": industry_key,
                    "industry_code": industry_code,
                    "industry_name": industry_name,
                    "metric": metric,
                    "period": period,
                    "q10": round(_compute_quantile(values, 0.1), 4) if values else None,
                    "q50": round(_compute_quantile(values, 0.5), 4) if values else None,
                    "q90": round(_compute_quantile(values, 0.9), 4) if values else None,
                    "latest_value": latest_row.get("value") if latest_row else None,
                    "latest_trade_date": latest_row.get("trade_date") if latest_row else None,
                    "count": len(rows),
                },
            }
            cache.set(cache_key, payload, timeout=THS_INDUSTRY_HISTORY_CACHE_TTL_SECONDS)
            return Response(payload)

        qs, industry_name = _resolve_corporation_queryset_by_industry_universe(
            industry_type,
            industry_key,
            market_scope=market,
        )
        ts_codes = list(qs.values_list("ts_code", flat=True).distinct())

        source = "realtime"
        rows = []
        history_meta = {
            "q10": None,
            "q50": None,
            "q90": None,
            "latest_value": None,
            "latest_trade_date": None,
            "count": 0,
        }
        if industry_type == "valuation_variant":
            rows, history_meta = _load_variant_metric_history_from_cache(
                market=market,
                variant_key=industry_key,
                metric=metric,
                period_delta=lookback_delta,
            )
            if rows:
                source = "persisted"
            else:
                rows, history_meta = _build_industry_universe_median_history(
                    ts_codes,
                    period_delta=lookback_delta,
                    metric=metric,
                )
        else:
            rows, history_meta = _build_industry_universe_median_history(
                ts_codes,
                period_delta=lookback_delta,
                metric=metric,
            )

        return Response(
            {
                "data": rows,
                "meta": {
                    "industry_type": industry_type,
                    "industry_key": industry_key,
                    "industry_name": industry_name or industry_key,
                    "metric": metric,
                    "period": period,
                    "member_count": len(ts_codes),
                    "source": source,
                    **history_meta,
                },
            }
        )
    except Exception as exc:
        return Response(
            {
                "data": [],
                "meta": {
                    "industry_type": industry_type,
                    "industry_key": industry_key,
                    "metric": metric,
                    "period": period,
                },
                "error": str(exc),
            },
            status=500,
        )


@api_view(["GET"])
def get_industry_universe_constituents(request):
    industry_type = _normalize_industry_universe_type(
        request.query_params.get("industry_type", "sw") if hasattr(request, "query_params") else "sw"
    )
    industry_key = str(request.query_params.get("industry_key", "") if hasattr(request, "query_params") else "").strip()
    market_filter = str(request.query_params.get("market", "ALL") if hasattr(request, "query_params") else "ALL").strip().upper() or "ALL"
    keyword = str(request.query_params.get("keyword", "") if hasattr(request, "query_params") else "").strip()
    market_scope = str(request.query_params.get("market_scope", "CN") if hasattr(request, "query_params") else "CN").strip().upper() or "CN"

    if not industry_key:
        return Response({"error": "industry_key is required"}, status=400)

    try:
        from_index = max(0, int(request.query_params.get("from_index", "0") if hasattr(request, "query_params") else 0))
        to_index = max(
            from_index + 1,
            int(request.query_params.get("to_index", str(from_index + 30)) if hasattr(request, "query_params") else from_index + 30),
        )

        if industry_type == "ths":
            snapshot_rows = _get_ths_snapshot_member_rows(industry_key)
            if not snapshot_rows:
                try:
                    pro = get_tushare_pro()
                    fetched_rows = _fetch_ths_member_rows(pro, industry_key)
                    if fetched_rows:
                        snapshot_entry = _get_ths_snapshot_entry(industry_key) or {}
                        _upsert_ths_snapshot_entry(
                            industry_key=industry_key,
                            display_name=str(snapshot_entry.get("display_name") or industry_key),
                            member_stocks=fetched_rows,
                            member_count=len(fetched_rows),
                        )
                        snapshot_rows = fetched_rows
                except Exception:
                    snapshot_rows = snapshot_rows or []
            if snapshot_rows:
                filtered_rows = []
                keyword_lower = str(keyword or "").strip().lower()
                for item in snapshot_rows:
                    ts_code = str(item.get("ts_code") or "").strip().upper()
                    name = str(item.get("name") or "").strip()
                    if not ts_code:
                        continue
                    base_code = ts_code.split(".", 1)[0] if "." in ts_code else ts_code

                    if market_filter in {"SH", "SSE"} and not base_code.startswith("6"):
                        continue
                    if market_filter in {"SZ", "SZSE"} and not base_code.startswith(("0", "3")):
                        continue
                    if market_filter in {"CYB", "GEM"} and not base_code.startswith("3"):
                        continue
                    if market_filter in {"STAR", "KCB"} and not base_code.startswith("688"):
                        continue

                    if keyword_lower and keyword_lower not in ts_code.lower() and keyword_lower not in name.lower():
                        continue
                    filtered_rows.append({"ts_code": ts_code, "name": name})

                total_count = len(filtered_rows)
                selected_rows = filtered_rows[from_index:to_index]
                ts_codes = [str(item.get("ts_code") or "").strip().upper() for item in selected_rows if str(item.get("ts_code") or "").strip()]

                user = request.user if request.user.is_authenticated else User.get_admin_user()
                watchlist_map = _build_watchlist_map(user, ts_codes)
                basic_info_map = _build_basic_info_map(ts_codes)
                corp_map = {
                    str(corp.ts_code or "").strip().upper(): corp
                    for corp in Corporation.objects.filter(ts_code__in=ts_codes)
                }

                entry = _get_ths_snapshot_entry(industry_key) or {}
                industry_name = str(entry.get("display_name") or industry_key)

                rows = []
                for item in selected_rows:
                    ts_code_value = str(item.get("ts_code") or "").strip().upper()
                    if not ts_code_value:
                        continue
                    corp = corp_map.get(ts_code_value)
                    watch_info = watchlist_map.get(ts_code_value) or {
                        "in_watchlist": False,
                        "hold_position": False,
                        "observe_only": False,
                    }
                    rows.append(
                        {
                            "ts_code": ts_code_value,
                            "name": str(item.get("name") or (str(getattr(corp, "name", "") or ""))),
                            "industry_name": industry_name,
                            "website": str(getattr(corp, "website", "") or ""),
                            "website_url": _normalize_company_website_url(getattr(corp, "website", "")),
                            "basic_info": basic_info_map.get(ts_code_value) or {"website": "", "website_url": None, "main_business": ""},
                            "in_watchlist": watch_info["in_watchlist"],
                            "hold_position": watch_info["hold_position"],
                            "observe_only": watch_info["observe_only"],
                        }
                    )

                return Response(
                    {
                        "data": rows,
                        "meta": {
                            "industry_type": "ths",
                            "industry_key": industry_key,
                            "industry_name": industry_name,
                            "total": total_count,
                            "from_index": from_index,
                            "to_index": to_index,
                            "market": market_filter,
                            "keyword": keyword,
                            "source": "snapshot_members",
                        },
                    }
                )

        qs, industry_name = _resolve_corporation_queryset_by_industry_universe(
            industry_type,
            industry_key,
            market_scope=market_scope,
        )

        qs = _apply_constituent_market_filter(qs, market_filter)
        if keyword:
            qs = qs.filter(Q(ts_code__icontains=keyword) | Q(name__icontains=keyword))

        total_count = qs.count()
        corporations = list(qs.order_by("ts_code")[from_index:to_index])
        ts_codes = [str(c.ts_code or "").strip().upper() for c in corporations if str(c.ts_code or "").strip()]

        user = request.user if request.user.is_authenticated else User.get_admin_user()
        watchlist_map = _build_watchlist_map(user, ts_codes)
        basic_info_map = _build_basic_info_map(ts_codes)

        rows = []
        for corp in corporations:
            ts_code_value = str(corp.ts_code or "").strip().upper()
            watch_info = watchlist_map.get(ts_code_value) or {
                "in_watchlist": False,
                "hold_position": False,
                "observe_only": False,
            }
            rows.append(
                {
                    "ts_code": ts_code_value,
                    "name": str(corp.name or ""),
                    "industry_name": str(getattr(getattr(corp, "industry", None), "name", "") or ""),
                    "website": str(getattr(corp, "website", "") or ""),
                    "website_url": _normalize_company_website_url(getattr(corp, "website", "")),
                    "basic_info": basic_info_map.get(ts_code_value) or {"website": "", "website_url": None, "main_business": ""},
                    "in_watchlist": watch_info["in_watchlist"],
                    "hold_position": watch_info["hold_position"],
                    "observe_only": watch_info["observe_only"],
                }
            )

        return Response(
            {
                "data": rows,
                "meta": {
                    "industry_type": industry_type,
                    "industry_key": industry_key,
                    "industry_name": industry_name or industry_key,
                    "total": total_count,
                    "from_index": from_index,
                    "to_index": to_index,
                    "market": market_filter,
                    "keyword": keyword,
                },
            }
        )
    except Exception as exc:
        return Response(
            {
                "data": [],
                "meta": {
                    "industry_type": industry_type,
                    "industry_key": industry_key,
                },
                "error": str(exc),
            },
            status=500,
        )


@api_view(["GET"])
def get_weekly_undervalued_downloads(request):
    items = {}
    for kind in ["traditional", "predictive"]:
        latest_file = _get_latest_weekly_undervalued_file(kind)
        if latest_file is None:
            items[kind] = {
                "available": False,
                "filename": None,
                "updated_at": None,
                "download_url": None,
            }
            continue

        stat = latest_file.stat()
        items[kind] = {
            "available": True,
            "filename": latest_file.name,
            "updated_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "download_url": f"/stock-pick-valuation/weekly-downloads/{kind}/",
        }

    return Response({"code": 0, "message": "ok", "data": items})


@api_view(["GET"])
def download_weekly_undervalued_file(request, kind):
    latest_file = _get_latest_weekly_undervalued_file(kind)
    if latest_file is None:
        raise Http404("weekly undervalued file not found")

    content_type, _encoding = mimetypes.guess_type(str(latest_file))
    return FileResponse(
        latest_file.open("rb"),
        as_attachment=True,
        filename=latest_file.name,
        content_type=content_type or "text/csv",
    )


@api_view(["GET", "POST"])
def get_or_update_weekly_job_strategy_config(request):
    if request.method == "GET":
        data = _load_weekly_undervalued_job_config()
        data["config_path"] = str(_resolve_weekly_undervalued_job_config_path())
        return Response({"code": 0, "message": "ok", "data": data})

    payload = request.data if isinstance(request.data, dict) else {}
    saved = _save_weekly_undervalued_job_config(payload)
    saved["config_path"] = str(_resolve_weekly_undervalued_job_config_path())
    return Response({"code": 0, "message": "saved", "data": saved})


@api_view(["POST"])
def create_stock_pick_valuation_job(request):
    payload = request.data if isinstance(request.data, dict) else {}
    trade_date = str(payload.get("trade_date") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    freq = str(query.get("freq") or payload.get("freq") or "D").strip().upper() or "D"
    if not trade_date or not scope:
        return Response({"error": "trade_date and scope are required"}, status=400)

    owner_key = _resolve_valuation_pick_job_owner(request)
    superseded_job_id = _get_valuation_pick_active_job_id(owner_key)
    if superseded_job_id:
        _cancel_valuation_pick_job(superseded_job_id, "任务已取消（被新任务抢占）")

    job_id = uuid.uuid4().hex
    state = _set_valuation_pick_job_state(
        job_id,
        {
            "status": "queued",
            "progress_pct": 0,
            "processed_count": 0,
            "matched_count": 0,
            "total_candidates": None,
            "message": "任务已排队",
            "data": [],
            "has_more": True,
            "poll_interval_seconds": VALUATION_PICK_JOB_POLL_INTERVAL_SECONDS,
            "trade_date": trade_date,
            "freq": freq,
            "owner_key": owner_key,
            "superseded_job_id": superseded_job_id or None,
        },
    )
    _set_valuation_pick_active_job_id(owner_key, job_id)
    worker = threading.Thread(
        target=_run_valuation_pick_job,
        args=(job_id, {"trade_date": trade_date, "scope": scope, "query": query, "freq": freq, "owner_key": owner_key}),
        daemon=True,
    )
    worker.start()
    return Response(state, status=202)


@api_view(["GET"])
def get_stock_pick_valuation_job(request, job_id):
    state = _get_valuation_pick_job_state(job_id)
    if state is None:
        return Response({"error": "job not found"}, status=404)
    return Response(state)


@api_view(["GET"])
def pick_stocks_by_valuation_simple(request, trade_date, scope):
    freq = request.query_params.get("freq", "D") if hasattr(request, "query_params") else "D"
    try:
        from_index = int(request.query_params.get("from_index", "0")) if hasattr(request, "query_params") else 0
    except (TypeError, ValueError):
        from_index = 0
    try:
        to_index = int(request.query_params.get("to_index", str(from_index + 25))) if hasattr(request, "query_params") else from_index + 25
    except (TypeError, ValueError):
        to_index = from_index + 25

    return _pick_stocks_by_valuation_fast(
        request=request,
        trade_date=trade_date,
        scope=scope,
        freq=freq,
        from_index=from_index,
        to_index=to_index,
    )


@api_view(["POST"])
def add_stock_to_watchlist(request, ts_code):
    try:
        normalized_ts_code = str(ts_code or "").strip().upper()
        if not normalized_ts_code:
            return Response({"error": "ts_code is required."}, status=400)
        user = request.user if request.user.is_authenticated else User.get_admin_user()

        if not user:
            return Response({"error": "Authentication required."}, status=401)
        corporation = Corporation.objects.filter(ts_code=normalized_ts_code).first()
        watchlist_entry, created = UserWatchlist.objects.get_or_create(
            user=user,
            ts_code=normalized_ts_code,
            defaults={
                "is_enabled": True,
                "name": getattr(corporation, "name", ""),
                "corporation": corporation,
                "observe_only": False,
            },
        )
        update_fields = []
        if corporation and watchlist_entry.corporation_id != corporation.id:
            watchlist_entry.corporation = corporation
            update_fields.append("corporation")
        corp_name = (getattr(corporation, "name", "") or "").strip()
        if corp_name and (watchlist_entry.name or "").strip() != corp_name:
            watchlist_entry.name = corp_name
            update_fields.append("name")
        if not watchlist_entry.is_enabled:
            watchlist_entry.is_enabled = True
            update_fields.append("is_enabled")
        if update_fields:
            watchlist_entry.save(update_fields=update_fields)
        return Response(
            {
                "message": "Stock added to watchlist.",
                "ts_code": normalized_ts_code,
                "in_watchlist": True,
                "hold_position": bool(watchlist_entry.hold_a_position),
                "observe_status": bool(getattr(watchlist_entry, "observe_only", False)),
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["PUT", "DELETE"])
def soft_delete_stock_from_watchlist(request, ts_code):
    try:
        if not ts_code:
            return Response({"error": "ts_code is required."}, status=400)
        user = request.user if request.user.is_authenticated else User.get_admin_user()

        if not user:
            return Response({"error": "Authentication required."}, status=401)
        result = UserWatchlist.disable_for_user_and_code(user, ts_code)
        if not result:
            return Response({"error": "Stock not found in watchlist."}, status=404)
        return Response(
            {"message": "Stock removed from watchlist.", "ts_code": ts_code}
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["POST"])
def mark_stock_as_hold(request, ts_code):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()

        if not ts_code:
            return Response({"error": "ts_code is required."}, status=400)
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        corporation = Corporation.objects.filter(ts_code=ts_code).first()
        # Θ╗ÿΦ«ñσ░åΦéíτÑ¿µ╖╗σèáσê░Φç¬ΘÇëΦéíσêùΦí¿∩╝êσªéµ₧£Σ╕ìσ£¿τÜäΦ»¥∩╝ë
        watchlist_entry, created = UserWatchlist.objects.get_or_create(
            user=user,
            ts_code=ts_code,
            defaults={
                "is_enabled": True,
                "name": getattr(corporation, "name", ""),
                "corporation": corporation,
                "observe_only": False,
            },
        )
        if corporation and not watchlist_entry.corporation_id:
            watchlist_entry.corporation = corporation
        if not (watchlist_entry.name or "").strip() and corporation:
            watchlist_entry.name = corporation.name
        if not watchlist_entry.is_enabled:
            watchlist_entry.is_enabled = True
        watchlist_entry.save(update_fields=["corporation", "name", "is_enabled"])
        result = UserWatchlist.set_stock_as_hold(user, ts_code)
        if not result:
            return Response({"error": "Failed to mark stock as hold."}, status=400)
        in_watchlist = True  # Since we just marked it as hold, it's in the watchlist
        return Response(
            {
                "message": "Stock marked as hold.",
                "ts_code": ts_code,
                "in_watchlist": True,
                "hold_position": True,
                "observe_status": bool(getattr(watchlist_entry, "observe_only", False)),
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["PUT", "DELETE"])
def unmark_stock_as_hold(request, ts_code):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()

        if not ts_code:
            return Response({"error": "ts_code is required."}, status=400)
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        updated = UserWatchlist.objects.filter(
            user=user, ts_code=ts_code, is_enabled=True
        ).update(hold_a_position=False)
        if not updated:
            return Response({"error": "Failed to unmark stock as hold."}, status=400)
        watchlist_entry = UserWatchlist.objects.filter(
            user=user, ts_code=ts_code, is_enabled=True
        ).first()
        return Response(
            {
                "message": "Stock unmarked as hold.",
                "ts_code": ts_code,
                "in_watchlist": bool(watchlist_entry),
                "hold_position": False,
                "observe_status": bool(watchlist_entry and watchlist_entry.observe_only),
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["POST"])
def mark_stock_as_observe(request, ts_code):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not ts_code:
            return Response({"error": "ts_code is required."}, status=400)
        if not user:
            return Response({"error": "Authentication required."}, status=401)

        corporation = Corporation.objects.filter(ts_code=ts_code).first()
        watchlist_entry, _created = UserWatchlist.objects.get_or_create(
            user=user,
            ts_code=ts_code,
            defaults={
                "is_enabled": True,
                "name": getattr(corporation, "name", ""),
                "corporation": corporation,
                "observe_only": True,
            },
        )

        if corporation and not watchlist_entry.corporation_id:
            watchlist_entry.corporation = corporation
        if not (watchlist_entry.name or "").strip() and corporation:
            watchlist_entry.name = corporation.name
        if not watchlist_entry.is_enabled:
            watchlist_entry.is_enabled = True
        watchlist_entry.observe_only = True
        watchlist_entry.save(update_fields=["corporation", "name", "is_enabled", "observe_only"])

        return Response(
            {
                "message": "Stock marked as observe.",
                "ts_code": ts_code,
                "in_watchlist": True,
                "hold_position": bool(watchlist_entry.hold_a_position),
                "observe_status": True,
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["PUT", "DELETE"])
def unmark_stock_as_observe(request, ts_code):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not ts_code:
            return Response({"error": "ts_code is required."}, status=400)
        if not user:
            return Response({"error": "Authentication required."}, status=401)

        updated = UserWatchlist.objects.filter(
            user=user, ts_code=ts_code, is_enabled=True
        ).update(observe_only=False)
        if not updated:
            return Response({"error": "Failed to unmark stock as observe."}, status=400)

        watchlist_entry = UserWatchlist.objects.filter(
            user=user, ts_code=ts_code, is_enabled=True
        ).first()
        hold_position = bool(watchlist_entry and watchlist_entry.hold_a_position)
        observe_status = bool(watchlist_entry and watchlist_entry.observe_only)
        in_watchlist = bool(watchlist_entry)

        return Response(
            {
                "message": "Stock unmarked as observe.",
                "ts_code": ts_code,
                "in_watchlist": in_watchlist,
                "hold_position": hold_position,
                "observe_status": observe_status,
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def check_watchlist_or_hold(request, ts_code):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        watchlist_entry = UserWatchlist.objects.filter(
            user=user, ts_code=ts_code, is_enabled=True
        ).first()
        hold_position = bool(watchlist_entry and watchlist_entry.hold_a_position)
        observe_status = bool(watchlist_entry and getattr(watchlist_entry, "observe_only", False))
        in_watchlist = bool(watchlist_entry)
        return Response(
            {
                "ts_code": ts_code,
                "in_watchlist": in_watchlist,
                "hold_position": hold_position,
                "observe_status": observe_status,
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_tags(request, ts_code):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        tags = UserStockTag.objects.filter(user=user, ts_code=ts_code, is_enabled=True)
        tag_list = [tag.tag for tag in tags]
        return Response({"ts_code": ts_code, "tags": tag_list})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["POST"])
def add_stock_tag(request, ts_code, tag):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        if not tag:
            return Response({"error": "Tag name is required."}, status=400)
        corporation = Corporation.objects.filter(ts_code=ts_code).first()
        tag_obj, created = UserStockTag.objects.get_or_create(
            user=user, ts_code=ts_code, corporation=corporation, tag=tag
        )
        if not created:
            return Response({"error": "Tag already exists."}, status=400)
        return Response(
            {"message": "Tag added successfully.", "ts_code": ts_code, "tag": tag}
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["DELETE"])
def delete_stock_tag(request, ts_code, tag):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        if not tag:
            return Response({"error": "Tag name is required."}, status=400)
        deleted = UserStockTag.objects.filter(
            user=user, ts_code=ts_code, tag=tag, is_enabled=True
        ).update(is_enabled=False)
        if not deleted:
            return Response({"error": "Tag not found."}, status=404)
        return Response(
            {
                "message": "Tag deleted successfully.",
                "ts_code": ts_code,
                "tag": tag,
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stocks_with_same_tag(request, ts_code):
    try:
        user = request.user if request.user.is_authenticated else User.get_admin_user()
        if not user:
            return Response({"error": "Authentication required."}, status=401)
        # Find all tags for the given ts_code
        tags = UserStockTag.objects.filter(user=user, ts_code=ts_code, is_enabled=True)
        tag_names = [tag.tag for tag in tags]
        if not tag_names:
            return Response({"error": "No tags found for given ts_code."}, status=404)
        # Find all stocks with any of these tags for the user
        related_tags = UserStockTag.objects.filter(
            user=user, tag__in=tag_names, is_enabled=True
        ).exclude(ts_code=ts_code)
        stocks = []
        for tag_obj in related_tags:
            corp = tag_obj.corporation
            corp_basic = getattr(
                getattr(tag_obj, "corporation", None), "basic_info", None
            )
            stock_info = {
                "ts_code": corp.ts_code,
                "name": corp.name,
                # "fullname": corp.fullname,
                # "enname": corp.enname,
                # "listdate": corp.list_date,
                # "cnspell": corp.cnspell,
                # "tag": tag_obj.tag,
            }
            if corp_basic and hasattr(corp_basic.get(), "to_dict_short"):
                stock_info["basic_info"] = corp_basic.get().to_dict_short()
            stocks.append(stock_info)
        return Response({"data": stocks, "tags": tag_names, "ts_code": ts_code})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_tushare_data(request, ts_code, data_type):
    try:
        data_type = str(data_type or "").upper()

        def _parse_ymd(value):
            text = str(value or "").strip()
            if not text:
                return None
            for fmt in ("%Y%m%d", "%Y-%m-%d"):
                try:
                    return datetime.datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
            return None

        def _report_type_from_date(value):
            parsed = _parse_ymd(value)
            if parsed is None:
                return "σ┐½"
            month_day = (parsed.month, parsed.day)
            if month_day == (3, 31):
                return "Q1"
            if month_day == (6, 30):
                return "H1"
            if month_day == (9, 30):
                return "Q3"
            if month_day == (12, 31):
                return "FY"
            return "σ┐½"

        start_date = _parse_ymd(request.query_params.get("start_date"))
        end_date = _parse_ymd(request.query_params.get("end_date"))
        report_type_raw = str(request.query_params.get("report_type", "ALL") or "ALL").strip().upper()
        history_mode = str(request.query_params.get("history", "0") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        try:
            history_limit = int(request.query_params.get("limit", 8))
        except (TypeError, ValueError):
            history_limit = 8
        history_limit = max(1, min(history_limit, 32))

        if report_type_raw in {"", "ALL", "A", "*"}:
            report_type_filter = "ALL"
        elif report_type_raw in {"Q1", "H1", "Q3", "FY"}:
            report_type_filter = report_type_raw
        elif report_type_raw in {"σ┐½", "EXP", "EXPRESS"}:
            report_type_filter = "σ┐½"
        else:
            report_type_filter = "ALL"

        if data_type == "HOLD":
            try:
                hold_limit = int(request.query_params.get("limit", 0))
            except (TypeError, ValueError):
                hold_limit = 0
            hold_limit = max(0, min(hold_limit, 3000))

            snapshot = get_stock_fund_holding_snapshot(ts_code, limit=hold_limit)
            rows = snapshot.get("rows", [])
            summary = snapshot.get("summary", {})
            return Response(
                {
                    "data": rows,
                    "meta": {
                        "ts_code": ts_code,
                        "data_type": data_type,
                        "count": len(rows),
                        "summary": summary,
                    },
                }
            )

        if data_type == "TOP10_FLOATHOLDERS":
            today = datetime.date.today()
            if end_date is None:
                end_date = today
            if start_date is None:
                start_date = today - datetime.timedelta(days=3650)

        if data_type == "CYQ_PERF":
            normalized_ts_code = str(ts_code or "").strip().upper()
            candidate_codes = [normalized_ts_code] if normalized_ts_code else []
            if re.fullmatch(r"\d{6}", normalized_ts_code):
                candidate_codes = [
                    f"{normalized_ts_code}.SH",
                    f"{normalized_ts_code}.SZ",
                    f"{normalized_ts_code}.BJ",
                    normalized_ts_code,
                ]

            cost_qs = StockCostHistory.objects.filter(ts_code__in=candidate_codes)
            if start_date is not None:
                cost_qs = cost_qs.filter(trade_date__gte=start_date)
            if end_date is not None:
                cost_qs = cost_qs.filter(trade_date__lte=end_date)

            latest_cost = (
                cost_qs.order_by("-trade_date")
                .values(
                    "ts_code",
                    "trade_date",
                    "his_low",
                    "his_high",
                    "cost_5pct",
                    "cost_15pct",
                    "cost_50pct",
                    "cost_85pct",
                    "cost_95pct",
                    "weight_avg",
                    "winner_rate",
                )
                .first()
            )

            if not latest_cost:
                return Response({"error": "No local cost data found."}, status=404)

            trade_date = latest_cost.get("trade_date")
            if hasattr(trade_date, "strftime"):
                latest_cost["trade_date"] = trade_date.strftime("%Y-%m-%d")

            return Response(
                {
                    "data": latest_cost,
                    "meta": {
                        "ts_code": latest_cost.get("ts_code") or normalized_ts_code,
                        "data_type": data_type,
                        "source": "local_cost",
                    },
                }
            )

        # Call the Tushare API or your data fetching logic here
        df = fetch_tushare_data(ts_code, data_type, start_date=start_date, end_date=end_date)
        if df.empty:
            # Calculate previous workday's date
            prev_workday = datetime.date.today() - BDay(1)
            # Pass start/end date to fetch_tushare_data
            df = fetch_tushare_data(
                ts_code, data_type, start_date=prev_workday, end_date=prev_workday
            )
            if df.empty:
                return Response({"error": "No data found."}, status=404)
        # Define fields to include based on data_type
        fields_map = {
            "INDEX_DAILY": [
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
                "vol",
                "amount",
            ],
            "INDEX_DAILYBASIC": [
                "ts_code",
                "trade_date",
                "pe",
                "pe_ttm",
                "pb",
                "turnover_rate",
                "total_mv",
                "float_mv",
            ],
            "CYQ_PERF": [
                "ts_code",
                "trade_date",
                "his_low",
                "his_high",
                "cost_5pct",
                "cost_15pct",
                "cost_50pct",
                "cost_85pct",
                "cost_95pct",
                "weight_avg",
                "winner_rate",
            ],
            "CYQ_CHIPS": [
                "ts_code",
                "trade_date",
                "price",
                "percent",
            ],
            "INDICATOR": [
                "ts_code",
                "end_date",
                "eps",
                "total_revenue_ps",
                "revenue_ps",
                "undist_profit_ps",
                "gross_margin",
                # "inv_turn",
                "ar_turn",
                # "daa",
                "ebit",
                "ebitda",
                "fcff",
                "interestdebt",
                "netprofit_margin",
                "grossprofit_margin",
                "roe",
                "roe_dt",
                "debt_to_assets",
                "ca_to_assets",
                # "q_eps",
                "or_yoy",
                # "q_sales_yoy",
                # "q_sales_qoq",
                # "q_op_yoy",
                "q_op_qoq",
                "netprofit_yoy",
                "dt_netprofit_yoy",
            ],
            "PROFIT_FORECAST": [
                "ts_code",
                "trade_date",
                "report_date",
                "op_rt",
                "op_pr",
                "tp",
                "np",
                "eps",
                "pe",
                "rd",
                "roe",
                "ev_ebitda",
                "rating",
                "max_price",
                "min_price",
                "imp_dg",
            ],
            "TOP10_FLOATHOLDERS": [
                "ts_code",
                "end_date",
                "ann_date",
                "holder_name",
                "hold_amount",
                "hold_ratio",
            ],
            "FUND": [
                "ts_code",
                "end_date",
                "mkv",
                "amount",
                "stk_mkv_ratio",
                "stk_float_ratio",
            ],
            # Add more mappings as needed
        }
        # For INDICATOR type, scale specific fields
        if data_type == "INDICATOR" and not df.empty:
            for field in ["fcff", "gross_margin", "ebit", "ebitda", "interestdebt"]:
                if field in df.columns:
                    df[field] = df[field].apply(
                        lambda x: round(x / 1_000_000, 2) if pd.notnull(x) else x
                    )

        fields = fields_map.get(data_type, [])
        # Only keep the fields defined in fields_map for the given data_type
        df = df[fields] if fields and all(f in df.columns for f in fields) else df

        if report_type_filter != "ALL" and data_type in {"INDICATOR", "TOP10_FLOATHOLDERS", "CYQ_PERF"}:
            date_field = "end_date" if "end_date" in df.columns else "trade_date" if "trade_date" in df.columns else None
            if date_field is not None and not df.empty:
                df = df[df[date_field].apply(lambda value: _report_type_from_date(value) == report_type_filter)]

        if history_mode and data_type == "INDICATOR":
            if df.empty:
                return Response(
                    {
                        "data": [],
                        "meta": {
                            "history": True,
                            "count": 0,
                            "limit": history_limit,
                            "report_type": report_type_filter,
                        },
                    }
                )

            history_df = df.copy()
            if "end_date" not in history_df.columns:
                return Response(
                    {
                        "data": [],
                        "meta": {
                            "history": True,
                            "count": 0,
                            "limit": history_limit,
                            "report_type": report_type_filter,
                        },
                    }
                )

            history_df["end_date"] = history_df["end_date"].astype(str)
            history_df = history_df.dropna(subset=["end_date"]).copy()
            history_df = history_df.sort_values("end_date", ascending=False).drop_duplicates(subset=["end_date"], keep="first")

            records = []
            for row in history_df.to_dict(orient="records"):
                cleaned = {
                    key: (None if pd.isnull(value) else value)
                    for key, value in row.items()
                }
                cleaned["report_type"] = _report_type_from_date(cleaned.get("end_date"))
                records.append(cleaned)
                if len(records) >= history_limit:
                    break

            return Response(
                {
                    "data": records,
                    "meta": {
                        "history": True,
                        "count": len(records),
                        "limit": history_limit,
                        "report_type": report_type_filter,
                    },
                }
            )

        if data_type == "TOP10_FLOATHOLDERS":
            if df.empty:
                return Response({"error": "No data found."}, status=404)

            report_df = df.copy()
            if "end_date" in report_df.columns:
                report_df["end_date"] = report_df["end_date"].astype(str)
                latest_end_date = sorted(report_df["end_date"].dropna().unique(), reverse=True)[0]
                report_df = report_df[report_df["end_date"] == latest_end_date]
            else:
                latest_end_date = None

            latest_ann_date = None
            if "ann_date" in report_df.columns:
                report_df["ann_date"] = report_df["ann_date"].astype(str)
                ann_candidates = sorted(report_df["ann_date"].dropna().unique(), reverse=True)
                if ann_candidates:
                    latest_ann_date = ann_candidates[0]
                    report_df = report_df[report_df["ann_date"] == latest_ann_date]

            if "hold_amount" in report_df.columns:
                report_df["hold_amount"] = pd.to_numeric(report_df["hold_amount"], errors="coerce")
            if "hold_ratio" in report_df.columns:
                report_df["hold_ratio"] = pd.to_numeric(report_df["hold_ratio"], errors="coerce")

            if "hold_amount" in report_df.columns:
                report_df = report_df.sort_values("hold_amount", ascending=False)

            top_df = report_df.head(10).copy()
            total_hold_amount = float(top_df["hold_amount"].fillna(0).sum()) if "hold_amount" in top_df.columns else 0.0
            total_hold_ratio = float(top_df["hold_ratio"].fillna(0).sum()) if "hold_ratio" in top_df.columns else 0.0

            payload = {
                "ts_code": ts_code,
                "end_date": latest_end_date,
                "ann_date": latest_ann_date,
                "holder_count": int(len(top_df.index)),
                "total_hold_amount": round(total_hold_amount, 2),
                "total_hold_ratio": round(total_hold_ratio, 2),
            }

            for idx, row in enumerate(top_df.to_dict(orient="records"), start=1):
                holder_name = row.get("holder_name") or f"ΦéíΣ╕£{idx}"
                hold_amount = row.get("hold_amount")
                hold_ratio = row.get("hold_ratio")
                amount_text = f"{float(hold_amount):,.2f}" if hold_amount is not None and pd.notnull(hold_amount) else "-"
                ratio_text = f"{float(hold_ratio):.2f}%" if hold_ratio is not None and pd.notnull(hold_ratio) else "-"
                payload[f"holder_{idx}"] = f"{holder_name} | {amount_text} | {ratio_text}"

            return Response({"data": payload})

        if data_type == "CYQ_CHIPS":
            if "price" in df.columns:
                df["price"] = pd.to_numeric(df["price"], errors="coerce")
            if "percent" in df.columns:
                df["percent"] = pd.to_numeric(df["percent"], errors="coerce")
            df = df.dropna(subset=["price", "percent"]).copy()
            if "trade_date" in df.columns:
                df["trade_date"] = df["trade_date"].astype(str)
            df = df.sort_values(["trade_date", "price"], ascending=[False, False])
            records = df.to_dict(orient="records")
            return Response(
                {
                    "data": records,
                    "meta": {
                        "ts_code": ts_code,
                        "data_type": data_type,
                        "count": len(records),
                    },
                }
            )

        if data_type == "INDEX_DAILY":
            if df.empty:
                return Response({"error": "No data found."}, status=404)
            records_df = df.copy()
            if "trade_date" in records_df.columns:
                records_df["trade_date"] = records_df["trade_date"].astype(str)
                records_df = records_df.sort_values("trade_date", ascending=True)
            for metric_col in ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]:
                if metric_col in records_df.columns:
                    records_df[metric_col] = pd.to_numeric(records_df[metric_col], errors="coerce")
            records = records_df.to_dict(orient="records")
            return Response(
                {
                    "data": records,
                    "meta": {
                        "ts_code": ts_code,
                        "data_type": data_type,
                        "count": len(records),
                    },
                }
            )

        if data_type == "INDEX_DAILYBASIC":
            if df.empty:
                return Response({"error": "No data found."}, status=404)
            records_df = df.copy()
            if "trade_date" in records_df.columns:
                records_df["trade_date"] = records_df["trade_date"].astype(str)
                records_df = records_df.sort_values("trade_date", ascending=True)
            for metric_col in ["pe", "pe_ttm", "pb", "turnover_rate", "total_mv", "float_mv"]:
                if metric_col in records_df.columns:
                    records_df[metric_col] = pd.to_numeric(records_df[metric_col], errors="coerce")
            records = records_df.to_dict(orient="records")
            return Response(
                {
                    "data": records,
                    "meta": {
                        "ts_code": ts_code,
                        "data_type": data_type,
                        "count": len(records),
                    },
                }
            )

        latest_rec = (
            df.iloc[0].replace({float("nan"): "n/a"}).to_dict() if not df.empty else {}
        )
        return Response({"data": latest_rec})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_valuation_methods(request, ts_code):
    """Return latest valuation prices by method for a single stock."""

    try:
        market = (request.query_params.get("market") or "CN").strip() or "CN"
        freq = (request.query_params.get("freq") or "D").strip().upper() or "D"
        valuation_report_type_raw = (
            request.query_params.get("earnings_report_type")
            or request.query_params.get("valuation_report_type")
        )
        valuation_report_type_text = str(valuation_report_type_raw or "").strip().upper()
        express_only = valuation_report_type_text in {"EXP", "EXPRESS", "σ┐½"}
        fusion_only = valuation_report_type_text == "FUSION"
        valuation_report_type = _normalize_valuation_profit_report_type(
            valuation_report_type_raw
        )
        valuation_report_end_date = _resolve_valuation_report_end_date(
            valuation_report_type,
            explicit_value=request.query_params.get("valuation_report_end_date"),
            fiscal_year_value=request.query_params.get("valuation_fiscal_year")
            or request.query_params.get("target_fiscal_year"),
        )
        band_pct = _parse_optional_float(
            request.query_params.get("valuation_band_pct"),
            default=0.1,
        )
        if band_pct is None:
            band_pct = 0.1

        trading_row = (
            StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
            .order_by("-trade_date")
            .values("trade_date", "close_qfq", "close")
            .first()
        )
        current_price = None
        current_trade_date = None
        if trading_row:
            current_trade_date = trading_row.get("trade_date")
            current_price = trading_row.get("close_qfq") or trading_row.get("close")
        current_total_share_shares, current_total_share_trade_date = _load_latest_total_share_shares(
            ts_code,
            freq=freq,
            max_trade_date=current_trade_date,
        )
        if current_trade_date is None and current_total_share_trade_date is not None:
            current_trade_date = current_total_share_trade_date

        latest_formal_report_type, latest_formal_report_end_date = _resolve_latest_report_meta_from_feature_panel(
            ts_code=ts_code,
            asof_date=current_trade_date,
        )

        if valuation_report_type and not express_only and valuation_report_end_date is None:
            valuation_report_end_date = _resolve_valuation_report_end_date_from_snapshot_latest(
                ts_code=ts_code,
                report_type=valuation_report_type,
                market=market,
                asof_date=current_trade_date,
            )
            if valuation_report_end_date is None:
                valuation_report_end_date = _resolve_valuation_report_end_date_from_feature_panel(
                    ts_code=ts_code,
                    report_type=valuation_report_type,
                    asof_date=current_trade_date,
                )

        if valuation_report_type or express_only or fusion_only:
            snapshot_qs = StockValuationSnapshot.objects.filter(
                ts_code=ts_code,
                market=market,
            )
            if express_only:
                snapshot_qs = snapshot_qs.filter(profit_data_source__startswith="express")
            elif fusion_only:
                snapshot_qs = snapshot_qs.filter(profit_data_source="express_vip_blended")
            else:
                snapshot_qs = snapshot_qs.filter(profit_report_type=valuation_report_type)
            if not express_only and not fusion_only and valuation_report_end_date is not None:
                snapshot_qs = snapshot_qs.filter(profit_report_end_date=valuation_report_end_date)
            snapshot_rows = list(
                snapshot_qs.order_by("valuation_variant", "valuation_method", "-trade_date", "-updated_at").values(
                    "valuation_method",
                    "valuation_variant",
                    "valuation_price",
                    "valuation_market_cap",
                    "source",
                    "trade_date",
                    "profit_data_source",
                    "profit_report_end_date",
                    "profit_report_ann_date",
                    "profit_report_type",
                    "industry_level",
                    "industry_code",
                    "industry_name",
                    "compare_group",
                    "match_score",
                )
            )
            snapshots = []
            seen_snapshot_keys = set()
            for row in snapshot_rows:
                method = _normalize_valuation_method_name(row.get("valuation_method"))
                variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
                snapshot_key = (variant, method)
                if not method or snapshot_key in seen_snapshot_keys:
                    continue
                seen_snapshot_keys.add(snapshot_key)
                mapped = dict(row)
                mapped["latest_trade_date"] = row.get("trade_date")
                snapshots.append(mapped)
        else:
            snapshots = list(
                StockValuationSnapshotLatest.objects.filter(ts_code=ts_code, market=market)
                .order_by("valuation_variant", "valuation_method", "-updated_at")
                .values(
                    "valuation_method",
                    "valuation_variant",
                    "valuation_price",
                    "valuation_market_cap",
                    "source",
                    "latest_trade_date",
                    "profit_data_source",
                    "profit_report_end_date",
                    "profit_report_ann_date",
                    "profit_report_type",
                    "industry_level",
                    "industry_code",
                    "industry_name",
                    "compare_group",
                    "match_score",
                )
            )

        method_order = {
            m: idx
            for idx, m in enumerate(
                [
                    "recommended",
                    "scarcity_overlay",
                    "market_style",
                    "sw_history",
                    "pe",
                    "pb",
                    "ps",
                    "peg",
                    "fcff_dcf",
                    "ddm",
                    "market_cap",
                ]
            )
        }

        data_by_variant = {}
        valuation_variants = []
        active_variant = "default"

        if snapshots:
            method_map_by_variant = {}
            variant_meta = {}
            for row in snapshots:
                method = _normalize_valuation_method_name(row.get("valuation_method"))
                if not method:
                    continue

                variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
                method_map = method_map_by_variant.setdefault(variant, {})
                if method in method_map:
                    continue

                valuation_price = row.get("valuation_price")
                valuation_price = float(valuation_price) if valuation_price is not None else None
                status, gap_pct = _classify_valuation(current_price, valuation_price, band_pct)
                normalized_report_end_date, normalized_report_ann_date = _normalize_report_dates(
                    row.get("profit_report_end_date"),
                    row.get("profit_report_ann_date"),
                )
                method_map[method] = {
                    "valuation_method": method,
                    "valuation_variant": variant,
                    "valuation_price": round(valuation_price, 4) if valuation_price is not None else None,
                    "valuation_market_cap": float(row.get("valuation_market_cap")) if row.get("valuation_market_cap") is not None else None,
                    "valuation_status": status,
                    "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
                    "source": row.get("source"),
                    "latest_trade_date": row.get("latest_trade_date"),
                    "profit_data_source": row.get("profit_data_source"),
                    "profit_report_end_date": normalized_report_end_date,
                    "profit_report_ann_date": normalized_report_ann_date,
                    "profit_report_type": row.get("profit_report_type"),
                    "industry_level": row.get("industry_level"),
                    "industry_code": row.get("industry_code"),
                    "industry_name": row.get("industry_name"),
                    "compare_group": row.get("compare_group"),
                    "match_score": float(row.get("match_score")) if row.get("match_score") is not None else None,
                }

                meta = variant_meta.setdefault(
                    variant,
                    {
                        "valuation_variant": variant,
                        "industry_level": row.get("industry_level"),
                        "industry_code": row.get("industry_code"),
                        "industry_name": row.get("industry_name"),
                        "compare_group": row.get("compare_group"),
                        "max_match_score": None,
                    },
                )
                if meta.get("industry_name") in (None, "") and row.get("industry_name"):
                    meta["industry_name"] = row.get("industry_name")
                if meta.get("industry_code") in (None, "") and row.get("industry_code"):
                    meta["industry_code"] = row.get("industry_code")
                if meta.get("industry_level") in (None, "") and row.get("industry_level"):
                    meta["industry_level"] = row.get("industry_level")
                if meta.get("compare_group") in (None, "") and row.get("compare_group"):
                    meta["compare_group"] = row.get("compare_group")

                match_score = row.get("match_score")
                if match_score is not None:
                    score = float(match_score)
                    if meta.get("max_match_score") is None or score > meta.get("max_match_score"):
                        meta["max_match_score"] = score

            for variant, method_map in method_map_by_variant.items():
                rows_for_variant = list(method_map.values())
                rows_for_variant.sort(key=lambda item: method_order.get(item.get("valuation_method"), 999))
                data_by_variant[variant] = rows_for_variant

            def _variant_sort_key(meta):
                variant = str(meta.get("valuation_variant") or "")
                compare_group = str(meta.get("compare_group") or "")
                score = meta.get("max_match_score")
                if score is None:
                    score = -1e9
                if compare_group == "sw_l3_baseline":
                    group_rank = 0
                elif compare_group == "business_match":
                    group_rank = 1
                elif variant == "default":
                    group_rank = 2
                else:
                    group_rank = 3
                return (group_rank, -float(score), variant)

            for meta in sorted(variant_meta.values(), key=_variant_sort_key):
                variant = meta.get("valuation_variant")
                if variant not in data_by_variant:
                    continue
                label = "Θ╗ÿΦ«ñΣ╝░σÇ╝"
                if variant != "default":
                    if meta.get("industry_name"):
                        label = str(meta.get("industry_name"))
                    elif meta.get("industry_code"):
                        label = str(meta.get("industry_code"))
                    else:
                        label = variant

                valuation_variants.append(
                    {
                        "valuation_variant": variant,
                        "label": label,
                        "industry_level": meta.get("industry_level"),
                        "industry_code": meta.get("industry_code"),
                        "industry_name": meta.get("industry_name"),
                        "compare_group": meta.get("compare_group"),
                        "match_score": round(float(meta.get("max_match_score")), 4)
                        if meta.get("max_match_score") is not None
                        else None,
                        "method_count": len(data_by_variant.get(variant) or []),
                    }
                )

            requested_variant = _normalize_valuation_variant(
                request.query_params.get("valuation_variant"),
                fallback="",
            )
            if requested_variant and requested_variant in data_by_variant:
                active_variant = requested_variant
            elif valuation_variants:
                # Keep default variant selection aligned with market_style logic:
                # allow strong business-match variants when they are much closer
                # to current price than SW baseline.
                active_variant = valuation_variants[0].get("valuation_variant")

                sw_candidate = next(
                    (item for item in valuation_variants if item.get("compare_group") == "sw_l3_baseline"),
                    None,
                )
                business_candidate = None
                business_pool = [
                    item for item in valuation_variants
                    if item.get("compare_group") == "business_match"
                ]
                if business_pool:
                    business_candidate = sorted(
                        business_pool,
                        key=lambda item: -(float(item.get("match_score") or 0.0)),
                    )[0]

                if sw_candidate and business_candidate:
                    sw_variant = sw_candidate.get("valuation_variant")
                    business_variant = business_candidate.get("valuation_variant")
                    sw_summary = _build_valuation_summary_payload(
                        current_price,
                        data_by_variant.get(sw_variant, []),
                        band_pct,
                    )
                    business_summary = _build_valuation_summary_payload(
                        current_price,
                        data_by_variant.get(business_variant, []),
                        band_pct,
                    )
                    sw_composite = _parse_optional_float(sw_summary.get("composite_valuation_price"), default=None)
                    business_composite = _parse_optional_float(
                        business_summary.get("composite_valuation_price"),
                        default=None,
                    )
                    current_price_float = _parse_optional_float(current_price, default=None)
                    business_score = float(business_candidate.get("match_score") or 0.0)

                    if (
                        current_price_float not in (None, 0)
                        and sw_composite is not None
                        and business_composite is not None
                    ):
                        sw_gap = abs(sw_composite - current_price_float) / abs(current_price_float)
                        business_gap = abs(business_composite - current_price_float) / abs(current_price_float)
                        if business_score >= 20.0 and business_gap <= (sw_gap - 0.08):
                            active_variant = business_variant
            elif "default" in data_by_variant:
                active_variant = "default"
            else:
                active_variant = "default"

            rows = data_by_variant.get(active_variant, [])
        else:
            rows = []

        if not rows and not express_only and not fusion_only:
            trade_date_arg = None
            if current_trade_date is not None:
                trade_date_arg = current_trade_date.strftime("%Y-%m-%d")

            valuation_result = test_valuation(
                ts_code=ts_code,
                trade_date=trade_date_arg,
                forced_report_end_date=valuation_report_end_date,
                allow_express_adjustment=False,
                prefer_sw_history_targets=True,
            )
            valuation_df = valuation_result.get("valuations")
            valuation_snapshot = valuation_result.get("snapshot") or {}
            fallback_report_end_source = (
                valuation_snapshot.get("profit_report_end_date")
                or valuation_snapshot.get("end_date")
                or valuation_report_end_date
            )
            fallback_report_end_date, fallback_report_ann_date = _normalize_report_dates(
                fallback_report_end_source,
                valuation_snapshot.get("profit_report_ann_date"),
            )
            fallback_profit_report_type = valuation_snapshot.get("profit_report_type") or valuation_report_type
            fallback_profit_data_source = valuation_snapshot.get("profit_data_source")
            fallback_methods = ["scarcity_overlay", "sw_history", "pe", "pb", "ps", "peg", "fcff_dcf", "ddm"]
            for method in fallback_methods:
                method_rows = _extract_method_valuation_rows(valuation_df, method)
                if not method_rows:
                    continue
                selected = _select_valuation_candidate(method_rows, "baseline", asof_date=current_trade_date)
                valuation_price = selected.get("implied_price")
                if valuation_price is None:
                    continue
                status, gap_pct = _classify_valuation(current_price, valuation_price, band_pct)
                rows.append(
                    {
                        "valuation_method": _normalize_valuation_method_name(selected.get("method") or method),
                        "valuation_variant": "default",
                        "valuation_price": round(float(valuation_price), 4),
                        "valuation_market_cap": round(float(selected.get("equity_value")), 2)
                        if selected.get("equity_value") is not None
                        else None,
                        "valuation_status": status,
                        "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
                        "source": "live_compute",
                        "latest_trade_date": current_trade_date,
                        "profit_data_source": fallback_profit_data_source,
                        "profit_report_end_date": fallback_report_end_date,
                        "profit_report_ann_date": fallback_report_ann_date,
                        "profit_report_type": fallback_profit_report_type,
                        "industry_level": None,
                        "industry_code": None,
                        "industry_name": None,
                        "compare_group": None,
                        "match_score": None,
                    }
                )

            rows.sort(key=lambda item: method_order.get(item.get("valuation_method"), 999))
            data_by_variant = {"default": rows}
            valuation_variants = [
                {
                    "valuation_variant": "default",
                    "label": "Θ╗ÿΦ«ñΣ╝░σÇ╝",
                    "industry_level": None,
                    "industry_code": None,
                    "industry_name": None,
                    "compare_group": None,
                    "match_score": None,
                    "method_count": len(rows),
                }
            ]
            active_variant = "default"

        rows.sort(key=lambda item: method_order.get(item.get("valuation_method"), 999))

        for variant, variant_rows in data_by_variant.items():
            data_by_variant[variant] = _enrich_rows_with_share_basis(
                ts_code=ts_code,
                current_trade_date=current_trade_date,
                current_total_share_shares=current_total_share_shares,
                current_price=current_price,
                band_pct=band_pct,
                rows=variant_rows,
            )
        rows = data_by_variant.get(active_variant, rows)

        has_scarcity_overlay = any(
            _normalize_valuation_method_name(item.get("valuation_method")) == "scarcity_overlay"
            for item in rows
        )
        if not has_scarcity_overlay and not valuation_report_type and not fusion_only:
            trade_date_arg = None
            if current_trade_date is not None:
                trade_date_arg = current_trade_date.strftime("%Y-%m-%d")
            try:
                scarcity_result = test_valuation(
                    ts_code=ts_code,
                    trade_date=trade_date_arg,
                )
                scarcity_df = scarcity_result.get("valuations")
                scarcity_rows = _extract_method_valuation_rows(scarcity_df, "scarcity_overlay")
                selected_scarcity = _select_valuation_candidate(scarcity_rows, "baseline", asof_date=current_trade_date)
                scarcity_price = selected_scarcity.get("implied_price") if selected_scarcity else None
                if scarcity_price is not None:
                    status, gap_pct = _classify_valuation(current_price, scarcity_price, band_pct)
                    scarcity_row = {
                        "valuation_method": "scarcity_overlay",
                        "valuation_variant": active_variant,
                        "valuation_price": round(float(scarcity_price), 4),
                        "valuation_market_cap": round(float(selected_scarcity.get("equity_value")), 2)
                        if selected_scarcity.get("equity_value") is not None
                        else None,
                        "valuation_status": status,
                        "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
                        "source": "live_compute",
                        "latest_trade_date": current_trade_date,
                        "industry_level": None,
                        "industry_code": None,
                        "industry_name": None,
                        "compare_group": None,
                        "match_score": None,
                    }
                    rows.append(scarcity_row)
                    rows.sort(key=lambda item: method_order.get(item.get("valuation_method"), 999))
                    if active_variant in data_by_variant:
                        updated_variant_rows = list(data_by_variant.get(active_variant) or [])
                        updated_variant_rows.append(scarcity_row)
                        updated_variant_rows.sort(
                            key=lambda item: method_order.get(item.get("valuation_method"), 999)
                        )
                        data_by_variant[active_variant] = updated_variant_rows
            except Exception:
                pass

        market_style_allow_fallback_inference = not (valuation_report_type or express_only or fusion_only or valuation_report_end_date is not None)
        market_style_snapshot = None
        if market_style_allow_fallback_inference and current_trade_date is not None:
            try:
                trade_date_text = current_trade_date.strftime("%Y-%m-%d") if hasattr(current_trade_date, "strftime") else str(current_trade_date)
                market_style_snapshot = get_stock_valuation_snapshot(ts_code=ts_code, trade_date=trade_date_text)
            except Exception:
                market_style_snapshot = None
        market_style_price_series = (
            _load_market_style_price_series(ts_code=ts_code, freq=freq, trade_date=current_trade_date)
            if market_style_allow_fallback_inference
            else []
        )

        summary_by_variant = {}
        summary_by_variant_normalized = {}
        market_style_by_variant = {}
        market_style_by_variant_normalized = {}
        for variant, variant_rows in data_by_variant.items():
            anchor_row = (variant_rows or [{}])[0] if variant_rows else {}
            market_style_payload = _build_market_style_payload_for_variant(
                variant=variant,
                variant_rows=variant_rows,
                current_price=current_price,
                band_pct=band_pct,
                stock_snapshot=market_style_snapshot,
                price_series=market_style_price_series,
                allow_fallback=market_style_allow_fallback_inference,
                price_key="valuation_price",
            )
            market_style_payload_normalized = _build_market_style_payload_for_variant(
                variant=variant,
                variant_rows=variant_rows,
                current_price=current_price,
                band_pct=band_pct,
                stock_snapshot=market_style_snapshot,
                price_series=market_style_price_series,
                allow_fallback=market_style_allow_fallback_inference,
                price_key="valuation_price_normalized_to_latest_share",
            )
            market_style_by_variant[variant] = market_style_payload
            market_style_by_variant_normalized[variant] = market_style_payload_normalized
            persisted_summary_payload = None
            if LIVE_VALUATION_SUMMARY_USE_PERSISTED_FIRST:
                persisted_summary_payload = _load_persisted_variant_summary_payload(
                    ts_code=ts_code,
                    market=market,
                    valuation_variant=variant,
                    trade_date=anchor_row.get("latest_trade_date") or current_trade_date,
                    profit_report_type=anchor_row.get("profit_report_type") or valuation_report_type,
                    profit_report_end_date=anchor_row.get("profit_report_end_date"),
                )
            base_summary_payload = persisted_summary_payload or _build_valuation_summary_payload(
                current_price,
                variant_rows,
                band_pct,
                ts_code=ts_code,
                freq=freq,
            )
            base_summary_payload = _hydrate_summary_gap_fields(
                base_summary_payload,
                current_price=current_price,
                rows=variant_rows,
                band_pct=band_pct,
                ts_code=ts_code,
                freq=freq,
            )
            summary_by_variant[variant] = _merge_summary_with_market_style(
                base_summary_payload,
                market_style_payload,
            )
            summary_by_variant_normalized[variant] = _merge_summary_with_market_style(
                _build_valuation_summary_payload(
                    current_price,
                    variant_rows,
                    band_pct,
                    price_key="valuation_price_normalized_to_latest_share",
                    ts_code=ts_code,
                    freq=freq,
                ),
                market_style_payload_normalized,
            )

        indicator_profile = _load_latest_indicator_profile(ts_code)

        valuation_risk_by_variant = {}
        summary_by_variant_optimized = {}
        summary_by_variant_normalized_optimized = {}
        for variant, variant_rows in data_by_variant.items():
            anchor_row = (variant_rows or [{}])[0] if variant_rows else {}
            risk_payload = None
            if LIVE_VALUATION_RISK_USE_PERSISTED_FIRST:
                risk_payload = _load_persisted_valuation_risk_payload(
                    ts_code=ts_code,
                    market=market,
                    valuation_variant=variant,
                    profit_report_type=anchor_row.get('profit_report_type') or valuation_report_type,
                    trade_date=anchor_row.get('latest_trade_date') or current_trade_date,
                )
            if risk_payload is None:
                risk_payload = build_valuation_risk_payload(
                    ts_code=ts_code,
                    market=market,
                    trade_date=current_trade_date,
                    valuation_variant=variant,
                    profit_report_type=anchor_row.get('profit_report_type') or valuation_report_type,
                    profit_report_end_date=anchor_row.get('profit_report_end_date'),
                    profit_report_ann_date=anchor_row.get('profit_report_ann_date'),
                    profit_data_source=anchor_row.get('profit_data_source'),
                    current_price=current_price,
                    rows=variant_rows,
                    summary=summary_by_variant.get(variant) or {},
                    financial_profile=indicator_profile,
                    base_band_pct=band_pct,
                )
            valuation_risk_by_variant[variant] = risk_payload

        for variant, variant_rows in data_by_variant.items():
            summary_by_variant_optimized[variant] = _build_traditional_summary_optimized(
                summary_by_variant.get(variant) or {},
                variant_rows=variant_rows,
                current_price=current_price,
                band_pct=band_pct,
                risk_payload=valuation_risk_by_variant.get(variant) or {},
                stats_price_key="valuation_price",
            )
            summary_by_variant_normalized_optimized[variant] = _build_traditional_summary_optimized(
                summary_by_variant_normalized.get(variant) or {},
                variant_rows=variant_rows,
                current_price=current_price,
                band_pct=band_pct,
                risk_payload=valuation_risk_by_variant.get(variant) or {},
                stats_price_key="valuation_price_normalized_to_latest_share",
            )

        summary_payload = summary_by_variant.get(active_variant) or _build_valuation_summary_payload(
            current_price,
            rows,
            band_pct,
            ts_code=ts_code,
            freq=freq,
        )
        summary_payload = dict(summary_payload or {})
        summary_report_end_date = next(
            (
                item.get("profit_report_end_date")
                for item in (rows or [])
                if isinstance(item, dict) and item.get("profit_report_end_date")
            ),
            None,
        )
        summary_payload["summary_mode"] = "single_variant_strict"
        summary_payload["summary_variant"] = active_variant
        summary_payload["summary_report_end_date"] = summary_report_end_date
        normalized_summary_payload = summary_by_variant_normalized.get(active_variant) or _build_valuation_summary_payload(
            current_price,
            rows,
            band_pct,
            price_key="valuation_price_normalized_to_latest_share",
            ts_code=ts_code,
            freq=freq,
        )
        optimized_summary_payload = summary_by_variant_optimized.get(active_variant) or _build_traditional_summary_optimized(
            summary_payload,
            variant_rows=rows,
            current_price=current_price,
            band_pct=band_pct,
            risk_payload=valuation_risk_by_variant.get(active_variant) or {},
            stats_price_key="valuation_price",
        )
        optimized_normalized_summary_payload = summary_by_variant_normalized_optimized.get(active_variant) or _build_traditional_summary_optimized(
            normalized_summary_payload,
            variant_rows=rows,
            current_price=current_price,
            band_pct=band_pct,
            risk_payload=valuation_risk_by_variant.get(active_variant) or {},
            stats_price_key="valuation_price_normalized_to_latest_share",
        )
        valuation_risk_payload = valuation_risk_by_variant.get(active_variant) or build_valuation_risk_payload(
            ts_code=ts_code,
            market=market,
            trade_date=current_trade_date,
            valuation_variant=active_variant,
            profit_report_type=valuation_report_type,
            current_price=current_price,
            rows=rows,
            summary=summary_payload,
            financial_profile=indicator_profile,
            base_band_pct=band_pct,
        )

        variant_meta_map = {
            str(item.get("valuation_variant") or ""): item
            for item in (valuation_variants or [])
            if isinstance(item, dict)
        }
        traditional_tiered_template_by_variant = {}
        for variant, variant_rows in (data_by_variant or {}).items():
            variant_meta = variant_meta_map.get(str(variant or ""), {})
            variant_industry_name = (
                (variant_meta or {}).get("industry_name")
                or ((variant_rows or [{}])[0] or {}).get("industry_name")
                or (variant_meta or {}).get("label")
                or "Θ╗ÿΦ«ñΣ╝░σÇ╝"
            )
            variant_industry_code = (
                (variant_meta or {}).get("industry_code")
                or ((variant_rows or [{}])[0] or {}).get("industry_code")
                or None
            )
            template_payload = _build_traditional_tiered_template(
                variant_rows=variant_rows,
                summary_payload=summary_by_variant.get(variant) or {},
                current_price=current_price,
                industry_name=variant_industry_name,
                industry_code=variant_industry_code,
                indicator_profile=indicator_profile,
                ts_code=ts_code,
                freq=freq,
            )
            if template_payload:
                traditional_tiered_template_by_variant[variant] = template_payload

        traditional_tiered_template = _blend_traditional_tiered_template(
            traditional_tiered_template_by_variant=traditional_tiered_template_by_variant,
            valuation_variants=valuation_variants,
            active_variant=active_variant,
        ) or traditional_tiered_template_by_variant.get(active_variant)

        return Response(
            _sanitize_non_finite_numbers(
                {
                "ts_code": ts_code,
                "market": market,
                "freq": freq,
                "current_price": float(current_price) if current_price is not None else None,
                "current_trade_date": current_trade_date,
                "current_total_share": round(current_total_share_shares / 10000.0, 4)
                if current_total_share_shares is not None
                else None,
                "latest_formal_report_type": latest_formal_report_type or None,
                "latest_formal_report_end_date": latest_formal_report_end_date,
                "valuation_band_pct": band_pct,
                "valuation_report_type": valuation_report_type or None,
                "active_valuation_variant": active_variant,
                "valuation_variants": valuation_variants,
                "data_by_variant": data_by_variant,
                "summary": summary_payload,
                "summary_normalized_to_latest_share": normalized_summary_payload,
                "summary_optimized": optimized_summary_payload,
                "summary_normalized_to_latest_share_optimized": optimized_normalized_summary_payload,
                "summary_by_variant": summary_by_variant,
                "summary_by_variant_normalized_to_latest_share": summary_by_variant_normalized,
                "summary_by_variant_optimized": summary_by_variant_optimized,
                "summary_by_variant_normalized_to_latest_share_optimized": summary_by_variant_normalized_optimized,
                "market_style_by_variant": market_style_by_variant,
                "market_style_by_variant_normalized_to_latest_share": market_style_by_variant_normalized,
                "valuation_risk": valuation_risk_payload,
                "valuation_risk_by_variant": valuation_risk_by_variant,
                "traditional_tiered_template": traditional_tiered_template,
                "traditional_tiered_template_by_variant": traditional_tiered_template_by_variant,
                "data": rows,
                }
            )
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_market_index_simple_valuation(request):
    """Return simplified valuation summary for a market index."""

    try:
        raw_index_code = str(request.query_params.get("index_code") or "000001.SH").strip().upper()
        freq = str(request.query_params.get("freq") or "D").strip().upper() or "D"
        start_date = _parse_date_like(request.query_params.get("start_date"))
        if start_date is None:
            start_date = datetime.date(2004, 1, 1)

        band_pct = _parse_optional_float(
            request.query_params.get("band_pct"),
            default=0.1,
        )
        if band_pct is None:
            band_pct = 0.1

        index_code = str(raw_index_code or "").strip().upper()
        if not index_code:
            return Response({"error": "index_code is required"}, status=400)
        if "." not in index_code and re.fullmatch(r"\d{6}", index_code):
            index_code = _normalize_ts_code(index_code)
        def _build_index_code_candidates(input_code):
            raw = str(input_code or "").strip().upper()
            if not raw:
                return []
            candidates = [raw]
            if "." in raw:
                base, suffix = raw.split(".", 1)
                base = base.strip()
                suffix = suffix.strip().upper()
                if re.fullmatch(r"\d{6}", base):
                    candidates.append(base)
                    if suffix == "SH":
                        candidates.append(f"{base}.SZ")
                    elif suffix == "SZ":
                        candidates.append(f"{base}.SH")
            elif re.fullmatch(r"\d{6}", raw):
                candidates.extend([f"{raw}.SH", f"{raw}.SZ", f"{raw}.BJ"])

            seen = set()
            output = []
            for item in candidates:
                key = str(item or "").strip().upper()
                if not key or key in seen:
                    continue
                seen.add(key)
                output.append(key)
            return output

        def _load_latest_index_trade_close(input_code):
            for candidate in _build_index_code_candidates(input_code):
                latest_trade_row = (
                    StockTradingHistory.objects.filter(ts_code=candidate, freq=freq)
                    .order_by("-trade_date")
                    .values("trade_date", "close")
                    .first()
                )
                if not latest_trade_row:
                    continue
                trade_close = _to_float_or_none(latest_trade_row.get("close"))
                if trade_close is None or trade_close <= 0:
                    continue
                return candidate, float(trade_close), latest_trade_row.get("trade_date")
            return None, None, None

        def _load_index_dailybasic_from_earnings_table(input_code):
            table_name = getattr(
                settings,
                "VALUATION_MARKET_INDEX_DAILYBASIC_TABLE",
                "earnings_mkt_index_dailybasic",
            )
            start_date_text = start_date.strftime("%Y%m%d")
            for candidate in _build_index_code_candidates(input_code):
                try:
                    with connections["earnings"].cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT ts_code, trade_date, pe, pe_ttm, pb
                            FROM {table_name}
                            WHERE ts_code = %s AND trade_date >= %s
                            ORDER BY trade_date ASC
                            """,
                            [candidate, start_date_text],
                        )
                        rows = cur.fetchall()
                except Exception:
                    rows = []
                if not rows:
                    continue

                basic_table_df = pd.DataFrame(
                    rows,
                    columns=["ts_code", "trade_date", "pe", "pe_ttm", "pb"],
                )
                if basic_table_df.empty:
                    continue

                basic_table_df["trade_date"] = basic_table_df["trade_date"].astype(str)
                for metric_col in ["pe", "pe_ttm", "pb"]:
                    if metric_col in basic_table_df.columns:
                        basic_table_df[metric_col] = pd.to_numeric(
                            basic_table_df[metric_col], errors="coerce"
                        )

                latest_trade_date = str(basic_table_df.iloc[-1].get("trade_date") or "")
                return candidate, basic_table_df.sort_values("trade_date"), latest_trade_date

            return None, pd.DataFrame(), None
        basic_source_mode = "earnings_table_latest"
        basic_source_note = None
        basic_source_code, basic_df_from_table, latest_basic_table_trade_date = _load_index_dailybasic_from_earnings_table(index_code)
        if basic_df_from_table is not None and not basic_df_from_table.empty:
            basic_df = basic_df_from_table
            basic_source_note = f"Primary source earnings table INDEX_DAILYBASIC ({basic_source_code}) latest trade_date={latest_basic_table_trade_date}."
        else:
            realtime_basic_df = fetch_tushare_data(index_code, "INDEX_DAILYBASIC", start_date=start_date)
            if realtime_basic_df is not None and not realtime_basic_df.empty:
                basic_df = realtime_basic_df.copy()
                basic_source_mode = "tushare_realtime"
                basic_source_note = f"Earnings table missing local data for {index_code}; fallback to Tushare INDEX_DAILYBASIC."
            else:
                return Response({"error": f"No INDEX_DAILYBASIC data found for {index_code}."}, status=404)

        if "trade_date" not in basic_df.columns:
            return Response({"error": "INDEX_DAILYBASIC payload missing trade_date."}, status=500)

        basic_df["trade_date"] = basic_df["trade_date"].astype(str)
        for metric_col in ["pe", "pe_ttm", "pb"]:
            if metric_col in basic_df.columns:
                basic_df[metric_col] = pd.to_numeric(basic_df[metric_col], errors="coerce")
        basic_df = basic_df.sort_values("trade_date")

        current_price_mode = "trading_history_close"
        current_price_field = "close"
        current_price_source_table = "datastore_stocktradinghistory"
        price_mode_note = None
        resolved_trade_code, trade_close, trade_date = _load_latest_index_trade_close(index_code)
        if trade_close is not None and trade_close > 0:
            current_price = float(trade_close)
            asof_trade_date = _parse_date_like(trade_date)
            asof_trade_date_text = (
                asof_trade_date.strftime("%Y-%m-%d")
                if asof_trade_date is not None
                else str(trade_date or "")
            )
            price_mode_note = (
                f"Primary source StockTradingHistory close ({resolved_trade_code}) latest trade_date={asof_trade_date_text}."
            )
        else:
            daily_df = fetch_tushare_data(index_code, "INDEX_DAILY", start_date=start_date)
            if daily_df is None or daily_df.empty:
                current_price_mode = "relative_base_100"
                current_price_field = "relative_base_100"
                current_price_source_table = "synthetic"
                current_price = 100.0
                latest_basic_trade_date = str(basic_df.iloc[-1].get("trade_date") or "") if not basic_df.empty else ""
                asof_trade_date = _parse_date_like(latest_basic_trade_date)
                asof_trade_date_text = (
                    asof_trade_date.strftime("%Y-%m-%d")
                    if asof_trade_date is not None
                    else latest_basic_trade_date
                )
                price_mode_note = f"StockTradingHistory/INDEX_DAILY missing for {index_code}; fallback to relative base-100 mode."
            else:
                daily_df = daily_df.copy()
                if "trade_date" not in daily_df.columns or "close" not in daily_df.columns:
                    return Response({"error": "INDEX_DAILY payload missing trade_date/close."}, status=500)

                daily_df["trade_date"] = daily_df["trade_date"].astype(str)
                daily_df["close"] = pd.to_numeric(daily_df["close"], errors="coerce")
                daily_df = daily_df.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
                if daily_df.empty:
                    current_price_mode = "relative_base_100"
                    current_price_field = "relative_base_100"
                    current_price_source_table = "synthetic"
                    current_price = 100.0
                    latest_basic_trade_date = str(basic_df.iloc[-1].get("trade_date") or "") if not basic_df.empty else ""
                    asof_trade_date = _parse_date_like(latest_basic_trade_date)
                    asof_trade_date_text = (
                        asof_trade_date.strftime("%Y-%m-%d")
                        if asof_trade_date is not None
                        else latest_basic_trade_date
                    )
                    price_mode_note = f"StockTradingHistory/INDEX_DAILY invalid for {index_code}; fallback to relative base-100 mode."
                else:
                    latest_daily = daily_df.iloc[-1]
                    current_price = _to_float_or_none(latest_daily.get("close"))
                    if current_price is None or current_price <= 0:
                        current_price_mode = "relative_base_100"
                        current_price_field = "relative_base_100"
                        current_price_source_table = "synthetic"
                        current_price = 100.0
                        latest_basic_trade_date = str(basic_df.iloc[-1].get("trade_date") or "") if not basic_df.empty else ""
                        asof_trade_date = _parse_date_like(latest_basic_trade_date)
                        asof_trade_date_text = (
                            asof_trade_date.strftime("%Y-%m-%d")
                            if asof_trade_date is not None
                            else latest_basic_trade_date
                        )
                        price_mode_note = f"StockTradingHistory/INDEX_DAILY close invalid for {index_code}; fallback to relative base-100 mode."
                    else:
                        current_price_mode = "index_daily"
                        current_price_field = "close"
                        current_price_source_table = "tushare_index_daily"
                        asof_trade_date = _parse_date_like(latest_daily.get("trade_date"))
                        asof_trade_date_text = (
                            asof_trade_date.strftime("%Y-%m-%d")
                            if asof_trade_date is not None
                            else str(latest_daily.get("trade_date") or "")
                        )
                        price_mode_note = f"StockTradingHistory missing local data for {index_code}; fallback to INDEX_DAILY close."

        metric_defs = [
            ("pe", "pe"),
            ("pe_ttm", "pe_ttm"),
            ("pb", "pb"),
        ]
        composite_metric_quantile = 0.60
        conservative_metric_quantile = 0.25

        methods = []
        method_map_composite = {}
        method_map_conservative = {}
        for method_name, metric_col in metric_defs:
            if metric_col not in basic_df.columns:
                continue

            metric_series = pd.to_numeric(basic_df[metric_col], errors="coerce")
            valid_metric = basic_df.assign(_metric=metric_series).dropna(subset=["_metric"])
            valid_metric = valid_metric[valid_metric["_metric"] > 0]
            if valid_metric.empty:
                continue

            current_metric = _to_float_or_none(valid_metric.iloc[-1].get("_metric"))
            if current_metric is None or current_metric <= 0:
                continue

            metric_values = [
                float(val)
                for val in valid_metric["_metric"].tolist()
                if val is not None and float(val) > 0
            ]
            p50_metric = _compute_quantile(metric_values, 0.5)
            q60_metric = _compute_quantile(metric_values, composite_metric_quantile)
            q25_metric = _compute_quantile(metric_values, conservative_metric_quantile)
            if p50_metric is None or p50_metric <= 0:
                continue
            if q60_metric is None or q60_metric <= 0:
                continue
            if q25_metric is None or q25_metric <= 0:
                continue

            implied_price_m50 = float(current_price) * float(p50_metric) / float(current_metric)
            implied_price_q60 = float(current_price) * float(q60_metric) / float(current_metric)
            implied_price_q25 = float(current_price) * float(q25_metric) / float(current_metric)
            status_q60, gap_pct_q60 = _classify_valuation(current_price, implied_price_q60, band_pct)
            status_q25, gap_pct_q25 = _classify_valuation(current_price, implied_price_q25, band_pct)

            methods.append(
                {
                    "method": method_name,
                    "current_metric": round(float(current_metric), 4),
                    "p50_metric": round(float(p50_metric), 4),
                    "q60_metric": round(float(q60_metric), 4),
                    "q25_metric": round(float(q25_metric), 4),
                    "implied_index_price": round(float(implied_price_q60), 4),
                    "implied_index_price_q60": round(float(implied_price_q60), 4),
                    "implied_index_price_q25": round(float(implied_price_q25), 4),
                    "implied_index_price_m50": round(float(implied_price_m50), 4),
                    "implied_index_price_mode": current_price_mode,
                    "valuation_status": status_q60,
                    "valuation_gap_pct": round(gap_pct_q60 * 100, 2) if gap_pct_q60 is not None else None,
                    "valuation_status_q25": status_q25,
                    "valuation_gap_pct_q25": round(gap_pct_q25 * 100, 2) if gap_pct_q25 is not None else None,
                    "sample_size": len(metric_values),
                }
            )
            method_map_composite[method_name] = {
                "valuation_price": float(implied_price_q60),
                "candidate_count": 1,
            }
            method_map_conservative[method_name] = {
                "valuation_price": float(implied_price_q25),
                "candidate_count": 1,
            }

        if not method_map_composite or not method_map_conservative:
            return Response(
                {
                    "error": f"No valid valuation methods for {index_code}.",
                    "index_code": index_code,
                    "asof_trade_date": asof_trade_date_text,
                    "current_index_price": round(float(current_price), 4),
                },
                status=404,
            )

        summary_composite = _summarize_buy_candidate(
            current_price=current_price,
            method_map=method_map_composite,
            band_pct=band_pct,
        )
        summary_conservative = _summarize_buy_candidate(
            current_price=current_price,
            method_map=method_map_conservative,
            band_pct=band_pct,
        )
        composite_price = _to_float_or_none(summary_composite.get("composite_valuation_price"))
        conservative_price = _to_float_or_none(summary_conservative.get("conservative_valuation_price"))
        composite_status, composite_gap_pct = _classify_valuation(current_price, composite_price, band_pct)
        conservative_status, conservative_gap_pct = _classify_valuation(current_price, conservative_price, band_pct)

        return Response(
            {
                "index_code": index_code,
                "freq": freq,
                "asof_trade_date": asof_trade_date_text,
                "current_index_price": round(float(current_price), 4),
                "current_index_price_mode": current_price_mode,
                "current_index_price_field": current_price_field,
                "current_index_price_source_table": current_price_source_table,
                "note": price_mode_note,
                "basic_source_mode": basic_source_mode,
                "basic_source_note": basic_source_note,
                "valuation_band_pct": round(float(band_pct), 4),
                "methods": methods,
                "summary": {
                    **summary_composite,
                    "composite_metric_quantile": composite_metric_quantile,
                    "conservative_metric_quantile": conservative_metric_quantile,
                    "conservative_valuation_price": conservative_price,
                    "composite_valuation_status": composite_status,
                    "composite_valuation_gap_pct": round(composite_gap_pct * 100, 2)
                    if composite_gap_pct is not None
                    else None,
                    "conservative_valuation_status": conservative_status,
                    "conservative_valuation_gap_pct": round(conservative_gap_pct * 100, 2)
                    if conservative_gap_pct is not None
                    else None,
                },
            }
        )
    except Exception as exc:
        return Response({"error": str(exc)}, status=500)


@api_view(["GET"])
def get_stock_valuation_snapshot_history(request, ts_code):
    """Return valuation snapshot points for trend chart overlay."""

    normalized_ts_code = str(ts_code or "").strip().upper()
    if not normalized_ts_code:
        return Response({"error": "ts_code is required"}, status=400)

    market = (request.query_params.get("market") or "CN").strip() or "CN"
    freq = (request.query_params.get("freq") or "D").strip().upper() or "D"
    mode = str(request.query_params.get("mode") or "traditional").strip().lower()
    if mode in {"prediction", "earnings", "forecast"}:
        mode = "predictive"
    if mode not in {"traditional", "predictive"}:
        mode = "traditional"

    period_raw = request.query_params.get("period")
    try:
        period = int(period_raw) if period_raw not in (None, "") else 200
    except (TypeError, ValueError):
        period = 200
    period = max(30, min(period, 2000))

    band_pct = _parse_optional_float(request.query_params.get("valuation_band_pct"), default=0.1)
    if band_pct is None:
        band_pct = 0.1

    latest_trade_row = (
        StockTradingHistory.objects.filter(ts_code=normalized_ts_code, freq=freq)
        .order_by("-trade_date")
        .values("trade_date")
        .first()
    )
    latest_trade_date = _parse_date_like((latest_trade_row or {}).get("trade_date"))
    if latest_trade_date is None:
        return Response(
            {
                "code": 0,
                "message": "ok",
                "data": [],
                "meta": {
                    "ts_code": normalized_ts_code,
                    "mode": mode,
                    "freq": freq,
                    "period": period,
                },
            }
        )

    year_window_map = {200: 1, 400: 2, 1000: 5, 2000: 10}
    years = year_window_map.get(period)
    trading_qs = StockTradingHistory.objects.filter(ts_code=normalized_ts_code, freq=freq, trade_date__lte=latest_trade_date)
    if years:
        try:
            start_date = datetime.date(latest_trade_date.year - years, latest_trade_date.month, latest_trade_date.day)
        except ValueError:
            start_date = datetime.date(latest_trade_date.year - years, latest_trade_date.month, 1)
        trading_rows = list(
            trading_qs.filter(trade_date__gte=start_date)
            .order_by("trade_date")
            .values("trade_date", "close_qfq", "close")
        )
    else:
        trading_rows = list(
            trading_qs.order_by("-trade_date")
            .values("trade_date", "close_qfq", "close")[:period]
        )
        trading_rows.reverse()

    if not trading_rows:
        return Response(
            {
                "code": 0,
                "message": "ok",
                "data": [],
                "meta": {
                    "ts_code": normalized_ts_code,
                    "mode": mode,
                    "freq": freq,
                    "period": period,
                },
            }
        )

    period_start_date = _parse_date_like(trading_rows[0].get("trade_date"))
    period_end_date = _parse_date_like(trading_rows[-1].get("trade_date"))
    price_by_date = {}
    trading_dates = []
    for row in trading_rows:
        trade_date = _parse_date_like(row.get("trade_date"))
        if trade_date is None:
            continue
        close_price = _to_float_or_none(row.get("close_qfq"))
        if close_price is None:
            close_price = _to_float_or_none(row.get("close"))
        price_by_date[trade_date] = close_price
        trading_dates.append(trade_date)

    if not trading_dates:
        return Response(
            {
                "code": 0,
                "message": "ok",
                "data": [],
                "meta": {
                    "ts_code": normalized_ts_code,
                    "mode": mode,
                    "freq": freq,
                    "period": period,
                },
            }
        )

    points = []

    if mode == "traditional":
        requested_variant = _normalize_valuation_variant(
            request.query_params.get("valuation_variant"),
            fallback="",
        )
        history_rows = list(
            StockValuationSnapshotHistory.objects.filter(
                ts_code=normalized_ts_code,
                market=market,
                trade_date__gte=period_start_date,
                trade_date__lte=period_end_date,
            )
            .order_by("trade_date", "valuation_variant", "valuation_method", "-id")
            .values("trade_date", "valuation_method", "valuation_variant", "valuation_price")
        )

        grouped = {}
        seen = set()
        for row in history_rows:
            trade_date = _parse_date_like(row.get("trade_date"))
            method = _normalize_valuation_method_name(row.get("valuation_method"))
            variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
            valuation_price = _to_float_or_none(row.get("valuation_price"))
            if trade_date is None or not method or valuation_price is None:
                continue
            dedup_key = (trade_date, variant, method)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            grouped.setdefault(trade_date, {}).setdefault(variant, {})[method] = {
                "valuation_price": valuation_price,
                "candidate_count": 1,
            }

        # Fallback: if snapshot table has a newer trade_date than archived history,
        # append that latest date to avoid missing freshly generated snapshots.
        latest_history_trade_date = max(grouped.keys()) if grouped else None
        latest_snapshot_row = (
            StockValuationSnapshot.objects.filter(
                ts_code=normalized_ts_code,
                market=market,
                trade_date__gte=period_start_date,
                trade_date__lte=period_end_date,
            )
            .order_by("-trade_date")
            .values("trade_date")
            .first()
        )
        latest_snapshot_trade_date = _parse_date_like((latest_snapshot_row or {}).get("trade_date"))
        if (
            latest_snapshot_trade_date is not None
            and (latest_history_trade_date is None or latest_snapshot_trade_date > latest_history_trade_date)
            and latest_snapshot_trade_date not in grouped
        ):
            snapshot_rows = list(
                StockValuationSnapshot.objects.filter(
                    ts_code=normalized_ts_code,
                    market=market,
                    trade_date=latest_snapshot_trade_date,
                )
                .order_by("valuation_variant", "valuation_method", "-id")
                .values("valuation_variant", "valuation_method", "valuation_price")
            )
            variant_map = {}
            variant_seen = set()
            for row in snapshot_rows:
                method = _normalize_valuation_method_name(row.get("valuation_method"))
                variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
                valuation_price = _to_float_or_none(row.get("valuation_price"))
                if not method or valuation_price is None:
                    continue
                dedup_key = (variant, method)
                if dedup_key in variant_seen:
                    continue
                variant_seen.add(dedup_key)
                variant_map.setdefault(variant, {})[method] = {
                    "valuation_price": valuation_price,
                    "candidate_count": 1,
                }
            if variant_map:
                grouped[latest_snapshot_trade_date] = variant_map

        for trade_date in sorted(grouped.keys()):
            current_price = _to_float_or_none(price_by_date.get(trade_date))
            if current_price is None:
                older_dates = [d for d in trading_dates if d <= trade_date]
                if older_dates:
                    current_price = _to_float_or_none(price_by_date.get(older_dates[-1]))
            if current_price is None or current_price <= 0:
                continue
            variant_map = grouped.get(trade_date) or {}
            if not variant_map:
                continue

            if requested_variant:
                # Strict variant mode: when caller pins a variant, skip dates
                # that do not contain this variant instead of falling back.
                if requested_variant not in variant_map:
                    continue
                selected_variant = requested_variant
            elif "default" in variant_map:
                selected_variant = "default"
            else:
                selected_variant = sorted(
                    variant_map.keys(),
                    key=lambda key: (-len(variant_map.get(key) or {}), key),
                )[0]

            summary = _summarize_buy_candidate(current_price, variant_map.get(selected_variant) or {}, band_pct)
            composite_price = _to_float_or_none(summary.get("composite_valuation_price"))
            conservative_price = _to_float_or_none(summary.get("conservative_valuation_price"))
            if composite_price is None and conservative_price is None:
                continue

            points.append(
                {
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "composite_price": round(composite_price, 4) if composite_price is not None else None,
                    "conservative_price": round(conservative_price, 4) if conservative_price is not None else None,
                    "source_mode": "traditional",
                    "valuation_variant": selected_variant,
                }
            )
    else:
        report_type = _normalize_earnings_report_type(request.query_params.get("report_type") or "FY")
        panel_report_type = _map_valuation_report_type_to_panel_type(report_type)
        suffix_map = {
            "Q1": "0331",
            "H1": "0630",
            "Q3": "0930",
            "FY": "1231",
        }
        suffix = suffix_map.get(panel_report_type)

        sql_params = [normalized_ts_code, period_start_date.strftime("%Y%m%d"), period_end_date.strftime("%Y%m%d")]
        sql = """
            SELECT ann_date, end_date
            FROM earnings_fin_income
            WHERE ts_code = %s
              AND ann_date IS NOT NULL
              AND ann_date >= %s
              AND ann_date <= %s
        """
        if suffix:
            sql += " AND RIGHT(CAST(end_date AS TEXT), 4) = %s"
            sql_params.append(suffix)
        sql += " ORDER BY ann_date ASC, end_date ASC"

        try:
            report_df = query_local_financial_df(sql, sql_params)
        except Exception:
            report_df = None

        release_rows = []
        if report_df is not None and not report_df.empty:
            seen_release = set()
            for _, row in report_df.iterrows():
                ann_date = _parse_date_like(row.get("ann_date"))
                end_date = _parse_date_like(row.get("end_date"))
                if ann_date is None:
                    continue
                key = (ann_date, end_date)
                if key in seen_release:
                    continue
                seen_release.add(key)
                release_rows.append((ann_date, end_date))

        for ann_date, end_date in release_rows:
            current_price = _to_float_or_none(price_by_date.get(ann_date))
            if current_price is None:
                older_dates = [d for d in trading_dates if d <= ann_date]
                if older_dates:
                    current_price = _to_float_or_none(price_by_date.get(older_dates[-1]))

            try:
                signal_payload = _fetch_earnings_signal(
                    normalized_ts_code,
                    report_type,
                    financial_end_date=end_date,
                    source="snapshot",
                    anchor_mode="ann",
                )
                signal_payload = _build_earnings_dual_target_payload(
                    signal_payload,
                    current_price=current_price,
                    latest_trade_date=ann_date,
                    anchor_mode="ann",
                )
            except Exception:
                continue

            conservative_price = _to_float_or_none(signal_payload.get("target_price_low_raw"))
            if conservative_price is None:
                conservative_price = _to_float_or_none(signal_payload.get("target_price_low"))
            if conservative_price is None:
                conservative_price = _to_float_or_none(signal_payload.get("target_price_raw"))
            if conservative_price is None:
                conservative_price = _to_float_or_none(signal_payload.get("target_price"))

            composite_price = _to_float_or_none(signal_payload.get("target_price_high_raw"))
            if composite_price is None:
                composite_price = _to_float_or_none(signal_payload.get("target_price_high"))
            if composite_price is None:
                composite_price = _to_float_or_none(signal_payload.get("target_price_raw"))
            if composite_price is None:
                composite_price = _to_float_or_none(signal_payload.get("target_price"))

            if composite_price is None and conservative_price is None:
                continue

            anchor_trade_date = _parse_date_like(signal_payload.get("anchor_trade_date"))
            point_trade_date = anchor_trade_date or ann_date
            points.append(
                {
                    "trade_date": point_trade_date.strftime("%Y-%m-%d"),
                    "composite_price": round(composite_price, 4) if composite_price is not None else None,
                    "conservative_price": round(conservative_price, 4) if conservative_price is not None else None,
                    "source_mode": "predictive",
                    "report_type": report_type,
                    "report_end_date": end_date.strftime("%Y-%m-%d") if end_date is not None else None,
                    "anchor_mode": "ann",
                }
            )

    dedup = {}
    for item in points:
        key = str(item.get("trade_date") or "").strip()
        if not key:
            continue
        dedup[key] = item

    output_rows = [dedup[key] for key in sorted(dedup.keys())]
    return Response(
        {
            "code": 0,
            "message": "ok",
            "data": output_rows,
            "meta": {
                "ts_code": normalized_ts_code,
                "mode": mode,
                "freq": freq,
                "period": period,
                "period_start_date": period_start_date.strftime("%Y-%m-%d") if period_start_date is not None else None,
                "period_end_date": period_end_date.strftime("%Y-%m-%d") if period_end_date is not None else None,
            },
        }
    )


def _extract_ts_code_from_text(text):
    if not text:
        return None
    match = re.search(r"\b\d{6}\.(?:SH|SZ)\b", str(text).upper())
    if not match:
        return None
    return match.group(0)


def _extract_band_pct_from_text(text, default_pct=0.1):
    if not text:
        return default_pct

    normalized = str(text)
    if "Σ╕Ñµá╝" in normalized:
        return 0.05
    if "σ«╜µ¥╛" in normalized:
        return 0.15

    match = re.search(r"(\d{1,2})\s*%", normalized)
    if match:
        try:
            pct = float(match.group(1)) / 100.0
            if 0.01 <= pct <= 0.4:
                return pct
        except ValueError:
            return default_pct

    return default_pct


def _get_latest_valuation_payload(ts_code, market="CN", freq="D", band_pct=0.1):
    trading_row = (
        StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
        .order_by("-trade_date")
        .values("trade_date", "close_qfq", "close")
        .first()
    )
    current_price = None
    current_trade_date = None
    if trading_row:
        current_trade_date = trading_row.get("trade_date")
        current_price = trading_row.get("close_qfq") or trading_row.get("close")

    snapshots = list(
        StockValuationSnapshotLatest.objects.filter(ts_code=ts_code, market=market)
        .order_by("valuation_method", "-updated_at")
        .values(
            "valuation_method",
            "valuation_price",
            "valuation_market_cap",
            "source",
            "latest_trade_date",
        )
    )

    latest_by_method = {}
    for row in snapshots:
        method = _normalize_valuation_method_name(row.get("valuation_method"))
        if not method or method in latest_by_method:
            continue
        latest_by_method[method] = row

    rows = []
    for method, row in latest_by_method.items():
        valuation_price = row.get("valuation_price")
        valuation_price = float(valuation_price) if valuation_price is not None else None
        status, gap_pct = _classify_valuation(current_price, valuation_price, band_pct)
        rows.append(
            {
                "valuation_method": method,
                "valuation_price": round(valuation_price, 4) if valuation_price is not None else None,
                "valuation_market_cap": float(row.get("valuation_market_cap")) if row.get("valuation_market_cap") is not None else None,
                "valuation_status": status,
                "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
                "source": row.get("source"),
                "latest_trade_date": row.get("latest_trade_date"),
            }
        )

    method_map_for_summary = {}
    for row in rows:
        method = _normalize_valuation_method_name(row.get("valuation_method"))
        valuation_price = row.get("valuation_price")
        if not method or valuation_price is None:
            continue
        method_map_for_summary[method] = {
            "valuation_price": valuation_price,
            "candidate_count": 1,
        }

    summary = _summarize_buy_candidate(current_price, method_map_for_summary, band_pct)
    composite_status, composite_gap_pct = _classify_valuation(
        current_price,
        summary.get("composite_valuation_price"),
        band_pct,
    )
    conservative_status, conservative_gap_pct = _classify_valuation(
        current_price,
        summary.get("conservative_valuation_price"),
        band_pct,
    )

    return {
        "ts_code": ts_code,
        "market": market,
        "freq": freq,
        "current_price": float(current_price) if current_price is not None else None,
        "current_trade_date": current_trade_date,
        "valuation_band_pct": band_pct,
        "summary": {
            "composite_valuation_price": summary.get("composite_valuation_price"),
            "composite_valuation_status": composite_status,
            "composite_valuation_gap_pct": round(composite_gap_pct * 100, 2) if composite_gap_pct is not None else None,
            "conservative_valuation_price": summary.get("conservative_valuation_price"),
            "conservative_valuation_status": conservative_status,
            "conservative_valuation_gap_pct": round(conservative_gap_pct * 100, 2) if conservative_gap_pct is not None else None,
            "buy_candidate": bool(summary.get("buy_candidate")),
            "valuation_under_methods": summary.get("valuation_under_methods") or [],
            "valuation_valid_methods": summary.get("valuation_valid_methods") or [],
        },
        "data": rows,
    }


def _load_internal_stock_valuation_methods_payload(
    ts_code,
    *,
    freq="D",
    earnings_report_type=None,
    valuation_report_end_date=None,
    valuation_band_pct=0.1,
    valuation_variant=None,
):
    query_params = {
        "freq": str(freq),
        "valuation_band_pct": str(valuation_band_pct),
    }
    if earnings_report_type:
        query_params["earnings_report_type"] = str(earnings_report_type)
    if valuation_report_end_date:
        query_params["valuation_report_end_date"] = str(valuation_report_end_date)
    if valuation_variant:
        query_params["valuation_variant"] = str(valuation_variant)

    internal_request = RequestFactory().get("/internal/valuation/methods/", query_params)
    response = get_stock_valuation_methods(internal_request, ts_code)
    return response.data if hasattr(response, "data") else {}


def _render_openclaw_advice_text(question, payload):
    current_price = payload.get("current_price")
    summary = payload.get("summary") or {}
    under_methods = summary.get("valuation_under_methods") or []
    valid_methods = summary.get("valuation_valid_methods") or []

    composite_status = summary.get("composite_valuation_status")
    conservative_status = summary.get("conservative_valuation_status")
    composite_gap_pct = summary.get("composite_valuation_gap_pct")
    conservative_gap_pct = summary.get("conservative_valuation_gap_pct")

    if composite_status == "under" and conservative_status in {"under", "fair"}:
        stance = "σ╜ôσëìσüÅΣ╜ÄΣ╝░∩╝îσÅ»σêåµë╣σà│µ│¿πÇé"
    elif composite_status == "over" and conservative_status in {"over", "fair"}:
        stance = "σ╜ôσëìσüÅΘ½ÿΣ╝░∩╝îσ╗║Φ««Φ░¿µàÄ∩╝îτ¡ëσ╛àµ¢┤σÑ╜σ«ëσà¿Φ╛╣ΘÖàπÇé"
    else:
        stance = "σ╜ôσëìΣ╝░σÇ╝σñºΣ╜ôΣ╕¡µÇº∩╝îσÅ»τ╗ôσÉêΦ╢ïσè┐σÆîΣ╗ôΣ╜ìτ«íτÉåπÇé"

    def _fmt_num(value):
        if value is None:
            return "-"
        return f"{float(value):.2f}"

    advice = [
        f"Θù«Θóÿ: {question or 'Σ╝░σÇ╝σ╗║Φ««'}",
        f"µáçτÜä: {payload.get('ts_code')} ({payload.get('freq')})",
        f"τÄ░Σ╗╖: {_fmt_num(current_price)}",
        (
            "τ╗äσÉêΣ╝░σÇ╝: "
            f"{_fmt_num(summary.get('composite_valuation_price'))} "
            f"({composite_status or '-'}, {_fmt_num(composite_gap_pct)}%)"
        ),
        (
            "Σ┐¥σ«êΣ╝░σÇ╝: "
            f"{_fmt_num(summary.get('conservative_valuation_price'))} "
            f"({conservative_status or '-'}, {_fmt_num(conservative_gap_pct)}%)"
        ),
        f"Σ╜ÄΣ╝░µû╣µ│ò: {', '.join(under_methods) if under_methods else '-'}",
        f"µ£ëµòêµû╣µ│òµò░: {len(valid_methods)}",
        f"σ╗║Φ««: {stance}",
        "µÅÉτñ║: µ£¼σ╗║Φ««Σ╗àσƒ║Σ║ÄσÄåσÅ▓Σ╕Äσ┐½τàºΣ╝░σÇ╝σÅúσ╛ä∩╝îΣ╕ìµ₧äµêÉµèòΦ╡äµë┐Φ»║πÇé",
    ]
    return "\n".join(advice)


def _forward_to_feishu(text):
    webhook = str(getattr(settings, "FEISHU_BOT_WEBHOOK", "") or "").strip()
    if not webhook:
        return False, "FEISHU_BOT_WEBHOOK µ£¬Θàìτ╜«"

    payload = {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=8) as resp:
            _ = resp.read()
        return True, None
    except HTTPError as err:
        return False, f"Feishu HTTPError: {err.code}"
    except URLError as err:
        return False, f"Feishu URLError: {err.reason}"
    except Exception as err:
        return False, f"Feishu Error: {err}"


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


TRADITIONAL_TIER_SCHEMES = {
    "high_growth": {
        "style_label": "高成长风格",
        "tiers": {
            "conservative": {
                "label": "稳健配置",
                "weights": {"pe": 0.20, "peg": 0.20, "ps": 0.15, "scarcity_overlay": 0.15, "sw_history": 0.10, "fcff_dcf": 0.10, "pb": 0.08, "ddm": 0.02},
                "range_multiplier": (0.94, 1.04),
            },
            "balanced": {
                "label": "均衡配置",
                "weights": {"pe": 0.28, "peg": 0.24, "ps": 0.16, "scarcity_overlay": 0.14, "sw_history": 0.08, "fcff_dcf": 0.06, "pb": 0.03, "ddm": 0.01},
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "进攻配置",
                "weights": {"pe": 0.35, "peg": 0.28, "ps": 0.16, "scarcity_overlay": 0.12, "sw_history": 0.06, "fcff_dcf": 0.02, "pb": 0.01, "ddm": 0.00},
                "range_multiplier": (0.95, 1.15),
            },
        },
    },
    "stable_value": {
        "style_label": "稳健价值风格",
        "tiers": {
            "conservative": {
                "label": "稳健配置",
                "weights": {"pb": 0.30, "fcff_dcf": 0.24, "pe": 0.16, "sw_history": 0.10, "ps": 0.08, "scarcity_overlay": 0.06, "peg": 0.04, "ddm": 0.02},
                "range_multiplier": (0.96, 1.04),
            },
            "balanced": {
                "label": "均衡配置",
                "weights": {"pb": 0.24, "fcff_dcf": 0.22, "pe": 0.20, "sw_history": 0.12, "ps": 0.10, "scarcity_overlay": 0.06, "peg": 0.04, "ddm": 0.02},
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "进攻配置",
                "weights": {"pb": 0.18, "fcff_dcf": 0.17, "pe": 0.28, "sw_history": 0.12, "ps": 0.12, "scarcity_overlay": 0.07, "peg": 0.04, "ddm": 0.02},
                "range_multiplier": (0.94, 1.13),
            },
        },
    },
    "balanced": {
        "style_label": "均衡风格",
        "tiers": {
            "conservative": {
                "label": "稳健配置",
                "weights": {"pe": 0.23, "peg": 0.18, "ps": 0.14, "scarcity_overlay": 0.12, "sw_history": 0.12, "fcff_dcf": 0.10, "pb": 0.09, "ddm": 0.02},
                "range_multiplier": (0.95, 1.04),
            },
            "balanced": {
                "label": "均衡配置",
                "weights": {"pe": 0.26, "peg": 0.20, "ps": 0.15, "scarcity_overlay": 0.12, "sw_history": 0.10, "fcff_dcf": 0.09, "pb": 0.06, "ddm": 0.02},
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "进攻配置",
                "weights": {"pe": 0.31, "peg": 0.24, "ps": 0.15, "scarcity_overlay": 0.11, "sw_history": 0.08, "fcff_dcf": 0.06, "pb": 0.04, "ddm": 0.01},
                "range_multiplier": (0.95, 1.14),
            },
        },
    },
    "cyclical_resource": {
        "style_label": "周期资源风格",
        "tiers": {
            "conservative": {
                "label": "稳健配置",
                "weights": {"sw_history": 0.22, "scarcity_overlay": 0.20, "fcff_dcf": 0.18, "pb": 0.16, "ps": 0.10, "pe": 0.08, "peg": 0.04, "ddm": 0.02},
                "range_multiplier": (0.95, 1.04),
            },
            "balanced": {
                "label": "均衡配置",
                "weights": {"sw_history": 0.24, "scarcity_overlay": 0.22, "fcff_dcf": 0.20, "ps": 0.14, "pb": 0.10, "pe": 0.06, "peg": 0.03, "ddm": 0.01},
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "进攻配置",
                "weights": {"sw_history": 0.27, "scarcity_overlay": 0.24, "fcff_dcf": 0.22, "ps": 0.17, "pb": 0.07, "pe": 0.02, "peg": 0.01, "ddm": 0.00},
                "range_multiplier": (0.95, 1.14),
            },
        },
    },
}

TRADITIONAL_INDUSTRY_SCHEME_OVERRIDES = [
    {
        "scheme_key": "cyclical_resource",
        "keywords": ["煤", "炭", "有色金属", "钢铁", "石油", "基础化工", "建筑材料", "资源"],
    }
]

TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS = [
    "半导体", "计算机", "通信", "电子", "新能源", "新能源设备", "军工", "医药", "高端制造",
    "ai", "aigc", "llm", "人工智能", "算力", "agent", "新能源车", "机器人", "创新药", "自动驾驶",
]
TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS = [
    "银行", "保险", "公用", "交运", "消费", "家电", "食品饮料", "公用事业", "电力", "港口", "水务", "运营商",
]
TRADITIONAL_STYLE_INDUSTRY_CYCLICAL_KEYWORDS = [
    "煤", "炭", "油气", "建筑材料", "钢铁", "基础化工", "石油", "石化", "工程机械", "有色", "航运", "资源",
]

# Phase A: industry-code-first regime mapping.
# Use concise SW-style code prefixes (digits only) and keep keyword logic as fallback.
TRADITIONAL_REGIME_CODE_RULES = [
    {
        "regime": "high_growth",
        "code_prefixes": ["80108", "80175", "80176", "8515"],
    },
    {
        "regime": "cyclical_resource",
        "code_prefixes": [
            "80102", "80103", "80104", "80105", "80106", "80107", "80109", "80111", "80112", "80117", "80118", "80119", "80120", "80121", "8517",
            "8503", "85037", "85038", "85039", "85040",
        ],
    },
    {
        "regime": "stable_value",
        "code_prefixes": ["80178", "80179", "80188", "80195", "80196"],
    },
]

TRADITIONAL_STYLE_SCORE_RULES = {
    "industry_growth_bias": 1.15,
    "industry_stable_bias": -0.9,
    "roe_high_threshold": 20.0,
    "roe_mid_threshold": 12.0,
    "roe_high_bonus": 0.7,
    "roe_mid_bonus": 0.35,
    "gross_margin_high_threshold": 40.0,
    "gross_margin_mid_threshold": 28.0,
    "gross_margin_high_bonus": 0.55,
    "gross_margin_mid_bonus": 0.25,
    "debt_low_threshold": 35.0,
    "debt_high_threshold": 65.0,
    "debt_low_bonus": 0.2,
    "debt_high_penalty": -0.2,
    "peg_available_bonus": 0.25,
    "pb_fcff_available_penalty": -0.1,
}
TRADITIONAL_STYLE_SCORE_THRESHOLDS = {
    "high_growth_min": 1.1,
    "stable_value_max": -0.35,
}

TRADITIONAL_METHOD_WINSOR_RULES = {
    "enabled": True,
    "lower_percentile": 0.15,
    "upper_percentile": 0.85,
    "min_methods": 6,
}

TRADITIONAL_TIER_MIN_GAP_RULES = {
    "high_growth": {"down": 0.055, "up": 0.085},
    "balanced": {"down": 0.045, "up": 0.070},
    "stable_value": {"down": 0.035, "up": 0.055},
    "cyclical_resource": {"down": 0.050, "up": 0.080},
    "volatility_adjust": {
        "high": 0.015,
        "medium": 0.0,
        "low": -0.010,
    },
    "dispersion_scale": 0.02,
    "dispersion_cap": 0.025,
    "min_floor": 0.02,
    "max_ceiling": 0.16,
}


def _quantile_linear(sorted_values, quantile):
    if not sorted_values:
        return None
    q = max(0.0, min(1.0, float(quantile)))
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    index = (len(sorted_values) - 1) * q
    low = int(math.floor(index))
    high = int(math.ceil(index))
    low_val = float(sorted_values[low])
    high_val = float(sorted_values[high])
    if low == high:
        return low_val
    return low_val + (high_val - low_val) * (index - low)


def _winsorize_method_price_map(method_price_map, rules=None):
    normalized = {
        str(method): float(price)
        for method, price in (method_price_map or {}).items()
        if _to_float_or_none(price) is not None and float(price) > 0
    }
    meta = {
        "enabled": False,
        "applied": False,
        "lower_percentile": None,
        "upper_percentile": None,
        "lower_bound": None,
        "upper_bound": None,
        "method_count": len(normalized),
        "clipped_count": 0,
    }
    if not normalized:
        return normalized, meta

    cfg = rules if isinstance(rules, dict) else TRADITIONAL_METHOD_WINSOR_RULES
    enabled = bool(cfg.get("enabled", True))
    min_methods = int(cfg.get("min_methods", 6) or 6)
    lower_pct = float(cfg.get("lower_percentile", 0.15) or 0.15)
    upper_pct = float(cfg.get("upper_percentile", 0.85) or 0.85)
    lower_pct = max(0.0, min(1.0, lower_pct))
    upper_pct = max(0.0, min(1.0, upper_pct))
    if lower_pct > upper_pct:
        lower_pct, upper_pct = upper_pct, lower_pct

    meta.update({
        "enabled": enabled,
        "lower_percentile": lower_pct,
        "upper_percentile": upper_pct,
    })

    if not enabled or len(normalized) < max(2, min_methods):
        return normalized, meta

    sorted_values = sorted(normalized.values())
    lower_bound = _quantile_linear(sorted_values, lower_pct)
    upper_bound = _quantile_linear(sorted_values, upper_pct)
    if lower_bound is None or upper_bound is None:
        return normalized, meta
    if lower_bound > upper_bound:
        lower_bound, upper_bound = upper_bound, lower_bound

    clipped = {}
    clipped_count = 0
    for method, price in normalized.items():
        next_price = min(max(price, lower_bound), upper_bound)
        if abs(next_price - price) > 1e-9:
            clipped_count += 1
        clipped[method] = float(next_price)

    meta.update({
        "applied": clipped_count > 0,
        "clipped_count": clipped_count,
        "lower_bound": round(float(lower_bound), 4),
        "upper_bound": round(float(upper_bound), 4),
    })
    return clipped, meta


def _normalize_industry_code_for_regime(industry_code):
    raw = str(industry_code or "").strip().upper()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits


_SW_REGIME_LOOKUP_CACHE = None
_SUGGESTED_REGIME_LOOKUP_CACHE = None


def _normalize_regime_value(raw):
    text = str(raw or "").strip().lower()
    allowed = {"high_growth", "stable_value", "cyclical_resource", "balanced"}
    return text if text in allowed else ""


def _load_suggested_regime_lookup():
    global _SUGGESTED_REGIME_LOOKUP_CACHE
    if isinstance(_SUGGESTED_REGIME_LOOKUP_CACHE, dict):
        return _SUGGESTED_REGIME_LOOKUP_CACHE

    lookup = {}
    suggested_path = Path(settings.BASE_DIR) / "static" / "regime_mapping_suggested_v1.csv"
    try:
        with suggested_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not isinstance(row, dict):
                    continue
                regime = _normalize_regime_value(row.get("suggested_regime"))
                if not regime:
                    continue
                reason = f"suggested_v1:{regime}"
                index_code = _normalize_industry_code_for_regime(row.get("index_code"))
                industry_code = _normalize_industry_code_for_regime(row.get("industry_code"))
                for code in [index_code, industry_code]:
                    if code:
                        lookup[code] = (regime, reason)
    except Exception:
        lookup = {}

    _SUGGESTED_REGIME_LOOKUP_CACHE = lookup
    return lookup


def _resolve_regime_by_keywords(industry_name):
    name = str(industry_name or "").strip().lower()
    if not name:
        return None, None

    for keyword in TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS:
        text = str(keyword or "").strip().lower()
        if text and text in name:
            return "stable_value", text

    for keyword in TRADITIONAL_STYLE_INDUSTRY_CYCLICAL_KEYWORDS:
        text = str(keyword or "").strip().lower()
        if text and text in name:
            return "cyclical_resource", text

    for keyword in TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS:
        text = str(keyword or "").strip().lower()
        if text and text in name:
            return "high_growth", text

    return None, None


def _resolve_regime_by_code_prefix(code_digits):
    code = _normalize_industry_code_for_regime(code_digits)
    if not code:
        return None, None
    for item in TRADITIONAL_REGIME_CODE_RULES:
        regime = str((item or {}).get("regime") or "").strip()
        prefixes = (item or {}).get("code_prefixes")
        if not regime or not isinstance(prefixes, (list, tuple, set)):
            continue
        for prefix in prefixes:
            text = str(prefix or "").strip()
            if text and code.startswith(text):
                return regime, text
    return None, None


def _load_sw_regime_lookup():
    global _SW_REGIME_LOOKUP_CACHE
    if isinstance(_SW_REGIME_LOOKUP_CACHE, dict):
        return _SW_REGIME_LOOKUP_CACHE

    lookup = {}
    mapping_path = Path(settings.BASE_DIR) / "static" / "valuation_config" / "sw_industry_mapping_CN.json"
    try:
        with mapping_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        _SW_REGIME_LOOKUP_CACHE = lookup
        return lookup

    levels = payload.get("levels") if isinstance(payload, dict) else {}
    if not isinstance(levels, dict):
        _SW_REGIME_LOOKUP_CACHE = lookup
        return lookup

    l1_regime_by_prefix2 = {}
    l1_map = levels.get("L1") if isinstance(levels.get("L1"), dict) else {}
    for _, entry in l1_map.items():
        if not isinstance(entry, dict):
            continue
        index_code = _normalize_industry_code_for_regime(entry.get("index_code"))
        industry_code = _normalize_industry_code_for_regime(entry.get("industry_code"))
        industry_name = str(entry.get("industry_name") or "").strip()

        regime, matched = _resolve_regime_by_code_prefix(index_code or industry_code)
        source = f"sw_l1_prefix={matched}" if regime and matched else ""
        if not regime:
            regime, matched = _resolve_regime_by_keywords(industry_name)
            if regime and matched:
                source = f"sw_l1_keyword={matched}"
        if not regime:
            regime = "balanced"
            source = "sw_l1_default_balanced"

        if industry_code and len(industry_code) >= 2:
            l1_regime_by_prefix2[industry_code[:2]] = (regime, source)

    for level_name, level_map in levels.items():
        if not isinstance(level_map, dict):
            continue
        for _, entry in level_map.items():
            if not isinstance(entry, dict):
                continue

            index_code = _normalize_industry_code_for_regime(entry.get("index_code"))
            industry_code = _normalize_industry_code_for_regime(entry.get("industry_code"))
            industry_name = str(entry.get("industry_name") or "").strip()

            regime, matched = _resolve_regime_by_code_prefix(index_code or industry_code)
            source = f"sw_{level_name}_prefix={matched}" if regime and matched else ""
            if not regime:
                regime, matched = _resolve_regime_by_keywords(industry_name)
                if regime and matched:
                    source = f"sw_{level_name}_keyword={matched}"
            if not regime and industry_code and len(industry_code) >= 2:
                inherited = l1_regime_by_prefix2.get(industry_code[:2])
                if inherited:
                    regime, source = inherited
                    source = f"sw_l1_inherit:{source}"
            if not regime:
                regime = "balanced"
                source = f"sw_{level_name}_default_balanced"

            for code in [index_code, industry_code]:
                if code:
                    lookup[code] = (regime, source)

    _SW_REGIME_LOOKUP_CACHE = lookup
    return lookup


def _resolve_regime_by_industry_code(industry_code, industry_name=None):
    code = _normalize_industry_code_for_regime(industry_code)
    if code:
        suggested_lookup = _load_suggested_regime_lookup()
        suggested_hit = suggested_lookup.get(code)
        if isinstance(suggested_hit, tuple) and len(suggested_hit) >= 2:
            return suggested_hit[0], suggested_hit[1]

        sw_lookup = _load_sw_regime_lookup()
        sw_hit = sw_lookup.get(code)
        if isinstance(sw_hit, tuple) and len(sw_hit) >= 2:
            return sw_hit[0], sw_hit[1]

        regime, matched_prefix = _resolve_regime_by_code_prefix(code)
        if regime:
            return regime, f"industry_code_prefix={matched_prefix}"

    regime, matched_keyword = _resolve_regime_by_keywords(industry_name)
    if regime:
        return regime, f"industry_keyword={matched_keyword}"

    if code or str(industry_name or "").strip():
        return "balanced", "fallback_balanced"
    return None, None


def _resolve_traditional_style(industry_name, indicator_profile, method_price_map, industry_code=None):
    name = str(industry_name or "").lower()
    growth_score = 0.0
    reasons = []

    regime_by_code, regime_reason = _resolve_regime_by_industry_code(industry_code, industry_name=industry_name)
    if regime_by_code:
        reasons.append(str(regime_reason or "industry_regime_resolved"))
        if regime_by_code == "high_growth":
            growth_score += 1.35
        elif regime_by_code == "stable_value":
            growth_score -= 0.95
        elif regime_by_code == "cyclical_resource":
            growth_score += 0.05

    if any(keyword.lower() in name for keyword in TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS):
        growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("industry_growth_bias", 1.15) or 1.15)
        reasons.append("industry_growth_bias")
    elif any(keyword.lower() in name for keyword in TRADITIONAL_STYLE_INDUSTRY_CYCLICAL_KEYWORDS):
        growth_score += 0.08
        reasons.append("industry_cyclical_bias")
    elif any(keyword.lower() in name for keyword in TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS):
        growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("industry_stable_bias", -0.9) or -0.9)
        reasons.append("industry_stable_bias")

    roe = _to_float_or_none((indicator_profile or {}).get("roe"))
    gross_margin = _to_float_or_none((indicator_profile or {}).get("gross_margin"))
    debt_to_assets = _to_float_or_none((indicator_profile or {}).get("debt_to_assets"))

    if roe is not None:
        if roe >= float(TRADITIONAL_STYLE_SCORE_RULES.get("roe_high_threshold", 20.0) or 20.0):
            growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("roe_high_bonus", 0.7) or 0.7)
            reasons.append("roe>=20")
        elif roe >= float(TRADITIONAL_STYLE_SCORE_RULES.get("roe_mid_threshold", 12.0) or 12.0):
            growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("roe_mid_bonus", 0.35) or 0.35)
            reasons.append("roe>=12")

    if gross_margin is not None:
        if gross_margin >= float(TRADITIONAL_STYLE_SCORE_RULES.get("gross_margin_high_threshold", 40.0) or 40.0):
            growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("gross_margin_high_bonus", 0.55) or 0.55)
            reasons.append("gross_margin>=40")
        elif gross_margin >= float(TRADITIONAL_STYLE_SCORE_RULES.get("gross_margin_mid_threshold", 28.0) or 28.0):
            growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("gross_margin_mid_bonus", 0.25) or 0.25)
            reasons.append("gross_margin>=28")

    if debt_to_assets is not None:
        if debt_to_assets <= float(TRADITIONAL_STYLE_SCORE_RULES.get("debt_low_threshold", 35.0) or 35.0):
            growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("debt_low_bonus", 0.2) or 0.2)
            reasons.append("debt_to_assets<=35")
        elif debt_to_assets >= float(TRADITIONAL_STYLE_SCORE_RULES.get("debt_high_threshold", 65.0) or 65.0):
            growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("debt_high_penalty", -0.2) or -0.2)
            reasons.append("debt_to_assets>=65")

    if _to_float_or_none((method_price_map or {}).get("peg")) is not None:
        growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("peg_available_bonus", 0.25) or 0.25)
        reasons.append("peg_available")
    if _to_float_or_none((method_price_map or {}).get("pb")) is not None and _to_float_or_none((method_price_map or {}).get("fcff_dcf")) is not None:
        growth_score += float(TRADITIONAL_STYLE_SCORE_RULES.get("pb_fcff_available_penalty", -0.1) or -0.1)
        reasons.append("pb_fcff_available")

    if regime_by_code in {"high_growth", "stable_value", "cyclical_resource", "balanced"}:
        style_key = regime_by_code
    elif growth_score >= float(TRADITIONAL_STYLE_SCORE_THRESHOLDS.get("high_growth_min", 1.1) or 1.1):
        style_key = "high_growth"
    elif growth_score <= float(TRADITIONAL_STYLE_SCORE_THRESHOLDS.get("stable_value_max", -0.35) or -0.35):
        style_key = "stable_value"
    else:
        style_key = "balanced"
    return style_key, round(growth_score, 3), reasons


def _resolve_traditional_scheme_key(style_key, industry_name):
    industry_text = str(industry_name or "").strip()
    if industry_text:
        for item in TRADITIONAL_INDUSTRY_SCHEME_OVERRIDES:
            scheme_key = str((item or {}).get("scheme_key") or "").strip()
            keywords = (item or {}).get("keywords")
            if not scheme_key or not isinstance(keywords, (list, tuple, set)):
                continue
            for keyword in keywords:
                text = str(keyword or "").strip()
                if text and text in industry_text and scheme_key in TRADITIONAL_TIER_SCHEMES:
                    return scheme_key, text
    normalized_style_key = str(style_key or "balanced").strip().lower()
    if normalized_style_key in TRADITIONAL_TIER_SCHEMES:
        return normalized_style_key, None
    return "balanced", None


def _weighted_template_target(method_price_map, weights):
    total_weight = float(sum(float(v) for v in (weights or {}).values()))
    if total_weight <= 0:
        return None, 0.0, []

    weighted_sum = 0.0
    covered_weight = 0.0
    used_methods = []
    for method, weight in (weights or {}).items():
        price = _to_float_or_none((method_price_map or {}).get(method))
        normalized_weight = float(weight)
        if price is None or price <= 0 or normalized_weight <= 0:
            continue
        weighted_sum += float(price) * normalized_weight
        covered_weight += normalized_weight
        used_methods.append(method)

    if covered_weight <= 0:
        return None, 0.0, []

    target_price = weighted_sum / covered_weight
    coverage_ratio = max(0.0, min(1.0, covered_weight / total_weight))
    return round(target_price, 4), round(coverage_ratio, 4), used_methods


def _enforce_monotonic_tier_targets(tier_payload, scheme, current_price):
    order = ["conservative", "balanced", "aggressive"]
    raw_targets = []
    for key in order:
        tier = (tier_payload or {}).get(key) or {}
        target = _to_float_or_none(tier.get("target_price"))
        if target is None or target <= 0:
            return {"enabled": True, "applied": False, "reason": "missing_target"}
        raw_targets.append(float(target))

    if raw_targets[0] <= raw_targets[1] <= raw_targets[2]:
        return {
            "enabled": True,
            "applied": False,
            "reason": "already_monotonic",
            "before": [round(v, 4) for v in raw_targets],
            "after": [round(v, 4) for v in raw_targets],
        }

    adjusted_targets = sorted(raw_targets)
    cp = _to_float_or_none(current_price)
    tiers_cfg = (scheme or {}).get("tiers") if isinstance((scheme or {}).get("tiers"), dict) else {}

    for idx, key in enumerate(order):
        tier = (tier_payload or {}).get(key)
        if not isinstance(tier, dict):
            continue
        target = adjusted_targets[idx]
        tier_cfg = (tiers_cfg or {}).get(key) if isinstance((tiers_cfg or {}).get(key), dict) else {}
        lower_multiplier, upper_multiplier = tier_cfg.get("range_multiplier") or (0.95, 1.08)
        tier["target_price"] = round(float(target), 4)
        tier["range"] = {
            "lower": round(float(target) * float(lower_multiplier), 4),
            "upper": round(float(target) * float(upper_multiplier), 4),
        }
        if cp is not None and cp > 0:
            tier["expected_return_pct"] = round(((float(target) / cp) - 1.0) * 100.0, 2)
        else:
            tier["expected_return_pct"] = None

    return {
        "enabled": True,
        "applied": True,
        "reason": "sorted_targets",
        "before": [round(v, 4) for v in raw_targets],
        "after": [round(v, 4) for v in adjusted_targets],
    }


def _apply_tier_min_gap_constraints(tier_payload, scheme, current_price, style_key, volatility_profile, method_price_map):
    cp = _to_float_or_none(current_price)
    if cp is None or cp <= 0:
        return {
            "enabled": True,
            "applied": False,
            "reason": "invalid_current_price",
        }

    conservative = _to_float_or_none(((tier_payload or {}).get("conservative") or {}).get("target_price"))
    balanced = _to_float_or_none(((tier_payload or {}).get("balanced") or {}).get("target_price"))
    aggressive = _to_float_or_none(((tier_payload or {}).get("aggressive") or {}).get("target_price"))
    if conservative is None or balanced is None or aggressive is None:
        return {
            "enabled": True,
            "applied": False,
            "reason": "missing_target",
        }

    cfg = TRADITIONAL_TIER_MIN_GAP_RULES
    style_key_normalized = str(style_key or "balanced").strip().lower()
    style_cfg = cfg.get(style_key_normalized) or cfg.get("balanced") or {"down": 0.045, "up": 0.07}
    base_down = float(style_cfg.get("down", 0.045) or 0.045)
    base_up = float(style_cfg.get("up", 0.07) or 0.07)

    volatility_bucket = str((volatility_profile or {}).get("volatility_bucket") or "medium").strip().lower()
    if volatility_bucket not in {"high", "medium", "low"}:
        volatility_bucket = "medium"
    vol_adjust = float(((cfg.get("volatility_adjust") or {}).get(volatility_bucket, 0.0)) or 0.0)

    valid_prices = [float(v) for v in (method_price_map or {}).values() if _to_float_or_none(v) is not None and float(v) > 0]
    dispersion_adjust = 0.0
    dispersion_value = None
    if len(valid_prices) >= 2:
        sorted_prices = sorted(valid_prices)
        median = _quantile_linear(sorted_prices, 0.5)
        low = sorted_prices[0]
        high = sorted_prices[-1]
        if median is not None and median > 0 and high >= low:
            dispersion_value = (high - low) / median
            dispersion_adjust = min(
                float(cfg.get("dispersion_cap", 0.025) or 0.025),
                max(0.0, float(dispersion_value) * float(cfg.get("dispersion_scale", 0.02) or 0.02)),
            )

    min_floor = float(cfg.get("min_floor", 0.02) or 0.02)
    max_ceiling = float(cfg.get("max_ceiling", 0.16) or 0.16)
    min_down_gap_pct = max(min_floor, min(max_ceiling, base_down + vol_adjust + dispersion_adjust))
    min_up_gap_pct = max(min_floor, min(max_ceiling, base_up + vol_adjust + dispersion_adjust))

    required_conservative_max = balanced * (1.0 - min_down_gap_pct)
    required_aggressive_min = balanced * (1.0 + min_up_gap_pct)

    adjusted_conservative = min(float(conservative), float(required_conservative_max))
    adjusted_aggressive = max(float(aggressive), float(required_aggressive_min))
    if adjusted_aggressive <= adjusted_conservative:
        adjusted_aggressive = max(adjusted_aggressive, adjusted_conservative * (1.0 + min_down_gap_pct + min_up_gap_pct))

    applied = (
        abs(adjusted_conservative - float(conservative)) > 1e-9
        or abs(adjusted_aggressive - float(aggressive)) > 1e-9
    )

    if applied:
        tiers_cfg = (scheme or {}).get("tiers") if isinstance((scheme or {}).get("tiers"), dict) else {}
        adjustments = {
            "conservative": adjusted_conservative,
            "balanced": float(balanced),
            "aggressive": adjusted_aggressive,
        }
        for tier_key, target in adjustments.items():
            tier = (tier_payload or {}).get(tier_key)
            if not isinstance(tier, dict):
                continue
            tier_cfg = (tiers_cfg or {}).get(tier_key) if isinstance((tiers_cfg or {}).get(tier_key), dict) else {}
            lower_multiplier, upper_multiplier = tier_cfg.get("range_multiplier") or (0.95, 1.08)
            tier["target_price"] = round(float(target), 4)
            tier["range"] = {
                "lower": round(float(target) * float(lower_multiplier), 4),
                "upper": round(float(target) * float(upper_multiplier), 4),
            }
            tier["expected_return_pct"] = round(((float(target) / cp) - 1.0) * 100.0, 2)

    return {
        "enabled": True,
        "applied": applied,
        "style_key": style_key_normalized,
        "volatility_bucket": volatility_bucket,
        "min_down_gap_pct": round(min_down_gap_pct, 4),
        "min_up_gap_pct": round(min_up_gap_pct, 4),
        "dispersion": round(float(dispersion_value), 4) if dispersion_value is not None else None,
        "before": {
            "conservative": round(float(conservative), 4),
            "balanced": round(float(balanced), 4),
            "aggressive": round(float(aggressive), 4),
        },
        "after": {
            "conservative": round(float(adjusted_conservative), 4),
            "balanced": round(float(balanced), 4),
            "aggressive": round(float(adjusted_aggressive), 4),
        },
    }


def _load_traditional_volatility_profile(ts_code, current_price=None, freq="D", lookback=60):
    try:
        records = list(
            StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
            .order_by("-trade_date")
            .values("trade_date", "high_qfq", "low_qfq", "close_qfq")[:lookback]
        )
        if not records:
            return None
        df = pd.DataFrame(records)
        if df.empty:
            return None
        df = df.sort_values("trade_date").reset_index(drop=True)
        df = calculate_atr(df=df, period=20, high_col="high_qfq", low_col="low_qfq", close_col="close_qfq")

        latest_row = df.iloc[-1].to_dict() if len(df) else {}
        close_price = _to_float_or_none(latest_row.get("close_qfq"))
        if close_price is None or close_price <= 0:
            close_price = _to_float_or_none(current_price)
        atr_value = _to_float_or_none(latest_row.get("atr"))
        atr_ratio = None
        if close_price is not None and close_price > 0 and atr_value is not None and atr_value > 0:
            atr_ratio = atr_value / close_price

        returns = pd.to_numeric(df.get("close_qfq"), errors="coerce").pct_change()
        realized_volatility = None
        if returns is not None:
            clean_returns = returns.dropna()
            if len(clean_returns) >= 10:
                tail_std = clean_returns.tail(20).std()
                if pd.notnull(tail_std):
                    realized_volatility = float(tail_std * (252 ** 0.5))

        volatility_bucket = "medium"
        if atr_ratio is not None:
            if atr_ratio <= 0.03:
                volatility_bucket = "low"
            elif atr_ratio >= 0.06:
                volatility_bucket = "high"
        volatility_label = {"low": "低波动", "medium": "中波动", "high": "高波动"}.get(volatility_bucket, "中波动")
        return {
            "atr": round(atr_value, 4) if atr_value is not None else None,
            "atr_ratio": round(atr_ratio, 4) if atr_ratio is not None else None,
            "realized_volatility_20d": round(realized_volatility, 4) if realized_volatility is not None else None,
            "volatility_bucket": volatility_bucket,
            "volatility_label": volatility_label,
            "lookback": lookback,
        }
    except Exception:
        return None


def _resolve_position_guidance(current_price, conservative_range, balanced_range, aggressive_range, style_key=None, industry_name=None, volatility_profile=None):
    cp = _to_float_or_none(current_price)
    style_key_normalized = str(style_key or "balanced").strip().lower()
    style_label = {
        "high_growth": "高成长风格",
        "stable_value": "稳健价值风格",
        "balanced": "均衡风格",
        "cyclical_resource": "周期资源风格",
    }.get(style_key_normalized, "均衡风格")

    volatility_bucket = str((volatility_profile or {}).get("volatility_bucket") or "medium").lower()
    if volatility_bucket not in {"low", "medium", "high"}:
        volatility_bucket = "medium"
    volatility_label = (volatility_profile or {}).get("volatility_label") or {"low": "低波动", "medium": "中波动", "high": "高波动"}.get(volatility_bucket, "中波动")

    default_payload = {
        "suggested_position_range": "35%-55%",
        "message": "处于平衡区间，建议维持中性仓位。",
        "state_key": "within_balanced",
        "state_label": "平衡区间",
    }
    if cp is None or cp <= 0:
        payload = dict(default_payload)
    else:
        c_low = _to_float_or_none((conservative_range or {}).get("lower"))
        b_low = _to_float_or_none((balanced_range or {}).get("lower"))
        b_high = _to_float_or_none((balanced_range or {}).get("upper"))
        a_high = _to_float_or_none((aggressive_range or {}).get("upper"))

        if c_low is not None and cp < c_low:
            payload = {
                "suggested_position_range": "52%-68%" if volatility_bucket == "high" else "60%-75%",
                "message": "低于稳健区下沿，建议分批增加仓位。",
                "state_key": "below_conservative",
                "state_label": "低估区",
            }
        elif b_low is not None and cp < b_low:
            payload = {
                "suggested_position_range": "40%-58%" if volatility_bucket == "high" else "45%-65%",
                "message": "低于平衡区下沿，建议适度增加仓位。",
                "state_key": "below_balanced",
                "state_label": "偏低区",
            }
        elif b_high is not None and cp <= b_high:
            payload = dict(default_payload)
        elif a_high is not None and cp <= a_high:
            payload = {
                "suggested_position_range": "20%-35%" if volatility_bucket == "high" else "25%-40%",
                "message": "处于偏高区间，建议逐步降仓。",
                "state_key": "within_aggressive",
                "state_label": "偏高区",
            }
        else:
            payload = {
                "suggested_position_range": "12%-25%" if volatility_bucket == "high" else "15%-30%",
                "message": "高于进攻区上沿，建议防守并降低仓位。",
                "state_key": "above_aggressive",
                "state_label": "高估区",
            }

    summary = f"{style_label} | {volatility_label} | {payload['state_label']} | 建议 {payload['suggested_position_range']}"
    payload.update({
        "style_key": style_key_normalized,
        "style_label": style_label,
        "volatility_bucket": volatility_bucket,
        "volatility_label": volatility_label,
        "industry_name": industry_name or "",
        "holding_summary": summary,
    })
    return payload


def _build_traditional_tiered_template(
    *,
    variant_rows,
    summary_payload,
    current_price,
    industry_name,
    industry_code,
    indicator_profile,
    ts_code,
    freq="D",
):
    cp = _to_float_or_none(current_price)
    if cp is None or cp <= 0:
        return None

    method_price_map_raw = {}
    for row in (variant_rows or []):
        method = _normalize_valuation_method_name((row or {}).get("valuation_method"))
        price = _to_float_or_none((row or {}).get("valuation_price"))
        if not method or price is None or price <= 0:
            continue
        method_price_map_raw[method] = float(price)
    if not method_price_map_raw:
        return None

    method_price_map, winsor_meta = _winsorize_method_price_map(method_price_map_raw, rules=TRADITIONAL_METHOD_WINSOR_RULES)
    style_key, style_score, style_reasons = _resolve_traditional_style(
        industry_name=industry_name,
        indicator_profile=indicator_profile or {},
        method_price_map=method_price_map,
        industry_code=industry_code,
    )
    scheme_key, matched_keyword = _resolve_traditional_scheme_key(style_key, industry_name)
    scheme = TRADITIONAL_TIER_SCHEMES.get(scheme_key) or TRADITIONAL_TIER_SCHEMES["balanced"]

    tier_payload = {}
    for tier_key in ["conservative", "balanced", "aggressive"]:
        tier_cfg = ((scheme or {}).get("tiers") or {}).get(tier_key) or {}
        weights = tier_cfg.get("weights") or {}
        target_price, coverage_ratio, used_methods = _weighted_template_target(method_price_map, weights)
        lower_multiplier, upper_multiplier = tier_cfg.get("range_multiplier") or (0.95, 1.08)
        lower = round(target_price * float(lower_multiplier), 4) if target_price is not None else None
        upper = round(target_price * float(upper_multiplier), 4) if target_price is not None else None
        return_pct = None
        if target_price is not None and cp > 0:
            return_pct = round(((target_price / cp) - 1.0) * 100.0, 2)
        tier_payload[tier_key] = {
            "label": tier_cfg.get("label") or tier_key,
            "target_price": round(target_price, 4) if target_price is not None else None,
            "expected_return_pct": return_pct,
            "range": {"lower": lower, "upper": upper},
            "coverage_ratio": coverage_ratio,
            "used_methods": used_methods,
            "weights": {k: round(float(v), 4) for k, v in (weights or {}).items()},
        }

    volatility_profile = _load_traditional_volatility_profile(ts_code=ts_code, current_price=cp, freq=freq) if ts_code else None
    monotonic_meta = _enforce_monotonic_tier_targets(tier_payload, scheme, cp)
    spacing_meta = _apply_tier_min_gap_constraints(
        tier_payload=tier_payload,
        scheme=scheme,
        current_price=cp,
        style_key=style_key,
        volatility_profile=volatility_profile,
        method_price_map=method_price_map,
    )
    guidance = _resolve_position_guidance(
        current_price=cp,
        conservative_range=(tier_payload.get("conservative") or {}).get("range"),
        balanced_range=(tier_payload.get("balanced") or {}).get("range"),
        aggressive_range=(tier_payload.get("aggressive") or {}).get("range"),
        style_key=style_key,
        industry_name=industry_name,
        volatility_profile=volatility_profile,
    )

    reference_composite = _to_float_or_none((summary_payload or {}).get("composite_valuation_price"))
    reference_conservative = _to_float_or_none((summary_payload or {}).get("conservative_valuation_price"))

    return {
        "enabled": True,
        "style_key": style_key,
        "style_label": scheme.get("style_label") or style_key,
        "scheme_key": scheme_key,
        "industry_scheme_override_keyword": matched_keyword,
        "style_score": style_score,
        "style_reasons": style_reasons,
        "industry_name": industry_name or "",
        "industry_code": industry_code or None,
        "indicator_profile": {
            "roe": _to_float_or_none((indicator_profile or {}).get("roe")),
            "gross_margin": _to_float_or_none((indicator_profile or {}).get("gross_margin")),
            "debt_to_assets": _to_float_or_none((indicator_profile or {}).get("debt_to_assets")),
            "indicator_end_date": (indicator_profile or {}).get("indicator_end_date"),
        },
        "method_prices": {k: round(float(v), 4) for k, v in (method_price_map or {}).items()},
        "method_prices_raw": {k: round(float(v), 4) for k, v in (method_price_map_raw or {}).items()},
        "winsorization": winsor_meta,
        "tier_monotonicity": monotonic_meta,
        "tier_spacing": spacing_meta,
        "tiers": tier_payload,
        "position_guidance": guidance,
        "volatility_profile": volatility_profile,
        "holding_summary": guidance.get("holding_summary"),
        "reference": {
            "current_price": cp,
            "traditional_composite_price": reference_composite,
            "traditional_conservative_price": reference_conservative,
        },
    }


def _build_traditional_variant_weights(
    traditional_tiered_template_by_variant,
    valuation_variants,
    active_variant,
):
    template_map = traditional_tiered_template_by_variant or {}
    if not template_map:
        return {}, []

    meta_map = {
        str(item.get("valuation_variant") or ""): item
        for item in (valuation_variants or [])
        if isinstance(item, dict)
    }
    raw_items = []
    for variant, template in template_map.items():
        if not isinstance(template, dict):
            continue
        variant_key = str(variant or "")
        meta = meta_map.get(variant_key, {})
        compare_group = str((meta or {}).get("compare_group") or "").strip().lower()
        match_score = _to_float_or_none((meta or {}).get("match_score"))
        if match_score is None:
            if compare_group == "business_match":
                match_score = 30.0
            elif compare_group == "sw_l3_baseline":
                match_score = 45.0
            elif variant_key == "default":
                match_score = 35.0
            else:
                match_score = 25.0

        match_component = _clip_float(float(match_score) / 100.0, lower=0.12, upper=1.0)
        coverage = _to_float_or_none((((template.get("tiers") or {}).get("balanced") or {}).get("coverage_ratio")))
        coverage_component = _clip_float(coverage if coverage is not None else 0.55, lower=0.2, upper=1.0)
        style_score = _to_float_or_none(template.get("style_score"))
        quality_component = _clip_float((style_score / 100.0) if style_score is not None else 0.72, lower=0.35, upper=1.0)

        group_bias = 1.0
        if compare_group == "business_match":
            group_bias = 1.12
            if match_score >= 60.0:
                group_bias += 0.08
            elif match_score >= 45.0:
                group_bias += 0.04
        elif compare_group == "sw_l3_baseline":
            group_bias = 1.06
        elif variant_key == "default":
            group_bias = 1.03
        active_bias = 1.06 if variant_key == str(active_variant or "") else 1.0

        raw_weight = float(match_component) * float(coverage_component) * float(quality_component) * group_bias * active_bias
        raw_items.append(
            {
                "valuation_variant": variant_key,
                "raw_weight": max(0.0001, float(raw_weight)),
                "match_score": round(float(match_score), 4),
                "coverage_component": round(float(coverage_component), 4),
                "quality_component": round(float(quality_component), 4),
                "group_bias": round(float(group_bias), 4),
                "compare_group": compare_group or None,
            }
        )

    if not raw_items:
        return {}, []

    total_raw = sum(item.get("raw_weight", 0.0) for item in raw_items) or 1.0
    normalized = {}
    detail_rows = []
    for item in raw_items:
        variant_key = item["valuation_variant"]
        weight = float(item.get("raw_weight", 0.0)) / float(total_raw)
        normalized[variant_key] = round(weight, 6)
        detail = dict(item)
        detail["weight"] = round(weight, 6)
        detail_rows.append(detail)
    detail_rows.sort(key=lambda x: -float(x.get("weight") or 0.0))
    return normalized, detail_rows


def _blend_traditional_tiered_template(
    traditional_tiered_template_by_variant,
    valuation_variants,
    active_variant,
):
    template_map = traditional_tiered_template_by_variant or {}
    if not template_map:
        return None

    if active_variant in template_map and len(template_map) == 1:
        single = dict(template_map.get(active_variant) or {})
        single["variant_weights"] = {str(active_variant or "default"): 1.0}
        single["variant_weights_detail"] = [
            {"valuation_variant": str(active_variant or "default"), "weight": 1.0}
        ]
        single["blend"] = {
            "enabled": True,
            "applied": False,
            "reason": "single_variant",
            "dominant_variant": str(active_variant or "default"),
        }
        return single

    variant_weights, variant_weight_rows = _build_traditional_variant_weights(
        traditional_tiered_template_by_variant=template_map,
        valuation_variants=valuation_variants,
        active_variant=active_variant,
    )
    if not variant_weights:
        return template_map.get(active_variant)

    dominant_variant = max(variant_weights.keys(), key=lambda key: float(variant_weights.get(key) or 0.0))
    dominant_template = dict(template_map.get(dominant_variant) or {})
    blended_template = dict(dominant_template)

    cp = _to_float_or_none(((dominant_template.get("reference") or {}).get("current_price")))
    tiers = {}
    for tier_key in ["conservative", "balanced", "aggressive"]:
        target_acc = 0.0
        lower_acc = 0.0
        upper_acc = 0.0
        coverage_acc = 0.0
        weights_acc = {}
        methods_set = set()
        has_value = False
        label = ((dominant_template.get("tiers") or {}).get(tier_key) or {}).get("label") or tier_key

        for variant, weight in variant_weights.items():
            tpl = template_map.get(variant) or {}
            tier_payload = (tpl.get("tiers") or {}).get(tier_key) or {}
            target = _to_float_or_none(tier_payload.get("target_price"))
            lower = _to_float_or_none((tier_payload.get("range") or {}).get("lower"))
            upper = _to_float_or_none((tier_payload.get("range") or {}).get("upper"))
            coverage = _to_float_or_none(tier_payload.get("coverage_ratio"))
            if target is None:
                continue
            has_value = True
            w = float(weight)
            target_acc += float(target) * w
            lower_acc += float(lower if lower is not None else target) * w
            upper_acc += float(upper if upper is not None else target) * w
            coverage_acc += float(coverage if coverage is not None else 0.0) * w
            for method in (tier_payload.get("used_methods") or []):
                methods_set.add(str(method))
            for method, method_weight in (tier_payload.get("weights") or {}).items():
                val = _to_float_or_none(method_weight)
                if val is None:
                    continue
                weights_acc[method] = float(weights_acc.get(method, 0.0)) + float(val) * w

        if not has_value:
            continue

        expected_return_pct = None
        if cp is not None and cp > 0:
            expected_return_pct = round(((target_acc / cp) - 1.0) * 100.0, 2)
        tiers[tier_key] = {
            "label": label,
            "target_price": round(float(target_acc), 4),
            "expected_return_pct": expected_return_pct,
            "range": {
                "lower": round(float(lower_acc), 4),
                "upper": round(float(upper_acc), 4),
            },
            "coverage_ratio": round(float(coverage_acc), 4),
            "used_methods": sorted(methods_set),
            "weights": {
                key: round(float(val), 4)
                for key, val in sorted(weights_acc.items(), key=lambda x: -x[1])
            },
        }

    if not tiers:
        return template_map.get(active_variant)

    blended_template["tiers"] = tiers
    blended_template["style_key"] = dominant_template.get("style_key")
    blended_template["style_label"] = dominant_template.get("style_label")
    blended_template["scheme_key"] = dominant_template.get("scheme_key")
    blended_template["industry_name"] = dominant_template.get("industry_name")
    blended_template["industry_code"] = dominant_template.get("industry_code")
    blended_template["variant_weights"] = variant_weights
    blended_template["variant_weights_detail"] = variant_weight_rows
    blended_template["blend"] = {
        "enabled": True,
        "applied": True,
        "dominant_variant": dominant_variant,
        "active_variant": str(active_variant or "default"),
        "variant_count": len(variant_weights),
    }

    scheme_key = str(blended_template.get("scheme_key") or "balanced").strip().lower()
    scheme = TRADITIONAL_TIER_SCHEMES.get(scheme_key) or TRADITIONAL_TIER_SCHEMES.get("balanced")
    monotonic_meta = _enforce_monotonic_tier_targets(blended_template.get("tiers") or {}, scheme, cp)
    spacing_meta = _apply_tier_min_gap_constraints(
        tier_payload=blended_template.get("tiers") or {},
        scheme=scheme,
        current_price=cp,
        style_key=blended_template.get("style_key"),
        volatility_profile=blended_template.get("volatility_profile") or {},
        method_price_map=blended_template.get("method_prices") or {},
    )
    guidance = _resolve_position_guidance(
        current_price=cp,
        conservative_range=((blended_template.get("tiers") or {}).get("conservative") or {}).get("range"),
        balanced_range=((blended_template.get("tiers") or {}).get("balanced") or {}).get("range"),
        aggressive_range=((blended_template.get("tiers") or {}).get("aggressive") or {}).get("range"),
        style_key=blended_template.get("style_key"),
        industry_name=blended_template.get("industry_name"),
        volatility_profile=blended_template.get("volatility_profile") or {},
    )
    blended_template["tier_monotonicity"] = monotonic_meta
    blended_template["tier_spacing"] = spacing_meta
    blended_template["position_guidance"] = guidance
    blended_template["holding_summary"] = guidance.get("holding_summary")
    return blended_template


def _clip_float(value, *, lower=None, upper=None):
    if value is None:
        return None
    clipped = float(value)
    if lower is not None:
        clipped = max(float(lower), clipped)
    if upper is not None:
        clipped = min(float(upper), clipped)
    return clipped


def _calc_return_pct_simple(current_price, target_price):
    current = _to_float_or_none(current_price)
    target = _to_float_or_none(target_price)
    if current is None or current <= 0 or target is None:
        return None
    return round((target / current - 1.0) * 100.0, 2)


def _calc_target_price_from_return_pct(current_price, return_pct):
    current = _to_float_or_none(current_price)
    pct = _to_float_or_none(return_pct)
    if current is None or current <= 0 or pct is None:
        return None
    return round(current * (1.0 + pct / 100.0), 4)


def _resolve_trade_anchor_on_or_after(ts_code, start_date, *, freq="D", upper_bound=None):
    normalized_ts_code = str(ts_code or "").strip().upper()
    normalized_start = _parse_date_like(start_date)
    normalized_upper = _parse_date_like(upper_bound)
    if not normalized_ts_code or normalized_start is None:
        return None

    qs = StockTradingHistory.objects.filter(
        ts_code=normalized_ts_code,
        freq=str(freq or "D").strip().upper() or "D",
        trade_date__gte=normalized_start,
    )
    if normalized_upper is not None:
        qs = qs.filter(trade_date__lte=normalized_upper)

    row = qs.order_by("trade_date").values("trade_date").first()
    if row:
        return _parse_date_like(row.get("trade_date"))
    return None


def _resolve_predictive_anchor_trade_date(payload, *, latest_trade_date=None, anchor_mode="ann"):
    normalized_payload = payload if isinstance(payload, dict) else {}
    normalized_anchor_mode = _normalize_predict_anchor_mode(anchor_mode)
    latest_date = _parse_date_like(latest_trade_date)
    asof_date = _parse_date_like(normalized_payload.get("asof_date"))
    if normalized_anchor_mode != "ann":
        return asof_date or latest_date

    ts_code = str(normalized_payload.get("ts_code") or "").strip().upper()
    ann_date = _parse_date_like(normalized_payload.get("financial_ann_date"))
    if ts_code and ann_date is not None:
        aligned_trade_date = _resolve_trade_anchor_on_or_after(
            ts_code,
            ann_date,
            freq="D",
            upper_bound=latest_date,
        )
        if aligned_trade_date is not None:
            return aligned_trade_date

    return ann_date or asof_date or latest_date


def _compute_predictive_reliability_weight(signal_score=None, stale_days=None):
    score = _to_float_or_none(signal_score)
    stale = _to_float_or_none(stale_days)

    score_component = 1.0
    if score is not None:
        normalized_score = _clip_float(score / 100.0, lower=0.0, upper=1.0)
        score_component = 0.35 + normalized_score * 0.65

    stale_component = 1.0
    if stale is not None and stale >= 0:
        half_life = max(PREDICTIVE_RETURN_STALE_HALF_LIFE_DAYS, 1.0)
        stale_component = 1.0 / (1.0 + float(stale) / half_life)
        stale_component = _clip_float(stale_component, lower=0.55, upper=1.0)

    reliability = score_component * stale_component
    return _clip_float(
        reliability,
        lower=PREDICTIVE_RETURN_SHRINK_WEIGHT_MIN,
        upper=PREDICTIVE_RETURN_SHRINK_WEIGHT_MAX,
    )


def _apply_predictive_return_optimization(
    raw_return_pct,
    *,
    traditional_return_pct=None,
    signal_score=None,
    stale_days=None,
):
    raw = _to_float_or_none(raw_return_pct)
    if raw is None:
        return None

    optimized = raw
    if PREDICTIVE_RETURN_ROBUSTNESS_ENABLED:
        optimized = _clip_float(
            optimized,
            lower=PREDICTIVE_RETURN_MIN_PCT,
            upper=PREDICTIVE_RETURN_MAX_PCT,
        )

        traditional = _to_float_or_none(traditional_return_pct)
        if traditional is not None:
            divergence_cap = max(PREDICTIVE_RETURN_DIVERGENCE_CAP_PCT, 0.0)
            lower_bound = traditional - divergence_cap
            upper_bound = traditional + divergence_cap
            optimized = _clip_float(optimized, lower=lower_bound, upper=upper_bound)

        reliability = _compute_predictive_reliability_weight(
            signal_score=signal_score,
            stale_days=stale_days,
        )
        optimized = float(optimized) * float(reliability)

    if PREDICTIVE_RETURN_CALIBRATION_ENABLED:
        optimized = PREDICTIVE_RETURN_CALIBRATION_BIAS + PREDICTIVE_RETURN_CALIBRATION_SLOPE * float(optimized)

    optimized = _clip_float(
        optimized,
        lower=PREDICTIVE_RETURN_MIN_PCT,
        upper=PREDICTIVE_RETURN_MAX_PCT,
    )
    return round(float(optimized), 2)


def _compute_traditional_price_stats(rows, price_key="valuation_price"):
    prices = []
    method_count = 0
    for row in rows or []:
        method = _normalize_valuation_method_name((row or {}).get("valuation_method"))
        if not method or method == "market_style":
            continue
        price = _to_float_or_none((row or {}).get(price_key))
        if price is None or price <= 0:
            continue
        method_count += 1
        prices.append(float(price))

    if not prices:
        return {
            "method_count": 0,
            "min_price": None,
            "max_price": None,
            "avg_price": None,
            "dispersion_ratio": None,
        }

    min_price = min(prices)
    max_price = max(prices)
    avg_price = sum(prices) / len(prices)
    dispersion_ratio = None
    if avg_price and avg_price > 0:
        dispersion_ratio = (max_price - min_price) / avg_price

    return {
        "method_count": method_count,
        "min_price": min_price,
        "max_price": max_price,
        "avg_price": avg_price,
        "dispersion_ratio": dispersion_ratio,
    }


def _compute_traditional_reliability_weight(method_count=None, dispersion_ratio=None, risk_score=None):
    count = int(method_count or 0)
    dispersion = _to_float_or_none(dispersion_ratio)
    risk = _to_float_or_none(risk_score)

    coverage_component = 0.45 + min(max(count, 0), 4) * 0.1
    coverage_component = _clip_float(coverage_component, lower=0.45, upper=0.85)

    dispersion_component = 1.0
    if dispersion is not None and dispersion >= 0:
        ref = max(TRADITIONAL_RETURN_DISPERSION_REF, 0.05)
        dispersion_component = 1.0 / (1.0 + float(dispersion) / ref)
        dispersion_component = _clip_float(dispersion_component, lower=0.5, upper=1.0)

    risk_component = 1.0
    if risk is not None and risk >= 0:
        normalized_risk = _clip_float(risk / 100.0, lower=0.0, upper=1.0)
        risk_component = 1.0 - normalized_risk * 0.45
        risk_component = _clip_float(risk_component, lower=0.55, upper=1.0)

    reliability = coverage_component * dispersion_component * risk_component
    return _clip_float(
        reliability,
        lower=TRADITIONAL_RETURN_SHRINK_WEIGHT_MIN,
        upper=TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX,
    )


def _apply_traditional_return_optimization(raw_return_pct, *, reliability_weight=None):
    raw = _to_float_or_none(raw_return_pct)
    if raw is None:
        return None

    optimized = raw
    if TRADITIONAL_RETURN_OPTIMIZATION_ENABLED:
        weight = _to_float_or_none(reliability_weight)
        if weight is None:
            weight = TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX
        weight = _clip_float(
            weight,
            lower=TRADITIONAL_RETURN_SHRINK_WEIGHT_MIN,
            upper=TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX,
        )
        optimized = float(optimized) * float(weight)

    if TRADITIONAL_RETURN_CALIBRATION_ENABLED:
        optimized = TRADITIONAL_RETURN_CALIBRATION_BIAS + TRADITIONAL_RETURN_CALIBRATION_SLOPE * float(optimized)

    optimized = _clip_float(
        optimized,
        lower=TRADITIONAL_RETURN_MIN_PCT,
        upper=TRADITIONAL_RETURN_MAX_PCT,
    )
    return round(float(optimized), 2)


def _build_traditional_summary_optimized(
    summary_payload,
    *,
    variant_rows,
    current_price,
    band_pct,
    risk_payload=None,
    stats_price_key="valuation_price",
):
    summary_raw = dict(summary_payload or {})
    summary_opt = dict(summary_raw)

    stats = _compute_traditional_price_stats(variant_rows, price_key=stats_price_key)
    risk_score = _to_float_or_none((risk_payload or {}).get("risk_score"))
    reliability = _compute_traditional_reliability_weight(
        method_count=stats.get("method_count"),
        dispersion_ratio=stats.get("dispersion_ratio"),
        risk_score=risk_score,
    )

    def _apply_for_prefix(prefix):
        price_key = f"{prefix}_price"
        status_key = f"{prefix}_status"
        gap_key = f"{prefix}_gap_pct"

        raw_price = _to_float_or_none(summary_raw.get(price_key))
        raw_return = _calc_return_pct_simple(current_price, raw_price)
        opt_return = _apply_traditional_return_optimization(raw_return, reliability_weight=reliability)
        opt_price = _calc_target_price_from_return_pct(current_price, opt_return)
        opt_status, opt_gap = _classify_valuation(current_price, opt_price, band_pct)

        summary_opt[f"{price_key}_raw"] = round(float(raw_price), 4) if raw_price is not None else None
        summary_opt[f"{prefix}_return_pct_raw"] = raw_return
        summary_opt[f"{price_key}_optimized"] = round(float(opt_price), 4) if opt_price is not None else None
        summary_opt[f"{prefix}_return_pct_optimized"] = opt_return
        summary_opt[f"{status_key}_optimized"] = opt_status if opt_price is not None else "unknown"
        summary_opt[f"{gap_key}_optimized"] = round(opt_gap * 100, 2) if opt_gap is not None else None

    _apply_for_prefix("composite_valuation")
    _apply_for_prefix("conservative_valuation")
    if (
        "market_style_valuation_price" in summary_raw
        or "market_style_valuation_status" in summary_raw
        or "market_style_valuation_gap_pct" in summary_raw
    ):
        _apply_for_prefix("market_style_valuation")

    summary_opt["traditional_optimization_meta"] = {
        "enabled": TRADITIONAL_RETURN_OPTIMIZATION_ENABLED,
        "method_count": stats.get("method_count"),
        "dispersion_ratio": round(float(stats.get("dispersion_ratio")), 6)
        if stats.get("dispersion_ratio") is not None
        else None,
        "risk_score": risk_score,
        "reliability_weight": round(float(reliability), 4) if reliability is not None else None,
    }
    return summary_opt


def _build_earnings_dual_target_payload(earnings_payload, *, current_price=None, latest_trade_date=None, anchor_mode="ann"):
    if not isinstance(earnings_payload, dict):
        return earnings_payload

    payload = dict(earnings_payload)

    target_price_raw = _to_float_or_none(payload.get("target_price"))
    target_price_low_raw = _to_float_or_none(payload.get("target_price_low"))
    target_price_high_raw = _to_float_or_none(payload.get("target_price_high"))
    target_market_cap_raw = _to_float_or_none(payload.get("target_market_cap"))
    target_market_cap_low_raw = _to_float_or_none(payload.get("target_market_cap_low"))
    target_market_cap_high_raw = _to_float_or_none(payload.get("target_market_cap_high"))

    target_return_raw = _to_float_or_none(payload.get("target_return_pct"))
    if target_return_raw is None:
        target_return_raw = _calc_return_pct_simple(current_price, target_price_raw)

    target_return_low_raw = _to_float_or_none(payload.get("target_return_low_pct"))
    if target_return_low_raw is None:
        target_return_low_raw = _calc_return_pct_simple(current_price, target_price_low_raw)

    target_return_high_raw = _to_float_or_none(payload.get("target_return_high_pct"))
    if target_return_high_raw is None:
        target_return_high_raw = _calc_return_pct_simple(current_price, target_price_high_raw)

    signal_score = _to_float_or_none(payload.get("signal_score"))
    ann_date = _parse_date_like(payload.get("financial_ann_date"))
    anchor_date = _parse_date_like(latest_trade_date)
    stale_days = None
    if ann_date is not None and anchor_date is not None:
        stale_days = max((anchor_date - ann_date).days, 0)

    anchor_trade_date = _resolve_predictive_anchor_trade_date(
        payload,
        latest_trade_date=latest_trade_date,
        anchor_mode=anchor_mode,
    )
    anchor_close_price = None
    anchor_ts_code = str(payload.get("ts_code") or "").strip().upper()
    if anchor_ts_code and anchor_trade_date is not None:
        anchor_trade_row = (
            StockTradingHistory.objects.filter(ts_code=anchor_ts_code, freq="D", trade_date=anchor_trade_date)
            .values("close_qfq", "close")
            .first()
        )
        anchor_close_price = _to_float_or_none((anchor_trade_row or {}).get("close_qfq"))
        if anchor_close_price is None:
            anchor_close_price = _to_float_or_none((anchor_trade_row or {}).get("close"))

    def _derive_basis_value(raw_target_value, raw_return_value, fallback_value):
        target_val = _to_float_or_none(raw_target_value)
        return_val = _to_float_or_none(raw_return_value)
        fallback_val = _to_float_or_none(fallback_value)
        if target_val is not None and return_val is not None:
            denom = 1.0 + float(return_val) / 100.0
            if abs(denom) > 1e-9:
                return float(target_val) / denom
        return fallback_val

    def _calc_target_value_from_return_pct(current_value, return_pct):
        current_val = _to_float_or_none(current_value)
        return_val = _to_float_or_none(return_pct)
        if current_val in (None, 0) or return_val is None:
            return None
        return round(float(current_val) * (1.0 + float(return_val) / 100.0), 4)

    target_return_opt = _apply_predictive_return_optimization(
        target_return_raw,
        traditional_return_pct=None,
        signal_score=signal_score,
        stale_days=stale_days,
    )
    target_return_low_opt = _apply_predictive_return_optimization(
        target_return_low_raw,
        traditional_return_pct=None,
        signal_score=signal_score,
        stale_days=stale_days,
    )
    target_return_high_opt = _apply_predictive_return_optimization(
        target_return_high_raw,
        traditional_return_pct=None,
        signal_score=signal_score,
        stale_days=stale_days,
    )

    payload["target_return_pct_raw"] = target_return_raw
    payload["target_return_low_pct_raw"] = target_return_low_raw
    payload["target_return_high_pct_raw"] = target_return_high_raw
    payload["target_return_pct_anchor"] = _calc_return_pct_simple(anchor_close_price, target_price_raw)
    payload["target_return_low_pct_anchor"] = _calc_return_pct_simple(anchor_close_price, target_price_low_raw)
    payload["target_return_high_pct_anchor"] = _calc_return_pct_simple(anchor_close_price, target_price_high_raw)
    payload["target_return_pct_optimized"] = target_return_opt
    payload["target_return_low_pct_optimized"] = target_return_low_opt
    payload["target_return_high_pct_optimized"] = target_return_high_opt
    payload["anchor_close_price"] = anchor_close_price
    payload["anchor_trade_date"] = anchor_trade_date.strftime("%Y-%m-%d") if anchor_trade_date is not None else None

    payload["target_price_raw"] = target_price_raw
    payload["target_price_low_raw"] = target_price_low_raw
    payload["target_price_high_raw"] = target_price_high_raw
    payload["target_market_cap_raw"] = target_market_cap_raw
    payload["target_market_cap_low_raw"] = target_market_cap_low_raw
    payload["target_market_cap_high_raw"] = target_market_cap_high_raw

    main_price_basis = _derive_basis_value(target_price_raw, target_return_raw, current_price)
    low_price_basis = _derive_basis_value(target_price_low_raw, target_return_low_raw, current_price)
    high_price_basis = _derive_basis_value(target_price_high_raw, target_return_high_raw, current_price)
    main_market_cap_basis = _derive_basis_value(target_market_cap_raw, target_return_raw, target_market_cap_raw)
    low_market_cap_basis = _derive_basis_value(target_market_cap_low_raw, target_return_low_raw, target_market_cap_raw)
    high_market_cap_basis = _derive_basis_value(target_market_cap_high_raw, target_return_high_raw, target_market_cap_raw)

    payload["target_return_pct_anchor_optimized"] = _calc_return_pct_simple(anchor_close_price, _calc_target_value_from_return_pct(main_price_basis, target_return_opt))
    payload["target_return_low_pct_anchor_optimized"] = _calc_return_pct_simple(anchor_close_price, _calc_target_value_from_return_pct(low_price_basis, target_return_low_opt))
    payload["target_return_high_pct_anchor_optimized"] = _calc_return_pct_simple(anchor_close_price, _calc_target_value_from_return_pct(high_price_basis, target_return_high_opt))

    payload["target_price_optimized"] = _calc_target_value_from_return_pct(main_price_basis, target_return_opt)
    payload["target_price_low_optimized"] = _calc_target_value_from_return_pct(low_price_basis, target_return_low_opt)
    payload["target_price_high_optimized"] = _calc_target_value_from_return_pct(high_price_basis, target_return_high_opt)
    payload["target_market_cap_optimized"] = _calc_target_value_from_return_pct(main_market_cap_basis, target_return_opt)
    payload["target_market_cap_low_optimized"] = _calc_target_value_from_return_pct(low_market_cap_basis, target_return_low_opt)
    payload["target_market_cap_high_optimized"] = _calc_target_value_from_return_pct(high_market_cap_basis, target_return_high_opt)

    return payload


def _normalize_earnings_report_type(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    alias = {
        "ANNUAL": "FY",
        "FULL_YEAR": "FY",
        "A": "FY",
        "EXP": "FUSION",
        "EXPRESS": "FUSION",
        "σ┐½": "FUSION",
    }
    normalized = alias.get(text, text)
    if normalized in {"Q1", "H1", "Q3", "FY", "FUSION"}:
        return normalized
    return ""


def _normalize_earnings_report_type_with_all(value):
    text = str(value or "").strip().upper()
    if not text:
        return "ALL"
    if text == "ALL":
        return "ALL"
    normalized = _normalize_earnings_report_type(text)
    return normalized or "ALL"


def _normalize_predict_anchor_mode(value):
    text = str(value or "").strip().lower()
    if text == "live":
        return "live"
    return "ann"


def _normalize_valuation_profit_report_type(value):
    text = str(value or "").strip().upper()
    if not text or text == "ALL":
        return ""

    alias = {
        "FY": "ANNUAL",
        "ANNUAL": "ANNUAL",
        "FULL_YEAR": "ANNUAL",
        "A": "ANNUAL",
    }
    normalized = alias.get(text, text)
    if normalized in {"Q1", "H1", "Q3", "ANNUAL", "OTHER"}:
        return normalized
    return ""


def _resolve_valuation_report_end_date(report_type, explicit_value=None, fiscal_year_value=None):
    text = str(explicit_value or "").strip()
    if text:
        normalized = text.replace("/", "-")
        if re.fullmatch(r"\d{8}", normalized):
            normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:8]}"
        try:
            return datetime.datetime.strptime(normalized, "%Y-%m-%d").date()
        except ValueError:
            return None

    fiscal_year_text = str(fiscal_year_value or "").strip()
    if not fiscal_year_text.isdigit():
        return None

    suffix_map = {
        "Q1": "03-31",
        "H1": "06-30",
        "Q3": "09-30",
        "ANNUAL": "12-31",
    }
    suffix = suffix_map.get(report_type)
    if not suffix:
        return None
    return datetime.datetime.strptime(f"{fiscal_year_text}-{suffix}", "%Y-%m-%d").date()


def _map_valuation_report_type_to_panel_type(report_type):
    normalized = str(report_type or "").strip().upper()
    if normalized == "ANNUAL":
        return "FY"
    return normalized


def _resolve_expected_end_date_for_report_type(report_type, anchor_trade_date=None):
    normalized_report_type = str(report_type or "").strip().upper()
    normalized_trade_date = _parse_date_like(anchor_trade_date)
    if normalized_trade_date is None:
        return None

    year = int(normalized_trade_date.year)
    if normalized_report_type == "Q1":
        return datetime.date(year, 3, 31)
    if normalized_report_type == "H1":
        return datetime.date(year, 6, 30)
    if normalized_report_type == "Q3":
        return datetime.date(year, 9, 30)
    if normalized_report_type == "FY":
        return datetime.date(year - 1, 12, 31)
    return None


def _resolve_valuation_report_end_date_from_feature_panel(ts_code, report_type, asof_date=None):
    resolved_end_date, _resolved_ann_date = _resolve_valuation_report_meta_from_feature_panel(
        ts_code=ts_code,
        report_type=report_type,
        asof_date=asof_date,
    )
    return resolved_end_date


def _resolve_valuation_report_meta_from_feature_panel(ts_code, report_type, asof_date=None):
    normalized_ts_code = str(ts_code or "").strip().upper()
    panel_report_type = _map_valuation_report_type_to_panel_type(report_type)
    if not normalized_ts_code or panel_report_type not in {"Q1", "H1", "Q3", "FY"}:
        return None, None

    # Resolve target period from formal income statements only. Feature panel may
    # expose future period keys populated by forecast/express signals.
    suffix_map = {
        "Q1": "0331",
        "H1": "0630",
        "Q3": "0930",
        "FY": "1231",
    }
    report_suffix = suffix_map.get(panel_report_type)
    if not report_suffix:
        return None, None

    params = [normalized_ts_code, report_suffix]
    sql = """
        SELECT end_date, ann_date
        FROM earnings_fin_income
        WHERE ts_code = %s
          AND RIGHT(CAST(end_date AS TEXT), 4) = %s
    """
    normalized_asof_date = _parse_date_like(asof_date)
    if normalized_asof_date is not None:
        sql += " AND ann_date <= %s"
        params.append(normalized_asof_date.strftime("%Y%m%d"))
    sql += " ORDER BY ann_date DESC, end_date DESC LIMIT 1"

    try:
        df = query_local_financial_df(sql, params)
    except Exception:
        return None, None
    if df is None or df.empty:
        return None, None
    return _parse_date_like(df.iloc[0].get("end_date")), _parse_date_like(df.iloc[0].get("ann_date"))


def _resolve_valuation_report_end_date_from_snapshot_latest(
    ts_code,
    report_type,
    market="CN",
    asof_date=None,
):
    normalized_ts_code = str(ts_code or "").strip().upper()
    panel_report_type = _map_valuation_report_type_to_panel_type(report_type)
    if not normalized_ts_code or panel_report_type not in {"Q1", "H1", "Q3", "FY"}:
        return None

    snapshot_qs = StockValuationSnapshotLatest.objects.filter(
        ts_code=normalized_ts_code,
        market=str(market or "CN").strip() or "CN",
        profit_report_type=panel_report_type,
    )
    normalized_asof_date = _parse_date_like(asof_date)
    if normalized_asof_date is not None:
        snapshot_qs = snapshot_qs.filter(latest_trade_date__lte=normalized_asof_date)

    row = (
        snapshot_qs.order_by("-profit_report_end_date", "-latest_trade_date", "-updated_at")
        .values("profit_report_end_date")
        .first()
    )
    if not row:
        return None
    return _parse_date_like(row.get("profit_report_end_date"))


def _infer_report_type_from_end_date(end_date):
    normalized = _parse_date_like(end_date)
    if normalized is None:
        return ""
    month_day = normalized.strftime("%m-%d")
    if month_day == "03-31":
        return "Q1"
    if month_day == "06-30":
        return "H1"
    if month_day == "09-30":
        return "Q3"
    if month_day == "12-31":
        return "FY"
    return ""


def _resolve_latest_report_meta_from_feature_panel(ts_code, asof_date=None):
    normalized_ts_code = str(ts_code or "").strip().upper()
    if not normalized_ts_code:
        return "", None

    params = [normalized_ts_code]
    sql = """
        SELECT end_date, ann_date
        FROM earnings_fin_income
        WHERE ts_code = %s
    """
    normalized_asof_date = _parse_date_like(asof_date)
    if normalized_asof_date is not None:
        sql += " AND ann_date <= %s"
        params.append(normalized_asof_date.strftime("%Y%m%d"))
    sql += " ORDER BY ann_date DESC, end_date DESC LIMIT 1"

    try:
        df = query_local_financial_df(sql, params)
    except Exception:
        return "", None
    if df is None or df.empty:
        return "", None

    resolved_end_date = _parse_date_like(df.iloc[0].get("end_date"))
    if resolved_end_date is None:
        return "", None
    resolved_report_type = _infer_report_type_from_end_date(resolved_end_date)
    return resolved_report_type, resolved_end_date


def _normalize_predictive_mode(value):
    text = str(value or "").strip().lower()
    if text in {"predictive", "prediction", "earnings", "forecast"}:
        return "predictive"
    return "baseline"


def _normalize_optional_choice(value, valid_choices):
    text = str(value or "").strip().upper()
    if not text or text == "ALL":
        return ""
    return text if text in valid_choices else ""


def _canonicalize_risk_level(value):
    text = str(value or "").strip().upper()
    mapping = {
        "L": "LOW",
        "M": "MEDIUM",
        "H": "HIGH",
        "Σ╜Ä": "LOW",
        "Σ╕¡": "MEDIUM",
        "Θ½ÿ": "HIGH",
    }
    text = mapping.get(text, text)
    return text if text in {"LOW", "MEDIUM", "HIGH"} else ""


def _normalize_risk_level_filters(value):
    tokens = [str(item or "").strip() for item in str(value or "").split(",")]
    normalized = [_canonicalize_risk_level(item) for item in tokens]
    normalized = [item for item in normalized if item]
    return set(normalized)


def _build_latest_risk_snapshot_map(ts_codes, market="CN"):
    code_list = [str(code or "").strip().upper() for code in (ts_codes or []) if str(code or "").strip()]
    if not code_list:
        return {}

    rows = (
        ValuationRiskSnapshot.objects.filter(ts_code__in=code_list, market=market)
        .order_by("ts_code", "-trade_date", "-updated_at")
        .values("ts_code", "risk_score", "risk_level", "trade_date")
    )

    risk_map = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code or ts_code in risk_map:
            continue
        normalized_risk_level = _canonicalize_risk_level(row.get("risk_level")) or None
        risk_map[ts_code] = {
            "valuation_risk_score": _to_float_or_none(row.get("risk_score")),
            "valuation_risk_level": normalized_risk_level,
            "valuation_risk_trade_date": row.get("trade_date"),
        }
    return risk_map


def _build_latest_income_netprofit_map(ts_codes):
    code_list = [str(code or "").strip().upper() for code in (ts_codes or []) if str(code or "").strip()]
    if not code_list:
        return {}

    placeholders = ",".join(["%s"] * len(code_list))

    sql_primary = f"""
        SELECT ts_code, end_date, ann_date, netprofit_value
        FROM (
            SELECT
                ts_code,
                end_date,
                ann_date,
                n_income_attr_p AS netprofit_value,
                ROW_NUMBER() OVER (
                    PARTITION BY ts_code
                    ORDER BY ann_date DESC NULLS LAST, end_date DESC NULLS LAST
                ) AS rn
            FROM earnings_fin_income
            WHERE ts_code IN ({placeholders})
        ) ranked
        WHERE rn = 1
    """

    sql_fallback = f"""
        SELECT ts_code, end_date, ann_date, netprofit_value
        FROM (
            SELECT
                ts_code,
                end_date,
                ann_date,
                n_income AS netprofit_value,
                ROW_NUMBER() OVER (
                    PARTITION BY ts_code
                    ORDER BY ann_date DESC NULLS LAST, end_date DESC NULLS LAST
                ) AS rn
            FROM earnings_fin_income
            WHERE ts_code IN ({placeholders})
        ) ranked
        WHERE rn = 1
    """

    try:
        df = query_local_financial_df(sql_primary, code_list)
    except Exception:
        try:
            df = query_local_financial_df(sql_fallback, code_list)
        except Exception:
            df = None

    if df is None or df.empty:
        return {}

    sql_history_primary = f"""
        SELECT ts_code, end_date, ann_date, n_income_attr_p AS netprofit_value
        FROM earnings_fin_income
        WHERE ts_code IN ({placeholders})
    """
    sql_history_fallback = f"""
        SELECT ts_code, end_date, ann_date, n_income AS netprofit_value
        FROM earnings_fin_income
        WHERE ts_code IN ({placeholders})
    """

    try:
        history_df = query_local_financial_df(sql_history_primary, code_list)
    except Exception:
        try:
            history_df = query_local_financial_df(sql_history_fallback, code_list)
        except Exception:
            history_df = None

    history_map = {}
    if history_df is not None and not history_df.empty:
        for _, history_row in history_df.iterrows():
            ts_code = str(history_row.get("ts_code") or "").strip().upper()
            if not ts_code:
                continue
            end_date = _parse_date_like(history_row.get("end_date"))
            ann_date = _parse_date_like(history_row.get("ann_date"))
            netprofit_value = _to_float_or_none(history_row.get("netprofit_value"))
            if end_date is None or netprofit_value is None:
                continue
            history_map.setdefault(ts_code, []).append(
                {
                    "end_date": end_date,
                    "ann_date": ann_date,
                    "netprofit_value": netprofit_value,
                }
            )

    netprofit_map = {}
    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code:
            continue

        latest_end_date = _parse_date_like(row.get("end_date"))
        latest_netprofit = _to_float_or_none(row.get("netprofit_value"))
        netprofit_yoy = None

        if latest_end_date is not None and latest_netprofit is not None:
            compare_end_date = datetime.date(latest_end_date.year - 1, latest_end_date.month, latest_end_date.day)
            candidates = history_map.get(ts_code) or []
            compare_row = next(
                (item for item in candidates if item.get("end_date") == compare_end_date),
                None,
            )
            compare_netprofit = _to_float_or_none((compare_row or {}).get("netprofit_value"))
            if compare_netprofit is not None and abs(compare_netprofit) > 1e-9:
                netprofit_yoy = (float(latest_netprofit) - float(compare_netprofit)) / abs(float(compare_netprofit))

        netprofit_map[ts_code] = {
            "financial_netprofit": latest_netprofit,
            "financial_netprofit_end_date": latest_end_date,
            "financial_netprofit_ann_date": _parse_date_like(row.get("ann_date")),
            "financial_netprofit_yoy": netprofit_yoy,
        }
    return netprofit_map


def _attach_traditional_quick_metrics(rows, market="CN"):
    if not rows:
        return

    ts_codes = [str((row or {}).get("ts_code") or "").strip().upper() for row in rows]
    ts_codes = [code for code in ts_codes if code]
    if not ts_codes:
        return

    risk_map = _build_latest_risk_snapshot_map(ts_codes, market=market)
    netprofit_map = _build_latest_income_netprofit_map(ts_codes)

    for row in rows:
        ts_code = str((row or {}).get("ts_code") or "").strip().upper()
        risk_payload = risk_map.get(ts_code) or {}
        netprofit_payload = netprofit_map.get(ts_code) or {}

        row["valuation_risk_score"] = risk_payload.get("valuation_risk_score")
        row["valuation_risk_level"] = risk_payload.get("valuation_risk_level")
        row["valuation_risk_trade_date"] = risk_payload.get("valuation_risk_trade_date")
        row["financial_netprofit"] = netprofit_payload.get("financial_netprofit")
        row["financial_netprofit_end_date"] = netprofit_payload.get("financial_netprofit_end_date")
        row["financial_netprofit_ann_date"] = netprofit_payload.get("financial_netprofit_ann_date")

        if row.get("valuation_risk_score") is None:
            current_price = _to_float_or_none((row or {}).get("close_qfq") or (row or {}).get("close"))
            valuation_price = _to_float_or_none((row or {}).get("valuation_price"))
            variant_rows = []
            if valuation_price is not None:
                variant_rows.append(
                    {
                        "valuation_method": (row or {}).get("valuation_method"),
                        "valuation_price": valuation_price,
                    }
                )
            risk_fallback = build_valuation_risk_payload(
                ts_code=ts_code,
                market=market,
                trade_date=(row or {}).get("latest_trade_date") or datetime.date.today(),
                valuation_variant="default",
                profit_report_type=(row or {}).get("valuation_profit_report_type"),
                profit_report_end_date=(row or {}).get("valuation_profit_report_end_date"),
                profit_report_ann_date=(row or {}).get("valuation_profit_report_ann_date"),
                profit_data_source=(row or {}).get("valuation_profit_data_source"),
                current_price=current_price,
                rows=variant_rows,
                summary={
                    "composite_valuation_price": (row or {}).get("composite_valuation_price"),
                    "conservative_valuation_price": (row or {}).get("conservative_valuation_price"),
                    "undervalue_score": (row or {}).get("undervalue_score"),
                    "buy_candidate": (row or {}).get("buy_candidate"),
                },
                financial_profile=_load_latest_indicator_profile(ts_code),
                base_band_pct=0.1,
            )
            row["valuation_risk_score"] = _to_float_or_none((risk_fallback or {}).get("risk_score"))
            row["valuation_risk_level"] = str((risk_fallback or {}).get("risk_level") or "").strip().upper() or None
            row["valuation_risk_trade_date"] = (risk_fallback or {}).get("trade_date") or row.get("valuation_risk_trade_date")


def _build_earnings_default_data(ts_code, report_type=""):
    return {
        "ts_code": ts_code,
        "report_type": report_type or "UNKNOWN",
        "pred_earnings_growth": None,
        "prev_year_netprofit_non_negative": None,
        "signal_score": None,
        "target_return_pct": None,
        "target_price": None,
        "target_market_cap": None,
        "target_return_low_pct": None,
        "target_return_high_pct": None,
        "target_price_low": None,
        "target_price_high": None,
        "target_market_cap_low": None,
        "target_market_cap_high": None,
        "action": "HOLD",
        "risk_level": "MEDIUM",
        "model_version": None,
        "asof_date": None,
        "feature_data_source": None,
        "financial_fiscal_year": None,
        "financial_ann_date": None,
        "market_regime": None,
        "quantitative_target_components": {},
        "explain": {
            "stance": "HOLD",
            "confidence": "LOW",
            "prob_component": None,
            "earnings_component": None,
        },
    }


def _map_earnings_result_to_be_data(ts_code, upstream_result):
    be_payload = upstream_result.get("be_payload") or {}
    valuation_mapping = upstream_result.get("valuation_mapping") or {}
    quantitative_target = upstream_result.get("quantitative_target") or {}

    action = be_payload.get("action") or upstream_result.get("action") or "HOLD"
    risk_level = be_payload.get("risk_level") or upstream_result.get("risk_level") or "MEDIUM"
    signal_score = be_payload.get("signal_score")
    if signal_score is None:
        signal_score = upstream_result.get("signal_score")

    target_return_pct = be_payload.get("target_return_pct")
    if target_return_pct is None:
        target_return_pct = upstream_result.get("target_return_pct")
    if target_return_pct is None:
        target_return_pct = quantitative_target.get("target_return_pct")

    target_price = be_payload.get("target_price")
    if target_price is None:
        target_price = upstream_result.get("target_price")
    if target_price is None:
        target_price = quantitative_target.get("target_price")

    target_market_cap = be_payload.get("target_market_cap")
    if target_market_cap is None:
        target_market_cap = upstream_result.get("target_market_cap")
    if target_market_cap is None:
        target_market_cap = quantitative_target.get("target_market_cap")

    target_return_low_pct = quantitative_target.get("target_return_low_pct")
    target_return_high_pct = quantitative_target.get("target_return_high_pct")
    target_price_low = quantitative_target.get("target_price_low")
    target_price_high = quantitative_target.get("target_price_high")
    target_market_cap_low = quantitative_target.get("target_market_cap_low")
    target_market_cap_high = quantitative_target.get("target_market_cap_high")
    quant_components = quantitative_target.get("components")
    if not isinstance(quant_components, dict):
        quant_components = {}

    market_regime = (
        quant_components.get("market_regime")
        or ((upstream_result.get("market_regime") or {}).get("regime") if isinstance(upstream_result.get("market_regime"), dict) else None)
        or be_payload.get("market_regime")
    )

    model_version = (
        upstream_result.get("model_version")
        or upstream_result.get("serving_version")
        or upstream_result.get("model_source")
    )
    report_type = _normalize_earnings_report_type(
        upstream_result.get("report_type")
        or upstream_result.get("financial_report_type")
    )

    return {
        "ts_code": (upstream_result.get("ts_code") or ts_code),
        "report_type": report_type or "UNKNOWN",
        "pred_earnings_growth": _to_float_or_none(upstream_result.get("pred_earnings_growth")),
        "prev_year_netprofit_non_negative": upstream_result.get("prev_year_netprofit_non_negative"),
        "signal_score": _to_float_or_none(signal_score),
        "target_return_pct": _to_float_or_none(target_return_pct),
        "target_price": _to_float_or_none(target_price),
        "target_market_cap": _to_float_or_none(target_market_cap),
        "target_return_low_pct": _to_float_or_none(target_return_low_pct),
        "target_return_high_pct": _to_float_or_none(target_return_high_pct),
        "target_price_low": _to_float_or_none(target_price_low),
        "target_price_high": _to_float_or_none(target_price_high),
        "target_market_cap_low": _to_float_or_none(target_market_cap_low),
        "target_market_cap_high": _to_float_or_none(target_market_cap_high),
        "action": str(action).upper(),
        "risk_level": str(risk_level).upper(),
        "model_version": model_version,
        "asof_date": upstream_result.get("trade_date"),
        "feature_data_source": upstream_result.get("feature_data_source"),
        "feature_trade_date": upstream_result.get("feature_trade_date"),
        "request_asof_date": upstream_result.get("request_asof_date"),
        "live_feature_compliant": upstream_result.get("live_feature_compliant"),
        "live_feature_gap_days": upstream_result.get("live_feature_gap_days"),
        "financial_end_date": upstream_result.get("financial_end_date"),
        "financial_fiscal_year": upstream_result.get("financial_fiscal_year"),
        "financial_ann_date": upstream_result.get("financial_ann_date"),
        "market_regime": str(market_regime).upper() if market_regime else None,
        "quantitative_target_components": quant_components,
        "explain": {
            "stance": valuation_mapping.get("stance") or str(action).upper(),
            "confidence": valuation_mapping.get("confidence") or "LOW",
            "prob_component": _to_float_or_none(valuation_mapping.get("prob_component")),
            "earnings_component": _to_float_or_none(valuation_mapping.get("earnings_component")),
        },
    }


def _apply_fusion_time_discount(payload, latest_trade_date=None, strict_matched=True):
    """Apply time-decay discount for fusion score within comparable candidates only."""
    if not isinstance(payload, dict):
        return payload

    signal_score = _to_float_or_none(payload.get("signal_score"))
    ann_date = _parse_date_like(payload.get("financial_ann_date"))
    asof_date = _parse_date_like(payload.get("asof_date"))
    anchor_date = _parse_date_like(latest_trade_date) or asof_date

    if signal_score is None:
        factor = 1.0
        stale_days = None
        adjusted_score = None
    else:
        stale_days = None
        if ann_date is not None and anchor_date is not None:
            stale_days = max((anchor_date - ann_date).days, 0)

        # Half-life-like decay approximation without introducing extra dependencies.
        # 0 days => 1.0, 180 days => 0.5, then clipped to avoid over-penalization.
        if stale_days is None:
            factor = 1.0
        else:
            factor = 1.0 / (1.0 + (float(stale_days) / 180.0))
            factor = max(0.55, min(1.0, factor))

        # strict missing fallback gets an additional conservative haircut.
        if not strict_matched:
            factor *= 0.92

        factor = max(0.5, min(1.0, factor))
        adjusted_score = round(signal_score * factor, 2)

    next_payload = dict(payload)
    if adjusted_score is not None:
        next_payload["signal_score_raw"] = signal_score
        next_payload["signal_score"] = adjusted_score

    explain = dict(next_payload.get("explain") or {})
    explain["fusion_time_discount_factor"] = round(float(factor), 4)
    explain["fusion_stale_days"] = stale_days
    explain["fusion_strict_matched"] = bool(strict_matched)
    next_payload["explain"] = explain
    return next_payload


def _fetch_earnings_signal(
    ts_code,
    report_type="",
    financial_end_date=None,
    source="snapshot",
    serving_slot="",
    model_version="",
    anchor_mode="",
    asof_date=None,
    require_live_features=False,
    feature_source_preference="",
):
    base_url = str(
        getattr(settings, "EARNINGS_SERVICE_BASE_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    base_timeout_seconds = float(getattr(settings, "EARNINGS_SERVICE_TIMEOUT_SECONDS", 4.0) or 4.0)
    retry_count = int(getattr(settings, "EARNINGS_SERVICE_RETRY_COUNT", 1) or 1)

    query_payload = {"ts_code": ts_code}
    normalized_report_type = _normalize_earnings_report_type(report_type)
    if normalized_report_type:
        query_payload["report_type"] = normalized_report_type
    normalized_source = str(source or "snapshot").strip().lower()
    if normalized_source not in {"snapshot", "predict"}:
        normalized_source = "snapshot"
    predict_timeout_seconds = float(
        getattr(
            settings,
            "EARNINGS_SERVICE_PREDICT_TIMEOUT_SECONDS",
            max(base_timeout_seconds, 20.0),
        )
        or max(base_timeout_seconds, 20.0)
    )
    timeout_seconds = predict_timeout_seconds if normalized_source == "predict" else base_timeout_seconds

    normalized_serving_slot = str(serving_slot or "").strip().lower()
    if normalized_source == "predict" and normalized_serving_slot in {"production", "candidate"}:
        query_payload["serving_slot"] = normalized_serving_slot

    normalized_model_version = str(model_version or "").strip()
    if normalized_source == "predict" and normalized_model_version:
        query_payload["model_version"] = normalized_model_version

    normalized_anchor_mode = _normalize_predict_anchor_mode(anchor_mode)
    if normalized_source == "predict" and normalized_anchor_mode in {"ann", "live"}:
        query_payload["anchor_mode"] = normalized_anchor_mode

    normalized_asof_date = _parse_date_like(asof_date)
    if normalized_asof_date is not None:
        query_payload["asof_date"] = normalized_asof_date.strftime("%Y-%m-%d")

    if normalized_source == "predict" and bool(require_live_features):
        query_payload["require_live_features"] = "true"

    normalized_feature_source_preference = str(feature_source_preference or "").strip().lower()
    if normalized_source == "predict" and normalized_feature_source_preference:
        query_payload["feature_source_preference"] = normalized_feature_source_preference

    normalized_financial_end_date = _parse_date_like(financial_end_date)
    if normalized_financial_end_date is not None:
        query_payload["financial_end_date"] = normalized_financial_end_date.strftime("%Y-%m-%d")

    query = urlencode(query_payload)
    endpoint = "/api/forecast/predict/" if normalized_source == "predict" else "/api/forecast/signal/"
    url = f"{base_url}{endpoint}?{query}"
    req = urllib_request.Request(
        url,
        data=(b"" if normalized_source == "predict" else None),
        method=("POST" if normalized_source == "predict" else "GET"),
    )

    last_error = None
    for _ in range(retry_count + 1):
        try:
            with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                payload = json.loads(body)
                result = payload.get("result") if isinstance(payload, dict) else None
                if not isinstance(result, dict):
                    raise ValueError("Invalid upstream response: missing result object")
                return _map_earnings_result_to_be_data(ts_code, result)
        except HTTPError as err:
            last_error = err
            if err.code == 422:
                try:
                    body = err.read().decode("utf-8", errors="replace")
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {}
                code = str((payload or {}).get("code") or "").strip().upper()
                if code == "LIVE_FEATURE_UNAVAILABLE":
                    detail = (payload or {}).get("detail") or {}
                    raise RuntimeError(
                        json.dumps(
                            {
                                "code": code,
                                "message": (payload or {}).get("message") or "live features unavailable",
                                "detail": detail if isinstance(detail, dict) else {},
                            },
                            ensure_ascii=False,
                        )
                    )
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as err:
            last_error = err

    raise RuntimeError(str(last_error) if last_error else "unknown upstream error")


def _fetch_earnings_signal_batch(ts_codes, report_type="ALL", return_stats=False, financial_end_date_map=None):
    perf_t0 = time.perf_counter()
    codes = []
    seen = set()
    for item in ts_codes or []:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    stats = {
        "batch_cache_hit": False,
        "total_codes": 0,
        "per_code_cache_hit": 0,
        "per_code_cache_miss": 0,
        "chunk_size": 0,
        "total_chunks": 0,
        "successful_chunks": 0,
        "failed_chunks": 0,
        "upstream_request_count": 0,
        "failed_code_count": 0,
        "elapsed_ms": 0.0,
    }

    def _finalize(payload):
        stats["elapsed_ms"] = round((time.perf_counter() - perf_t0) * 1000.0, 2)
        if return_stats:
            return payload, stats
        return payload

    if not codes:
        return _finalize({})

    stats["total_codes"] = len(codes)

    cache_ttl_seconds = int(getattr(settings, "EARNINGS_SIGNAL_CACHE_SECONDS", 1800) or 1800)
    batch_cache_ttl_seconds = int(
        getattr(settings, "EARNINGS_SIGNAL_BATCH_CACHE_SECONDS", min(120, cache_ttl_seconds))
        or min(120, cache_ttl_seconds)
    )
    cache_prefix = "earnings_signal"
    base_url = str(
        getattr(settings, "EARNINGS_SERVICE_BASE_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    timeout_seconds = float(getattr(settings, "EARNINGS_SERVICE_TIMEOUT_SECONDS", 4.0) or 4.0)
    retry_count = int(getattr(settings, "EARNINGS_SERVICE_RETRY_COUNT", 1) or 1)
    normalized_report_type = _normalize_earnings_report_type_with_all(report_type)

    normalized_financial_end_date_map = {}
    if isinstance(financial_end_date_map, dict):
        for code, end_date in financial_end_date_map.items():
            normalized_code = str(code or "").strip().upper()
            if not normalized_code or normalized_code not in codes:
                continue
            normalized_end_date = _parse_date_like(end_date)
            if normalized_end_date is None:
                continue
            normalized_financial_end_date_map[normalized_code] = normalized_end_date.strftime("%Y-%m-%d")

    if normalized_financial_end_date_map:
        chunk_size = int(getattr(settings, "EARNINGS_SIGNAL_BATCH_CHUNK_SIZE", 200) or 200)
        chunk_size = max(1, chunk_size)
        chunks = [codes[idx: idx + chunk_size] for idx in range(0, len(codes), chunk_size)]
        stats["chunk_size"] = chunk_size
        stats["total_chunks"] = len(chunks)

        fetched_results = {}
        failed_codes = []

        for chunk in chunks:
            request_payload = {
                "ts_codes": chunk,
                "report_type": normalized_report_type,
                "financial_end_date_map": {
                    code: normalized_financial_end_date_map[code]
                    for code in chunk
                    if code in normalized_financial_end_date_map
                },
            }
            req = urllib_request.Request(
                f"{base_url}/api/forecast/signal/batch/",
                data=json.dumps(request_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            chunk_ok = False
            last_error = None
            for _ in range(retry_count + 1):
                try:
                    stats["upstream_request_count"] += 1
                    with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
                        body = resp.read().decode("utf-8", errors="replace")
                        payload = json.loads(body)
                        results = payload.get("results") if isinstance(payload, dict) else None
                        if not isinstance(results, dict):
                            raise ValueError("Invalid upstream batch response: missing results object")

                        for code, result in results.items():
                            if not isinstance(result, dict):
                                continue
                            fetched_results[code] = _map_earnings_result_to_be_data(code, result)

                        chunk_ok = True
                        stats["successful_chunks"] += 1
                        break
                except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as err:
                    last_error = err

            if not chunk_ok:
                failed_codes.extend(chunk)
                stats["failed_chunks"] += 1
                logger.warning(
                    "earnings batch chunk failed, report_type=%s, chunk_size=%s, error=%s",
                    normalized_report_type,
                    len(chunk),
                    str(last_error) if last_error else "unknown upstream batch error",
                )

        for code in codes:
            if code not in fetched_results:
                fetched_results[code] = _build_earnings_default_data(code, normalized_report_type)

        stats["failed_code_count"] = len(failed_codes)
        return _finalize(fetched_results)

    batch_cache_digest = hashlib.md5(",".join(codes).encode("utf-8")).hexdigest()
    batch_cache_key = f"{cache_prefix}:batch:{normalized_report_type}:{len(codes)}:{batch_cache_digest}"

    cached_batch = cache.get(batch_cache_key)
    if isinstance(cached_batch, dict):
        stats["batch_cache_hit"] = True
        stats["per_code_cache_hit"] = len(codes)
        return _finalize({
            code: cached_batch.get(code) or _build_earnings_default_data(code, normalized_report_type)
            for code in codes
        })

    cached_results = {}
    missing_codes = []
    for code in codes:
        cache_key = f"{cache_prefix}:{code}:{normalized_report_type}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            cached_results[code] = cached
            stats["per_code_cache_hit"] += 1
        else:
            missing_codes.append(code)
            stats["per_code_cache_miss"] += 1

    if not missing_codes:
        cache.set(batch_cache_key, cached_results, timeout=batch_cache_ttl_seconds)
        return _finalize(cached_results)

    chunk_size = int(getattr(settings, "EARNINGS_SIGNAL_BATCH_CHUNK_SIZE", 200) or 200)
    chunk_size = max(1, chunk_size)
    chunks = [missing_codes[idx: idx + chunk_size] for idx in range(0, len(missing_codes), chunk_size)]
    stats["chunk_size"] = chunk_size
    stats["total_chunks"] = len(chunks)

    fetched_results = {}
    failed_codes = []

    for chunk in chunks:
        request_payload = {
            "ts_codes": chunk,
            "report_type": normalized_report_type,
        }
        req = urllib_request.Request(
            f"{base_url}/api/forecast/signal/batch/",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        chunk_ok = False
        last_error = None
        for _ in range(retry_count + 1):
            try:
                stats["upstream_request_count"] += 1
                with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    payload = json.loads(body)
                    results = payload.get("results") if isinstance(payload, dict) else None
                    if not isinstance(results, dict):
                        raise ValueError("Invalid upstream batch response: missing results object")

                    for code, result in results.items():
                        if not isinstance(result, dict):
                            continue
                        mapped = _map_earnings_result_to_be_data(code, result)
                        fetched_results[code] = mapped
                        cache_key = f"{cache_prefix}:{code}:{normalized_report_type}"
                        cache.set(cache_key, mapped, timeout=cache_ttl_seconds)

                    chunk_ok = True
                    stats["successful_chunks"] += 1
                    break
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as err:
                last_error = err

        if not chunk_ok:
            failed_codes.extend(chunk)
            stats["failed_chunks"] += 1
            logger.warning(
                "earnings batch chunk failed, report_type=%s, chunk_size=%s, error=%s",
                normalized_report_type,
                len(chunk),
                str(last_error) if last_error else "unknown upstream batch error",
            )

    merged_results = {**cached_results, **fetched_results}
    for code in missing_codes:
        if code not in merged_results:
            merged_results[code] = _build_earnings_default_data(code, normalized_report_type)

    if failed_codes:
        cache.set(batch_cache_key, merged_results, timeout=max(10, min(30, batch_cache_ttl_seconds)))
    else:
        cache.set(batch_cache_key, merged_results, timeout=batch_cache_ttl_seconds)

    stats["failed_code_count"] = len(failed_codes)
    return _finalize(merged_results)


def _classify_predictive_valuation_status(target_return_pct, band_pct=0.1):
    target_return = _to_float_or_none(target_return_pct)
    if target_return is None:
        return "unknown"

    band = _to_float_or_none(band_pct)
    if band is None or float(band) <= 0:
        band = 0.1
    threshold_pct = float(band) * 100.0

    if float(target_return) >= threshold_pct:
        return "under"
    if float(target_return) <= -threshold_pct:
        return "over"
    return "fair"


def _is_predictive_buy_candidate(action, signal_score, risk_level, target_return_pct):
    action_value = str(action or "").strip().upper()
    risk_value = _canonicalize_risk_level(risk_level) or "MEDIUM"
    score_value = _to_float_or_none(signal_score)
    target_return_value = _to_float_or_none(target_return_pct)

    try:
        min_signal_score = float(
            getattr(settings, "PREDICTIVE_BUY_CANDIDATE_MIN_SIGNAL_SCORE", 85.0) or 85.0
        )
    except (TypeError, ValueError):
        min_signal_score = 85.0
    try:
        min_target_return_pct = float(
            getattr(settings, "PREDICTIVE_BUY_CANDIDATE_MIN_TARGET_RETURN_PCT", 10.0) or 10.0
        )
    except (TypeError, ValueError):
        min_target_return_pct = 10.0

    allowed_risk_levels_raw = getattr(
        settings,
        "PREDICTIVE_BUY_CANDIDATE_ALLOWED_RISK_LEVELS",
        ("LOW", "MEDIUM"),
    )
    if isinstance(allowed_risk_levels_raw, str):
        allowed_risk_levels = {
            _canonicalize_risk_level(item)
            for item in allowed_risk_levels_raw.split(",")
            if str(item or "").strip()
        }
    else:
        allowed_risk_levels = {
            _canonicalize_risk_level(item)
            for item in (allowed_risk_levels_raw or ("LOW", "MEDIUM"))
            if str(item or "").strip()
        }
    allowed_risk_levels.discard(None)
    if not allowed_risk_levels:
        allowed_risk_levels = {"LOW", "MEDIUM"}

    return (
        action_value == "BUY"
        and score_value is not None
        and float(score_value) >= float(min_signal_score)
        and risk_value in allowed_risk_levels
        and target_return_value is not None
        and float(target_return_value) >= float(min_target_return_pct)
    )


def _compute_predictive_pick_score(row):
    score = float(_to_float_or_none(row.get("signal_score")) or 0.0)
    action = str(row.get("action") or "").upper()
    if action == "BUY":
        score += 10.0
    elif action == "SELL_PART":
        score -= 8.0
    elif action == "SELL":
        score -= 16.0

    risk_level = str(row.get("risk_level") or "").upper()
    if risk_level == "LOW":
        score += 5.0
    elif risk_level == "HIGH":
        score -= 8.0

    target_return_pct = float(_to_float_or_none(row.get("target_return_pct")) or 0.0)
    score += max(-10.0, min(12.0, target_return_pct * 0.2))

    valuation_status = str(row.get("valuation_status") or "").lower()
    if valuation_status == "under":
        score += 8.0
    elif valuation_status == "over":
        score -= 6.0

    if row.get("buy_candidate"):
        score += 6.0

    report_type = str(row.get("earnings_report_type") or row.get("report_type") or "").upper()
    if report_type == "FUSION":
        score += 4.0
    elif report_type == "FY":
        score += 2.0

    return round(score, 2)


def _build_earnings_signal_view(
    *,
    ts_code,
    report_type,
    latest_trade_date,
    latest_current_price,
    financial_end_date=None,
    serving_slot="",
    model_version="",
    anchor_mode="ann",
    asof_date=None,
    require_live_features=False,
    feature_source_preference="",
):
    normalized_report_type = _normalize_earnings_report_type(report_type)
    normalized_anchor_mode = _normalize_predict_anchor_mode(anchor_mode)
    normalized_financial_end_date = _parse_date_like(financial_end_date)
    normalized_serving_slot = str(serving_slot or "").strip().lower()
    if normalized_serving_slot not in {"production", "candidate"}:
        normalized_serving_slot = ""
    normalized_model_version = str(model_version or "").strip()

    use_predict_path = bool(normalized_serving_slot or normalized_model_version)
    if normalized_anchor_mode == "live":
        use_predict_path = True
        if not normalized_serving_slot:
            normalized_serving_slot = "production"

    resolved_financial_end_date = normalized_financial_end_date
    if (
        normalized_report_type in {"Q1", "H1", "Q3"}
        and resolved_financial_end_date is None
        and latest_trade_date is not None
        and use_predict_path
    ):
        resolved_financial_end_date = _resolve_expected_end_date_for_report_type(
            normalized_report_type,
            anchor_trade_date=latest_trade_date,
        )

    if (
        normalized_report_type in {"Q1", "H1", "Q3", "FY"}
        and resolved_financial_end_date is None
        and use_predict_path
    ):
        resolved_financial_end_date = _resolve_valuation_report_end_date_from_feature_panel(
            ts_code=ts_code,
            report_type=_normalize_valuation_profit_report_type(normalized_report_type),
            asof_date=latest_trade_date,
        )

    if normalized_report_type == "FUSION" and not use_predict_path:
        anchor_end_date = resolved_financial_end_date
        anchor_report_type = None
        if anchor_end_date is None:
            snapshot_map = _build_latest_snapshot_method_map(
                ts_codes=[ts_code],
                market="CN",
                pick_strategy=_normalize_pick_strategy(LIVE_VALUATION_PICK_STRATEGY),
                max_trade_date=latest_trade_date,
                express_only=False,
            )
            anchor = _pick_latest_predictive_snapshot_anchor(
                snapshot_map.get(ts_code) or {}
            )
            if anchor is not None:
                anchor_report_type = anchor.get("report_type")
                anchor_end_date = anchor.get("report_end_date")

        strict_payload = None
        strict_matched = False
        strict_missing = False
        if anchor_end_date is not None:
            strict_payload = _fetch_earnings_signal(
                ts_code,
                normalized_report_type,
                financial_end_date=anchor_end_date,
                anchor_mode=normalized_anchor_mode,
            )
            strict_end_date = _parse_date_like((strict_payload or {}).get("financial_end_date"))
            strict_matched = strict_end_date is not None and strict_end_date == _parse_date_like(anchor_end_date)
            strict_missing = not strict_matched

        if strict_matched and isinstance(strict_payload, dict):
            data = dict(strict_payload)
            data["fusion_selection"] = {
                "strategy": "strict_then_decay",
                "selected_source": "strict",
                "strict_missing": False,
                "anchor_report_type": anchor_report_type,
                "anchor_end_date": _parse_date_like(anchor_end_date).strftime("%Y-%m-%d") if _parse_date_like(anchor_end_date) else None,
            }
        else:
            data = _fetch_earnings_signal(
                ts_code,
                normalized_report_type,
                financial_end_date=None,
                anchor_mode=normalized_anchor_mode,
            )
            data["fusion_selection"] = {
                "strategy": "strict_then_decay",
                "selected_source": "default_fallback",
                "strict_missing": strict_missing,
                "anchor_report_type": anchor_report_type,
                "anchor_end_date": _parse_date_like(anchor_end_date).strftime("%Y-%m-%d") if _parse_date_like(anchor_end_date) else None,
            }

        data = _apply_fusion_time_discount(
            data,
            latest_trade_date=latest_trade_date,
            strict_matched=(data.get("fusion_selection", {}).get("selected_source") == "strict"),
        )
    else:
        data = _fetch_earnings_signal(
            ts_code,
            normalized_report_type,
            financial_end_date=resolved_financial_end_date,
            source=("predict" if use_predict_path else "snapshot"),
            serving_slot=normalized_serving_slot,
            model_version=normalized_model_version,
            anchor_mode=normalized_anchor_mode,
            asof_date=asof_date,
            require_live_features=require_live_features,
            feature_source_preference=feature_source_preference,
        )

    data = _build_earnings_dual_target_payload(
        data,
        current_price=latest_current_price,
        latest_trade_date=latest_trade_date,
        anchor_mode=normalized_anchor_mode,
    )
    data["anchor_mode"] = normalized_anchor_mode

    return {
        "data": data,
        "resolved_financial_end_date": resolved_financial_end_date,
        "use_predict_path": use_predict_path,
    }


def _build_earnings_compare_summary(latest_payload, report_anchor_payload):
    latest_score = _to_float_or_none((latest_payload or {}).get("signal_score"))
    report_score = _to_float_or_none((report_anchor_payload or {}).get("signal_score"))

    latest_target = _to_float_or_none(
        (latest_payload or {}).get("target_price")
        or (latest_payload or {}).get("target_price_raw")
    )
    report_target = _to_float_or_none(
        (report_anchor_payload or {}).get("target_price")
        or (report_anchor_payload or {}).get("target_price_raw")
    )

    score_delta = None
    if latest_score is not None and report_score is not None:
        score_delta = round(latest_score - report_score, 2)

    target_price_delta_pct = None
    if latest_target is not None and report_target not in (None, 0):
        target_price_delta_pct = round((latest_target - report_target) / report_target * 100.0, 2)

    latest_action = str((latest_payload or {}).get("action") or "").upper()
    report_action = str((report_anchor_payload or {}).get("action") or "").upper()
    action_changed = bool(latest_action and report_action and latest_action != report_action)

    confidence_hint = "stable"
    if action_changed:
        confidence_hint = "action_changed"
    elif score_delta is not None and abs(score_delta) >= 8:
        confidence_hint = "score_shifted"

    return {
        "score_delta": score_delta,
        "target_price_delta_pct": target_price_delta_pct,
        "action_changed": action_changed,
        "confidence_hint": confidence_hint,
    }


@api_view(["GET"])
def get_earnings_signal_compare(request, ts_code):
    normalized_ts_code = str(ts_code or "").strip().upper()
    if not normalized_ts_code:
        return Response({"error": "ts_code is required."}, status=400)

    normalized_report_type = _normalize_earnings_report_type(request.GET.get("report_type"))
    normalized_financial_end_date = _parse_date_like(request.GET.get("financial_end_date"))
    normalized_serving_slot = str(request.GET.get("serving_slot") or "").strip().lower()
    normalized_model_version = str(request.GET.get("model_version") or "").strip()
    latest_anchor_mode = _normalize_predict_anchor_mode(request.GET.get("anchor_mode_latest") or "live")
    report_anchor_mode = _normalize_predict_anchor_mode(request.GET.get("anchor_mode_report") or "ann")
    requested_serving_slot = normalized_serving_slot if normalized_serving_slot in {"production", "candidate"} else ""
    effective_predict_serving_slot = requested_serving_slot or "production"
    request_date = datetime.date.today()
    request_date_text = request_date.strftime("%Y-%m-%d")

    latest_trade_payload = (
        StockTradingHistory.objects.filter(ts_code=normalized_ts_code, freq="D")
        .order_by("-trade_date")
        .values("trade_date", "close_qfq", "close")
        .first()
    )
    latest_trade_date = _parse_date_like((latest_trade_payload or {}).get("trade_date"))
    latest_current_price = _to_float_or_none((latest_trade_payload or {}).get("close_qfq"))
    if latest_current_price is None:
        latest_current_price = _to_float_or_none((latest_trade_payload or {}).get("close"))

    compare_cache_key = (
        f"earnings_signal_compare:{normalized_ts_code}:{normalized_report_type or 'ALL'}:"
        f"{normalized_financial_end_date.strftime('%Y-%m-%d') if normalized_financial_end_date else 'latest'}:"
        f"{effective_predict_serving_slot or 'default'}:{normalized_model_version or 'default'}:{latest_anchor_mode}:{report_anchor_mode}:"
        f"{request_date_text}:latest_realtime"
    )
    cache_ttl_seconds = int(getattr(settings, "EARNINGS_SIGNAL_CACHE_SECONDS", 1800) or 1800)

    try:
        # Latest view: always realtime predict with selected report-period financial input.
        latest_snapshot_error = None
        try:
            latest_snapshot_result = _build_earnings_signal_view(
                ts_code=normalized_ts_code,
                report_type=normalized_report_type,
                latest_trade_date=latest_trade_date,
                latest_current_price=latest_current_price,
                financial_end_date=normalized_financial_end_date,
                serving_slot="",
                model_version="",
                anchor_mode="ann",
            )
            latest_snapshot_data = dict(latest_snapshot_result.get("data") or {})
        except Exception as snapshot_err:
            latest_snapshot_error = snapshot_err
            latest_snapshot_data = _build_earnings_default_data(normalized_ts_code, normalized_report_type)

        latest_snapshot_asof_date = _parse_date_like(latest_snapshot_data.get("asof_date"))
        latest_snapshot_staleness_days = None
        if latest_snapshot_asof_date is not None:
            latest_snapshot_staleness_days = max(0, (request_date - latest_snapshot_asof_date).days)

        resolved_latest_financial_end_date = (
            normalized_financial_end_date
            or _parse_date_like(latest_snapshot_data.get("financial_end_date"))
        )

        latest_source_used = "predict_realtime"
        latest_data = latest_snapshot_data

        latest_predict_error = None
        latest_feature_data_source = None
        latest_live_feature_ok = False
        try:
            latest_predict_result = _build_earnings_signal_view(
                ts_code=normalized_ts_code,
                report_type=normalized_report_type,
                latest_trade_date=latest_trade_date,
                latest_current_price=latest_current_price,
                financial_end_date=resolved_latest_financial_end_date,
                serving_slot=effective_predict_serving_slot,
                model_version=normalized_model_version,
                anchor_mode="live",
                asof_date=request_date,
                require_live_features=True,
                feature_source_preference="live_db_only",
            )
            latest_data = dict(latest_predict_result.get("data") or {})
            latest_feature_data_source = str(latest_data.get("feature_data_source") or "").strip().lower() or None
            latest_live_feature_ok = (
                latest_feature_data_source in {"live", "live_db"}
                or (
                    latest_feature_data_source == "fusion"
                    and bool(latest_data.get("live_feature_compliant"))
                )
            )
            if not latest_live_feature_ok:
                latest_source_used = "predict_non_live_rejected"
                latest_data = _build_earnings_default_data(normalized_ts_code, normalized_report_type)
                latest_data["degrade_reason"] = "latest_requires_live_feature_source"
            else:
                latest_source_used = "predict_realtime"
        except Exception as predict_err:
            latest_predict_error = predict_err
            latest_source_used = "predict_realtime_rejected"
            latest_data = _build_earnings_default_data(normalized_ts_code, normalized_report_type)
            latest_data["degrade_reason"] = "latest_requires_live_feature_source"
            err_text = str(predict_err or "")
            try:
                err_payload = json.loads(err_text)
            except Exception:
                err_payload = None
            if isinstance(err_payload, dict) and str(err_payload.get("code") or "").strip().upper() == "LIVE_FEATURE_UNAVAILABLE":
                latest_data["degrade_code"] = "LIVE_FEATURE_UNAVAILABLE"
                latest_data["degrade_detail"] = err_payload.get("detail") if isinstance(err_payload.get("detail"), dict) else {}
                latest_data["degrade_message"] = err_payload.get("message")
            else:
                latest_data["degrade_code"] = "UPSTREAM_ERROR"
                latest_data["degrade_message"] = err_text

        latest_data = _build_earnings_dual_target_payload(
            latest_data,
            current_price=latest_current_price,
            latest_trade_date=latest_trade_date,
            anchor_mode=latest_anchor_mode,
        )
        latest_data["anchor_mode"] = "live"
        if latest_trade_date is not None:
            latest_data["anchor_trade_date"] = latest_trade_date.strftime("%Y-%m-%d")

        # Right card view: report-type disclosure-anchored snapshot (non-latest).
        report_anchor_error = None
        report_source_used = "snapshot"
        report_anchor_financial_end_date = None
        report_anchor_asof_date = None
        if normalized_report_type in {"Q1", "H1", "Q3", "FY"}:
            report_anchor_financial_end_date, report_anchor_asof_date = _resolve_valuation_report_meta_from_feature_panel(
                ts_code=normalized_ts_code,
                report_type=normalized_report_type,
                asof_date=latest_trade_date,
            )

        try:
            report_anchor_result = _build_earnings_signal_view(
                ts_code=normalized_ts_code,
                report_type=normalized_report_type,
                latest_trade_date=latest_trade_date,
                latest_current_price=latest_current_price,
                financial_end_date=report_anchor_financial_end_date,
                serving_slot="",
                model_version="",
                anchor_mode=report_anchor_mode,
                asof_date=report_anchor_asof_date,
            )
            report_anchor_data = dict(report_anchor_result.get("data") or {})
        except Exception as report_err:
            report_anchor_error = report_err
            report_source_used = "snapshot_fallback_latest"
            report_anchor_data = dict(latest_snapshot_data or {})
            if not report_anchor_data:
                report_source_used = "default"
                report_anchor_data = _build_earnings_default_data(normalized_ts_code, normalized_report_type)

        latest_data["view_type"] = "latest"
        latest_data["view_label"] = "latest_predictive"
        report_anchor_data["view_type"] = "report_anchor"
        report_anchor_data["view_label"] = "report_type_release_anchor_snapshot"

        # Fusion is temporarily aligned with report-anchor semantics.
        # It does not enforce strict live-source gating for latest card.
        if normalized_report_type == "FUSION":
            latest_data = dict(report_anchor_data)
            latest_data["view_type"] = "latest"
            latest_data["view_label"] = "latest_predictive"
            latest_source_used = "fusion_mirror_report_anchor"
            latest_feature_data_source = str(latest_data.get("feature_data_source") or "").strip().lower() or None
            latest_live_feature_ok = True

        response_data = {
            "ts_code": normalized_ts_code,
            "selected_report_type": normalized_report_type,
            "latest_view": latest_data,
            "report_anchor_view": report_anchor_data,
            "compare_summary": _build_earnings_compare_summary(latest_data, report_anchor_data),
            "compare_meta": {
                "anchor_policy": "latest_request_time_and_report_type_release_anchor_snapshot",
                "fusion_policy": "strict_then_decay",
                "latest_policy": "realtime_predict_with_selected_financial_period",
                "report_policy": "snapshot_only_selected_report_type_release_anchor",
                "request_date": request_date_text,
                "latest_source_used": latest_source_used,
                "latest_feature_data_source": latest_feature_data_source,
                "latest_live_feature_ok": latest_live_feature_ok,
                "latest_snapshot_staleness_days": latest_snapshot_staleness_days,
                "latest_snapshot_asof_date": (
                    latest_snapshot_asof_date.strftime("%Y-%m-%d") if latest_snapshot_asof_date is not None else None
                ),
                "report_source_used": report_source_used,
                "report_anchor_financial_end_date": (
                    report_anchor_financial_end_date.strftime("%Y-%m-%d")
                    if _parse_date_like(report_anchor_financial_end_date) is not None
                    else None
                ),
                "report_anchor_asof_date": (
                    report_anchor_asof_date.strftime("%Y-%m-%d")
                    if _parse_date_like(report_anchor_asof_date) is not None
                    else None
                ),
                "effective_serving_slot": effective_predict_serving_slot,
                "latest_partial_degrade": bool(latest_snapshot_error or latest_predict_error or (not latest_live_feature_ok)),
                "report_partial_degrade": bool(report_anchor_error),
            },
        }
        cache.set(compare_cache_key, response_data, timeout=cache_ttl_seconds)
        return Response({
            "code": 0,
            "message": "ok",
            "data": response_data,
        })
    except Exception as err:
        logger.warning("earnings signal compare degraded for %s: %s", normalized_ts_code, err)
        cached_data = cache.get(compare_cache_key)
        if cached_data:
            return Response({
                "code": 0,
                "message": "ok",
                "data": cached_data,
                "degrade": {
                    "enabled": True,
                    "reason": "upstream_error_cache_hit",
                },
            })

        return Response(
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "ts_code": normalized_ts_code,
                    "selected_report_type": normalized_report_type,
                    "latest_view": {
                        **_build_earnings_default_data(normalized_ts_code, normalized_report_type),
                        "anchor_mode": latest_anchor_mode,
                        "view_type": "latest",
                        "view_label": "latest_predictive",
                    },
                    "report_anchor_view": {
                        **_build_earnings_default_data(normalized_ts_code, normalized_report_type),
                        "anchor_mode": report_anchor_mode,
                        "view_type": "report_anchor",
                        "view_label": "report_release_anchor",
                    },
                    "compare_summary": {
                        "score_delta": None,
                        "target_price_delta_pct": None,
                        "action_changed": False,
                        "confidence_hint": "stable",
                    },
                    "compare_meta": {
                        "anchor_policy": "latest_request_time_and_report_anchor_snapshot",
                        "fusion_policy": "strict_then_decay",
                        "latest_policy": "snapshot_preferred_with_30d_predict_fallback",
                        "report_policy": "snapshot_only_report_anchor_including_fusion",
                        "request_date": request_date_text,
                        "latest_source_used": "default",
                        "latest_snapshot_staleness_days": None,
                        "latest_snapshot_asof_date": None,
                        "report_source_used": "default",
                    },
                },
                "degrade": {
                    "enabled": True,
                    "reason": "upstream_error_default",
                },
            }
        )


@api_view(["GET"])
def get_earnings_signal(request, ts_code):
    """Read persisted earnings signal through earnings service snapshot endpoint."""

    normalized_ts_code = str(ts_code or "").strip().upper()
    if not normalized_ts_code:
        return Response({"error": "ts_code is required."}, status=400)
    raw_report_type = str(request.GET.get("report_type") or "").strip()
    raw_report_type_upper = raw_report_type.upper()
    express_like_request = raw_report_type_upper in {"σ┐½", "EXP", "EXPRESS"}
    normalized_report_type = _normalize_earnings_report_type(raw_report_type)
    normalized_anchor_mode = _normalize_predict_anchor_mode(request.GET.get("anchor_mode"))
    normalized_financial_end_date = _parse_date_like(request.GET.get("financial_end_date"))
    normalized_serving_slot = str(request.GET.get("serving_slot") or "").strip().lower()
    if normalized_serving_slot not in {"production", "candidate"}:
        normalized_serving_slot = ""
    normalized_model_version = str(request.GET.get("model_version") or "").strip()
    use_predict_path = bool(normalized_serving_slot or normalized_model_version)
    if normalized_anchor_mode == "live":
        use_predict_path = True
        if not normalized_serving_slot:
            normalized_serving_slot = "production"

    latest_trade_payload = (
        StockTradingHistory.objects.filter(ts_code=normalized_ts_code, freq="D")
        .order_by("-trade_date")
        .values("trade_date", "close_qfq", "close")
        .first()
    )
    latest_trade_date = _parse_date_like((latest_trade_payload or {}).get("trade_date"))
    latest_current_price = _to_float_or_none((latest_trade_payload or {}).get("close_qfq"))
    if latest_current_price is None:
        latest_current_price = _to_float_or_none((latest_trade_payload or {}).get("close"))

    if express_like_request and not use_predict_path:
        if normalized_financial_end_date is not None:
            resolved_report_type = _resolve_report_type_from_end_date(normalized_financial_end_date)
            if resolved_report_type in {"Q1", "H1", "Q3", "FY"}:
                normalized_report_type = resolved_report_type

        if normalized_report_type == "FUSION":
            snapshot_map = _build_latest_snapshot_method_map(
                ts_codes=[normalized_ts_code],
                market="CN",
                pick_strategy=_normalize_pick_strategy(LIVE_VALUATION_PICK_STRATEGY),
                max_trade_date=latest_trade_date,
                express_only=False,
            )
            anchor = _pick_latest_predictive_snapshot_anchor(
                snapshot_map.get(normalized_ts_code) or {}
            )
            if anchor is not None:
                anchor_report_type = anchor.get("report_type")
                anchor_end_date = anchor.get("report_end_date")
                if anchor_report_type in {"Q1", "H1", "Q3", "FY"}:
                    normalized_report_type = anchor_report_type
                if anchor_end_date is not None:
                    normalized_financial_end_date = anchor_end_date

    prefetched_signal_payload = None
    if (
        normalized_report_type == "FY"
        and not normalized_financial_end_date
        and latest_trade_date is not None
        and not use_predict_path
    ):
        preferred_fy_end_date = datetime.date(latest_trade_date.year - 1, 12, 31)
        try:
            strict_fy_payload = _fetch_earnings_signal(
                normalized_ts_code,
                normalized_report_type,
                financial_end_date=preferred_fy_end_date,
                anchor_mode=normalized_anchor_mode,
            )
            strict_fy_end_date = _parse_date_like((strict_fy_payload or {}).get("financial_end_date"))
            if strict_fy_end_date == preferred_fy_end_date:
                normalized_financial_end_date = preferred_fy_end_date
                prefetched_signal_payload = strict_fy_payload
        except Exception:
            prefetched_signal_payload = None

    if (
        normalized_report_type in {"Q1", "H1", "Q3"}
        and not normalized_financial_end_date
        and latest_trade_date is not None
        and prefetched_signal_payload is None
        and not use_predict_path
    ):
        preferred_period_end_date = _resolve_expected_end_date_for_report_type(
            normalized_report_type,
            anchor_trade_date=latest_trade_date,
        )
        if preferred_period_end_date is not None:
            try:
                strict_period_payload = _fetch_earnings_signal(
                    normalized_ts_code,
                    normalized_report_type,
                    financial_end_date=preferred_period_end_date,
                    anchor_mode=normalized_anchor_mode,
                )
                strict_period_end_date = _parse_date_like((strict_period_payload or {}).get("financial_end_date"))
                if strict_period_end_date == preferred_period_end_date:
                    normalized_financial_end_date = preferred_period_end_date
                    prefetched_signal_payload = strict_period_payload
            except Exception:
                prefetched_signal_payload = None

    if (
        normalized_report_type in {"Q1", "H1", "Q3", "FY"}
        and not normalized_financial_end_date
        and not use_predict_path
    ):
        normalized_financial_end_date = _resolve_valuation_report_end_date_from_feature_panel(
            ts_code=normalized_ts_code,
            report_type=_normalize_valuation_profit_report_type(normalized_report_type),
            asof_date=latest_trade_date,
        )

    report_type_cache_key = normalized_report_type or "ALL"

    try:
        cache_key_suffix = normalized_financial_end_date.strftime("%Y-%m-%d") if normalized_financial_end_date is not None else "latest"
        fetch_mode = "predict" if use_predict_path else "snapshot"
        slot_cache = normalized_serving_slot or "default"
        version_cache = normalized_model_version or "default"
        anchor_mode_cache = normalized_anchor_mode
        cache_key = f"earnings_signal:{normalized_ts_code}:{report_type_cache_key}:{cache_key_suffix}:{fetch_mode}:{slot_cache}:{version_cache}:{anchor_mode_cache}"
        cache_ttl_seconds = int(getattr(settings, "EARNINGS_SIGNAL_CACHE_SECONDS", 1800) or 1800)

        if prefetched_signal_payload is not None:
            data = dict(prefetched_signal_payload)
        elif normalized_report_type == "FUSION" and not use_predict_path:
            anchor_report_type = None
            anchor_end_date = normalized_financial_end_date

            if anchor_end_date is None:
                snapshot_map = _build_latest_snapshot_method_map(
                    ts_codes=[normalized_ts_code],
                    market="CN",
                    pick_strategy=_normalize_pick_strategy(LIVE_VALUATION_PICK_STRATEGY),
                    max_trade_date=latest_trade_date,
                    express_only=False,
                )
                anchor = _pick_latest_predictive_snapshot_anchor(
                    snapshot_map.get(normalized_ts_code) or {}
                )
                if anchor is not None:
                    anchor_report_type = anchor.get("report_type")
                    anchor_end_date = anchor.get("report_end_date")

            strict_payload = None
            strict_matched = False
            strict_missing = False

            if anchor_end_date is not None:
                strict_payload = _fetch_earnings_signal(
                    normalized_ts_code,
                    normalized_report_type,
                    financial_end_date=anchor_end_date,
                    anchor_mode=normalized_anchor_mode,
                )
                strict_end_date = _parse_date_like((strict_payload or {}).get("financial_end_date"))
                strict_matched = strict_end_date is not None and strict_end_date == _parse_date_like(anchor_end_date)
                strict_missing = not strict_matched

            if strict_matched and isinstance(strict_payload, dict):
                data = dict(strict_payload)
                data["fusion_selection"] = {
                    "strategy": "strict_then_decay",
                    "selected_source": "strict",
                    "strict_missing": False,
                    "anchor_report_type": anchor_report_type,
                    "anchor_end_date": _parse_date_like(anchor_end_date).strftime("%Y-%m-%d") if _parse_date_like(anchor_end_date) else None,
                }
            else:
                data = _fetch_earnings_signal(
                    normalized_ts_code,
                    normalized_report_type,
                    financial_end_date=None,
                    anchor_mode=normalized_anchor_mode,
                )
                data["fusion_selection"] = {
                    "strategy": "strict_then_decay",
                    "selected_source": "default_fallback",
                    "strict_missing": strict_missing,
                    "anchor_report_type": anchor_report_type,
                    "anchor_end_date": _parse_date_like(anchor_end_date).strftime("%Y-%m-%d") if _parse_date_like(anchor_end_date) else None,
                }

            data = _apply_fusion_time_discount(
                data,
                latest_trade_date=latest_trade_date,
                strict_matched=(data.get("fusion_selection", {}).get("selected_source") == "strict"),
            )
        else:
            data = _fetch_earnings_signal(
                normalized_ts_code,
                normalized_report_type,
                financial_end_date=normalized_financial_end_date,
                source=("predict" if use_predict_path else "snapshot"),
                serving_slot=normalized_serving_slot,
                model_version=normalized_model_version,
                anchor_mode=normalized_anchor_mode,
            )

        data = _build_earnings_dual_target_payload(
            data,
            current_price=latest_current_price,
            latest_trade_date=latest_trade_date,
        )
        data["anchor_mode"] = normalized_anchor_mode

        cache.set(cache_key, data, timeout=cache_ttl_seconds)
        return Response({
            "code": 0,
            "message": "ok",
            "data": data,
        })
    except Exception as err:
        logger.warning("earnings signal degraded for %s: %s", ts_code, err)

        cache_key_suffix = normalized_financial_end_date.strftime("%Y-%m-%d") if normalized_financial_end_date is not None else "latest"
        fetch_mode = "predict" if use_predict_path else "snapshot"
        slot_cache = normalized_serving_slot or "default"
        version_cache = normalized_model_version or "default"
        anchor_mode_cache = normalized_anchor_mode
        cache_key = f"earnings_signal:{normalized_ts_code}:{report_type_cache_key}:{cache_key_suffix}:{fetch_mode}:{slot_cache}:{version_cache}:{anchor_mode_cache}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(
                {
                    "code": 0,
                    "message": "ok",
                    "data": cached_data,
                    "degrade": {
                        "enabled": True,
                        "reason": "upstream_error_cache_hit",
                    },
                }
            )

        return Response(
            {
                "code": 0,
                "message": "ok",
                "data": {
                    **_build_earnings_default_data(normalized_ts_code, normalized_report_type),
                    "anchor_mode": normalized_anchor_mode,
                },
                "degrade": {
                    "enabled": True,
                    "reason": "upstream_error_default",
                },
            }
        )


@api_view(["GET"])
def get_earnings_signal_persisted(request, ts_code):
    """Proxy a persisted signal only; intentionally never calls the live predict path."""
    code = str(ts_code or "").strip().upper()
    report_type = _normalize_earnings_report_type(request.GET.get("report_type"))
    if not code or not report_type:
        return Response({"error": "ts_code and report_type are required"}, status=400)
    base_url = str(getattr(settings, "EARNINGS_SERVICE_BASE_URL", "http://127.0.0.1:5002")).rstrip("/")
    query = urlencode({
        "ts_code": code,
        "report_type": report_type,
        "require_refresh_reason": request.GET.get("require_refresh_reason", "0"),
        "view": request.GET.get("view", "latest"),
        "financial_end_date": request.GET.get("financial_end_date", ""),
    })
    try:
        with urllib_request.urlopen(f"{base_url}/api/forecast/signal/persisted/?{query}", timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return Response({"code": 404, "message": "persisted snapshot not found", "data": None}, status=404)
        return Response({"error": f"persisted signal upstream error: {exc}"}, status=502)
    except (URLError, TimeoutError, ValueError) as exc:
        return Response({"error": f"persisted signal unavailable: {exc}"}, status=502)
    if not isinstance(payload, dict) or not payload.get("ok"):
        return Response({"code": 404, "message": "persisted snapshot not found", "data": None}, status=404)
    return Response({"code": 0, "message": "ok", "data": payload.get("result")})


@api_view(["GET"])
def get_earnings_signal_history(request, ts_code):
    code = str(ts_code or "").strip().upper()
    if not code:
        return Response({"error": "ts_code is required"}, status=400)
    try:
        limit = max(1, min(int(request.GET.get("limit") or 100), 200))
    except (TypeError, ValueError):
        return Response({"error": "limit must be an integer"}, status=400)
    base_url = str(getattr(settings, "EARNINGS_SERVICE_BASE_URL", "http://127.0.0.1:5002")).rstrip("/")
    query = urlencode({"ts_code": code, "limit": limit})
    try:
        with urllib_request.urlopen(f"{base_url}/api/forecast/signal/history/?{query}", timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return Response({"error": f"signal history unavailable: {exc}"}, status=502)
    if not isinstance(payload, dict) or not payload.get("ok"):
        return Response({"error": "signal history unavailable"}, status=502)
    return Response({"code": 0, "message": "ok", "data": payload.get("items") or [], "total": payload.get("total") or 0})


@api_view(["POST"])
def openclaw_valuation_chat(request):
    """OpenClaw valuation assistant: natural-language query to valuation advice."""

    try:
        message = str((request.data or {}).get("message") or "").strip()
        provided_ts_code = str((request.data or {}).get("ts_code") or "").strip().upper()
        market = str((request.data or {}).get("market") or "CN").strip() or "CN"
        freq = str((request.data or {}).get("freq") or "D").strip().upper() or "D"

        query_band = _parse_optional_float((request.data or {}).get("valuation_band_pct"), default=None)
        inferred_band = _extract_band_pct_from_text(message, default_pct=0.1)
        band_pct = query_band if query_band is not None else inferred_band

        ts_code_from_message = _extract_ts_code_from_text(message)
        ts_code = ts_code_from_message or provided_ts_code
        if not ts_code:
            return Response({"error": "τ╝║σ░æ ts_code∩╝îΦ»╖σ£¿Θù«ΘóÿΘçîΦ╛ôσàÑσªé 600519.SH µêûΣ╝á ts_code σ¡ùµ«╡"}, status=400)

        valuation_payload = _get_latest_valuation_payload(
            ts_code=ts_code,
            market=market,
            freq=freq,
            band_pct=band_pct,
        )

        answer = _render_openclaw_advice_text(message, valuation_payload)

        forward_to_feishu = bool((request.data or {}).get("forward_to_feishu"))
        feishu_forwarded = False
        feishu_error = None
        if forward_to_feishu:
            feishu_forwarded, feishu_error = _forward_to_feishu(answer)

        return Response(
            {
                "skill": "openclaw.valuation_advisor",
                "answer": answer,
                "valuation": valuation_payload,
                "feishu_forwarded": feishu_forwarded,
                "feishu_error": feishu_error,
            }
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def get_stock_demo_valuation(request, ts_code):
    """Run demo valuation for a stock and return JSON-serializable output."""

    try:
        trade_date = request.query_params.get("trade_date")
        current_price = _parse_optional_float(
            request.query_params.get("current_price"),
            default=None,
        )
        pe_target = _parse_optional_float(request.query_params.get("pe_target"))
        ps_target = _parse_optional_float(request.query_params.get("ps_target"))
        pb_target = _parse_optional_float(request.query_params.get("pb_target"))
        peg_target = _parse_optional_float(
            request.query_params.get("peg_target"),
            default=1.0,
        )
        ev_ebitda_target = _parse_optional_float(
            request.query_params.get("ev_ebitda_target")
        )
        scenario_model = request.query_params.get("scenario_model", "fcff_dcf")

        dcf_kwargs = {
            "discount_rate": _parse_optional_float(
                request.query_params.get("discount_rate"),
                default=0.10,
            ),
            "terminal_growth_rate": _parse_optional_float(
                request.query_params.get("terminal_growth_rate"),
                default=0.03,
            ),
        }
        growth_rates = _parse_optional_float_list(request.query_params.get("growth_rates"))
        if growth_rates:
            dcf_kwargs["growth_rates"] = growth_rates

        ddm_kwargs = {
            "discount_rate": _parse_optional_float(
                request.query_params.get("ddm_discount_rate"),
                default=0.10,
            ),
            "dividend_growth_rate": _parse_optional_float(
                request.query_params.get("dividend_growth_rate"),
                default=0.03,
            ),
        }

        sw_history_kwargs = {}
        history_years_raw = request.query_params.get("history_years")
        if history_years_raw not in (None, ""):
            sw_history_kwargs["history_years"] = [
                int(item.strip())
                for item in str(history_years_raw).split(",")
                if item.strip()
            ]
        history_quantile = _parse_optional_float(request.query_params.get("history_quantile"))
        if history_quantile is not None:
            sw_history_kwargs["history_quantile"] = history_quantile
        history_min_samples_raw = request.query_params.get("history_min_samples")
        if history_min_samples_raw not in (None, ""):
            sw_history_kwargs["history_min_samples"] = int(history_min_samples_raw)

        sensitivity_grid = None
        sensitivity_discount_rates = _parse_optional_float_list(
            request.query_params.get("sensitivity_discount_rates")
        )
        sensitivity_terminal_growth_rates = _parse_optional_float_list(
            request.query_params.get("sensitivity_terminal_growth_rates")
        )
        if sensitivity_discount_rates or sensitivity_terminal_growth_rates:
            sensitivity_grid = {}
            if sensitivity_discount_rates:
                sensitivity_grid["discount_rate"] = sensitivity_discount_rates
            if sensitivity_terminal_growth_rates:
                sensitivity_grid[
                    "terminal_growth_rate"
                ] = sensitivity_terminal_growth_rates

        result = test_valuation(
            ts_code=ts_code,
            trade_date=trade_date,
            current_price=current_price,
            pe_target=pe_target,
            ps_target=ps_target,
            pb_target=pb_target,
            peg_target=peg_target,
            ev_ebitda_target=ev_ebitda_target,
            dcf_kwargs=dcf_kwargs,
            ddm_kwargs=ddm_kwargs,
            sw_history_kwargs=sw_history_kwargs or None,
            scenario_model=scenario_model,
            sensitivity_grid=sensitivity_grid,
        )

        return Response(
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "snapshot": result.get("snapshot"),
                "formatted_range": result.get("formatted_range"),
                "valuations": _json_safe_records(result.get("valuations")),
                "scenario_analysis": _json_safe_records(
                    result.get("scenario_analysis")
                ),
                "sensitivity_analysis": _json_safe_records(
                    result.get("sensitivity_analysis")
                ),
            }
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
