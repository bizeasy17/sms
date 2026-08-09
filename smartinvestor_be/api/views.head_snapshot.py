import datetime
import csv
import hashlib
import math
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
from django.db.models import Q, Max
from django.http import FileResponse, Http404
from prediction.models import (
    StockCombinedFeature,
    StockPrediction,
)
from valuation.models import StockValuationSnapshot, StockValuationSnapshotLatest
from prediction.services.business_industry_matcher import BusinessIndustryMatcher
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
from prediction.models import StockGainLossQuantile
from valuation_risk.models import ValuationRiskSnapshot
from valuation_risk.services import build_valuation_risk_payload
from pandas.tseries.offsets import BDay
from users.models import UserStockTag
from django.test import RequestFactory
import time


logger = logging.getLogger(__name__)

MARKET_OVERALL_DEFAULT_INDEX_WEIGHTS = {
    "000001.SH": 0.30,
    "399001.SZ": 0.30,
    "000300.SH": 0.20,
    "000905.SH": 0.15,
    "399006.SZ": 0.05,
}

WEEKLY_UNDERVALUED_FILE_PREFIX = {
    "traditional": "traditional_undervalued_",
    "predictive": "predictive_undervalued_",
}

WEEKLY_UNDERVALUED_JOB_CONFIG_FILE = "job_strategy_config.json"
WEEKLY_STRATEGY_STYLE_KEYS = ("CONSERVATIVE", "BALANCED", "AGGRESSIVE")


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


def _normalize_weekly_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _normalize_weekly_selection_params(payload):
    if not isinstance(payload, dict):
        return {}
    normalized = {}
    for key, value in payload.items():
        safe_key = str(key or "").strip()
        if not safe_key:
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            normalized[safe_key] = value
            continue
        if isinstance(value, (list, tuple)):
            normalized[safe_key] = [
                item
                for item in value
                if item is None or isinstance(item, (str, int, float, bool))
            ]
    return normalized


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
        "selection_params": _normalize_weekly_selection_params(entry_payload.get("selection_params")),
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
            "valuation_variant": "",
            "risk_variant_policy": "any",
            "min_netprofit_yoy": None,
            "min_ebit_yoy": None,
            "require_positive_prev_netprofit": True,
            "require_positive_prev_ebit": True,
            "financial_filter_mode": "all",
            "priority_policy": "score_desc",
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

    valuation_variant = str(merged_job.get("valuation_variant") or defaults["job"].get("valuation_variant") or "").strip()
    risk_variant_policy = str(merged_job.get("risk_variant_policy") or defaults["job"].get("risk_variant_policy") or "any").strip().lower()
    if risk_variant_policy not in {"any", "specific"}:
        risk_variant_policy = "any"

    min_netprofit_yoy = _to_float_or_none(merged_job.get("min_netprofit_yoy"))
    min_ebit_yoy = _to_float_or_none(merged_job.get("min_ebit_yoy"))
    require_positive_prev_netprofit = _normalize_weekly_bool(
        merged_job.get("require_positive_prev_netprofit"),
        defaults["job"].get("require_positive_prev_netprofit", True),
    )
    require_positive_prev_ebit = _normalize_weekly_bool(
        merged_job.get("require_positive_prev_ebit"),
        defaults["job"].get("require_positive_prev_ebit", True),
    )
    financial_filter_mode = str(merged_job.get("financial_filter_mode") or defaults["job"].get("financial_filter_mode") or "all").strip().lower()
    if financial_filter_mode not in {"all", "any"}:
        financial_filter_mode = "all"
    priority_policy = str(merged_job.get("priority_policy") or defaults["job"].get("priority_policy") or "score_desc").strip().lower()
    if priority_policy not in {"score_desc", "high_price_first", "low_price_first", "deep_discount_first", "target_discount_first", "low_risk_high_score"}:
        priority_policy = "score_desc"

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
            "valuation_variant": valuation_variant,
            "risk_variant_policy": risk_variant_policy,
            "min_netprofit_yoy": min_netprofit_yoy,
            "min_ebit_yoy": min_ebit_yoy,
            "require_positive_prev_netprofit": bool(require_positive_prev_netprofit),
            "require_positive_prev_ebit": bool(require_positive_prev_ebit),
            "financial_filter_mode": financial_filter_mode,
            "priority_policy": priority_policy,
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

# Baseline rule locked by backtest on 2026-03-19.
BUY_CANDIDATE_MIN_CORE_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_CORE_UNDER_COUNT = 1
BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT = -0.02
BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT = -0.12
COMPOSITE_SIZE_SMALL_CAP_MAX = float(getattr(settings, "COMPOSITE_SIZE_SMALL_CAP_MAX", 30_000_000_000) or 30_000_000_000)
COMPOSITE_SIZE_MID_CAP_MAX = float(getattr(settings, "COMPOSITE_SIZE_MID_CAP_MAX", 100_000_000_000) or 100_000_000_000)
COMPOSITE_SIZE_LARGE_CAP_MAX = float(getattr(settings, "COMPOSITE_SIZE_LARGE_CAP_MAX", 300_000_000_000) or 300_000_000_000)
COMPOSITE_SIZE_SMALL_CAP_FACTOR = float(getattr(settings, "COMPOSITE_SIZE_SMALL_CAP_FACTOR", 1.05) or 1.05)
COMPOSITE_SIZE_MID_CAP_FACTOR = float(getattr(settings, "COMPOSITE_SIZE_MID_CAP_FACTOR", 1.02) or 1.02)
COMPOSITE_SIZE_LARGE_CAP_FACTOR = float(getattr(settings, "COMPOSITE_SIZE_LARGE_CAP_FACTOR", 0.99) or 0.99)
COMPOSITE_SIZE_MEGA_CAP_FACTOR = float(getattr(settings, "COMPOSITE_SIZE_MEGA_CAP_FACTOR", 0.96) or 0.96)
LIVE_VALUATION_BUSINESS_MATCH_TOPN = int(getattr(settings, "LIVE_VALUATION_BUSINESS_MATCH_TOPN", 0) or 0)
LIVE_VALUATION_PICK_STRATEGY = str(getattr(settings, "LIVE_VALUATION_PICK_STRATEGY", "baseline") or "baseline").strip().lower()
MAX_VALUATION_CANDIDATES_IN_RESPONSE = int(getattr(settings, "MAX_VALUATION_CANDIDATES_IN_RESPONSE", 3) or 3)
LIVE_VALUATION_RISK_USE_PERSISTED_FIRST = bool(
    getattr(settings, "LIVE_VALUATION_RISK_USE_PERSISTED_FIRST", True)
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
):
    if not ts_codes:
        return {}

    normalized_profit_report_type = _normalize_valuation_profit_report_type(profit_report_type)
    normalized_codes = sorted(
        {
            str(code or "").strip().upper()
            for code in ts_codes
            if str(code or "").strip()
        }
    )
    if not normalized_codes:
        return {}

    codes_signature = hashlib.md5(
        ",".join(normalized_codes).encode("utf-8")
    ).hexdigest()
    snapshot_cache_key = (
        "valuation_snapshot_map:v1:"
        f"{str(market or 'CN').strip().upper()}:"
        f"{_normalize_pick_strategy(pick_strategy)}:"
        f"{str(max_trade_date or '')}:"
        f"{1 if express_only else 0}:"
        f"{normalized_profit_report_type or 'ALL'}:"
        f"{len(normalized_codes)}:"
        f"{codes_signature}"
    )
    cached_snapshot_map = cache.get(snapshot_cache_key)
    if isinstance(cached_snapshot_map, dict):
        return cached_snapshot_map

    snapshots = StockValuationSnapshotLatest.objects.filter(
        ts_code__in=normalized_codes,
        market=market,
    )
    if max_trade_date:
        snapshots = snapshots.filter(latest_trade_date__lte=max_trade_date)
    if express_only:
        snapshots = snapshots.filter(profit_data_source__startswith="express")
    if normalized_profit_report_type:
        snapshots = snapshots.filter(profit_report_type=normalized_profit_report_type)

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
                "candidate_count": len(candidates),
                "compare_group": selected.get("compare_group"),
                "match_score": selected.get("match_score"),
                **quality_payload,
            }

    # Cache a short-lived snapshot map for repeated requests with identical scope/date/filter tuples.
    cache.set(snapshot_cache_key, snapshot_map, timeout=600)
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


def _estimate_current_market_cap(current_price, method_map):
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
        # Drop the core method furthest from current price when the core set is internally inconsistent.
        farthest_method = max(
            filtered_methods.items(),
            key=lambda item: abs(item[1] - current_price),
        )[0]
        excluded_methods[farthest_method] = "core_outlier"
        filtered_methods.pop(farthest_method, None)

    return filtered_methods, excluded_methods


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
        "message": "σ╜ôσëìΣ╝░σÇ╝Σ╕ïΘÖìΣ╕╗Φªüµ¥ÑΦç¬ΘÖñµ¥âσÉÄµÇ╗Φéíµ£¼µë⌐σñº∩╝îσÉîτ¡ëΦéíµ¥âΣ╗╖σÇ╝Φó½µæèσê░µ¢┤σñÜΦéíΣ╗╜∩╝îΣ╕ìσ«£τ¢┤µÄÑΦºúΦ»╗Σ╕║σƒ║µ£¼Θ¥óµü╢σîûπÇé",
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
def _safe_sql_identifier(name, default_name):
    text = str(name or "").strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", text):
        return text
    return default_name


def _to_percentile_pct(series, value):
    if value is None:
        return None
    if series is None:
        return None
    clean = pd.Series(series).dropna()
    if clean.empty:
        return None
    return round(float((clean <= float(value)).mean() * 100.0), 2)


def _serialize_metric_history(series):
    clean = pd.Series(series).dropna().sort_index()
    if clean.empty:
        return []
    rows = []
    for idx, value in clean.items():
        trade_date = pd.to_datetime(idx, errors="coerce")
        if pd.isna(trade_date):
            continue
        try:
            value_num = float(value)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "value": round(value_num, 4),
            }
        )
    return rows


