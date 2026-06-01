import datetime
import hashlib
import pandas as pd
from pathlib import Path
import json
import logging
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
from prediction.models import (
    StockCombinedFeature,
    StockPrediction,
)
from valuation.models import StockValuationSnapshot, StockValuationSnapshotLatest
from prediction.services.business_industry_matcher import BusinessIndustryMatcher
from prediction.services.validation_loader import ValuationConfig
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datastore.utils.tushare_util import fetch_tushare_data
from prediction.utils.valuation_util import test_valuation, _query_local_financial_df as query_local_financial_df
from prediction.utils.ta_util import calculate_atr
from utils.analysis_utils import is_last_row_value_below_quantile
from users.models import User, UserWatchlist
from prediction.models import StockGainLossQuantile
from pandas.tseries.offsets import BDay
from users.models import UserStockTag
import time


logger = logging.getLogger(__name__)


BUY_CANDIDATE_CORE_METHODS = ("pe", "pb", "ps")
BUY_CANDIDATE_SUPPORT_METHODS = ("fcff_dcf", "ddm")
BUY_CANDIDATE_OPTIONAL_METHODS = ("peg",)
BUY_CANDIDATE_RULE_VERSION = "baseline_v20260319"

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
RECENT_FINANCIAL_ANNOUNCEMENT_DAYS = int(
    getattr(settings, "RECENT_FINANCIAL_ANNOUNCEMENT_DAYS", 45) or 45
)
VALUATION_SHARE_CHANGE_IMPACT_THRESHOLD = float(
    getattr(settings, "VALUATION_SHARE_CHANGE_IMPACT_THRESHOLD", 0.1) or 0.1
)


def _parse_optional_float(value, default=None):
    if value in (None, ""):
        return default
    return float(value)


def _parse_optional_float_list(value):
    if value in (None, ""):
        return None
    return [float(item.strip()) for item in value.split(",") if item.strip()]


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


def _select_valuation_candidate(candidates, pick_strategy):
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

    baseline_candidates = [row for row in candidates if row.get("compare_group") == "sw_l3_baseline"]
    if baseline_candidates:
        return baseline_candidates[0]
    scored = [row for row in candidates if row.get("match_score") is not None]
    if scored:
        return max(scored, key=lambda row: float(row.get("match_score", 0)))
    return candidates[0]


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

    selected = _select_valuation_candidate(method_candidates, pick_strategy)
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
            selected = _select_valuation_candidate(candidates, pick_strategy)
            if selected is None:
                continue
            method_map[method] = {
                "valuation_price": selected.get("valuation_price"),
                "valuation_market_cap": selected.get("valuation_market_cap"),
                "source": selected.get("source"),
                "candidate_count": len(candidates),
            }
    return snapshot_map


def _build_latest_snapshot_method_map(ts_codes, market="CN", pick_strategy="baseline", max_trade_date=None, express_only=False):
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
            selected = _select_valuation_candidate(candidates, pick_strategy)
            if selected is None:
                continue
            method_map[method] = {
                "valuation_price": selected.get("valuation_price"),
                "valuation_market_cap": selected.get("valuation_market_cap"),
                "source": selected.get("source") or "snapshot_latest",
                "profit_data_source": selected.get("profit_data_source"),
                "profit_report_end_date": selected.get("profit_report_end_date"),
                "profit_report_ann_date": selected.get("profit_report_ann_date"),
                "profit_report_type": selected.get("profit_report_type"),
                "express_ann_date": selected.get("express_ann_date"),
                "candidate_count": len(candidates),
            }
    return snapshot_map


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

    if any(k in name for k in ["银行", "保险", "证券", "多元金融"]):
        priors.update({"pb": 0.90, "pe": 0.45, "ps": 0.20, "ddm": 0.40})
    elif any(k in name for k in ["公用", "地产", "建材", "钢铁", "煤炭", "交通运输"]):
        priors.update({"pb": 0.78, "pe": 0.55, "ps": 0.35, "fcff_dcf": 0.52})
    elif any(k in name for k in ["半导体", "软件", "互联网", "传媒", "生物", "医药", "电子"]):
        priors.update({"ps": 0.86, "pe": 0.73, "peg": 0.68, "pb": 0.36})
    elif any(k in name for k in ["食品", "饮料", "家电", "轻工", "纺织", "汽车", "机械"]):
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
        has_value = price is not None and float(price) > 0
        availability_score = 1.0 if has_value else 0.0
        stability_bonus = min(candidate_count, 3) * 0.06

        final_score = (prior_score * 0.65) + (availability_score * 0.35) + stability_bonus
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
    industry_name = (industry_context or {}).get("industry_name") or "未知行业"
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


