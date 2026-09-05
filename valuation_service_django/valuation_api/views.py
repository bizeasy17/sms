import json
import re
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
import datetime
import pandas as pd

from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .business_industry_matcher import BusinessIndustryMatcher
from .models import StockTradingHistory
from .live_valuation import local_test_valuation, test_valuation_local
from .valuation_config import StandaloneValuationConfig

BUY_CANDIDATE_CORE_METHODS = ("pe", "pb", "ps")
BUY_CANDIDATE_SUPPORT_METHODS = ("fcff_dcf", "ddm")
BUY_CANDIDATE_OPTIONAL_METHODS = ("peg",)
BUY_CANDIDATE_RULE_VERSION = "baseline_v20260319"

BUY_CANDIDATE_MIN_CORE_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_CORE_UNDER_COUNT = 1
BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT = -0.02
BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT = -0.12

METHOD_ORDER = {m: idx for idx, m in enumerate(["sw_history", "pe", "pb", "ps", "peg", "ev_ebitda", "fcff_dcf", "ddm", "market_cap"])}

VALUATION_METHOD_ALIAS_MAP = {
    "sw_history": {"sw_history", "sw_hist", "industry_history"},
    "pe": {"pe"},
    "ps": {"ps"},
    "pb": {"pb"},
    "peg": {"peg"},
    "fcff_dcf": {"fcff_dcf", "fcff"},
    "ddm": {"ddm"},
    "ev_ebitda": {"ev_ebitda"},
    "market_cap": {"market_cap"},
}


def _normalize_method_name(method_name):
    if method_name is None:
        return ""
    return str(method_name).strip().lower().replace("/", "_").replace("-", "_").replace(" ", "")


def _classify_valuation(current_price, implied_price, band_pct):
    if current_price in (None, 0) or implied_price is None:
        return "unknown", None
    gap_pct = (float(implied_price) - float(current_price)) / float(current_price)
    if float(current_price) <= float(implied_price) * (1 - band_pct):
        return "under", gap_pct
    if float(current_price) >= float(implied_price) * (1 + band_pct):
        return "over", gap_pct
    return "fair", gap_pct


def _summarize_buy_candidate(current_price, method_map, band_pct):
    summary = {
        "composite_valuation_price": None,
        "conservative_valuation_price": None,
        "undervalue_score": None,
        "buy_candidate": False,
        "buy_candidate_reason": "no_valid_valuation_methods",
        "buy_candidate_rule_version": BUY_CANDIDATE_RULE_VERSION,
        "valuation_under_methods": [],
        "valuation_valid_methods": [],
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

    composite_price = float(pd.Series(candidate_prices, dtype="float64").median())
    core_prices = [valid_methods[m] for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods]
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
            "valuation_under_methods": sorted(under_methods),
            "valuation_valid_methods": sorted(valid_methods.keys()),
            "valuation_core_methods": [m for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods],
        }
    )
    return summary


def _resolve_method_candidates(selected_method):
    normalized_selected = _normalize_method_name(selected_method)
    return normalized_selected, VALUATION_METHOD_ALIAS_MAP.get(normalized_selected, {normalized_selected})


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


def _extract_method_valuation_rows(valuation_df, selected_method):
    if valuation_df is None or valuation_df.empty:
        return []

    normalized_selected, candidates = _resolve_method_candidates(selected_method)
    rows = []
    for _, row in valuation_df.iterrows():
        method = _normalize_method_name(row.get("method"))
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

        rows.append(
            {
                "method": row.get("method"),
                "implied_price": implied_price_float,
                "equity_value": equity_value_float,
                "method_weight": _to_float(row.get("method_weight")),
                "valuation_variant": row_variant,
            }
        )
    return rows