def _build_market_overall_valuation_snapshot(asof_trade_date=None):
    table_name = _safe_sql_identifier(
        getattr(settings, "VALUATION_MARKET_INDEX_DAILYBASIC_TABLE", "earnings_mkt_index_dailybasic"),
        "earnings_mkt_index_dailybasic",
    )
    db_alias = str(getattr(settings, "VALUATION_LOCAL_FINANCIAL_DB_ALIAS", "earnings") or "earnings")

    raw_weights = getattr(settings, "VALUATION_MARKET_OVERALL_INDEX_WEIGHTS", None)
    configured_weights = raw_weights if isinstance(raw_weights, dict) else MARKET_OVERALL_DEFAULT_INDEX_WEIGHTS
    weights = {}
    for code, weight in configured_weights.items():
        norm_code = str(code or "").strip().upper()
        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            continue
        if not norm_code or weight_value <= 0:
            continue
        weights[norm_code] = weight_value
    if not weights:
        return None

    index_codes = list(weights.keys())
    placeholders = ", ".join(["%s"] * len(index_codes))
    sql = f"""
        SELECT ts_code, trade_date, pe, pe_ttm, pb
        FROM {table_name}
        WHERE ts_code IN ({placeholders})
    """
    params = list(index_codes)

    parsed_asof = None
    if asof_trade_date is not None:
        try:
            parsed_asof = pd.to_datetime(asof_trade_date, errors="coerce")
        except Exception:
            parsed_asof = None
    if parsed_asof is not None and not pd.isna(parsed_asof):
        sql += " AND trade_date <= %s"
        params.append(parsed_asof.date())

    sql += " ORDER BY trade_date ASC"

    try:
        frame = query_local_financial_df(sql, params, db_alias=db_alias)
    except Exception as exc:
        logger.warning("market overall valuation load failed: %s", exc)
        return None

    if frame is None or frame.empty:
        return None

    frame = frame.copy()
    frame["ts_code"] = frame["ts_code"].astype(str).str.upper().str.strip()
    frame = frame[frame["ts_code"].isin(index_codes)]
    if frame.empty:
        return None

    frame["trade_date"] = pd.to_datetime(frame.get("trade_date"), errors="coerce")
    frame = frame.dropna(subset=["trade_date"]).copy()
    if frame.empty:
        return None

    for metric_name in ["pe", "pe_ttm", "pb"]:
        frame[metric_name] = pd.to_numeric(frame.get(metric_name), errors="coerce")

    weight_series = pd.Series(weights, dtype="float64")
    metrics_payload = {}
    asof_dates = []
    sh_metrics_payload = {}
    sh_asof_dates = []

    for metric_name in ["pe", "pe_ttm", "pb"]:
        metric_df = frame.dropna(subset=[metric_name]).copy()
        if metric_df.empty:
            continue

        pivot = metric_df.pivot_table(
            index="trade_date",
            columns="ts_code",
            values=metric_name,
            aggfunc="last",
        )
        if pivot.empty:
            continue

        usable_cols = [col for col in pivot.columns if col in weight_series.index]
        if not usable_cols:
            continue
        pivot = pivot[usable_cols]
        usable_weights = weight_series[usable_cols]

        weighted_sum = pivot.fillna(0.0).mul(usable_weights, axis=1).sum(axis=1)
        available_weight = pivot.notna().mul(usable_weights, axis=1).sum(axis=1)
        metric_series = (weighted_sum / available_weight).where(available_weight > 0).dropna().sort_index()
        if metric_series.empty:
            continue

        metric_asof = metric_series.index.max()
        current_value = float(metric_series.loc[metric_asof])
        all_history_percentile = _to_percentile_pct(metric_series, current_value)

        cutoff_dt = metric_asof - pd.DateOffset(years=5)
        metric_series_5y = metric_series[metric_series.index >= cutoff_dt]
        five_year_percentile = _to_percentile_pct(metric_series_5y, current_value)

        metrics_payload[metric_name] = {
            "current": round(current_value, 4),
            "history_percentile_pct": all_history_percentile,
            "five_year_percentile_pct": five_year_percentile,
            "sample_size": int(metric_series.shape[0]),
            "sample_size_5y": int(metric_series_5y.shape[0]),
            "history": _serialize_metric_history(metric_series),
        }
        asof_dates.append(metric_asof)

        sh_series = (
            metric_df[metric_df["ts_code"] == "000001.SH"]
            .sort_values("trade_date")
            .drop_duplicates(subset=["trade_date"], keep="last")
            .set_index("trade_date")[metric_name]
            .dropna()
            .sort_index()
        )
        if not sh_series.empty:
            sh_asof = sh_series.index.max()
            sh_current = float(sh_series.loc[sh_asof])
            sh_all_history_percentile = _to_percentile_pct(sh_series, sh_current)
            sh_cutoff_dt = sh_asof - pd.DateOffset(years=5)
            sh_series_5y = sh_series[sh_series.index >= sh_cutoff_dt]
            sh_five_year_percentile = _to_percentile_pct(sh_series_5y, sh_current)
            sh_metrics_payload[metric_name] = {
                "current": round(sh_current, 4),
                "history_percentile_pct": sh_all_history_percentile,
                "five_year_percentile_pct": sh_five_year_percentile,
                "sample_size": int(sh_series.shape[0]),
                "sample_size_5y": int(sh_series_5y.shape[0]),
                "history": _serialize_metric_history(sh_series),
            }
            sh_asof_dates.append(sh_asof)

    if not metrics_payload:
        return None

    asof_ts = max(asof_dates) if asof_dates else None
    asof_text = asof_ts.strftime("%Y-%m-%d") if asof_ts is not None else None

    sh_asof_ts = max(sh_asof_dates) if sh_asof_dates else None
    sh_asof_text = sh_asof_ts.strftime("%Y-%m-%d") if sh_asof_ts is not None else None

    return {
        "asof_trade_date": asof_text,
        "metrics": metrics_payload,
        "shanghai_benchmark": {
            "ts_code": "000001.SH",
            "asof_trade_date": sh_asof_text,
            "metrics": sh_metrics_payload,
        } if sh_metrics_payload else None,
    }


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
                return ["00"]
            if code == "6":
                return ["60"]
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
        result_style = "BALANCED"
        result_style_strategy = None
        result_lite_mode = False
        traditional_return_pct_map = {}
        predictive_optimistic_return_pct_map = {}
        predictive_conservative_return_pct_map = {}
        latest_report_end_date_map = {}
        traditional_signal_map = {}
        traditional_risk_level_map = {}
        traditional_summary_map = {}
        traditional_variant_map = {}
        traditional_report_type_map = {}
        predictive_signal_map = {}
        predictive_risk_level_map = {}

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
            result_lite_mode = str(request.query_params.get("lite", "0") or "0").strip().lower() in {"1", "true", "yes", "y", "on"}
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
            try:
                effective_weekly_config = _resolve_effective_weekly_job_config(
                    _load_weekly_undervalued_job_config(),
                    requested_style=result_style,
                )
            except Exception:
                effective_weekly_config = None
            if isinstance(effective_weekly_config, dict):
                style_strategy = effective_weekly_config.get("style_strategy")
                result_style_strategy = {
                    "style": effective_weekly_config.get("style") or result_style,
                    "strategy_name": str((style_strategy or {}).get("strategy_name") or "").strip() or None,
                    "source_run_id": (style_strategy or {}).get("source_run_id"),
                    "run_key": str((style_strategy or {}).get("run_key") or "").strip() or None,
                    "saved_at_utc": str((style_strategy or {}).get("saved_at_utc") or "").strip() or None,
                    "selection_params": (style_strategy or {}).get("selection_params") if isinstance((style_strategy or {}).get("selection_params"), dict) else {},
                    "metrics": (style_strategy or {}).get("metrics") if isinstance((style_strategy or {}).get("metrics"), dict) else {},
                    "job": effective_weekly_config.get("job") if isinstance(effective_weekly_config.get("job"), dict) else {},
                    "quick_profiles": effective_weekly_config.get("quick_profiles") if isinstance(effective_weekly_config.get("quick_profiles"), dict) else {},
                }
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

        # WL/OBS/market keep lightweight valuation gap info; only RESULT runs full heavy alignment.
        enable_snapshot_metrics = record_mode in {"watchlist", "market", "result"} and not (record_mode == "result" and result_lite_mode)
        enable_heavy_alignment = record_mode == "result" and not result_lite_mode

        method_map_by_code = {}
        if ts_codes and enable_snapshot_metrics:
            method_map_by_code = _build_latest_snapshot_method_map(
                ts_codes=ts_codes,
                market="CN",
                pick_strategy=LIVE_VALUATION_PICK_STRATEGY,
                max_trade_date=signal_end_date,
            )
            risk_snapshot_map = _build_latest_risk_snapshot_map(ts_codes, market="CN")
            for code, payload in (risk_snapshot_map or {}).items():
                traditional_risk_level_map[code] = str(
                    (payload or {}).get("valuation_risk_level") or ""
                ).strip().upper() or None

        preferred_report_type_method_map_by_code = {}
        if (
            ts_codes
            and enable_snapshot_metrics
            and record_mode != "result"
            and requested_earnings_report_type
        ):
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
            if not enable_snapshot_metrics:
                continue
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

            if enable_heavy_alignment and (record_mode == "result" or (record_mode != "result" and not requested_earnings_report_type)):
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
            fallback_summary = _summarize_buy_candidate(current_price, strict_method_map, 0.1)
            selected_report_type_for_calc = selected_report_type
            if selected_report_type_for_calc not in {"Q1", "H1", "Q3", "FY"}:
                selected_report_type_for_calc = _infer_report_type_from_end_date(selected_report_end_date)

            aligned_payload = {}
            if enable_heavy_alignment and selected_report_type_for_calc in {"Q1", "H1", "Q3", "FY"}:
                try:
                    aligned_payload = _load_internal_stock_valuation_methods_payload(
                        ts_code,
                        freq="D",
                        earnings_report_type=selected_report_type_for_calc,
                        valuation_report_end_date=selected_report_end_date.strftime("%Y-%m-%d") if selected_report_end_date is not None else None,
                        valuation_band_pct=0.1,
                    ) or {}
                except Exception:
                    aligned_payload = {}

            aligned_summary = aligned_payload.get("summary") if isinstance(aligned_payload, dict) else None
            summary = aligned_summary if isinstance(aligned_summary, dict) and aligned_summary else fallback_summary
            traditional_summary_map[ts_code] = summary

            active_variant = str((aligned_payload or {}).get("active_valuation_variant") or "").strip()
            if not active_variant:
                first_method_payload = next(iter((strict_method_map or {}).values()), {})
                active_variant = str((first_method_payload or {}).get("valuation_variant") or "").strip()
            traditional_variant_map[ts_code] = active_variant or None

            effective_report_type = str((aligned_payload or {}).get("valuation_report_type") or "").strip().upper()
            if effective_report_type not in {"Q1", "H1", "Q3", "FY"}:
                effective_report_type = selected_report_type_for_calc if selected_report_type_for_calc in {"Q1", "H1", "Q3", "FY"} else None
            traditional_report_type_map[ts_code] = effective_report_type

            aligned_risk_payload = (aligned_payload or {}).get("valuation_risk") if isinstance(aligned_payload, dict) else None
            aligned_risk_level = str((aligned_risk_payload or {}).get("risk_level") or "").strip().upper() if isinstance(aligned_risk_payload, dict) else ""
            if aligned_risk_level:
                traditional_risk_level_map[ts_code] = aligned_risk_level

            traditional_signal_map[ts_code] = "BUY" if bool(summary.get("buy_candidate")) else "SELL"
            traditional_return_pct = _to_float_or_none(summary.get("composite_valuation_gap_pct"))
            if traditional_return_pct is not None:
                traditional_return_pct = round(float(traditional_return_pct), 2)
            else:
                traditional_return_pct = _calc_return_pct(current_price, summary.get("composite_valuation_price"))
            traditional_return_pct_map[ts_code] = traditional_return_pct

        if ts_codes and enable_heavy_alignment and earnings_end_date_map:
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
                latest_trade_date = _parse_date_like((latest_trade_map.get(code) or {}).get("trade_date"))
                earnings_payload = _build_earnings_dual_target_payload(
                    earnings_payload,
                    current_price=current_price,
                    latest_trade_date=latest_trade_date,
                ) if isinstance(earnings_payload, dict) else {}

                target_return_low_pct = _to_float_or_none(
                    earnings_payload.get("target_return_low_pct_raw")
                )
                if target_return_low_pct is None:
                    target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_low_pct"))
                if target_return_low_pct is None:
                    target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_pct_raw"))
                if target_return_low_pct is None:
                    target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))

                target_return_high_pct = _to_float_or_none(
                    earnings_payload.get("target_return_high_pct_raw")
                )
                if target_return_high_pct is None:
                    target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_high_pct"))
                if target_return_high_pct is None:
                    target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_pct_raw"))
                if target_return_high_pct is None:
                    target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))

                target_price_low = _to_float_or_none(earnings_payload.get("target_price_low_raw"))
                if target_price_low is None:
                    target_price_low = _to_float_or_none(earnings_payload.get("target_price_low"))
                if target_price_low is None:
                    target_price_low = _to_float_or_none(earnings_payload.get("target_price_raw"))
                if target_price_low is None:
                    target_price_low = _to_float_or_none(earnings_payload.get("target_price"))

                target_price_high = _to_float_or_none(earnings_payload.get("target_price_high_raw"))
                if target_price_high is None:
                    target_price_high = _to_float_or_none(earnings_payload.get("target_price_high"))
                if target_price_high is None:
                    target_price_high = _to_float_or_none(earnings_payload.get("target_price_raw"))
                if target_price_high is None:
                    target_price_high = _to_float_or_none(earnings_payload.get("target_price"))

                optimistic_pct_recalc = _calc_return_pct(current_price, target_price_high)
                conservative_pct_recalc = _calc_return_pct(current_price, target_price_low)

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
                predictive_signal_map[code] = str(earnings_payload.get("action") or "").strip().upper() or None
                predictive_risk_level_map[code] = str(earnings_payload.get("risk_level") or "").strip().upper() or None
        elif ts_codes and record_mode in {"watchlist", "market"}:
            # Lightweight predictive snapshot for list views: one batch call, no per-code report alignment.
            quick_earnings_map, _quick_stats = _fetch_earnings_signal_batch(
                ts_codes,
                report_type="ALL",
                return_stats=True,
            )

            for code in ts_codes:
                earnings_payload = quick_earnings_map.get(code) or {}
                current_price = _to_float_or_none((latest_trade_map.get(code) or {}).get("close"))
                latest_trade_date = _parse_date_like((latest_trade_map.get(code) or {}).get("trade_date"))
                earnings_payload = _build_earnings_dual_target_payload(
                    earnings_payload,
                    current_price=current_price,
                    latest_trade_date=latest_trade_date,
                ) if isinstance(earnings_payload, dict) else {}

                target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_low_pct_raw"))
                if target_return_low_pct is None:
                    target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_low_pct"))
                if target_return_low_pct is None:
                    target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_pct_raw"))
                if target_return_low_pct is None:
                    target_return_low_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))

                target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_high_pct_raw"))
                if target_return_high_pct is None:
                    target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_high_pct"))
                if target_return_high_pct is None:
                    target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_pct_raw"))
                if target_return_high_pct is None:
                    target_return_high_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))

                target_price_low = _to_float_or_none(earnings_payload.get("target_price_low_raw"))
                if target_price_low is None:
                    target_price_low = _to_float_or_none(earnings_payload.get("target_price_low"))
                if target_price_low is None:
                    target_price_low = _to_float_or_none(earnings_payload.get("target_price_raw"))
                if target_price_low is None:
                    target_price_low = _to_float_or_none(earnings_payload.get("target_price"))

                target_price_high = _to_float_or_none(earnings_payload.get("target_price_high_raw"))
                if target_price_high is None:
                    target_price_high = _to_float_or_none(earnings_payload.get("target_price_high"))
                if target_price_high is None:
                    target_price_high = _to_float_or_none(earnings_payload.get("target_price_raw"))
                if target_price_high is None:
                    target_price_high = _to_float_or_none(earnings_payload.get("target_price"))

                optimistic_pct_recalc = _calc_return_pct(current_price, target_price_high)
                conservative_pct_recalc = _calc_return_pct(current_price, target_price_low)

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
                predictive_signal_map[code] = str(earnings_payload.get("action") or "").strip().upper() or None
                predictive_risk_level_map[code] = str(earnings_payload.get("risk_level") or "").strip().upper() or None

        basic_info_map = {}
        prediction_map = {}
        if ts_codes:
            corp_rows = Corporation.objects.filter(ts_code__in=ts_codes).values("ts_code", "name")
            corp_name_map = {row["ts_code"]: row.get("name") for row in corp_rows}

            # Keep watchlist payload light; full prediction/detail payload is only needed for RESULT mode.
            if record_mode == "result":
                corp_basic_rows = CorporationBasic.objects.filter(ts_code__in=ts_codes)
                for basic in corp_basic_rows:
                    basic_info_map[basic.ts_code] = (
                        basic.to_dict_short() if hasattr(basic, "to_dict_short") else {}
                    )

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
            result_meta["traditional_report_type"] = traditional_report_type_map.get(ts_code)
            result_meta["traditional_valuation_variant"] = traditional_variant_map.get(ts_code)
            live_traditional_signal = traditional_signal_map.get(ts_code)
            result_meta["traditional_signal_live"] = live_traditional_signal
            source_kind_text = str(result_meta.get("source_kind") or "").strip().lower()
            if record_mode == "result" and source_kind_text == "traditional":
                result_meta["traditional_signal"] = "BUY"
            else:
                result_meta["traditional_signal"] = live_traditional_signal
            result_meta["traditional_risk_level"] = traditional_risk_level_map.get(ts_code)
            result_meta["predictive_signal"] = predictive_signal_map.get(ts_code)
            result_meta["predictive_risk_level"] = predictive_risk_level_map.get(ts_code)
            item_dict["result_meta"] = result_meta
            if traditional_risk_level_map.get(ts_code):
                item_dict["valuation_risk_level"] = traditional_risk_level_map.get(ts_code)

            item_dict["basic_info"] = basic_info_map.get(ts_code, {})
            if ts_code in prediction_map:
                item_dict["prediction"] = prediction_map.get(ts_code)

            current_payload = latest_trade_map.get(ts_code) or {}
            current_price = current_payload.get("close")
            method_map = anchored_method_map_by_code.get(ts_code) or {}
            summary = traditional_summary_map.get(ts_code) or _summarize_buy_candidate(current_price, method_map, 0.1)
            composite_price = _to_float_or_none(summary.get("composite_valuation_price"))
            composite_status = str(summary.get("composite_valuation_status") or "").strip().lower()
            composite_gap_pct_display = _to_float_or_none(summary.get("composite_valuation_gap_pct"))
            if composite_status not in {"under", "over", "fair"}:
                composite_status, composite_gap_pct = _classify_valuation(
                    current_price,
                    composite_price,
                    0.1,
                )
                composite_gap_pct_display = round(composite_gap_pct * 100, 2) if composite_gap_pct is not None else None
            elif composite_gap_pct_display is not None:
                composite_gap_pct_display = round(float(composite_gap_pct_display), 2)
            if record_mode == "result" and not result_lite_mode:
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
                    composite_gap_pct_display = aligned_gap_pct
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
                "composite_valuation_gap_pct": composite_gap_pct_display,
            }
            data.append(item_dict)
        if record_mode == "result" and not result_lite_mode:
            _attach_recent_financial_report_badge(data, market="CN")
        if market == "RESULT" and not result_lite_mode:
            _attach_signal_window_returns(
                data,
                trade_date_for_query=signal_end_date or datetime.date.today(),
                freq="D",
                signal_end_date=signal_end_date,
            )
        if market == "RESULT" and not result_lite_mode:
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
                "result_style_strategy": result_style_strategy if market == "RESULT" else None,
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
                return normalized_code.startswith("00")
            if scope == "6":
                return normalized_code.startswith("60")
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
                return normalized_code.startswith("00")
            if scope == "6":
                return normalized_code.startswith("60")
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