def _summarize_buy_candidate(current_price, method_map, band_pct):
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

    core_prices = [valid_methods[m] for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods]
    support_prices = [valid_methods[m] for m in BUY_CANDIDATE_SUPPORT_METHODS if m in valid_methods]
    optional_prices = []
    for method in BUY_CANDIDATE_OPTIONAL_METHODS:
        price = valid_methods.get(method)
        if price is None:
            continue
        if 0.5 * current_price <= price <= 2.5 * current_price:
            optional_prices.append(price)

    candidate_prices = core_prices + support_prices + optional_prices
    if not candidate_prices:
        return summary

    base_composite_price = float(pd.Series(candidate_prices, dtype="float64").median())
    current_market_cap = _estimate_current_market_cap(current_price, method_map)
    composite_size_factor = _resolve_composite_size_factor(current_market_cap)
    composite_price = base_composite_price * composite_size_factor
    conservative_pool = core_prices or candidate_prices
    conservative_price = min(conservative_pool)

    under_methods = [
        method for method, valuation_price in valid_methods.items()
        if current_price <= valuation_price * (1 - band_pct)
    ]
    core_under_methods = [
        method for method in BUY_CANDIDATE_CORE_METHODS
        if method in valid_methods and current_price <= valid_methods[method] * (1 - band_pct)
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
        f"size_factor={round(composite_size_factor, 4)}",
        f"composite_gap_pct={round(composite_gap_pct * 100, 2)}",
        f"conservative_gap_pct={round(conservative_gap_pct * 100, 2)}",
    ]

    summary.update(
        {
            "composite_valuation_price": round(composite_price, 4),
            "conservative_valuation_price": round(conservative_price, 4),
            "undervalue_score": min(score, 100),
            "buy_candidate": buy_candidate,
            "buy_candidate_reason": "; ".join(reasons),
            "valuation_valid_methods": sorted(valid_methods.keys()),
            "valuation_under_methods": sorted(under_methods),
            "valuation_core_methods": [m for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods],
        }
    )
    return summary