def _select_valuation_candidate(candidates):
    if not candidates:
        return None
    sorted_rows = sorted(candidates, key=lambda row: float(row.get("implied_price") or 0))
    return sorted_rows[len(sorted_rows) // 2]


def _extract_ts_code_from_text(text):
    if not text:
        return None
    match = re.search(r"\b\d{6}\.(?:SH|SZ)\b", str(text).upper())
    return match.group(0) if match else None


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
        pct = float(match.group(1)) / 100.0
        if 0.01 <= pct <= 0.4:
            return pct
    return default_pct


def _parse_json_query_param(raw_value, fallback):
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if raw_value in (None, ""):
        return fallback
    if isinstance(raw_value, bytes):
        try:
            raw_value = raw_value.decode("utf-8")
        except Exception:
            return fallback
    try:
        return json.loads(raw_value)
    except (TypeError, ValueError):
        return fallback


def _request_payload_dict(request):
    payload = getattr(request, "data", None)
    return payload if isinstance(payload, dict) else {}


def _get_request_value(request, key, default=None):
    if key in request.query_params:
        return request.query_params.get(key)
    return _request_payload_dict(request).get(key, default)


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_as_dict(value, default=None):
    parsed = _parse_json_query_param(value, default if default is not None else {})
    return parsed if isinstance(parsed, dict) else (default if default is not None else {})


def _parse_as_grid(value):
    parsed = _parse_json_query_param(value, None)
    if not isinstance(parsed, dict):
        return None
    normalized = {}
    for key, items in parsed.items():
        if not isinstance(items, (list, tuple)):
            return None
        casted = []
        for item in items:
            item_float = _to_float(item)
            if item_float is None:
                return None
            casted.append(item_float)
        normalized[str(key)] = casted
    return normalized


def _resolve_full_valuation_inputs(request):
    config_block = _parse_as_dict(
        _get_request_value(request, "valuation_config") or _get_request_value(request, "config"),
        default={},
    )
    targets_block = config_block.get("targets") if isinstance(config_block.get("targets"), dict) else {}

    def pick(*keys, default=None):
        for key in keys:
            val = _get_request_value(request, key)
            if val not in (None, ""):
                return val
            if key in config_block and config_block.get(key) not in (None, ""):
                return config_block.get(key)
            if key in targets_block and targets_block.get(key) not in (None, ""):
                return targets_block.get(key)
        return default

    dcf_kwargs = _parse_as_dict(pick("dcf_kwargs"), default={})
    ddm_kwargs = _parse_as_dict(pick("ddm_kwargs"), default={})

    # Backward-compatible flat keys -> dcf_kwargs
    for flat_key in ["forecast_fcff", "base_fcff", "growth_rates", "discount_rate", "terminal_growth_rate"]:
        flat_value = pick(flat_key)
        if flat_value not in (None, "") and flat_key not in dcf_kwargs:
            if flat_key in {"forecast_fcff", "growth_rates"}:
                parsed_list = _parse_json_query_param(flat_value, None)
                if isinstance(parsed_list, list):
                    dcf_kwargs[flat_key] = parsed_list
            else:
                dcf_kwargs[flat_key] = _to_float(flat_value)

    # Backward-compatible flat keys -> ddm_kwargs
    for flat_key in ["annual_dividend", "stage_dividends", "dividend_growth_rate"]:
        flat_value = pick(flat_key)
        if flat_value not in (None, "") and flat_key not in ddm_kwargs:
            if flat_key == "stage_dividends":
                parsed_list = _parse_json_query_param(flat_value, None)
                if isinstance(parsed_list, list):
                    ddm_kwargs[flat_key] = parsed_list
            else:
                ddm_kwargs[flat_key] = _to_float(flat_value)

    # Allow ddm-specific rate keys without breaking fcff defaults
    ddm_discount_rate = pick("ddm_discount_rate")
    ddm_terminal_growth_rate = pick("ddm_terminal_growth_rate")
    if ddm_discount_rate not in (None, "") and "discount_rate" not in ddm_kwargs:
        ddm_kwargs["discount_rate"] = _to_float(ddm_discount_rate)
    if ddm_terminal_growth_rate not in (None, "") and "terminal_growth_rate" not in ddm_kwargs:
        ddm_kwargs["terminal_growth_rate"] = _to_float(ddm_terminal_growth_rate)

    scenario_model = str(pick("scenario_model", default="fcff_dcf") or "fcff_dcf").strip().lower()
    valid_models = {"fcff_dcf", "ddm", "pe", "ps", "pb", "ev_ebitda"}
    if scenario_model not in valid_models:
        return None, Response(
            {
                "error": "invalid scenario_model",
                "allowed": sorted(valid_models),
                "received": scenario_model,
            },
            status=400,
        )

    sensitivity_grid = _parse_as_grid(pick("sensitivity_grid"))
    if pick("sensitivity_grid") not in (None, "") and sensitivity_grid is None:
        return None, Response(
            {
                "error": "invalid sensitivity_grid",
                "expected": "JSON object like {\"discount_rate\":[0.09,0.1,0.11]}",
            },
            status=400,
        )

    scenario_overrides = _parse_json_query_param(pick("scenario_overrides"), None)
    if scenario_overrides is not None and not isinstance(scenario_overrides, dict):
        return None, Response(
            {
                "error": "invalid scenario_overrides",
                "expected": "JSON object like {\"bear\":{...},\"base\":{...},\"bull\":{...}}",
            },
            status=400,
        )

    snapshot_overrides = _parse_as_dict(pick("snapshot_overrides"), default={})
    for field_name in ["ebitda", "cash", "debt"]:
        field_val = pick(field_name)
        if field_val in (None, "") or field_name in snapshot_overrides:
            continue
        snapshot_overrides[field_name] = _to_float(field_val)
    snapshot_overrides = {
        key: _to_float(value)
        for key, value in (snapshot_overrides or {}).items()
        if _to_float(value) is not None
    }

    payload = {
        "trade_date": pick("trade_date"),
        "freq": str(pick("freq", default="D") or "D").strip().upper() or "D",
        "current_price": _to_float(pick("current_price")),
        "pe_target": _to_float(pick("pe_target")),
        "ps_target": _to_float(pick("ps_target")),
        "pb_target": _to_float(pick("pb_target")),
        "peg_target": _to_float(pick("peg_target")),
        "ev_ebitda_target": _to_float(pick("ev_ebitda_target")),
        "dcf_kwargs": dcf_kwargs,
        "ddm_kwargs": ddm_kwargs,
        "scenario_model": scenario_model,
        "scenario_overrides": scenario_overrides,
        "sensitivity_grid": sensitivity_grid,
        "snapshot_overrides": snapshot_overrides,
        "match_business_industries": _to_bool(pick("match_business_industries"), default=False),
        "business_match_level": str(pick("business_match_level", default="L2") or "L2").strip().upper(),
        "business_topn": int(pick("business_topn", default=3) or 3),
        "disable_business_fallback": _to_bool(pick("disable_business_fallback"), default=False),
        "history_years": _parse_json_query_param(pick("history_years"), None),
        "history_quantile": _to_float(pick("history_quantile")),
        "history_min_samples": int(_to_float(pick("history_min_samples")) or 120),
    }
    history_years = payload.get("history_years")
    if isinstance(history_years, str) and "," in history_years:
        history_years = [part.strip() for part in history_years.split(",") if part.strip()]
    if isinstance(history_years, (int, float, str)):
        history_years = [history_years]
    if not isinstance(history_years, list):
        history_years = [3, 5, 10]

    normalized_years = []
    for item in history_years:
        value = _to_float(item)
        if value is None:
            continue
        ivalue = int(value)
        if ivalue > 0:
            normalized_years.append(ivalue)
    if not normalized_years:
        normalized_years = [3, 5, 10]

    history_quantile = payload.get("history_quantile")
    if history_quantile is None:
        history_quantile = 0.5
    history_quantile = min(max(float(history_quantile), 0.0), 1.0)

    payload["sw_history_kwargs"] = {
        "history_years": sorted(set(normalized_years)),
        "history_quantile": history_quantile,
        "history_min_samples": payload.get("history_min_samples") or 120,
    }
    return payload, None


def _extract_runtime_kwargs(params_payload):
    params = (params_payload or {}).get("params") or {}
    return {
        "pe_target": params.get("pe_target"),
        "ps_target": params.get("ps_target"),
        "pb_target": params.get("pb_target"),
        "peg_target": params.get("peg_target"),
        "ev_ebitda_target": params.get("ev_ebitda_target"),
        "dcf_kwargs": params.get("dcf_kwargs") or {},
        "ddm_kwargs": params.get("ddm_kwargs") or {},
        "sw_history_kwargs": params.get("sw_history_kwargs") or {},
        "scenario_model": params.get("scenario_model") or "fcff_dcf",
        "sensitivity_grid": params.get("sensitivity_grid"),
        "source_info": params_payload or {},
    }


def _build_valuation_variant(compare_group, industry_level=None, industry_code=None, industry_name=None):
    group = str(compare_group or "").strip()
    if not group:
        return "default"
    level = str(industry_level or "").strip()
    code = str(industry_code or "").strip()
    name = str(industry_name or "").strip()
    if any([level, code, name]):
        return "|".join([group, level, code, name])
    return group


def _apply_business_match_params(ts_code, resolved_params, market="CN"):
    matcher = BusinessIndustryMatcher(base_dir=Path(settings.BASE_DIR), market=market)
    top_n = max(int(resolved_params.get("business_topn") or 3), 1)
    level = str(resolved_params.get("business_match_level") or "L2").strip().upper() or "L2"
    matched_payload = matcher.match_by_tscode(ts_code=ts_code, top_n=top_n, level=level)
    matches = matched_payload.get("matches") or []
    citic_profile = matched_payload.get("citic_profile") or {}
    citic_mappings = matched_payload.get("citic_mappings") or []
    fallback_settings = matcher.get_fallback_settings_for_profile(citic_profile)
    should_fallback, fallback_reason = matcher.should_fallback(matches, citic_mappings, fallback_settings)

    chosen = None
    compare_group = "business_match"
    if (not matches or should_fallback) and not bool(resolved_params.get("disable_business_fallback")):
        chosen = matcher.choose_citic_fallback_match(matches, citic_mappings)
        compare_group = "business_fallback"
    elif matches:
        chosen = {
            "level": matches[0].get("level"),
            "industry_code": matches[0].get("industry_code"),
            "industry_name": matches[0].get("industry_name"),
            "score": matches[0].get("score"),
        }

    business_debug = {
        "profile": matched_payload.get("profile") or {},
        "matches": matches,
        "citic_profile": citic_profile,
        "fallback_reason": fallback_reason,
        "fallback_profile": fallback_settings.get("profile_name"),
        "compare_group": compare_group if chosen else None,
        "selected_match": chosen,
    }

    if chosen is None:
        return resolved_params, business_debug

    cfg = StandaloneValuationConfig(base_dir=Path(settings.BASE_DIR), market=market)
    sw_payload = cfg.get_sw_params_by_industry(
        industry=chosen.get("industry_code") or chosen.get("industry_name"),
        level=chosen.get("level"),
        fuzzy=False,
    )
    runtime = _extract_runtime_kwargs(sw_payload)

    # Business match acts as source template, but explicit API inputs still take priority.
    for key in ["pe_target", "ps_target", "pb_target", "peg_target", "ev_ebitda_target", "scenario_model", "sensitivity_grid"]:
        if resolved_params.get(key) is None:
            resolved_params[key] = runtime.get(key)

    if not resolved_params.get("dcf_kwargs"):
        resolved_params["dcf_kwargs"] = runtime.get("dcf_kwargs") or {}
    if not resolved_params.get("ddm_kwargs"):
        resolved_params["ddm_kwargs"] = runtime.get("ddm_kwargs") or {}

    business_debug["selected_source"] = runtime.get("source_info") or {}
    return resolved_params, business_debug


def _normalize_for_json(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _normalize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_json(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, float):
        if pd.isna(value):
            return None
        return float(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def _df_to_records(df):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    records = []
    for row in df.to_dict(orient="records"):
        normalized = {key: _normalize_for_json(val) for key, val in row.items()}
        records.append(normalized)
    return records


def _render_openclaw_advice_text(question, payload):
    summary = payload.get("summary") or {}

    if summary.get("composite_valuation_status") == "under":
        stance = "当前偏低估，可分批关注。"
    elif summary.get("composite_valuation_status") == "over":
        stance = "当前偏高估，建议谨慎。"
    else:
        stance = "当前估值中性，建议结合趋势管理仓位。"

    def _fmt(v):
        return "-" if v is None else f"{float(v):.2f}"

    return "\n".join(
        [
            f"问题: {question}",
            f"标的: {payload.get('ts_code')} ({payload.get('freq')})",
            f"现价: {_fmt(payload.get('current_price'))}",
            f"组合估值: {_fmt(summary.get('composite_valuation_price'))} ({summary.get('composite_valuation_status')}, {_fmt(summary.get('composite_valuation_gap_pct'))}%)",
            f"保守估值: {_fmt(summary.get('conservative_valuation_price'))} ({summary.get('conservative_valuation_status')}, {_fmt(summary.get('conservative_valuation_gap_pct'))}%)",
            f"建议: {stance}",
            "提示: 仅供参考，不构成投资承诺。",
        ]
    )


def _forward_to_feishu(text):
    webhook = str(getattr(settings, "FEISHU_BOT_WEBHOOK", "") or "").strip()
    if not webhook:
        return False, "FEISHU_BOT_WEBHOOK 未配置"

    payload = {
        "msg_type": "text",
        "content": {"text": text},
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


@api_view(["GET"])
def health_check(request):
    return Response({"status": "ok"})


def _build_valuation_payload(ts_code, market="CN", freq="D", band_pct=0.1):

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
        current_price = trading_row.get("close_qfq")

    rows = []
    method_map_for_summary = {}
    if bool(getattr(settings, "ENABLE_LIVE_VALUATION_FALLBACK", True)):
        trade_date_arg = current_trade_date.strftime("%Y-%m-%d") if current_trade_date is not None else None
        try:
            valuation_result = local_test_valuation(ts_code=ts_code, trade_date=trade_date_arg)
            valuation_df = valuation_result.get("valuations")
            weighted_payload = valuation_result.get("weighted_valuation") or {}
        except Exception:
            valuation_df = None
            weighted_payload = {}

        fallback_methods = ["sw_history", "pe", "pb", "ps", "peg", "ev_ebitda", "fcff_dcf", "ddm"]
        for method in fallback_methods:
            method_rows = _extract_method_valuation_rows(valuation_df, method)
            if not method_rows:
                continue
            selected = _select_valuation_candidate(method_rows)
            if not selected:
                continue
            valuation_price = selected.get("implied_price")
            if valuation_price is None:
                continue
            status, gap_pct = _classify_valuation(current_price, valuation_price, band_pct)
            normalized_method = _normalize_method_name(selected.get("method") or method)
            rows.append({"valuation_method": normalized_method, "valuation_price": round(float(valuation_price), 4), "valuation_market_cap": round(float(selected.get("equity_value")), 2) if selected.get("equity_value") is not None else None, "valuation_status": status, "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None, "valuation_weight": selected.get("method_weight"), "source": "live_compute", "latest_trade_date": current_trade_date})
            method_map_for_summary[normalized_method] = {"valuation_price": float(valuation_price)}
    else:
        weighted_payload = {}

    rows.sort(key=lambda item: METHOD_ORDER.get(item.get("valuation_method"), 999))

    summary = _summarize_buy_candidate(current_price, method_map_for_summary, band_pct)
    composite_status, composite_gap_pct = _classify_valuation(current_price, summary.get("composite_valuation_price"), band_pct)
    conservative_status, conservative_gap_pct = _classify_valuation(current_price, summary.get("conservative_valuation_price"), band_pct)

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
            "weighted_valuation_price": weighted_payload.get("weighted_price"),
            "weighted_valuation_equity": weighted_payload.get("weighted_equity_value"),
            "weighted_method_weights": weighted_payload.get("weights") or {},
            "weighted_source": weighted_payload.get("weight_source"),
            "buy_candidate": bool(summary.get("buy_candidate")),
            "valuation_under_methods": summary.get("valuation_under_methods") or [],
            "valuation_valid_methods": summary.get("valuation_valid_methods") or [],
        },
        "data": rows,
    }


@api_view(["GET"])
def get_stock_valuation_methods(request, ts_code):
    market = (request.query_params.get("market") or "CN").strip() or "CN"
    freq = (request.query_params.get("freq") or "D").strip().upper() or "D"
    band_pct = float(request.query_params.get("valuation_band_pct") or 0.1)
    payload = _build_valuation_payload(ts_code=ts_code, market=market, freq=freq, band_pct=band_pct)
    return Response(payload)


@api_view(["GET", "POST"])
def get_stock_valuation_full(request, ts_code):
    resolved_params, error_response = _resolve_full_valuation_inputs(request)
    if error_response is not None:
        return error_response

    business_match_debug = None
    persist_context = None
    if resolved_params.get("match_business_industries"):
        try:
            resolved_params, business_match_debug = _apply_business_match_params(
                ts_code=ts_code,
                resolved_params=resolved_params,
                market="CN",
            )
            selected_match = (business_match_debug or {}).get("selected_match") or {}
            compare_group = (business_match_debug or {}).get("compare_group")
            persist_context = {
                "compare_group": compare_group,
                "match_score": selected_match.get("score"),
                "industry_level": selected_match.get("level"),
                "industry_code": selected_match.get("industry_code"),
                "industry_name": selected_match.get("industry_name"),
                "valuation_variant": _build_valuation_variant(
                    compare_group,
                    selected_match.get("level"),
                    selected_match.get("industry_code"),
                    selected_match.get("industry_name"),
                ),
            }
        except Exception as exc:
            return Response({"error": f"business industry match failed: {exc}"}, status=400)

    result = test_valuation_local(
        ts_code=ts_code,
        trade_date=resolved_params.get("trade_date"),
        current_price=resolved_params.get("current_price"),
        freq=resolved_params.get("freq"),
        pe_target=resolved_params.get("pe_target"),
        ps_target=resolved_params.get("ps_target"),
        pb_target=resolved_params.get("pb_target"),
        peg_target=resolved_params.get("peg_target"),
        ev_ebitda_target=resolved_params.get("ev_ebitda_target"),
        dcf_kwargs=resolved_params.get("dcf_kwargs"),
        ddm_kwargs=resolved_params.get("ddm_kwargs"),
        scenario_model=resolved_params.get("scenario_model"),
        scenario_overrides=resolved_params.get("scenario_overrides"),
        sensitivity_grid=resolved_params.get("sensitivity_grid"),
        snapshot_overrides=resolved_params.get("snapshot_overrides"),
        persist_context=persist_context,
        sw_history_kwargs=resolved_params.get("sw_history_kwargs"),
    )

    return Response(
        {
            "ts_code": ts_code,
            "resolved_params": resolved_params,
            "business_match": business_match_debug,
            "snapshot": {k: _normalize_for_json(v) for k, v in (result.get("snapshot") or {}).items()},
            "valuations": _df_to_records(result.get("valuations")),
            "weighted_valuation": _normalize_for_json(result.get("weighted_valuation") or {}),
            "formatted_range": result.get("formatted_range") or {},
            "scenario_analysis": _df_to_records(result.get("scenario_analysis")),
            "sensitivity_analysis": _df_to_records(result.get("sensitivity_analysis")),
        }
    )


@api_view(["POST"])
def openclaw_valuation_chat(request):
    message = str((request.data or {}).get("message") or "").strip()
    provided_ts_code = str((request.data or {}).get("ts_code") or "").strip().upper()
    market = str((request.data or {}).get("market") or "CN").strip() or "CN"
    freq = str((request.data or {}).get("freq") or "D").strip().upper() or "D"

    query_band = (request.data or {}).get("valuation_band_pct")
    query_band = float(query_band) if query_band is not None else None
    band_pct = query_band if query_band is not None else _extract_band_pct_from_text(message, default_pct=0.1)

    ts_code = _extract_ts_code_from_text(message) or provided_ts_code
    if not ts_code:
        return Response({"error": "缺少 ts_code，请在问题里输入如 600519.SH 或传 ts_code 字段"}, status=400)

    valuation_payload = _build_valuation_payload(ts_code=ts_code, market=market, freq=freq, band_pct=band_pct)

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