def _attach_recent_financial_report_badge(rows, *, asof_date=None, market="CN"):
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

    code_min_start = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        asof_date = (
            _parse_date_like(row.get("screened_trade_date"))
            or _parse_date_like(row.get("result_trade_date"))
            or _parse_date_like(row.get("trade_date"))
            or _parse_date_like(row.get("earnings_asof_date"))
            or _parse_date_like(row.get("latest_financial_ann_date"))
            or _parse_date_like(row.get("valuation_profit_report_ann_date"))
            or _parse_date_like(row.get("profit_report_ann_date"))
            or _parse_date_like(row.get("valuation_express_ann_date"))
            or _parse_date_like(row.get("express_ann_date"))
            or _parse_date_like(row.get("financial_ann_date"))
            or _parse_date_like(row.get("valuation_profit_report_end_date"))
            or _parse_date_like(row.get("profit_report_end_date"))
        )
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
        asof_date = (
            _parse_date_like(row.get("screened_trade_date"))
            or _parse_date_like(row.get("result_trade_date"))
            or _parse_date_like(row.get("trade_date"))
            or _parse_date_like(row.get("earnings_asof_date"))
            or _parse_date_like(row.get("latest_financial_ann_date"))
            or _parse_date_like(row.get("valuation_profit_report_ann_date"))
            or _parse_date_like(row.get("profit_report_ann_date"))
            or _parse_date_like(row.get("valuation_express_ann_date"))
            or _parse_date_like(row.get("express_ann_date"))
            or _parse_date_like(row.get("financial_ann_date"))
            or _parse_date_like(row.get("valuation_profit_report_end_date"))
            or _parse_date_like(row.get("profit_report_end_date"))
        )
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
    from backtest.services import (
        _build_risk_map,
        _load_financial_panel_map,
        _resolve_financial_metrics,
        _passes_financial_filters,
        _candidate_buy_rank_key,
    )

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
    fiscal_year_raw = (
        request.query_params.get("fiscal_year", "") if hasattr(request, "query_params") else ""
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
    valuation_variant_raw = (
        request.query_params.get("valuation_variant", "") if hasattr(request, "query_params") else ""
    )
    risk_variant_policy_raw = (
        request.query_params.get("risk_variant_policy", "any") if hasattr(request, "query_params") else "any"
    )
    min_netprofit_yoy_raw = (
        request.query_params.get("min_netprofit_yoy", "") if hasattr(request, "query_params") else ""
    )
    min_ebit_yoy_raw = (
        request.query_params.get("min_ebit_yoy", "") if hasattr(request, "query_params") else ""
    )
    require_positive_prev_netprofit_raw = (
        request.query_params.get("require_positive_prev_netprofit", "1") if hasattr(request, "query_params") else "1"
    )
    require_positive_prev_ebit_raw = (
        request.query_params.get("require_positive_prev_ebit", "1") if hasattr(request, "query_params") else "1"
    )
    financial_filter_mode_raw = (
        request.query_params.get("financial_filter_mode", "all") if hasattr(request, "query_params") else "all"
    )
    priority_policy_raw = (
        request.query_params.get("priority_policy", "score_desc") if hasattr(request, "query_params") else "score_desc"
    )
    quick_preview_raw = (
        request.query_params.get("quick_preview", "0") if hasattr(request, "query_params") else "0"
    )
    preview_scan_limit_raw = (
        request.query_params.get("preview_scan_limit", "1200") if hasattr(request, "query_params") else "1200"
    )

    try:
        valuation_band_pct = max(0.01, float(valuation_band_pct_raw))
    except (TypeError, ValueError):
        valuation_band_pct = 0.1

    valuation_status = str(valuation_status).strip().lower()
    selected_valuation_method = str(valuation_method or "pe").strip().lower() or "pe"
    valuation_pick_strategy = _normalize_pick_strategy(valuation_pick_strategy_raw)
    valuation_variant = str(valuation_variant_raw or "").strip()
    risk_variant_policy = str(risk_variant_policy_raw or "any").strip().lower()
    if risk_variant_policy not in {"any", "specific"}:
        risk_variant_policy = "any"
    financial_filter_mode = str(financial_filter_mode_raw or "all").strip().lower()
    if financial_filter_mode not in {"all", "any"}:
        financial_filter_mode = "all"
    priority_policy = str(priority_policy_raw or "score_desc").strip().lower()
    if priority_policy not in {"score_desc", "high_price_first", "low_price_first", "deep_discount_first", "target_discount_first", "low_risk_high_score"}:
        priority_policy = "score_desc"
    quick_preview = _normalize_weekly_bool(quick_preview_raw, False)
    try:
        preview_scan_limit = int(str(preview_scan_limit_raw).strip())
    except (TypeError, ValueError):
        preview_scan_limit = 1200
    preview_scan_limit = max(100, min(preview_scan_limit, 5000))
    buy_candidate_only = str(buy_candidate_only_raw).strip().lower() in {
        "1", "true", "yes", "y", "on",
    }
    sw_industry = str(sw_industry_raw).strip()
    picking_mode = _normalize_predictive_mode(picking_mode_raw)
    valuation_report_type_text = str(earnings_report_type_raw or "").strip().upper()
    valuation_express_only = valuation_report_type_text in {"EXP", "EXPRESS", "σ┐½"}
    earnings_report_type = _normalize_earnings_report_type_with_all(earnings_report_type_raw)
    valuation_profit_report_type = _normalize_valuation_profit_report_type(earnings_report_type)
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
    try:
        fiscal_year = int(fiscal_year_raw) if str(fiscal_year_raw).strip() else None
    except (TypeError, ValueError):
        fiscal_year = None
    netprofit_growth = str(netprofit_growth_raw or "ALL").strip().upper()
    if netprofit_growth not in {"ALL", "MEDIUM", "HIGH"}:
        netprofit_growth = "ALL"
    # pred_earnings_growth is stored as ratio (e.g. 0.2 == 20%).
    min_netprofit_growth = 0.2 if netprofit_growth == "HIGH" else (0.1 if netprofit_growth == "MEDIUM" else None)
    min_netprofit_yoy = _to_float_or_none(min_netprofit_yoy_raw)
    min_ebit_yoy = _to_float_or_none(min_ebit_yoy_raw)
    require_positive_prev_netprofit = _normalize_weekly_bool(require_positive_prev_netprofit_raw, True)
    require_positive_prev_ebit = _normalize_weekly_bool(require_positive_prev_ebit_raw, True)
    financial_filters_enabled = (
        min_netprofit_yoy is not None
        or min_ebit_yoy is not None
        or bool(require_positive_prev_netprofit)
        or bool(require_positive_prev_ebit)
    )
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

    trading_values_qs = trading_qs.order_by("ts_code")
    if quick_preview and scope != "WATCHLIST":
        trading_values_qs = trading_values_qs[:preview_scan_limit]

    trading_rows = list(
        trading_values_qs.values(
            "ts_code",
            "close_qfq",
            "close",
            "pct_change_qfq",
        )
    )
    perf_after_trading = time.perf_counter()
    ts_codes = [row["ts_code"] for row in trading_rows]

    valuation_snapshot_map = _build_latest_snapshot_method_map(
        ts_codes=ts_codes,
        market="CN",
        pick_strategy=valuation_pick_strategy,
        max_trade_date=trade_date_for_query,
        express_only=valuation_express_only,
        profit_report_type=(None if valuation_express_only else valuation_profit_report_type),
    )
    predictive_anchor_snapshot_map = {}
    if picking_mode == "predictive" and valuation_express_only:
        predictive_anchor_snapshot_map = _build_latest_snapshot_method_map(
            ts_codes=ts_codes,
            market="CN",
            pick_strategy=valuation_pick_strategy,
            max_trade_date=trade_date_for_query,
            express_only=False,
        )
    industry_context_map = _build_industry_context_map(ts_codes=ts_codes, market="CN")

    traditional_risk_map = {}
    traditional_latest_risk_map = {}
    financial_panel_map = {}
    financial_metric_cache = {}
    if picking_mode != "predictive":
        traditional_latest_risk_map = _build_latest_risk_snapshot_map(ts_codes, market="CN")
        trade_date_for_risk = _parse_date_like(trade_date_for_query)
        if trade_date_for_risk is not None:
            traditional_risk_map = _build_risk_map(
                entry_dates=[trade_date_for_risk],
                market="CN",
                valuation_variant=valuation_variant if risk_variant_policy == "specific" else None,
            )
            if financial_filters_enabled:
                financial_panel_map = _load_financial_panel_map(ts_codes, trade_date_for_risk)

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

        buy_candidate_payload = _summarize_buy_candidate(
            current_price=current_price,
            method_map=method_map,
            band_pct=valuation_band_pct,
        )
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

        if min_valuation_score is not None and (valuation_score is None or float(valuation_score) < float(min_valuation_score)):
            continue

        if valuation_status and valuation_payload.get("valuation_status") != valuation_status:
            continue
        if buy_candidate_only and not buy_candidate_payload.get("buy_candidate"):
            continue

        traditional_metric_payload = {}
        if picking_mode != "predictive":
            trade_date_for_metrics = _parse_date_like(trade_date_for_query)
            risk_payload = traditional_risk_map.get((trade_date_for_metrics, ts_code)) or {}
            financial_payload = None
            if financial_filters_enabled and trade_date_for_metrics is not None:
                financial_payload = _resolve_financial_metrics(
                    financial_panel_map=financial_panel_map,
                    ts_code=ts_code,
                    trade_date=trade_date_for_metrics,
                    cache=financial_metric_cache,
                )
                if not _passes_financial_filters(
                    financial_payload,
                    min_netprofit_yoy=min_netprofit_yoy,
                    min_ebit_yoy=min_ebit_yoy,
                    financial_filter_mode=financial_filter_mode,
                    require_positive_prev_netprofit=require_positive_prev_netprofit,
                    require_positive_prev_ebit=require_positive_prev_ebit,
                ):
                    continue

            matched_risk_level = _normalize_risk_level_value(risk_payload.get("selected_variant_risk_level"))
            risk_levels = [
                _normalize_risk_level_value(level)
                for level in (risk_payload.get("risk_levels") or [])
            ]
            risk_levels = [level for level in risk_levels if level]
            fallback_risk_payload = traditional_latest_risk_map.get(ts_code) or {}
            fallback_risk_level = _normalize_risk_level_value(fallback_risk_payload.get("valuation_risk_level"))
            fallback_risk_score = _to_float_or_none(fallback_risk_payload.get("valuation_risk_score"))
            if not risk_levels and fallback_risk_level:
                risk_levels = [fallback_risk_level]
            if matched_risk_level is None and fallback_risk_level:
                matched_risk_level = fallback_risk_level
            if risk_level_set:
                if risk_variant_policy == "specific":
                    if matched_risk_level not in risk_level_set:
                        continue
                else:
                    if not any(level in risk_level_set for level in risk_levels):
                        continue

            netprofit_yoy = _to_float_or_none((financial_payload or {}).get("netprofit_yoy"))
            ebit_yoy = _to_float_or_none((financial_payload or {}).get("ebit_yoy"))
            prev_netprofit = _to_float_or_none((financial_payload or {}).get("prev_netprofit"))
            prev_ebit = _to_float_or_none((financial_payload or {}).get("prev_ebit"))

            financial_end_date = (financial_payload or {}).get("end_date")
            financial_ann_date = (financial_payload or {}).get("ann_date")
            row_risk_score = _to_float_or_none(risk_payload.get("min_risk_score"))
            if row_risk_score is None:
                row_risk_score = fallback_risk_score
            traditional_metric_payload = {
                "valuation_risk_score": row_risk_score,
                "valuation_risk_level": matched_risk_level or (risk_levels[0] if risk_levels else None),
                "financial_netprofit_yoy": netprofit_yoy,
                "financial_ebit_yoy": ebit_yoy,
                "financial_prev_netprofit": prev_netprofit,
                "financial_prev_ebit": prev_ebit,
                "financial_netprofit_end_date": financial_end_date,
                "financial_netprofit_ann_date": financial_ann_date,
            }

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

    if picking_mode == "predictive" and result:
        predictive_ts_codes = [row.get("ts_code") for row in result if row.get("ts_code")]
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

        predictive_rows = []
        for row in result:
            ts_code = row.get("ts_code")
            earnings_payload = earnings_map.get(ts_code) or _build_earnings_default_data(
                ts_code,
                earnings_report_type if earnings_report_type != "ALL" else "",
            )

            earnings_report_type_value = str(earnings_payload.get("report_type") or "UNKNOWN").upper()
            earnings_action_value = str(earnings_payload.get("action") or "HOLD").upper()
            earnings_risk_value = _normalize_risk_level_value(earnings_payload.get("risk_level")) or "MEDIUM"
            earnings_source_value = str(earnings_payload.get("feature_data_source") or "").strip().lower()
            earnings_fiscal_year = earnings_payload.get("financial_fiscal_year")
            pred_earnings_growth = _to_float_or_none(earnings_payload.get("pred_earnings_growth"))
            prev_year_netprofit_non_negative = earnings_payload.get("prev_year_netprofit_non_negative")
            earnings_signal_score = _to_float_or_none(earnings_payload.get("signal_score"))
            earnings_target_return_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))

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
            if fiscal_year is not None and earnings_fiscal_year != fiscal_year:
                continue
            if min_netprofit_growth is not None and (
                pred_earnings_growth is None or pred_earnings_growth < min_netprofit_growth
            ):
                continue
            if min_netprofit_growth is not None and prev_year_netprofit_non_negative is not True:
                continue

            merged_row = {
                **row,
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

    if picking_mode != "predictive":
        for item in result:
            current_price_for_rank = _to_float_or_none(item.get("close_qfq") or item.get("close"))
            target_price_for_rank = _to_float_or_none(item.get("composite_valuation_price"))
            conservative_price_for_rank = _to_float_or_none(item.get("conservative_valuation_price"))
            discount_pct = None
            target_discount_pct = None
            if current_price_for_rank not in (None, 0):
                if conservative_price_for_rank is not None:
                    discount_pct = (float(conservative_price_for_rank) / float(current_price_for_rank) - 1.0) * 100.0
                if target_price_for_rank is not None:
                    target_discount_pct = (float(target_price_for_rank) / float(current_price_for_rank) - 1.0) * 100.0
            item["_rank_key"] = _candidate_buy_rank_key(
                {
                    "score": item.get("valuation_score") if item.get("valuation_score") is not None else item.get("undervalue_score"),
                    "entry_price": current_price_for_rank,
                    "discount_pct": discount_pct,
                    "target_discount_pct": target_discount_pct,
                    "risk_score": item.get("valuation_risk_score"),
                    "ts_code": item.get("ts_code"),
                },
                priority_policy=priority_policy,
            )
        result.sort(key=lambda item: item.get("_rank_key") or ())
        for item in result:
            item.pop("_rank_key", None)

    paged_result = result[from_index:to_index]
    if picking_mode != "predictive":
        _attach_traditional_quick_metrics(paged_result, market="CN")
    _attach_recent_financial_report_badge(
        paged_result,
        asof_date=trade_date_for_query,
        market="CN",
    )
    _attach_signal_window_returns(
        paged_result,
        trade_date_for_query=trade_date_for_query,
        freq=normalized_freq,
        signal_end_date=latest_trade_date,
    )
    perf_after_all = time.perf_counter()

    def _ms(start, end):
        return round((end - start) * 1000.0, 2)

    timing_ms = {
        "total": _ms(perf_t0, perf_after_all),
        "load_trading_rows": _ms(perf_t0, perf_after_trading),
        "build_valuation_snapshot": _ms(perf_after_trading, perf_after_snapshot),
        "predictive_earnings_enrich": _ms(perf_after_snapshot, perf_after_earnings),
        "post_process_and_page": _ms(perf_after_earnings, perf_after_all),
    }
    if timing_ms["total"] >= 5000:
        logger.warning(
            "valuation pick slow request: trade_date=%s scope=%s freq=%s mode=%s total_ms=%s rows=%s filtered=%s page=%s-%s timing=%s filters=%s",
            trade_date_for_query,
            scope,
            normalized_freq,
            picking_mode,
            timing_ms["total"],
            len(trading_rows),
            len(result),
            from_index,
            to_index,
            timing_ms,
            {
                "valuation_method": selected_valuation_method,
                "valuation_status": valuation_status,
                "buy_candidate_only": buy_candidate_only,
                "risk_level": risk_level,
                "min_signal_score": min_signal_score,
                "min_valuation_score": min_valuation_score,
                "sw_industry": sw_industry,
            },
        )

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
                "sw_industry": sw_industry,
                "strict_snapshot_only": True,
                "picking_mode": picking_mode,
                "earnings_report_type": "σ┐½" if valuation_express_only else earnings_report_type,
                "signal_action": signal_action,
                "risk_level": risk_level,
                "min_signal_score": min_signal_score,
                "min_target_return_pct": min_target_return_pct,
                "feature_data_source": feature_data_source,
                "fiscal_year": fiscal_year,
                "netprofit_growth": netprofit_growth,
                "valuation_variant": valuation_variant,
                "risk_variant_policy": risk_variant_policy,
                "min_netprofit_yoy": min_netprofit_yoy,
                "min_ebit_yoy": min_ebit_yoy,
                "require_positive_prev_netprofit": require_positive_prev_netprofit,
                "require_positive_prev_ebit": require_positive_prev_ebit,
                "financial_filter_mode": financial_filter_mode,
                "priority_policy": priority_policy,
                "valuation_score": valuation_score_level,
                "min_valuation_score": min_valuation_score,
                "quick_preview": quick_preview,
                "preview_scan_limit": preview_scan_limit,
            },
            "meta": {
                "latest_trade_date_for_freq": latest_trade_date,
                "requested_trade_date_has_data": requested_date_has_data,
                "requested_trade_date": normalized_trade_date,
                "resolved_trade_date": trade_date_for_query,
                "auto_latest": auto_latest,
                "total_filtered": len(result),
                "strategy_effective_stocks": multi_candidate_rows,
                "page_from_index": from_index,
                "page_to_index": to_index,
                "current_page_size": len(paged_result),
                "scan_symbol_count": len(trading_rows),
                "valuation_method_recommendation_desc": recommendation_desc,
                "sw_industry": sw_industry,
                "predictive_mode_enabled": picking_mode == "predictive",
                "timing_ms": timing_ms,
                "predictive_earnings_stats": predictive_earnings_stats,
            },
        }
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

        latest_rec = (
            df.iloc[0].replace({float("nan"): "n/a"}).to_dict() if not df.empty else {}
        )
        return Response({"data": latest_rec})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