def _build_valuation_summary_payload(current_price, rows, band_pct, price_key="valuation_price"):
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
        "composite_valuation_price": summary.get("composite_valuation_price"),
        "composite_valuation_status": composite_status,
        "composite_valuation_gap_pct": round(composite_gap_pct * 100, 2) if composite_gap_pct is not None else None,
        "conservative_valuation_price": summary.get("conservative_valuation_price"),
        "conservative_valuation_status": conservative_status,
        "conservative_valuation_gap_pct": round(conservative_gap_pct * 100, 2) if conservative_gap_pct is not None else None,
    }


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
        "message": "当前估值下降主要来自除权后总股本扩大，同等股权价值被摊到更多股份，不宜直接解读为基本面恶化。",
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

    normalized_variant = (str(valuation_variant).strip() or "default")[:128]
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
        "profit_data_source": profit_source,
        "profit_report_end_date": effective_end_date,
        "profit_report_ann_date": effective_ann_date,
        "profit_report_type": _resolve_report_type(effective_end_date),
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
        defaults=snapshot_defaults,
    )

    StockValuationSnapshotLatest.objects.update_or_create(
        ts_code=ts_code,
        market=market,
        valuation_method=normalized_method,
        valuation_variant=normalized_variant,
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

        records = []
        record_mode = "watchlist"
        if market == "HO":
            queryset = UserWatchlist.objects.filter(
                user=user, is_enabled=True, hold_a_position=True,
            ).order_by("ts_code")
            total = queryset.count()
            records = list(queryset[from_index:to_index])
        elif market == "WL":
            queryset = UserWatchlist.objects.filter(
                user=user, is_enabled=True, hold_a_position=False
            ).order_by("ts_code")
            total = queryset.count()
            records = list(queryset[from_index:to_index])
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

        ts_codes = [item.ts_code for item in records]
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

        method_map_by_code = {}
        if ts_codes:
            snapshot_rows = (
                StockValuationSnapshotLatest.objects.filter(
                    ts_code__in=ts_codes,
                    market="CN",
                    valuation_method__in=["pe", "pb", "ps", "sw_history", "peg", "fcff_dcf", "ddm"],
                )
                .order_by("ts_code", "valuation_method", "-updated_at")
                .values("ts_code", "valuation_method", "valuation_price", "valuation_variant")
            )
            method_variant_rank = {}
            for row in snapshot_rows:
                code = row.get("ts_code")
                method = _normalize_valuation_method_name(row.get("valuation_method"))
                valuation_price = row.get("valuation_price")
                if not code or not method or valuation_price is None:
                    continue

                variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
                if variant.startswith("sw_l3_baseline|"):
                    variant_rank = 0
                elif variant.startswith("business_match|"):
                    variant_rank = 1
                elif variant == "default":
                    variant_rank = 2
                else:
                    variant_rank = 3

                method_map_by_code.setdefault(code, {})
                method_variant_rank.setdefault(code, {})
                existing_rank = method_variant_rank[code].get(method)
                if existing_rank is not None and existing_rank <= variant_rank:
                    continue
                method_variant_rank[code][method] = variant_rank
                method_map_by_code[code][method] = {
                    "valuation_price": float(valuation_price),
                    "candidate_count": 1,
                }

        basic_info_map = {}
        prediction_map = {}
        if ts_codes:
            corp_rows = Corporation.objects.filter(ts_code__in=ts_codes).values("ts_code", "name")
            corp_name_map = {row["ts_code"]: row.get("name") for row in corp_rows}

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

        data = []
        for item in records:
            if record_mode == "watchlist":
                item_dict = item.to_dict() if hasattr(item, "to_dict") else {}
                corp = getattr(item, "corporation", None)
                ts_code = item.ts_code
                if not (item_dict.get("name") or "").strip():
                    item_dict["name"] = getattr(corp, "name", "") or corp_name_map.get(ts_code, "")
            else:
                ts_code = item.ts_code
                item_dict = {
                    "ts_code": ts_code,
                    "name": getattr(item, "name", ""),
                    "is_enabled": False,
                    "hold_a_position": False,
                }

            item_dict["basic_info"] = basic_info_map.get(ts_code, {})
            if ts_code in prediction_map:
                item_dict["prediction"] = prediction_map.get(ts_code)

            current_payload = latest_trade_map.get(ts_code) or {}
            current_price = current_payload.get("close")
            method_map = method_map_by_code.get(ts_code) or {}
            summary = _summarize_buy_candidate(current_price, method_map, 0.1)
            composite_price = summary.get("composite_valuation_price")
            composite_status, composite_gap_pct = _classify_valuation(
                current_price,
                composite_price,
                0.1,
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
        return Response(
            {"data": data, "from": from_index, "to": to_index, "total": total}
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
            if end_date is not None and ann_date is not None and ann_date < end_date:
                ann_date = None
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
        if report_end_date is not None and profit_ann_date is not None and profit_ann_date < report_end_date:
            profit_ann_date = None
        express_ann_date = _parse_date_like(row.get("express_ann_date"))
        report_type = row.get("profit_report_type")
        profit_source = row.get("profit_data_source")

        candidates = []
        for candidate, label in [
            (
                profit_ann_date,
                _normalize_recent_report_label(
                    report_type=report_type,
                    profit_source=profit_source,
                    ann_date=profit_ann_date,
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
            candidates.append((financial_ann, _normalize_recent_report_label(report_type=earnings_report_type)))
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
            _parse_date_like(row.get("earnings_asof_date"))
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
            _parse_date_like(row.get("earnings_asof_date"))
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

        window = series[start_idx:]
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
    recommendation_desc = "行业推荐=按股票所属行业先验 + 估值方法可用性进行打分排序，优先返回当前股票有可用快照的方法，并给出置信度与推荐理由。"
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

    try:
        valuation_band_pct = max(0.01, float(valuation_band_pct_raw))
    except (TypeError, ValueError):
        valuation_band_pct = 0.1

    valuation_status = str(valuation_status).strip().lower()
    selected_valuation_method = str(valuation_method or "pe").strip().lower() or "pe"
    valuation_pick_strategy = _normalize_pick_strategy(valuation_pick_strategy_raw)
    buy_candidate_only = str(buy_candidate_only_raw).strip().lower() in {
        "1", "true", "yes", "y", "on",
    }
    sw_industry = str(sw_industry_raw).strip()
    picking_mode = _normalize_predictive_mode(picking_mode_raw)
    valuation_report_type_text = str(earnings_report_type_raw or "").strip().upper()
    valuation_express_only = valuation_report_type_text in {"EXP", "EXPRESS", "快"}
    earnings_report_type = _normalize_earnings_report_type_with_all(earnings_report_type_raw)
    valuation_profit_report_type = _normalize_valuation_profit_report_type(earnings_report_type)
    signal_action = _normalize_optional_choice(signal_action_raw, {"BUY", "HOLD", "SELL_PART", "SELL"})
    risk_level = _normalize_optional_choice(risk_level_raw, {"LOW", "MEDIUM", "HIGH"})
    feature_data_source = str(feature_data_source_raw or "").strip().lower()
    try:
        min_signal_score = _to_float_or_none(min_signal_score_raw)
    except (TypeError, ValueError):
        min_signal_score = None
    try:
        min_target_return_pct = _to_float_or_none(min_target_return_pct_raw)
    except (TypeError, ValueError):
        min_target_return_pct = None
    try:
        fiscal_year = int(fiscal_year_raw) if str(fiscal_year_raw).strip() else None
    except (TypeError, ValueError):
        fiscal_year = None
    netprofit_growth = str(netprofit_growth_raw or "ALL").strip().upper()
    if netprofit_growth not in {"ALL", "HIGH"}:
        netprofit_growth = "ALL"
    # pred_earnings_growth is stored as ratio (e.g. 0.2 == 20%).
    min_netprofit_growth = 0.2 if netprofit_growth == "HIGH" else None

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
    ts_codes = [row["ts_code"] for row in trading_rows]

    valuation_snapshot_map = _build_latest_snapshot_method_map(
        ts_codes=ts_codes,
        market="CN",
        pick_strategy=valuation_pick_strategy,
        max_trade_date=trade_date_for_query,
        express_only=valuation_express_only,
    )
    industry_context_map = _build_industry_context_map(ts_codes=ts_codes, market="CN")
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
        selected_candidate_count = selected_method_payload.get("candidate_count", 0)
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
            "valuation_pick_strategy": valuation_pick_strategy,
            "valuation_candidate_count": selected_candidate_count,
            "valuation_candidates": [],
        }

        if selected_price is None:
            valuation_payload["valuation_source"] = "snapshot_only_miss"

        buy_candidate_payload = _summarize_buy_candidate(
            current_price=current_price,
            method_map=method_map,
            band_pct=valuation_band_pct,
        )

        if valuation_status and valuation_payload.get("valuation_status") != valuation_status:
            continue
        if buy_candidate_only and not buy_candidate_payload.get("buy_candidate"):
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
            }
        )

    if picking_mode == "predictive" and result:
        predictive_ts_codes = [row.get("ts_code") for row in result if row.get("ts_code")]
        earnings_map = {}
        predictive_earnings_stats = {}
        try:
            earnings_map, predictive_earnings_stats = _fetch_earnings_signal_batch(
                predictive_ts_codes,
                report_type=earnings_report_type,
                return_stats=True,
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
            earnings_risk_value = str(earnings_payload.get("risk_level") or "MEDIUM").upper()
            earnings_source_value = str(earnings_payload.get("feature_data_source") or "").strip().lower()
            earnings_fiscal_year = earnings_payload.get("financial_fiscal_year")
            pred_earnings_growth = _to_float_or_none(earnings_payload.get("pred_earnings_growth"))
            prev_year_netprofit_non_negative = earnings_payload.get("prev_year_netprofit_non_negative")
            earnings_signal_score = _to_float_or_none(earnings_payload.get("signal_score"))
            earnings_target_return_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))

            if signal_action and earnings_action_value != signal_action:
                continue
            if risk_level and earnings_risk_value != risk_level:
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

    paged_result = result[from_index:to_index]
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
                "earnings_report_type": "快" if valuation_express_only else earnings_report_type,
                "signal_action": signal_action,
                "risk_level": risk_level,
                "min_signal_score": min_signal_score,
                "min_target_return_pct": min_target_return_pct,
                "feature_data_source": feature_data_source,
                "fiscal_year": fiscal_year,
                "netprofit_growth": netprofit_growth,
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
                "valuation_method_recommendation_desc": recommendation_desc,
                "sw_industry": sw_industry,
                "predictive_mode_enabled": picking_mode == "predictive",
                "timing_ms": {
                    "total": _ms(perf_t0, perf_after_all),
                    "load_trading_rows": _ms(perf_t0, perf_after_trading),
                    "build_valuation_snapshot": _ms(perf_after_trading, perf_after_snapshot),
                    "predictive_earnings_enrich": _ms(perf_after_snapshot, perf_after_earnings),
                    "post_process_and_page": _ms(perf_after_earnings, perf_after_all),
                },
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
        if not ts_code:
            return Response({"error": "ts_code is required."}, status=400)
        user = request.user if request.user.is_authenticated else User.get_admin_user()

        if not user:
            return Response({"error": "Authentication required."}, status=401)
        corporation = Corporation.objects.filter(ts_code=ts_code).first()
        watchlist_entry, created = UserWatchlist.objects.get_or_create(
            user=user,
            ts_code=ts_code,
            name=corporation.name,
            corporation=corporation,
            defaults={"is_enabled": True},
        )
        if not created and not watchlist_entry.is_enabled:
            watchlist_entry.is_enabled = True
            watchlist_entry.save()
        return Response({"message": "Stock added to watchlist.", "ts_code": ts_code})
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
        # 默认将股票添加到自选股列表（如果不在的话）
        watchlist_entry, created = UserWatchlist.objects.get_or_create(
            user=user,
            ts_code=ts_code,
            defaults={
                "is_enabled": True,
                "name": getattr(corporation, "name", ""),
                "corporation": corporation,
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
                "in_watchlist": False,
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
        return Response(
            {
                "message": "Stock unmarked as hold.",
                "ts_code": ts_code,
                "in_watchlist": True,  # Still in watchlist since is_enabled=True
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
        in_watchlist = bool(watchlist_entry and not hold_position)
        return Response(
            {
                "ts_code": ts_code,
                "in_watchlist": in_watchlist,
                "hold_position": hold_position,
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

        start_date = _parse_ymd(request.query_params.get("start_date"))
        end_date = _parse_ymd(request.query_params.get("end_date"))

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
        express_only = valuation_report_type_text in {"EXP", "EXPRESS", "快"}
        valuation_report_type = _normalize_valuation_profit_report_type(
            valuation_report_type_raw
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

        if valuation_report_type or express_only:
            snapshot_rows = list(
                StockValuationSnapshot.objects.filter(
                    ts_code=ts_code,
                    market=market,
                    **(
                        {"profit_data_source__startswith": "express"}
                        if express_only
                        else {"profit_report_type": valuation_report_type}
                    ),
                )
                .order_by("valuation_variant", "valuation_method", "-trade_date", "-updated_at")
                .values(
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
                    "profit_report_end_date": row.get("profit_report_end_date"),
                    "profit_report_ann_date": row.get("profit_report_ann_date"),
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
                label = "默认估值"
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
                active_variant = valuation_variants[0].get("valuation_variant")
            elif "default" in data_by_variant:
                active_variant = "default"
            else:
                active_variant = "default"

            rows = data_by_variant.get(active_variant, [])
        else:
            rows = []

        if not rows and not valuation_report_type:
            trade_date_arg = None
            if current_trade_date is not None:
                trade_date_arg = current_trade_date.strftime("%Y-%m-%d")

            valuation_result = test_valuation(
                ts_code=ts_code,
                trade_date=trade_date_arg,
            )
            valuation_df = valuation_result.get("valuations")
            fallback_methods = ["scarcity_overlay", "sw_history", "pe", "pb", "ps", "peg", "fcff_dcf", "ddm"]
            for method in fallback_methods:
                method_rows = _extract_method_valuation_rows(valuation_df, method)
                if not method_rows:
                    continue
                selected = _select_valuation_candidate(method_rows, "baseline")
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
                    "label": "默认估值",
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
        if not has_scarcity_overlay and not valuation_report_type:
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
                selected_scarcity = _select_valuation_candidate(scarcity_rows, "baseline")
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

        summary_by_variant = {}
        summary_by_variant_normalized = {}
        for variant, variant_rows in data_by_variant.items():
            summary_by_variant[variant] = _build_valuation_summary_payload(current_price, variant_rows, band_pct)
            summary_by_variant_normalized[variant] = _build_valuation_summary_payload(
                current_price,
                variant_rows,
                band_pct,
                price_key="valuation_price_normalized_to_latest_share",
            )

        summary_payload = summary_by_variant.get(active_variant) or _build_valuation_summary_payload(
            current_price,
            rows,
            band_pct,
        )
        normalized_summary_payload = summary_by_variant_normalized.get(active_variant) or _build_valuation_summary_payload(
            current_price,
            rows,
            band_pct,
            price_key="valuation_price_normalized_to_latest_share",
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
                "valuation_band_pct": band_pct,
                "valuation_report_type": valuation_report_type or None,
                "active_valuation_variant": active_variant,
                "valuation_variants": valuation_variants,
                "data_by_variant": data_by_variant,
                "summary": summary_payload,
                "summary_normalized_to_latest_share": normalized_summary_payload,
                "summary_by_variant": summary_by_variant,
                "summary_by_variant_normalized_to_latest_share": summary_by_variant_normalized,
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
    if "严格" in normalized:
        return 0.05
    if "宽松" in normalized:
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
        stance = "当前偏低估，可分批关注。"
    elif composite_status == "over" and conservative_status in {"over", "fair"}:
        stance = "当前偏高估，建议谨慎，等待更好安全边际。"
    else:
        stance = "当前估值大体中性，可结合趋势和仓位管理。"

    def _fmt_num(value):
        if value is None:
            return "-"
        return f"{float(value):.2f}"

    advice = [
        f"问题: {question or '估值建议'}",
        f"标的: {payload.get('ts_code')} ({payload.get('freq')})",
        f"现价: {_fmt_num(current_price)}",
        (
            "组合估值: "
            f"{_fmt_num(summary.get('composite_valuation_price'))} "
            f"({composite_status or '-'}, {_fmt_num(composite_gap_pct)}%)"
        ),
        (
            "保守估值: "
            f"{_fmt_num(summary.get('conservative_valuation_price'))} "
            f"({conservative_status or '-'}, {_fmt_num(conservative_gap_pct)}%)"
        ),
        f"低估方法: {', '.join(under_methods) if under_methods else '-'}",
        f"有效方法数: {len(valid_methods)}",
        f"建议: {stance}",
        "提示: 本建议仅基于历史与快照估值口径，不构成投资承诺。",
    ]
    return "\n".join(advice)


def _forward_to_feishu(text):
    webhook = str(getattr(settings, "FEISHU_BOT_WEBHOOK", "") or "").strip()
    if not webhook:
        return False, "FEISHU_BOT_WEBHOOK 未配置"

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


def _normalize_earnings_report_type(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    alias = {
        "ANNUAL": "FY",
        "FULL_YEAR": "FY",
        "A": "FY",
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
        "financial_fiscal_year": upstream_result.get("financial_fiscal_year"),
        "financial_ann_date": upstream_result.get("financial_ann_date"),
        "explain": {
            "stance": valuation_mapping.get("stance") or str(action).upper(),
            "confidence": valuation_mapping.get("confidence") or "LOW",
            "prob_component": _to_float_or_none(valuation_mapping.get("prob_component")),
            "earnings_component": _to_float_or_none(valuation_mapping.get("earnings_component")),
        },
    }


def _fetch_earnings_signal(ts_code, report_type=""):
    base_url = str(
        getattr(settings, "EARNINGS_SERVICE_BASE_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    timeout_seconds = float(getattr(settings, "EARNINGS_SERVICE_TIMEOUT_SECONDS", 4.0) or 4.0)
    retry_count = int(getattr(settings, "EARNINGS_SERVICE_RETRY_COUNT", 1) or 1)

    query_payload = {"ts_code": ts_code}
    normalized_report_type = _normalize_earnings_report_type(report_type)
    if normalized_report_type:
        query_payload["report_type"] = normalized_report_type
    query = urlencode(query_payload)
    url = f"{base_url}/api/forecast/signal/?{query}"
    req = urllib_request.Request(
        url,
        method="GET",
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


def _fetch_earnings_signal_batch(ts_codes, report_type="ALL", return_stats=False):
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
    normalized_report_type = _normalize_earnings_report_type(request.GET.get("report_type"))
    report_type_cache_key = normalized_report_type or "ALL"

    try:
        cache_key = f"earnings_signal:{normalized_ts_code}:{report_type_cache_key}"
        cache_ttl_seconds = int(getattr(settings, "EARNINGS_SIGNAL_CACHE_SECONDS", 1800) or 1800)

        data = _fetch_earnings_signal(normalized_ts_code, normalized_report_type)
        cache.set(cache_key, data, timeout=cache_ttl_seconds)
        return Response({
            "code": 0,
            "message": "ok",
            "data": data,
        })
    except Exception as err:
        logger.warning("earnings signal degraded for %s: %s", ts_code, err)

        cache_key = f"earnings_signal:{normalized_ts_code}:{report_type_cache_key}"
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
                "data": _build_earnings_default_data(normalized_ts_code, normalized_report_type),
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
            return Response({"error": "缺少 ts_code，请在问题里输入如 600519.SH 或传 ts_code 字段"}, status=400)

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