DEFAULT_TRADITIONAL_TIER_SCHEMES = {
    "high_growth": {
        "style_label": "Θ½ÿσó₧Θò┐",
        "tiers": {
            "conservative": {
                "label": "ΘúÄµÄºΣ╝ÿσàê",
                "weights": {
                    "pe": 0.20,
                    "peg": 0.20,
                    "ps": 0.15,
                    "scarcity_overlay": 0.15,
                    "sw_history": 0.10,
                    "fcff_dcf": 0.10,
                    "pb": 0.08,
                    "ddm": 0.02,
                },
                "range_multiplier": (0.94, 1.04),
            },
            "balanced": {
                "label": "σ╣│Φíí",
                "weights": {
                    "pe": 0.28,
                    "peg": 0.24,
                    "ps": 0.16,
                    "scarcity_overlay": 0.14,
                    "sw_history": 0.08,
                    "fcff_dcf": 0.06,
                    "pb": 0.03,
                    "ddm": 0.01,
                },
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "µêÉΘò┐Φ┐¢µö╗",
                "weights": {
                    "pe": 0.35,
                    "peg": 0.28,
                    "ps": 0.16,
                    "scarcity_overlay": 0.12,
                    "sw_history": 0.06,
                    "fcff_dcf": 0.02,
                    "pb": 0.01,
                    "ddm": 0.00,
                },
                "range_multiplier": (0.95, 1.15),
            },
        },
    },
    "stable_value": {
        "style_label": "Σ╜Äσó₧Θò┐τ¿│σ«Ü",
        "tiers": {
            "conservative": {
                "label": "ΘúÄµÄºΣ╝ÿσàê",
                "weights": {
                    "pb": 0.30,
                    "fcff_dcf": 0.24,
                    "pe": 0.16,
                    "sw_history": 0.10,
                    "ps": 0.08,
                    "scarcity_overlay": 0.06,
                    "peg": 0.04,
                    "ddm": 0.02,
                },
                "range_multiplier": (0.96, 1.04),
            },
            "balanced": {
                "label": "σ╣│Φíí",
                "weights": {
                    "pb": 0.24,
                    "fcff_dcf": 0.22,
                    "pe": 0.20,
                    "sw_history": 0.12,
                    "ps": 0.10,
                    "scarcity_overlay": 0.06,
                    "peg": 0.04,
                    "ddm": 0.02,
                },
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "µö╢τ¢èσó₧σ╝║",
                "weights": {
                    "pb": 0.18,
                    "fcff_dcf": 0.17,
                    "pe": 0.28,
                    "sw_history": 0.12,
                    "ps": 0.12,
                    "scarcity_overlay": 0.07,
                    "peg": 0.04,
                    "ddm": 0.02,
                },
                "range_multiplier": (0.94, 1.13),
            },
        },
    },
    "balanced": {
        "style_label": "σ¥çΦíí",
        "tiers": {
            "conservative": {
                "label": "ΘúÄµÄºΣ╝ÿσàê",
                "weights": {
                    "pe": 0.23,
                    "peg": 0.18,
                    "ps": 0.14,
                    "scarcity_overlay": 0.12,
                    "sw_history": 0.12,
                    "fcff_dcf": 0.10,
                    "pb": 0.09,
                    "ddm": 0.02,
                },
                "range_multiplier": (0.95, 1.04),
            },
            "balanced": {
                "label": "σ╣│Φíí",
                "weights": {
                    "pe": 0.26,
                    "peg": 0.20,
                    "ps": 0.15,
                    "scarcity_overlay": 0.12,
                    "sw_history": 0.10,
                    "fcff_dcf": 0.09,
                    "pb": 0.06,
                    "ddm": 0.02,
                },
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "µö╢τ¢èσó₧σ╝║",
                "weights": {
                    "pe": 0.31,
                    "peg": 0.24,
                    "ps": 0.15,
                    "scarcity_overlay": 0.11,
                    "sw_history": 0.08,
                    "fcff_dcf": 0.06,
                    "pb": 0.04,
                    "ddm": 0.01,
                },
                "range_multiplier": (0.95, 1.14),
            },
        },
    },
    "cyclical_resource": {
        "style_label": "σæ¿µ£ƒΦ╡äµ║É",
        "tiers": {
            "conservative": {
                "label": "ΘúÄµÄºΣ╝ÿσàê",
                "weights": {
                    "sw_history": 0.22,
                    "scarcity_overlay": 0.20,
                    "fcff_dcf": 0.18,
                    "pb": 0.16,
                    "ps": 0.10,
                    "pe": 0.08,
                    "peg": 0.04,
                    "ddm": 0.02,
                },
                "range_multiplier": (0.95, 1.04),
            },
            "balanced": {
                "label": "σ╣│Φíí",
                "weights": {
                    "sw_history": 0.24,
                    "scarcity_overlay": 0.22,
                    "fcff_dcf": 0.20,
                    "ps": 0.14,
                    "pb": 0.10,
                    "pe": 0.06,
                    "peg": 0.03,
                    "ddm": 0.01,
                },
                "range_multiplier": (0.95, 1.08),
            },
            "aggressive": {
                "label": "µö╢τ¢èσó₧σ╝║",
                "weights": {
                    "sw_history": 0.27,
                    "scarcity_overlay": 0.24,
                    "fcff_dcf": 0.22,
                    "ps": 0.17,
                    "pb": 0.07,
                    "pe": 0.02,
                    "peg": 0.01,
                    "ddm": 0.00,
                },
                "range_multiplier": (0.95, 1.14),
            },
        },
    },
}

DEFAULT_TRADITIONAL_INDUSTRY_SCHEME_OVERRIDES = [
    {
        "scheme_key": "cyclical_resource",
        "keywords": ["Θ╗äΘçæ", "µ£ëΦë▓", "Θô£", "Θô¥", "τàñτé¡", "τƒ│µ▓╣", "σñ⌐τä╢µ░ö", "ΘÆóΘôü"],
    },
]

DEFAULT_TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS = [
    "σìèσ»╝Σ╜ô", "τö╡σ¡É", "Φ╜»Σ╗╢", "Σ║ÆΦüöτ╜æ", "Σ╝áσ¬Æ", "τöƒτë⌐", "σî╗Φì»", "σå¢σ╖Ñ", "ΘÇÜΣ┐í",
]
DEFAULT_TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS = [
    "Θô╢Φíî", "Σ┐¥ΘÖ⌐", "σà¼τö¿", "τàñτé¡", "ΘÆóΘôü", "Σ║ñΦ┐É", "σ£░Σ║º",
]
DEFAULT_TRADITIONAL_STYLE_SCORE_RULES = {
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
DEFAULT_TRADITIONAL_STYLE_SCORE_THRESHOLDS = {
    "high_growth_min": 1.1,
    "stable_value_max": -0.35,
}
DEFAULT_TRADITIONAL_POSITION_GUIDANCE_RULES = {
    "no_price": {
        "suggested_position_range": "30%-55%",
        "message": "σ╜ôσëìΣ╗╖Σ╕ìσÅ»τö¿∩╝îΘ╗ÿΦ«ñτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé",
    },
    "below_conservative": {
        "suggested_position_range": "60%-75%",
        "message": "σ╜ôσëìΣ╗╖Σ╜ÄΣ║ÄΘúÄµÄºσî║Θù┤Σ╕ïµ▓┐∩╝îσÅ»ΦÇâΦÖæσêåµë╣µÅÉΘ½ÿΣ╗ôΣ╜ìπÇé",
    },
    "below_balanced": {
        "suggested_position_range": "45%-65%",
        "message": "σ╜ôσëìΣ╗╖Σ╜ÄΣ║Äσ╣│Φííσî║Θù┤∩╝îσÅ»ΦÇâΦÖæΘÇÉµ¡ÑσèáΣ╗ôπÇé",
    },
    "within_balanced": {
        "suggested_position_range": "35%-55%",
        "message": "σ╜ôσëìΣ╗╖Σ╜ìΣ║Äσ╣│Φííσî║Θù┤∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé",
    },
    "within_aggressive": {
        "suggested_position_range": "25%-40%",
        "message": "σ╜ôσëìΣ╗╖σñäΣ║ÄσüÅΘ½ÿσî║Θù┤∩╝îσ╗║Φ««ΘÇÉµ¡ÑΘÖìΣ╜ÄΣ╗ôΣ╜ìπÇé",
    },
    "above_aggressive": {
        "suggested_position_range": "15%-30%",
        "message": "σ╜ôσëìΣ╗╖Θ½ÿΣ║ÄΦ┐¢µö╗σî║Θù┤Σ╕èµ▓┐∩╝îσ╗║Φ««σüÅΘÿ▓σ«êΣ╗ôΣ╜ìπÇé",
    },
    "volatility_thresholds": {
        "low_max": 0.03,
        "high_min": 0.06,
    },
    "style_volatility_layers": {
        "high_growth": {
            "low": {
                "below_conservative": {"suggested_position_range": "60%-78%", "message": "Θ½ÿσó₧Θò┐Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îσüÅΦ┐¢µö╗Σ╜åΣ┐¥τòÖσ«ëσà¿σ₧½πÇé"},
                "below_balanced": {"suggested_position_range": "48%-68%", "message": "Θ½ÿσó₧Θò┐Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îΘÇéσÉêΘÇÉµ¡ÑσèáΣ╗ôπÇé"},
                "within_balanced": {"suggested_position_range": "38%-58%", "message": "Θ½ÿσó₧Θò┐Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îτ╗┤µîüΣ╕¡µÇºσüÅσñÜΣ╗ôΣ╜ìπÇé"},
                "within_aggressive": {"suggested_position_range": "26%-42%", "message": "Θ½ÿσó₧Θò┐Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îµÄÑΦ┐æτ¢«µáçσî║Θù┤Σ╕èµ▓┐∩╝îσÅ»µÄºΣ╗ôΦºéσ»ƒπÇé"},
                "above_aggressive": {"suggested_position_range": "18%-30%", "message": "Θ½ÿσó₧Θò┐Σ╜åΣ╗╖µá╝σ╖▓σüÅΘ½ÿ∩╝îσ╗║Φ««ΘÖìΣ╜ÄΦ┐╜Θ½ÿΣ╗ôΣ╜ìπÇé"},
            },
            "medium": {
                "below_conservative": {"suggested_position_range": "58%-75%", "message": "Θ½ÿσó₧Θò┐πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îΘÇéσÉêσêåµë╣σèáΣ╗ôπÇé"},
                "below_balanced": {"suggested_position_range": "45%-65%", "message": "Θ½ÿσó₧Θò┐πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îµîëΦèéσÑÅµÅÉΘ½ÿΣ╗ôΣ╜ìπÇé"},
                "within_balanced": {"suggested_position_range": "35%-55%", "message": "Θ½ÿσó₧Θò┐πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îτ╗┤µîüµá╕σ┐âΣ╗ôΣ╜ìπÇé"},
                "within_aggressive": {"suggested_position_range": "24%-38%", "message": "Θ½ÿσó₧Θò┐πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îµÄÑΦ┐æΦ┐¢µö╗Σ╕èµ▓┐∩╝îΣ╗ôΣ╜ìσ«£µö╢µò¢πÇé"},
                "above_aggressive": {"suggested_position_range": "15%-28%", "message": "Θ½ÿσó₧Θò┐Σ╜åµ│óσè¿σ╖▓µö╛σñº∩╝îσ╗║Φ««σüÅΘÿ▓σ«êπÇé"},
            },
            "high": {
                "below_conservative": {"suggested_position_range": "52%-68%", "message": "Θ½ÿσó₧Θò┐Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««σüÅΣ┐¥σ«êσêåµë╣πÇé"},
                "below_balanced": {"suggested_position_range": "40%-58%", "message": "Θ½ÿσó₧Θò┐Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ┐¥τòÖµ£║σè¿Σ╗ôπÇé"},
                "within_balanced": {"suggested_position_range": "30%-48%", "message": "Θ½ÿσó₧Θò┐Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ╗ÑΣ╕¡Σ╜ÄΣ╗ôΣ╜ìµîüµ£ëπÇé"},
                "within_aggressive": {"suggested_position_range": "20%-35%", "message": "Θ½ÿσó₧Θò┐Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««ΘÇÉµ¡ÑΘÖìΣ╗ôπÇé"},
                "above_aggressive": {"suggested_position_range": "12%-25%", "message": "Θ½ÿσó₧Θò┐Σ╕öµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ╕Ñµá╝Θÿ▓σ«êπÇé"},
            },
        },
        "stable_value": {
            "low": {
                "below_conservative": {"suggested_position_range": "62%-82%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îσÅ»ΘÇéσ║ªµÅÉΘ½ÿσ║òΣ╗ôπÇé"},
                "below_balanced": {"suggested_position_range": "50%-70%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îΘÇéσÉêτ¿│µ¡ÑσèáΣ╗ôπÇé"},
                "within_balanced": {"suggested_position_range": "40%-60%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îσ«£τ╗┤µîüσ¥çΦííΣ╗ôΣ╜ìπÇé"},
                "within_aggressive": {"suggested_position_range": "28%-42%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╜åΣ╗╖µá╝σüÅΘ½ÿ∩╝îσÅ»ΘÇéσ║ªσçÅΣ╗ôπÇé"},
                "above_aggressive": {"suggested_position_range": "18%-30%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╜åΣ╗╖µá╝σ╖▓σüÅΘ½ÿ∩╝îσ╗║Φ««σüÅΘÿ▓σ«êπÇé"},
            },
            "medium": {
                "below_conservative": {"suggested_position_range": "58%-76%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜπÇüµ│óσè¿Σ╕¡τ¡ë∩╝îσ╗║Φ««σêåµë╣µÅÉΘ½ÿΣ╗ôΣ╜ìπÇé"},
                "below_balanced": {"suggested_position_range": "46%-66%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜπÇüµ│óσè¿Σ╕¡τ¡ë∩╝îΘÇéσÉêΘÇÉµ¡ÑσèáΣ╗ôπÇé"},
                "within_balanced": {"suggested_position_range": "36%-56%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜπÇüµ│óσè¿Σ╕¡τ¡ë∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé"},
                "within_aggressive": {"suggested_position_range": "26%-40%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜπÇüµ│óσè¿Σ╕¡τ¡ë∩╝îΘÇÉµ¡ÑΘÖìΣ╜ÄΣ╗ôΣ╜ìπÇé"},
                "above_aggressive": {"suggested_position_range": "16%-28%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╜åΣ╗╖µá╝σüÅΘ½ÿ∩╝îσ╗║Φ««σüÅΘÿ▓σ«êπÇé"},
            },
            "high": {
                "below_conservative": {"suggested_position_range": "54%-70%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ┐¥σ«êσèáΣ╗ôπÇé"},
                "below_balanced": {"suggested_position_range": "42%-60%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ┐¥µîüµ£║σè¿µÇºπÇé"},
                "within_balanced": {"suggested_position_range": "32%-48%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ╜ÄΣ╕¡Σ╗ôΣ╜ìµîüµ£ëπÇé"},
                "within_aggressive": {"suggested_position_range": "22%-36%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««µö╢µò¢Σ╗ôΣ╜ìπÇé"},
                "above_aggressive": {"suggested_position_range": "12%-24%", "message": "Σ╜Äσó₧Θò┐τ¿│σ«ÜΣ╕öµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ╕Ñµá╝Θÿ▓σ«êπÇé"},
            },
        },
        "balanced": {
            "low": {
                "below_conservative": {"suggested_position_range": "60%-77%", "message": "σ¥çΦííΘúÄµá╝Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îσÅ»ΘÇéσ║ªµÅÉΘ½ÿΣ╗ôΣ╜ìπÇé"},
                "below_balanced": {"suggested_position_range": "48%-67%", "message": "σ¥çΦííΘúÄµá╝Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îΘÇéσÉêσêåµë╣σèáΣ╗ôπÇé"},
                "within_balanced": {"suggested_position_range": "38%-58%", "message": "σ¥çΦííΘúÄµá╝Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îτ╗┤µîüσ¥çΦííΣ╗ôΣ╜ìπÇé"},
                "within_aggressive": {"suggested_position_range": "26%-40%", "message": "σ¥çΦííΘúÄµá╝Σ╕öµ│óσè¿Φ╛âΣ╜Ä∩╝îµÄÑΦ┐æΣ╕èµ▓┐∩╝îσÅ»ΘÇéσ║ªΘÖìΣ╗ôπÇé"},
                "above_aggressive": {"suggested_position_range": "16%-28%", "message": "σ¥çΦííΘúÄµá╝Σ╜åΣ╗╖µá╝σüÅΘ½ÿ∩╝îσ╗║Φ««Θÿ▓σ«êπÇé"},
            },
            "medium": {
                "below_conservative": {"suggested_position_range": "58%-74%", "message": "σ¥çΦííΘúÄµá╝πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îσ╗║Φ««σêåµë╣µÅÉΘ½ÿΣ╗ôΣ╜ìπÇé"},
                "below_balanced": {"suggested_position_range": "45%-64%", "message": "σ¥çΦííΘúÄµá╝πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îΘÇéσÉêΘÇÉµ¡ÑσèáΣ╗ôπÇé"},
                "within_balanced": {"suggested_position_range": "35%-55%", "message": "σ¥çΦííΘúÄµá╝πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé"},
                "within_aggressive": {"suggested_position_range": "25%-38%", "message": "σ¥çΦííΘúÄµá╝πÇüµ│óσè¿Σ╕¡τ¡ë∩╝îσ╗║Φ««µö╢µò¢Σ╗ôΣ╜ìπÇé"},
                "above_aggressive": {"suggested_position_range": "15%-26%", "message": "σ¥çΦííΘúÄµá╝Σ╜åΣ╗╖µá╝σüÅΘ½ÿ∩╝îσ╗║Φ««σüÅΘÿ▓σ«êπÇé"},
            },
            "high": {
                "below_conservative": {"suggested_position_range": "54%-70%", "message": "σ¥çΦííΘúÄµá╝Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ┐¥σ«êσèáΣ╗ôπÇé"},
                "below_balanced": {"suggested_position_range": "42%-60%", "message": "σ¥çΦííΘúÄµá╝Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ┐¥µîüµ£║σè¿µÇºπÇé"},
                "within_balanced": {"suggested_position_range": "32%-48%", "message": "σ¥çΦííΘúÄµá╝Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Σ╕¡Σ╜ÄΣ╗ôΣ╜ìµîüµ£ëπÇé"},
                "within_aggressive": {"suggested_position_range": "22%-35%", "message": "σ¥çΦííΘúÄµá╝Σ╜åµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««ΘÇÉµ¡ÑΘÖìΣ╗ôπÇé"},
                "above_aggressive": {"suggested_position_range": "12%-24%", "message": "σ¥çΦííΘúÄµá╝Σ╕öµ│óσè¿σüÅΘ½ÿ∩╝îσ╗║Φ««Θÿ▓σ«êπÇé"},
            },
        },
    },
    "summary_templates": {
        "default": "{style_label} | {volatility_label} | {state_label} | Σ╗ôΣ╜ì {suggested_position_range}",
        "holding": "{style_label}ΘúÄµá╝πÇü{volatility_label}πÇü{state_label}∩╝îσ╗║Φ««Σ╗ôΣ╜ì {suggested_position_range}∩╝¢{message}",
    },
}


def _load_dict_setting(name, default_value):
    candidate = getattr(settings, name, default_value)
    if isinstance(candidate, dict):
        return candidate
    return default_value


def _load_list_setting(name, default_value):
    candidate = getattr(settings, name, default_value)
    if isinstance(candidate, (list, tuple, set)):
        return list(candidate)
    return list(default_value)


def _load_tier_schemes_setting(name, default_value):
    merged = dict(default_value or {})
    candidate = getattr(settings, name, None)
    if not isinstance(candidate, dict):
        return merged
    for key, value in candidate.items():
        merged[key] = value
    return merged


TRADITIONAL_TIER_SCHEMES = _load_tier_schemes_setting(
    "TRADITIONAL_TIER_SCHEMES",
    DEFAULT_TRADITIONAL_TIER_SCHEMES,
)
TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS = _load_list_setting(
    "TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS",
    DEFAULT_TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS,
)
TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS = _load_list_setting(
    "TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS",
    DEFAULT_TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS,
)
TRADITIONAL_STYLE_SCORE_RULES = _load_dict_setting(
    "TRADITIONAL_STYLE_SCORE_RULES",
    DEFAULT_TRADITIONAL_STYLE_SCORE_RULES,
)
TRADITIONAL_STYLE_SCORE_THRESHOLDS = _load_dict_setting(
    "TRADITIONAL_STYLE_SCORE_THRESHOLDS",
    DEFAULT_TRADITIONAL_STYLE_SCORE_THRESHOLDS,
)
TRADITIONAL_POSITION_GUIDANCE_RULES = _load_dict_setting(
    "TRADITIONAL_POSITION_GUIDANCE_RULES",
    DEFAULT_TRADITIONAL_POSITION_GUIDANCE_RULES,
)
TRADITIONAL_INDUSTRY_SCHEME_OVERRIDES = _load_list_setting(
    "TRADITIONAL_INDUSTRY_SCHEME_OVERRIDES",
    DEFAULT_TRADITIONAL_INDUSTRY_SCHEME_OVERRIDES,
)

DEFAULT_TRADITIONAL_METHOD_WINSOR_RULES = {
    "enabled": True,
    "lower_percentile": 0.15,
    "upper_percentile": 0.85,
    "min_methods": 6,
}
TRADITIONAL_METHOD_WINSOR_RULES = _load_dict_setting(
    "TRADITIONAL_METHOD_WINSOR_RULES",
    DEFAULT_TRADITIONAL_METHOD_WINSOR_RULES,
)

DEFAULT_PREDICTIVE_TIER_TEMPLATE_CONFIG = {
    "reliability": {
        "score_min": 5.0,
        "score_max": 95.0,
        "default_signal_score": 50.0,
        "risk_penalty": {
            "HIGH": 18.0,
            "MEDIUM": 8.0,
            "LOW": 0.0,
            "DEFAULT": 5.0,
        },
        "dispersion_penalty_multiplier": 60.0,
        "dispersion_penalty_cap": 25.0,
        "freshness_days_per_penalty": 8.0,
        "freshness_penalty_cap": 20.0,
    },
    "style_thresholds": {
        "high_confidence_min": 75.0,
        "low_confidence_max": 50.0,
    },
    "styles": {
        "high_confidence": {
            "label": "Θ½ÿσÅ»Σ┐íσ║ª",
            "blend_high_weight": {
                "conservative": 0.14,
                "balanced": 0.62,
                "aggressive": 0.80,
            },
        },
        "balanced": {
            "label": "σ¥çΦííσÅ»Σ┐íσ║ª",
            "blend_high_weight": {
                "conservative": 0.14,
                "balanced": 0.50,
                "aggressive": 0.80,
            },
        },
        "low_confidence": {
            "label": "Φ░¿µàÄσÅ»Σ┐íσ║ª",
            "blend_high_weight": {
                "conservative": 0.14,
                "balanced": 0.38,
                "aggressive": 0.80,
            },
        },
    },
    "tier_ranges": {
        "conservative": [0.95, 1.04],
        "balanced": [0.95, 1.08],
        "aggressive": [0.95, 1.15],
    },
    "position_guidance": {
        "below_conservative": {
            "default": {"range": "55%-70%", "message": "Σ╜ÄΣ║ÄΘúÄµÄºσî║Θù┤Σ╕ïµ▓┐∩╝îσÅ»σêåµë╣µÅÉΘ½ÿΣ╗ôΣ╜ìπÇé"},
            "high_confidence": {"range": "65%-80%", "message": "Σ╜ÄΣ║ÄΘúÄµÄºσî║Θù┤Σ╕ïµ▓┐Σ╕öσÅ»Σ┐íσ║ªΘ½ÿ∩╝îσÅ»τº»µ₧üσêåµë╣µÅÉΘ½ÿΣ╗ôΣ╜ìπÇé"},
        },
        "below_balanced": {
            "default": {"range": "45%-65%", "message": "Σ╜ÄΣ║Äσ╣│Φííσî║Θù┤∩╝îσÅ»ΘÇÉµ¡ÑσèáΣ╗ôπÇé"},
            "low_confidence": {"range": "40%-55%", "message": "Σ╜ÄΣ║Äσ╣│Φííσî║Θù┤Σ╜åσÅ»Σ┐íσ║ªσüÅΣ╜Ä∩╝îσ╗║Φ««µ╕⌐σÆîσèáΣ╗ôπÇé"},
        },
        "within_balanced": {
            "default": {"range": "35%-55%", "message": "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé"},
        },
        "within_aggressive": {
            "default": {"range": "25%-40%", "message": "σñäΣ║ÄσüÅΘ½ÿσî║Θù┤∩╝îσÅ»ΘÇÉµ¡ÑΘÖìΣ╜ÄΣ╗ôΣ╜ìπÇé"},
        },
        "above_aggressive": {
            "default": {"range": "15%-30%", "message": "Θ½ÿΣ║ÄΦ┐¢µö╗σî║Θù┤Σ╕èµ▓┐∩╝îσ╗║Φ««σüÅΘÿ▓σ«êΣ╗ôΣ╜ìπÇé"},
            "high_confidence": {"range": "20%-35%", "message": "Θ½ÿΣ║ÄΦ┐¢µö╗σî║Θù┤Σ╕èµ▓┐∩╝îσ╗║Φ««σüÅΘÿ▓σ«êΣ╗ôΣ╜ìσ╣╢τ¡ëσ╛àµ¢┤Σ╝ÿΘúÄΘÖ⌐µö╢τ¢èµ»öπÇé"},
        },
    },
}

PREDICTIVE_TIER_TEMPLATE_CONFIG = _load_dict_setting(
    "PREDICTIVE_TIER_TEMPLATE_CONFIG",
    DEFAULT_PREDICTIVE_TIER_TEMPLATE_CONFIG,
)


def _resolve_predictive_guidance(state_key, style_key, guidance_cfg):
    state_cfg = guidance_cfg.get(state_key) if isinstance(guidance_cfg, dict) else None
    if not isinstance(state_cfg, dict):
        return {"range": "35%-55%", "message": "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé"}

    style_cfg = state_cfg.get(style_key)
    if isinstance(style_cfg, dict):
        return {
            "range": str(style_cfg.get("range") or "35%-55%"),
            "message": str(style_cfg.get("message") or "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé"),
        }

    default_cfg = state_cfg.get("default")
    if isinstance(default_cfg, dict):
        return {
            "range": str(default_cfg.get("range") or "35%-55%"),
            "message": str(default_cfg.get("message") or "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé"),
        }

    return {"range": "35%-55%", "message": "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé"}


def _build_predictive_tiered_template(payload, current_price=None, latest_trade_date=None):
    if not isinstance(payload, dict):
        return None

    cp = _to_float_or_none(current_price)
    if cp is None or cp <= 0:
        cp = _to_float_or_none(payload.get("anchor_basis_price"))
    if cp is None or cp <= 0:
        return None

    low = _to_float_or_none(payload.get("target_price_low_raw"))
    if low is None:
        low = _to_float_or_none(payload.get("target_price_low"))
    if low is None:
        low = _to_float_or_none(payload.get("target_price_raw"))
    if low is None:
        low = _to_float_or_none(payload.get("target_price"))

    high = _to_float_or_none(payload.get("target_price_high_raw"))
    if high is None:
        high = _to_float_or_none(payload.get("target_price_high"))
    if high is None:
        high = _to_float_or_none(payload.get("target_price_raw"))
    if high is None:
        high = _to_float_or_none(payload.get("target_price"))

    if low is None or high is None or low <= 0 or high <= 0:
        return None

    lo = min(low, high)
    hi = max(low, high)

    cfg = PREDICTIVE_TIER_TEMPLATE_CONFIG or DEFAULT_PREDICTIVE_TIER_TEMPLATE_CONFIG
    reliability_cfg = cfg.get("reliability") if isinstance(cfg, dict) else {}
    threshold_cfg = cfg.get("style_thresholds") if isinstance(cfg, dict) else {}
    style_cfg = cfg.get("styles") if isinstance(cfg, dict) else {}
    tier_range_cfg = cfg.get("tier_ranges") if isinstance(cfg, dict) else {}
    guidance_cfg = cfg.get("position_guidance") if isinstance(cfg, dict) else {}

    score_min = float(reliability_cfg.get("score_min", 5.0) or 5.0)
    score_max = float(reliability_cfg.get("score_max", 95.0) or 95.0)
    signal_default = float(reliability_cfg.get("default_signal_score", 50.0) or 50.0)
    risk_penalty_cfg = reliability_cfg.get("risk_penalty") if isinstance(reliability_cfg.get("risk_penalty"), dict) else {}
    risk_default_penalty = float(risk_penalty_cfg.get("DEFAULT", 5.0) or 5.0)

    signal_score = _to_float_or_none(payload.get("signal_score"))
    if signal_score is None:
        signal_score = signal_default
    signal_score = max(0.0, min(100.0, signal_score))

    risk_level = str(payload.get("risk_level") or "").strip().upper()
    risk_penalty = float(risk_penalty_cfg.get(risk_level, risk_default_penalty) or risk_default_penalty)

    dispersion = (hi - lo) / cp
    dispersion_penalty_multiplier = float(reliability_cfg.get("dispersion_penalty_multiplier", 60.0) or 60.0)
    dispersion_penalty_cap = float(reliability_cfg.get("dispersion_penalty_cap", 25.0) or 25.0)
    dispersion_penalty = max(0.0, min(dispersion_penalty_cap, dispersion * dispersion_penalty_multiplier))

    asof_date = _parse_date_like(payload.get("asof_date"))
    anchor_trade_date = _parse_date_like(latest_trade_date) or asof_date
    freshness_days_per_penalty = float(reliability_cfg.get("freshness_days_per_penalty", 8.0) or 8.0)
    freshness_penalty_cap = float(reliability_cfg.get("freshness_penalty_cap", 20.0) or 20.0)
    freshness_penalty = 0.0
    stale_days = 0
    if asof_date is not None and anchor_trade_date is not None:
        stale_days = max((anchor_trade_date - asof_date).days, 0)
        freshness_penalty = max(0.0, min(freshness_penalty_cap, stale_days / max(0.1, freshness_days_per_penalty)))

    reliability_score = signal_score - risk_penalty - dispersion_penalty - freshness_penalty
    reliability_score = max(score_min, min(score_max, reliability_score))

    high_confidence_min = float(threshold_cfg.get("high_confidence_min", 75.0) or 75.0)
    low_confidence_max = float(threshold_cfg.get("low_confidence_max", 50.0) or 50.0)
    if reliability_score >= high_confidence_min:
        selected_style_key = "high_confidence"
    elif reliability_score < low_confidence_max:
        selected_style_key = "low_confidence"
    else:
        selected_style_key = "balanced"

    selected_style_cfg = style_cfg.get(selected_style_key) if isinstance(style_cfg, dict) else {}
    if not isinstance(selected_style_cfg, dict):
        selected_style_cfg = {}
    blend_cfg = selected_style_cfg.get("blend_high_weight") if isinstance(selected_style_cfg.get("blend_high_weight"), dict) else {}

    def _blend_target(tier_key, fallback_weight):
        high_weight = float(blend_cfg.get(tier_key, fallback_weight) or fallback_weight)
        high_weight = max(0.0, min(1.0, high_weight))
        return lo * (1.0 - high_weight) + hi * high_weight

    target_conservative = _blend_target("conservative", 0.14)
    target_balanced = _blend_target("balanced", 0.5)
    target_aggressive = _blend_target("aggressive", 0.8)

    def _tier_bounds(tier_key, fallback_low, fallback_high):
        pair = tier_range_cfg.get(tier_key)
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            return float(pair[0]), float(pair[1])
        return float(fallback_low), float(fallback_high)

    con_low_mul, con_high_mul = _tier_bounds("conservative", 0.95, 1.04)
    bal_low_mul, bal_high_mul = _tier_bounds("balanced", 0.95, 1.08)
    agg_low_mul, agg_high_mul = _tier_bounds("aggressive", 0.95, 1.15)

    def _build_tier(target, low_mul, high_mul):
        return {
            "targetPrice": round(target, 4),
            "expectedReturnPct": round(((target / cp) - 1.0) * 100.0, 2),
            "rangeLower": round(target * low_mul, 4),
            "rangeUpper": round(target * high_mul, 4),
        }

    tiers = {
        "conservative": _build_tier(target_conservative, con_low_mul, con_high_mul),
        "balanced": _build_tier(target_balanced, bal_low_mul, bal_high_mul),
        "aggressive": _build_tier(target_aggressive, agg_low_mul, agg_high_mul),
    }

    state_key = "within_balanced"
    if cp < tiers["conservative"]["rangeLower"]:
        state_key = "below_conservative"
    elif cp < tiers["balanced"]["rangeLower"]:
        state_key = "below_balanced"
    elif cp > tiers["aggressive"]["rangeUpper"]:
        state_key = "above_aggressive"
    elif cp > tiers["balanced"]["rangeUpper"]:
        state_key = "within_aggressive"

    guidance = _resolve_predictive_guidance(state_key, selected_style_key, guidance_cfg)
    style_label = str(selected_style_cfg.get("label") or selected_style_key)

    return {
        "styleKey": selected_style_key,
        "styleLabel": style_label,
        "reliabilityScore": round(reliability_score, 2),
        "reasons": [
            f"signal={signal_score:.1f}",
            f"risk={risk_level or '-'}",
            f"dispersion={dispersion * 100.0:.2f}%",
            f"fresh_penalty={freshness_penalty:.1f}",
        ],
        "tiers": tiers,
        "positionRange": guidance.get("range") or "35%-55%",
        "positionMessage": guidance.get("message") or "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤∩╝îτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé",
    }


def _resolve_traditional_style(industry_name, indicator_profile, method_price_map):
    name = str(industry_name or "").lower()
    growth_score = 0.0
    reasons = []
    score_rules = TRADITIONAL_STYLE_SCORE_RULES or DEFAULT_TRADITIONAL_STYLE_SCORE_RULES
    score_thresholds = TRADITIONAL_STYLE_SCORE_THRESHOLDS or DEFAULT_TRADITIONAL_STYLE_SCORE_THRESHOLDS
    growth_keywords = [str(item).lower() for item in (TRADITIONAL_STYLE_INDUSTRY_GROWTH_KEYWORDS or []) if str(item).strip()]
    stable_keywords = [str(item).lower() for item in (TRADITIONAL_STYLE_INDUSTRY_STABLE_KEYWORDS or []) if str(item).strip()]

    if any(k in name for k in growth_keywords):
        growth_score += float(score_rules.get("industry_growth_bias", 1.15) or 1.15)
        reasons.append("industry_growth_bias")
    elif any(k in name for k in stable_keywords):
        growth_score += float(score_rules.get("industry_stable_bias", -0.9) or -0.9)
        reasons.append("industry_stable_bias")

    roe = _to_float_or_none((indicator_profile or {}).get("roe"))
    gross_margin = _to_float_or_none((indicator_profile or {}).get("gross_margin"))
    debt_to_assets = _to_float_or_none((indicator_profile or {}).get("debt_to_assets"))

    if roe is not None:
        if roe >= float(score_rules.get("roe_high_threshold", 20.0) or 20.0):
            growth_score += float(score_rules.get("roe_high_bonus", 0.7) or 0.7)
            reasons.append("roe>=20")
        elif roe >= float(score_rules.get("roe_mid_threshold", 12.0) or 12.0):
            growth_score += float(score_rules.get("roe_mid_bonus", 0.35) or 0.35)
            reasons.append("roe>=12")

    if gross_margin is not None:
        if gross_margin >= float(score_rules.get("gross_margin_high_threshold", 40.0) or 40.0):
            growth_score += float(score_rules.get("gross_margin_high_bonus", 0.55) or 0.55)
            reasons.append("gross_margin>=40")
        elif gross_margin >= float(score_rules.get("gross_margin_mid_threshold", 28.0) or 28.0):
            growth_score += float(score_rules.get("gross_margin_mid_bonus", 0.25) or 0.25)
            reasons.append("gross_margin>=28")

    if debt_to_assets is not None:
        if debt_to_assets <= float(score_rules.get("debt_low_threshold", 35.0) or 35.0):
            growth_score += float(score_rules.get("debt_low_bonus", 0.2) or 0.2)
            reasons.append("debt_to_assets<=35")
        elif debt_to_assets >= float(score_rules.get("debt_high_threshold", 65.0) or 65.0):
            growth_score += float(score_rules.get("debt_high_penalty", -0.2) or -0.2)
            reasons.append("debt_to_assets>=65")

    if _to_float_or_none(method_price_map.get("peg")) is not None:
        growth_score += float(score_rules.get("peg_available_bonus", 0.25) or 0.25)
        reasons.append("peg_available")

    if _to_float_or_none(method_price_map.get("pb")) is not None and _to_float_or_none(method_price_map.get("fcff_dcf")) is not None:
        growth_score += float(score_rules.get("pb_fcff_available_penalty", -0.1) or -0.1)
        reasons.append("pb_fcff_available")

    if growth_score >= float(score_thresholds.get("high_growth_min", 1.1) or 1.1):
        style_key = "high_growth"
    elif growth_score <= float(score_thresholds.get("stable_value_max", -0.35) or -0.35):
        style_key = "stable_value"
    else:
        style_key = "balanced"

    return style_key, round(growth_score, 3), reasons


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
        weighted_sum += price * normalized_weight
        covered_weight += normalized_weight
        used_methods.append(method)

    if covered_weight <= 0:
        return None, 0.0, []

    target_price = weighted_sum / covered_weight
    coverage_ratio = max(0.0, min(1.0, covered_weight / total_weight))
    return round(target_price, 4), round(coverage_ratio, 4), used_methods


def _resolve_traditional_scheme_key(style_key, industry_name):
    industry_text = str(industry_name or "").strip()
    if industry_text:
        for item in (TRADITIONAL_INDUSTRY_SCHEME_OVERRIDES or []):
            if not isinstance(item, dict):
                continue
            scheme_key = str(item.get("scheme_key") or "").strip()
            keywords = item.get("keywords")
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


def _enforce_monotonic_tier_targets(tier_payload, scheme, current_price):
    order = ["conservative", "balanced", "aggressive"]
    raw_targets = []
    for key in order:
        tier = (tier_payload or {}).get(key) or {}
        target = _to_float_or_none(tier.get("target_price"))
        if target is None or target <= 0:
            return {
                "enabled": True,
                "applied": False,
                "reason": "missing_target",
            }
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
        lower_multiplier = float(lower_multiplier)
        upper_multiplier = float(upper_multiplier)

        tier["target_price"] = round(float(target), 4)
        tier["range"] = {
            "lower": round(float(target) * lower_multiplier, 4),
            "upper": round(float(target) * upper_multiplier, 4),
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


def _interpolate_percentile(values, percentile):
    if not values:
        return None
    p = float(percentile)
    p = max(0.0, min(1.0, p))
    if len(values) == 1:
        return float(values[0])
    pos = p * (len(values) - 1)
    left = int(math.floor(pos))
    right = int(math.ceil(pos))
    if left == right:
        return float(values[left])
    ratio = pos - left
    return float(values[left]) * (1.0 - ratio) + float(values[right]) * ratio


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
    }
    if not normalized:
        return normalized, meta

    cfg = rules if isinstance(rules, dict) else {}
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
    lower_bound = _interpolate_percentile(sorted_values, lower_pct)
    upper_bound = _interpolate_percentile(sorted_values, upper_pct)
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
        df = calculate_atr(
            df=df,
            period=20,
            high_col="high_qfq",
            low_col="low_qfq",
            close_col="close_qfq",
        )

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

        volatility_thresholds = (
            TRADITIONAL_POSITION_GUIDANCE_RULES.get("volatility_thresholds")
            if isinstance(TRADITIONAL_POSITION_GUIDANCE_RULES, dict)
            else {}
        ) or (DEFAULT_TRADITIONAL_POSITION_GUIDANCE_RULES.get("volatility_thresholds") or {})
        low_max = float(volatility_thresholds.get("low_max", 0.03) or 0.03)
        high_min = float(volatility_thresholds.get("high_min", 0.06) or 0.06)

        volatility_bucket = "medium"
        if atr_ratio is not None:
            if atr_ratio <= low_max:
                volatility_bucket = "low"
            elif atr_ratio >= high_min:
                volatility_bucket = "high"

        volatility_label = {
            "low": "Σ╜Äµ│óσè¿",
            "medium": "Σ╕¡µ│óσè¿",
            "high": "Θ½ÿµ│óσè¿",
        }.get(volatility_bucket, "Σ╕¡µ│óσè¿")
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
    guidance_rules = TRADITIONAL_POSITION_GUIDANCE_RULES or DEFAULT_TRADITIONAL_POSITION_GUIDANCE_RULES
    volatility_thresholds = guidance_rules.get("volatility_thresholds") if isinstance(guidance_rules, dict) else {}
    style_layers = guidance_rules.get("style_volatility_layers") if isinstance(guidance_rules, dict) else {}
    summary_templates = guidance_rules.get("summary_templates") if isinstance(guidance_rules, dict) else {}

    def _rule_payload(key, default_payload):
        payload = guidance_rules.get(key)
        if isinstance(payload, dict):
            return {
                "suggested_position_range": str(payload.get("suggested_position_range") or default_payload["suggested_position_range"]),
                "message": str(payload.get("message") or default_payload["message"]),
            }
        return default_payload

    def _state_label(key):
        return {
            "no_price": "σ╜ôσëìΣ╗╖Σ╕ìσÅ»τö¿",
            "below_conservative": "Σ╜ÄΣ║ÄΘúÄµÄºσî║Θù┤Σ╕ïµ▓┐",
            "below_balanced": "Σ╜ÄΣ║Äσ╣│Φííσî║Θù┤",
            "within_balanced": "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤",
            "within_aggressive": "Σ╜ìΣ║ÄσüÅΘ½ÿσî║Θù┤",
            "above_aggressive": "Θ½ÿΣ║ÄΦ┐¢µö╗σî║Θù┤Σ╕èµ▓┐",
        }.get(key, "Σ╜ìΣ║Äσ╣│Φííσî║Θù┤")

    style_key_normalized = str(style_key or "balanced").strip().lower()
    style_label = {
        "high_growth": "Θ½ÿσó₧Θò┐",
        "stable_value": "Σ╜Äσó₧Θò┐τ¿│σ«Ü",
        "balanced": "σ¥çΦíí",
    }.get(style_key_normalized, "σ¥çΦíí")

    cp = _to_float_or_none(current_price)
    if cp is None or cp <= 0:
        payload = _rule_payload("no_price", DEFAULT_TRADITIONAL_POSITION_GUIDANCE_RULES["no_price"])
        payload.update({
            "style_key": style_key_normalized,
            "style_label": style_label,
            "volatility_bucket": (volatility_profile or {}).get("volatility_bucket") or "medium",
            "volatility_label": (volatility_profile or {}).get("volatility_label") or "Σ╕¡µ│óσè¿",
            "state_key": "no_price",
            "state_label": _state_label("no_price"),
            "industry_name": industry_name or "",
            "holding_summary": payload.get("message") or "σ╜ôσëìΣ╗╖Σ╕ìσÅ»τö¿∩╝îΘ╗ÿΦ«ñτ╗┤µîüΣ╕¡µÇºΣ╗ôΣ╜ìπÇé",
        })
        return payload

    atr_ratio = _to_float_or_none((volatility_profile or {}).get("atr_ratio"))
    volatility_bucket = str((volatility_profile or {}).get("volatility_bucket") or "").strip().lower()
    if volatility_bucket not in {"low", "medium", "high"}:
        if atr_ratio is not None:
            low_max = float((volatility_thresholds or {}).get("low_max", 0.03) or 0.03)
            high_min = float((volatility_thresholds or {}).get("high_min", 0.06) or 0.06)
            if atr_ratio <= low_max:
                volatility_bucket = "low"
            elif atr_ratio >= high_min:
                volatility_bucket = "high"
            else:
                volatility_bucket = "medium"
        else:
            volatility_bucket = "medium"

    c_low = _to_float_or_none((conservative_range or {}).get("lower"))
    b_low = _to_float_or_none((balanced_range or {}).get("lower"))
    b_high = _to_float_or_none((balanced_range or {}).get("upper"))
    a_high = _to_float_or_none((aggressive_range or {}).get("upper"))

    if c_low is not None and cp < c_low:
        state_key = "below_conservative"
    elif b_low is not None and cp < b_low:
        state_key = "below_balanced"
    elif b_high is not None and cp <= b_high:
        state_key = "within_balanced"
    elif a_high is not None and cp <= a_high:
        state_key = "within_aggressive"
    else:
        state_key = "above_aggressive"

    selected_payload = None
    style_cfg = (style_layers or {}).get(style_key_normalized) if isinstance(style_layers, dict) else None
    if not isinstance(style_cfg, dict):
        style_cfg = (style_layers or {}).get("balanced") if isinstance(style_layers, dict) else None
    if isinstance(style_cfg, dict):
        bucket_cfg = style_cfg.get(volatility_bucket)
        if isinstance(bucket_cfg, dict):
            selected_payload = bucket_cfg.get(state_key) or bucket_cfg.get("default")

    if not isinstance(selected_payload, dict):
        selected_payload = guidance_rules.get(state_key) or DEFAULT_TRADITIONAL_POSITION_GUIDANCE_RULES[state_key]

    payload = _rule_payload(state_key, selected_payload)
    volatility_label = (volatility_profile or {}).get("volatility_label") or {
        "low": "Σ╜Äµ│óσè¿",
        "medium": "Σ╕¡µ│óσè¿",
        "high": "Θ½ÿµ│óσè¿",
    }.get(volatility_bucket, "Σ╕¡µ│óσè¿")
    summary_template = None
    if isinstance(summary_templates, dict):
        summary_template = summary_templates.get("holding") or summary_templates.get("default")
    if not summary_template:
        summary_template = "{style_label}ΘúÄµá╝πÇü{volatility_label}πÇü{state_label}∩╝îσ╗║Φ««Σ╗ôΣ╜ì {suggested_position_range}∩╝¢{message}"

    payload.update({
        "style_key": style_key_normalized,
        "style_label": style_label,
        "volatility_bucket": volatility_bucket,
        "volatility_label": volatility_label,
        "state_key": state_key,
        "state_label": _state_label(state_key),
        "industry_name": industry_name or "",
        "holding_summary": summary_template.format(
            style_label=style_label,
            volatility_label=volatility_label,
            state_label=_state_label(state_key),
            suggested_position_range=payload.get("suggested_position_range") or "-",
            message=payload.get("message") or "",
        ),
    })
    return payload


def _build_traditional_tiered_template(current_price, rows, summary_payload, industry_name, indicator_profile, ts_code=None, freq="D"):
    method_price_map_raw = {}
    for row in (rows or []):
        method = _normalize_valuation_method_name((row or {}).get("valuation_method"))
        price = _to_float_or_none((row or {}).get("valuation_price"))
        if not method or price is None or price <= 0:
            continue
        method_price_map_raw[method] = float(price)

    method_price_map, winsor_meta = _winsorize_method_price_map(
        method_price_map_raw,
        rules=TRADITIONAL_METHOD_WINSOR_RULES,
    )

    style_key, style_score, style_reasons = _resolve_traditional_style(
        industry_name=industry_name,
        indicator_profile=indicator_profile or {},
        method_price_map=method_price_map,
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
        if target_price is not None and current_price not in (None, 0):
            return_pct = round(((target_price / float(current_price)) - 1.0) * 100.0, 2)
        tier_payload[tier_key] = {
            "label": tier_cfg.get("label") or tier_key,
            "target_price": round(target_price, 4) if target_price is not None else None,
            "expected_return_pct": return_pct,
            "range": {
                "lower": lower,
                "upper": upper,
            },
            "coverage_ratio": coverage_ratio,
            "used_methods": used_methods,
            "weights": {k: round(float(v), 4) for k, v in weights.items()},
        }

    monotonic_meta = _enforce_monotonic_tier_targets(tier_payload, scheme, current_price)

    volatility_profile = _load_traditional_volatility_profile(ts_code=ts_code, current_price=current_price, freq=freq) if ts_code else None
    guidance = _resolve_position_guidance(
        current_price=current_price,
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
        "indicator_profile": {
            "roe": _to_float_or_none((indicator_profile or {}).get("roe")),
            "gross_margin": _to_float_or_none((indicator_profile or {}).get("gross_margin")),
            "debt_to_assets": _to_float_or_none((indicator_profile or {}).get("debt_to_assets")),
            "indicator_end_date": (indicator_profile or {}).get("indicator_end_date"),
        },
        "method_prices": {k: round(float(v), 4) for k, v in method_price_map.items()},
        "method_prices_raw": {k: round(float(v), 4) for k, v in method_price_map_raw.items()},
        "winsorization": winsor_meta,
        "tier_monotonicity": monotonic_meta,
        "tiers": tier_payload,
        "position_guidance": guidance,
        "volatility_profile": volatility_profile,
        "holding_summary": guidance.get("holding_summary"),
        "reference": {
            "current_price": _to_float_or_none(current_price),
            "traditional_composite_price": reference_composite,
            "traditional_conservative_price": reference_conservative,
        },
    }


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
            summary_by_variant[variant] = _merge_summary_with_market_style(
                _build_valuation_summary_payload(current_price, variant_rows, band_pct, ts_code=ts_code, freq=freq),
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

        variant_meta_map = {
            str(item.get("valuation_variant") or ""): item
            for item in (valuation_variants or [])
            if isinstance(item, dict)
        }
        traditional_tiered_template_by_variant = {}
        for variant, variant_rows in data_by_variant.items():
            variant_meta = variant_meta_map.get(str(variant or ""), {})
            variant_industry_name = (
                (variant_meta or {}).get("industry_name")
                or ((variant_rows or [{}])[0] or {}).get("industry_name")
                or ""
            )
            traditional_tiered_template_by_variant[variant] = _build_traditional_tiered_template(
                current_price=current_price,
                rows=variant_rows,
                summary_payload=summary_by_variant.get(variant) or {},
                industry_name=variant_industry_name,
                indicator_profile=indicator_profile,
                ts_code=ts_code,
                freq=freq,
            )

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

        market_overall_valuation = _build_market_overall_valuation_snapshot(
            asof_trade_date=current_trade_date
        )
        traditional_tiered_template = traditional_tiered_template_by_variant.get(active_variant) or _build_traditional_tiered_template(
            current_price=current_price,
            rows=rows,
            summary_payload=summary_payload,
            industry_name=((rows or [{}])[0] or {}).get("industry_name") or "",
            indicator_profile=indicator_profile,
            ts_code=ts_code,
            freq=freq,
        )

        return Response(
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
                "market_overall_valuation": market_overall_valuation,
                "traditional_tiered_template": traditional_tiered_template,
                "traditional_tiered_template_by_variant": traditional_tiered_template_by_variant,
                "data": rows,
            }
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


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
):
    query_params = {
        "freq": str(freq),
        "valuation_band_pct": str(valuation_band_pct),
    }
    if earnings_report_type:
        query_params["earnings_report_type"] = str(earnings_report_type)
    if valuation_report_end_date:
        query_params["valuation_report_end_date"] = str(valuation_report_end_date)

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


def _build_earnings_dual_target_payload(earnings_payload, *, current_price=None, latest_trade_date=None):
    if not isinstance(earnings_payload, dict):
        return earnings_payload

    payload = dict(earnings_payload)

    quant_components = payload.get("quantitative_target_components")
    market_multiplier = None
    if isinstance(quant_components, dict):
        adjustment = quant_components.get("market_overall_adjustment")
        if isinstance(adjustment, dict):
            market_multiplier = _to_float_or_none(adjustment.get("multiplier"))
    if market_multiplier is not None and market_multiplier <= 0:
        market_multiplier = None
    has_valid_multiplier = (
        market_multiplier is not None and abs(float(market_multiplier) - 1.0) > 1e-9
    )

    target_price_raw = _to_float_or_none(payload.get("target_price_raw"))
    if target_price_raw is None:
        target_price_raw = _to_float_or_none(payload.get("target_price"))
    target_price_low_raw = _to_float_or_none(payload.get("target_price_low_raw"))
    if target_price_low_raw is None:
        target_price_low_raw = _to_float_or_none(payload.get("target_price_low"))
    target_price_high_raw = _to_float_or_none(payload.get("target_price_high_raw"))
    if target_price_high_raw is None:
        target_price_high_raw = _to_float_or_none(payload.get("target_price_high"))
    target_market_cap_raw = _to_float_or_none(payload.get("target_market_cap_raw"))
    if target_market_cap_raw is None:
        target_market_cap_raw = _to_float_or_none(payload.get("target_market_cap"))
    target_market_cap_low_raw = _to_float_or_none(payload.get("target_market_cap_low_raw"))
    if target_market_cap_low_raw is None:
        target_market_cap_low_raw = _to_float_or_none(payload.get("target_market_cap_low"))
    target_market_cap_high_raw = _to_float_or_none(payload.get("target_market_cap_high_raw"))
    if target_market_cap_high_raw is None:
        target_market_cap_high_raw = _to_float_or_none(payload.get("target_market_cap_high"))

    if has_valid_multiplier:
        if payload.get("target_price_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_price"))
            if adjusted is not None:
                target_price_raw = adjusted / float(market_multiplier)
        if payload.get("target_price_low_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_price_low"))
            if adjusted is not None:
                target_price_low_raw = adjusted / float(market_multiplier)
        if payload.get("target_price_high_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_price_high"))
            if adjusted is not None:
                target_price_high_raw = adjusted / float(market_multiplier)
        if payload.get("target_market_cap_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_market_cap"))
            if adjusted is not None:
                target_market_cap_raw = adjusted / float(market_multiplier)
        if payload.get("target_market_cap_low_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_market_cap_low"))
            if adjusted is not None:
                target_market_cap_low_raw = adjusted / float(market_multiplier)
        if payload.get("target_market_cap_high_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_market_cap_high"))
            if adjusted is not None:
                target_market_cap_high_raw = adjusted / float(market_multiplier)

    target_return_raw = _to_float_or_none(payload.get("target_return_pct_raw"))
    if target_return_raw is None:
        target_return_raw = _to_float_or_none(payload.get("target_return_pct"))
    if target_return_raw is None:
        target_return_raw = _calc_return_pct_simple(current_price, target_price_raw)

    target_return_low_raw = _to_float_or_none(payload.get("target_return_low_pct_raw"))
    if target_return_low_raw is None:
        target_return_low_raw = _to_float_or_none(payload.get("target_return_low_pct"))
    if target_return_low_raw is None:
        target_return_low_raw = _calc_return_pct_simple(current_price, target_price_low_raw)

    target_return_high_raw = _to_float_or_none(payload.get("target_return_high_pct_raw"))
    if target_return_high_raw is None:
        target_return_high_raw = _to_float_or_none(payload.get("target_return_high_pct"))
    if target_return_high_raw is None:
        target_return_high_raw = _calc_return_pct_simple(current_price, target_price_high_raw)

    if has_valid_multiplier:
        if payload.get("target_return_pct_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_return_pct"))
            if adjusted is not None:
                target_return_raw = ((1.0 + float(adjusted) / 100.0) / float(market_multiplier) - 1.0) * 100.0
        if payload.get("target_return_low_pct_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_return_low_pct"))
            if adjusted is not None:
                target_return_low_raw = ((1.0 + float(adjusted) / 100.0) / float(market_multiplier) - 1.0) * 100.0
        if payload.get("target_return_high_pct_raw") in (None, ""):
            adjusted = _to_float_or_none(payload.get("target_return_high_pct"))
            if adjusted is not None:
                target_return_high_raw = ((1.0 + float(adjusted) / 100.0) / float(market_multiplier) - 1.0) * 100.0

    signal_score = _to_float_or_none(payload.get("signal_score"))
    ann_date = _parse_date_like(payload.get("financial_ann_date"))
    anchor_date = _parse_date_like(latest_trade_date)
    stale_days = None
    if ann_date is not None and anchor_date is not None:
        stale_days = max((anchor_date - ann_date).days, 0)

    anchor_trade_date = _parse_date_like(payload.get("asof_date")) or _parse_date_like(latest_trade_date)
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
    normalized_ts_code = str(ts_code or "").strip().upper()
    panel_report_type = _map_valuation_report_type_to_panel_type(report_type)
    if not normalized_ts_code or panel_report_type not in {"Q1", "H1", "Q3", "FY"}:
        return None

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
        return None

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
        return None
    if df is None or df.empty:
        return None
    return _parse_date_like(df.iloc[0].get("end_date"))


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


def _normalize_risk_level_value(value):
    text = str(value or "").strip().upper()
    mapping = {
        "L": "LOW",
        "LOW": "LOW",
        "M": "MEDIUM",
        "MEDIUM": "MEDIUM",
        "H": "HIGH",
        "HIGH": "HIGH",
        "Σ╜Ä": "LOW",
        "Σ╕¡": "MEDIUM",
        "Θ½ÿ": "HIGH",
    }
    return mapping.get(text, "")


def _normalize_risk_level_filters(value):
    tokens = [str(item or "").strip() for item in str(value or "").split(",")]
    normalized = [_normalize_risk_level_value(item) for item in tokens]
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
        normalized_risk_level = _normalize_risk_level_value(row.get("risk_level")) or None
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
    target_return_pct_raw = quantitative_target.get("target_return_pct_raw")
    target_return_low_pct_raw = quantitative_target.get("target_return_low_pct_raw")
    target_return_high_pct_raw = quantitative_target.get("target_return_high_pct_raw")
    target_price_low = quantitative_target.get("target_price_low")
    target_price_high = quantitative_target.get("target_price_high")
    target_price_raw = quantitative_target.get("target_price_raw")
    target_price_low_raw = quantitative_target.get("target_price_low_raw")
    target_price_high_raw = quantitative_target.get("target_price_high_raw")
    target_market_cap_low = quantitative_target.get("target_market_cap_low")
    target_market_cap_high = quantitative_target.get("target_market_cap_high")
    target_market_cap_raw = quantitative_target.get("target_market_cap_raw")
    target_market_cap_low_raw = quantitative_target.get("target_market_cap_low_raw")
    target_market_cap_high_raw = quantitative_target.get("target_market_cap_high_raw")
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
        "target_return_pct_raw": _to_float_or_none(target_return_pct_raw),
        "target_return_low_pct_raw": _to_float_or_none(target_return_low_pct_raw),
        "target_return_high_pct_raw": _to_float_or_none(target_return_high_pct_raw),
        "target_price_low": _to_float_or_none(target_price_low),
        "target_price_high": _to_float_or_none(target_price_high),
        "target_price_raw": _to_float_or_none(target_price_raw),
        "target_price_low_raw": _to_float_or_none(target_price_low_raw),
        "target_price_high_raw": _to_float_or_none(target_price_high_raw),
        "target_market_cap_low": _to_float_or_none(target_market_cap_low),
        "target_market_cap_high": _to_float_or_none(target_market_cap_high),
        "target_market_cap_raw": _to_float_or_none(target_market_cap_raw),
        "target_market_cap_low_raw": _to_float_or_none(target_market_cap_low_raw),
        "target_market_cap_high_raw": _to_float_or_none(target_market_cap_high_raw),
        "action": str(action).upper(),
        "risk_level": str(risk_level).upper(),
        "model_version": model_version,
        "asof_date": upstream_result.get("trade_date"),
        "feature_data_source": upstream_result.get("feature_data_source"),
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

    if normalized_source == "snapshot":
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
    raw_anchor_mode = str(request.GET.get("anchor_mode") or "").strip().lower()
    normalized_anchor_mode = _normalize_predict_anchor_mode(raw_anchor_mode)
    anchor_mode_explicit = raw_anchor_mode in {"ann", "live", "live_latest", "latest"}
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
        data["predictive_tiered_template"] = _build_predictive_tiered_template(
            data,
            current_price=latest_current_price,
            latest_trade_date=latest_trade_date,
        )

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
                    "predictive_tiered_template": None,
                },
                "degrade": {
                    "enabled": True,
                    "reason": "upstream_error_default",
                },
            }
        )


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
