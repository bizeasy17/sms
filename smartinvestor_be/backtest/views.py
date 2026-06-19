import json
import itertools
import re
import zlib
import importlib
import math
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from backtest.models import TraditionalBacktestRun, TraditionalBacktestScanTask
from backtest.services import (
    run_traditional_value_exit_account_backtest,
    run_traditional_value_exit_backtest,
    _build_date_price_map,
    _resolve_history_entry_dates,
    _build_history_method_map,
    _build_risk_map,
    _normalize_risk_levels,
    _resolve_risk_alignment_payload,
    _load_financial_panel_map,
    _resolve_financial_metrics,
    _passes_financial_filters,
)
from datastore.models import Corporation, StockTradingHistory
from prediction.models import StockValuationSnapshot
from prediction.management.commands.backtestbuycandidates import _build_price_history, _resolve_entry_dates, _safe_price
from prediction.management.commands.pickbuycandidates import _build_snapshot_method_map, _summarize_buy_candidate
from prediction.utils.ta_util import calculate_atr

pd = importlib.import_module("pandas") if importlib.util.find_spec("pandas") else None
if importlib.util.find_spec("backtesting"):
    _backtesting_mod = importlib.import_module("backtesting")
    Backtest = getattr(_backtesting_mod, "Backtest")
    Strategy = getattr(_backtesting_mod, "Strategy")
else:
    Backtest = None
    Strategy = object


_SCAN_EXECUTOR = ThreadPoolExecutor(max_workers=1)

_SCAN_TASK_TABLE_MISSING_HINT = "scan task table missing; run `python manage.py migrate backtest`"

TRADITIONAL_TEMPLATE_MAP = {
    "baseline": {
        "mode": "account",
        "scope": "ALL",
        "market": "CN",
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "band_pct": 0.1,
        "min_score": 90,
        "risk_level": "LOW",
        "valuation_variant": "",
        "risk_variant_policy": "any",
        "min_netprofit_yoy": None,
        "min_ebit_yoy": None,
        "require_positive_prev_netprofit": True,
        "require_positive_prev_ebit": True,
        "financial_filter_mode": "all",
        "technical_strategy_enabled": False,
        "technical_lookback_days": 60,
        "technical_factors": [],
        "technical_low_quantile": 0.1,
        "take_profit_mode": "fixed",
        "take_profit_tiers": [],
        "trend_take_profit_enabled": False,
        "trend_position_pct": 0.0,
        "trend_activation_profit": 0.0,
        "trend_ma_period": 20,
        "trend_confirm_days": 2,
        "take_profit_pct": 0.0,
        "stop_loss_mode": "fixed",
        "trailing_stop_pct": 0.0,
        "stop_loss_scope": "position",
        "disable_target_hit": False,
        "starting_capital": 200000.0,
        "max_position_pct": 0.2,
        "first_entry_pct": 0.1,
        "add_on_entry_pct": 0.05,
        "add_on_drop_pct": 0.05,
        "add_on2_fill_remaining": False,
        "add_on2_drop_pct": 0.1,
        "max_buy_per_day": 3,
        "priority_policy": "score_desc",
    },
    "aggressive_score": {
        "scope": "ALL",
        "market": "CN",
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "band_pct": 0.12,
        "min_score": 94,
        "risk_level": "LOW,MEDIUM",
        "valuation_variant": "",
        "risk_variant_policy": "any",
        "min_netprofit_yoy": None,
        "min_ebit_yoy": None,
        "require_positive_prev_netprofit": True,
        "require_positive_prev_ebit": True,
        "financial_filter_mode": "all",
        "take_profit_mode": "fixed",
        "take_profit_tiers": [],
        "trend_take_profit_enabled": False,
        "trend_position_pct": 0.0,
        "trend_activation_profit": 0.0,
        "trend_ma_period": 20,
        "trend_confirm_days": 2,
        "take_profit_pct": 0.05,
        "stop_loss_mode": "fixed",
        "trailing_stop_pct": 0.0,
        "disable_target_hit": False,
    },
    "quality_focus": {
        "scope": "ALL",
        "market": "CN",
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "band_pct": 0.1,
        "min_score": 88,
        "risk_level": "LOW",
        "valuation_variant": "",
        "risk_variant_policy": "any",
        "min_netprofit_yoy": 8,
        "min_ebit_yoy": 5,
        "require_positive_prev_netprofit": True,
        "require_positive_prev_ebit": True,
        "financial_filter_mode": "all",
        "take_profit_mode": "fixed",
        "take_profit_tiers": [],
        "trend_take_profit_enabled": False,
        "trend_position_pct": 0.0,
        "trend_activation_profit": 0.0,
        "trend_ma_period": 20,
        "trend_confirm_days": 2,
        "take_profit_pct": 0.04,
        "stop_loss_mode": "fixed",
        "trailing_stop_pct": 0.0,
        "disable_target_hit": False,
    },
}


def _resolve_traditional_backtest_output_dir(strategy_name: str = "traditional_value_exit") -> Path:
    return Path(settings.BASE_DIR) / "output" / "backtests" / strategy_name


def _stable_run_id(file_name: str) -> int:
    return int(zlib.crc32(str(file_name).encode("utf-8")) & 0x7FFFFFFF)


def _safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _parse_iso_date_optional(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            parsed = datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def _safe_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _parse_bool_or_default(value, default=False):
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


def _format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _extract_params_from_result(payload):
    if not isinstance(payload, dict):
        return {}
    strategy = payload.get("strategy")
    if not isinstance(strategy, dict):
        return {}

    keys = [
        "mode", "scope", "market", "start_date", "end_date", "band_pct", "min_score", "risk_level",
        "valuation_variant", "risk_variant_policy", "min_netprofit_yoy", "min_ebit_yoy",
        "require_positive_prev_netprofit", "require_positive_prev_ebit", "financial_filter_mode",
        "take_profit_mode", "take_profit_tiers", "trend_take_profit_enabled", "trend_position_pct", "trend_activation_profit", "trend_ma_period", "trend_confirm_days",
        "take_profit_pct", "stop_loss_mode", "stop_loss_pct", "trailing_stop_pct", "stop_loss_scope", "disable_target_hit", "starting_capital", "commission_rate",
        "valuation_source", "entry_date_source", "entry_end_date", "max_buy_per_day", "max_position_pct",
        "buy_weight_ladder", "first_entry_pct", "add_on_drop_pct", "add_on_entry_pct", "add_on2_drop_pct", "max_holding_days",
        "add_on2_fill_remaining", "disable_eop_exit", "priority_policy",
    ]
    out = {key: strategy.get(key) for key in keys if key in strategy and strategy.get(key) is not None}
    if "mode" not in out:
        strategy_name = str((payload.get("metadata") or {}).get("strategy") or "").strip().lower()
        out["mode"] = "account" if "account" in strategy_name else "signal"
    return out


def _merge_run_params(primary_params, payload_candidates):
    merged = {}
    for payload in payload_candidates:
        merged.update(_extract_params_from_result(payload))
    if isinstance(primary_params, dict):
        merged.update({key: value for key, value in primary_params.items() if value is not None})
    return merged


def _build_run_row(path: Path):
    stat = path.stat()
    payload = _safe_read_json(path)
    combined = payload.get("combined") if isinstance(payload, dict) else {}
    account = payload.get("account") if isinstance(payload, dict) else {}
    summary_payload = account or combined or {}
    params_payload = _extract_params_from_result(payload)
    path_name = path.name.lower()
    strategy_name = "traditional_value_exit_account" if path_name.startswith("traditional_value_exit_account_") else "traditional_value_exit"
    return {
        "id": _stable_run_id(path.name),
        "run_key": path.stem,
        "batch_key": strategy_name,
        "status": "success",
        "start_date": str(params_payload.get("start_date") or ""),
        "end_date": str(params_payload.get("end_date") or ""),
        "created_at": _format_ts(stat.st_ctime),
        "updated_at": _format_ts(stat.st_mtime),
        "filename": path.name,
        "summary": summary_payload,
        "params": params_payload,
    }


def _format_dt(dt_value):
    if dt_value is None:
        return None
    return dt_value.strftime("%Y-%m-%d %H:%M:%S")


def _pick_snapshot_payload(rows):
    best_row = None
    best_key = None
    method_priority = {
        "pe": 1,
        "pb": 2,
        "ps": 3,
        "peg": 4,
        "sw_history": 5,
        "fcff_dcf": 6,
        "ddm": 7,
    }
    for row in rows:
        method = str(row.get("valuation_method") or "").strip().lower()
        key = (
            method_priority.get(method, 99),
            -(float(row.get("match_score")) if row.get("match_score") is not None else -1.0),
            str(row.get("updated_at") or ""),
        )
        if best_key is None or key < best_key:
            best_key = key
            best_row = row
    return best_row or {}


def _parse_date_or_raise(value, field_name):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc


def _parse_float_or_none(value):
    if value in (None, ""):
        return None
    return float(value)


def _parse_int_or_default(value, default_value):
    if value in (None, ""):
        return int(default_value)
    return int(value)


def _parse_float_list_or_empty(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return [float(item.strip()) for item in str(value).split(",") if str(item).strip()]


def _parse_string_list_or_empty(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value).split(",")

    parsed = []
    for item in raw_items:
        text = str(item or "").strip()
        if text:
            parsed.append(text)
    return parsed


def _parse_take_profit_tiers(value):
    if value in (None, ""):
        return []
    raw_items = value if isinstance(value, (list, tuple)) else []
    tiers = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        trigger_pct = _parse_float_or_none(item.get("trigger_pct"))
        sell_ratio = _parse_float_or_none(item.get("sell_ratio"))
        if trigger_pct is None or sell_ratio is None:
            continue
        tiers.append(
            {
                "trigger_pct": float(trigger_pct),
                "sell_ratio": float(sell_ratio),
            }
        )
    tiers.sort(key=lambda row: float(row.get("trigger_pct") or 0.0))
    return tiers


def _validate_take_profit_allocation(*, take_profit_mode, take_profit_tiers, trend_take_profit_enabled, trend_position_pct):
    if str(take_profit_mode or "fixed").strip().lower() != "dynamic":
        return
    step_weight_sum = sum(float((item or {}).get("sell_ratio") or 0.0) for item in (take_profit_tiers or []))
    effective_trend_pct = float(trend_position_pct or 0.0) if bool(trend_take_profit_enabled) else 0.0
    if abs((step_weight_sum + effective_trend_pct) - 1.0) > 1e-6:
        raise ValueError("止盈配置总和必须为100%")


def _build_task_key():
    return f"traditional_scan_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def _parse_scan_grid(scan_grid):
    grid = scan_grid if isinstance(scan_grid, dict) else {}
    keys = []
    values = []
    for key, raw in grid.items():
        if not isinstance(raw, (list, tuple)):
            continue
        cleaned = [item for item in raw if item not in (None, "")]
        if not cleaned:
            continue
        keys.append(str(key))
        values.append(cleaned)

    if not keys:
        return [{}]

    combos = []
    for picked in itertools.product(*values):
        row = {}
        for idx, key in enumerate(keys):
            picked_value = picked[idx]
            if key == "take_profit_bundle" and isinstance(picked_value, dict):
                take_profit_tiers = picked_value.get("take_profit_tiers")
                trend_position_pct = picked_value.get("trend_position_pct")
                take_profit_mode = picked_value.get("take_profit_mode")
                if take_profit_tiers is not None:
                    row["take_profit_tiers"] = take_profit_tiers
                if trend_position_pct not in (None, ""):
                    row["trend_position_pct"] = trend_position_pct
                if take_profit_mode not in (None, ""):
                    row["take_profit_mode"] = take_profit_mode
                continue
            row[key] = picked_value
        combos.append(row)
    return combos


def _normalize_run_request(raw_params):
    params = dict(TRADITIONAL_TEMPLATE_MAP["baseline"])
    incoming = raw_params if isinstance(raw_params, dict) else {}
    params.update({k: v for k, v in incoming.items() if v is not None})

    mode = str(params.get("mode") or "account").strip().lower()
    if mode not in {"signal", "account"}:
        raise ValueError("mode must be signal or account")

    parsed = {
        "mode": mode,
        "scope": str(params.get("scope") or "ALL"),
        "market": str(params.get("market") or "CN"),
        "start_date": _parse_date_or_raise(params.get("start_date"), "start_date"),
        "end_date": _parse_date_or_raise(params.get("end_date"), "end_date"),
        "band_pct": float(params.get("band_pct", 0.1)),
        "min_score": _parse_int_or_default(params.get("min_score"), 90),
        "risk_level": str(params.get("risk_level") or "LOW"),
        "valuation_variant": str(params.get("valuation_variant") or ""),
        "risk_variant_policy": str(params.get("risk_variant_policy") or "any"),
        "min_netprofit_yoy": _parse_float_or_none(params.get("min_netprofit_yoy")),
        "min_ebit_yoy": _parse_float_or_none(params.get("min_ebit_yoy")),
        "require_positive_prev_netprofit": _parse_bool_or_default(params.get("require_positive_prev_netprofit"), True),
        "require_positive_prev_ebit": _parse_bool_or_default(params.get("require_positive_prev_ebit"), True),
        "financial_filter_mode": str(params.get("financial_filter_mode") or "all"),
        "technical_strategy_enabled": _parse_bool_or_default(params.get("technical_strategy_enabled"), False),
        "technical_lookback_days": _parse_int_or_default(params.get("technical_lookback_days"), 60),
        "technical_factors": _parse_string_list_or_empty(params.get("technical_factors")),
        "technical_low_quantile": float(params.get("technical_low_quantile") or 0.1),
        "take_profit_mode": str(params.get("take_profit_mode") or "fixed").strip().lower(),
        "take_profit_tiers": _parse_take_profit_tiers(params.get("take_profit_tiers")),
        "trend_take_profit_enabled": _parse_bool_or_default(params.get("trend_take_profit_enabled"), False),
        "trend_position_pct": float(params.get("trend_position_pct") or 0.0),
        "trend_activation_profit": float(params.get("trend_activation_profit") or 0.0),
        "trend_ma_period": _parse_int_or_default(params.get("trend_ma_period"), 20),
        "trend_confirm_days": _parse_int_or_default(params.get("trend_confirm_days"), 2),
        "take_profit_pct": float(params.get("take_profit_pct") or 0),
        "stop_loss_mode": str(params.get("stop_loss_mode") or "fixed").strip().lower(),
        "stop_loss_pct": float(params.get("stop_loss_pct") or 0),
        "trailing_stop_pct": float(params.get("trailing_stop_pct") or 0),
        "stop_loss_scope": str(params.get("stop_loss_scope") or "position").strip().lower(),
        "disable_target_hit": bool(params.get("disable_target_hit")),
        "starting_capital": float(params.get("starting_capital") or 200000.0),
        "commission_rate": float(params.get("commission_rate") or 0.0005),
        "valuation_source": str(params.get("valuation_source") or "history").strip().lower(),
        "entry_date_source": str(params.get("entry_date_source") or "history").strip().lower(),
        "entry_end_date": _parse_date_or_raise(params.get("entry_end_date"), "entry_end_date") if params.get("entry_end_date") else None,
        "max_buy_per_day": _parse_int_or_default(params.get("max_buy_per_day"), 3),
        "max_position_pct": float(params.get("max_position_pct") or 0.2),
        "buy_weight_ladder": _parse_float_list_or_empty(params.get("buy_weight_ladder")),
        "first_entry_pct": float(params.get("first_entry_pct") or 0.1),
        "add_on_drop_pct": float(params.get("add_on_drop_pct") or 0.0),
        "add_on_entry_pct": float(params.get("add_on_entry_pct") or 0.0),
        "add_on2_drop_pct": float(params.get("add_on2_drop_pct") or 0.0),
        "max_holding_days": _parse_int_or_default(params.get("max_holding_days"), 0),
        "add_on2_fill_remaining": bool(params.get("add_on2_fill_remaining")),
        "disable_eop_exit": bool(params.get("disable_eop_exit")),
        "priority_policy": str(params.get("priority_policy") or "score_desc").strip().lower(),
    }
    if parsed["start_date"] > parsed["end_date"]:
        raise ValueError("start_date must be <= end_date")
    if parsed["stop_loss_scope"] not in {"position", "account"}:
        raise ValueError("stop_loss_scope must be position or account")
    if parsed["trend_position_pct"] < 0 or parsed["trend_position_pct"] > 1:
        raise ValueError("trend_position_pct must be within [0, 1]")
    if parsed["trend_activation_profit"] < 0 or parsed["trend_activation_profit"] > 1:
        raise ValueError("trend_activation_profit must be within [0, 1]")
    if parsed["technical_lookback_days"] <= 0:
        raise ValueError("technical_lookback_days must be > 0")
    if parsed["technical_low_quantile"] < 0 or parsed["technical_low_quantile"] > 1:
        raise ValueError("technical_low_quantile must be within [0, 1]")
    _validate_take_profit_allocation(
        take_profit_mode=parsed["take_profit_mode"],
        take_profit_tiers=parsed["take_profit_tiers"],
        trend_take_profit_enabled=parsed["trend_take_profit_enabled"],
        trend_position_pct=parsed["trend_position_pct"],
    )
    return parsed


def _run_one_task_item(params, output_json=None):
    common_kwargs = {
        "scope": params["scope"],
        "market": params["market"],
        "start_date": params["start_date"],
        "end_date": params["end_date"],
        "band_pct": params["band_pct"],
        "min_score": params["min_score"],
        "risk_level": params["risk_level"],
        "valuation_variant": params["valuation_variant"],
        "risk_variant_policy": params["risk_variant_policy"],
        "min_netprofit_yoy": params["min_netprofit_yoy"],
        "min_ebit_yoy": params["min_ebit_yoy"],
        "require_positive_prev_netprofit": params["require_positive_prev_netprofit"],
        "require_positive_prev_ebit": params["require_positive_prev_ebit"],
        "financial_filter_mode": params["financial_filter_mode"],
        "technical_strategy_enabled": params["technical_strategy_enabled"],
        "technical_lookback_days": params["technical_lookback_days"],
        "technical_factors": params["technical_factors"],
        "technical_low_quantile": params["technical_low_quantile"],
        "take_profit_mode": params["take_profit_mode"],
        "take_profit_tiers": params["take_profit_tiers"],
        "trend_take_profit_enabled": params["trend_take_profit_enabled"],
        "trend_position_pct": params["trend_position_pct"],
        "trend_activation_profit": params["trend_activation_profit"],
        "trend_ma_period": params["trend_ma_period"],
        "trend_confirm_days": params["trend_confirm_days"],
        "take_profit_pct": params["take_profit_pct"],
        "stop_loss_mode": params["stop_loss_mode"],
        "stop_loss_pct": params["stop_loss_pct"],
        "trailing_stop_pct": params["trailing_stop_pct"],
        "stop_loss_scope": params["stop_loss_scope"],
        "disable_target_hit": params["disable_target_hit"],
        "output_json": output_json,
    }

    if str(params.get("mode") or "account") == "account":
        account_kwargs = {
            "starting_capital": params["starting_capital"],
            "commission_rate": params["commission_rate"],
            "valuation_source": params["valuation_source"],
            "entry_date_source": params["entry_date_source"],
            "entry_end_date": params["entry_end_date"],
            "max_buy_per_day": params["max_buy_per_day"],
            "max_position_pct": params["max_position_pct"],
            "buy_weight_ladder": params["buy_weight_ladder"],
            "first_entry_pct": params["first_entry_pct"],
            "add_on_drop_pct": params["add_on_drop_pct"],
            "add_on_entry_pct": params["add_on_entry_pct"],
            "add_on2_drop_pct": params["add_on2_drop_pct"],
            "max_holding_days": params["max_holding_days"],
            "add_on2_fill_remaining": params["add_on2_fill_remaining"],
            "disable_eop_exit": params["disable_eop_exit"],
            "priority_policy": params["priority_policy"],
        }
        summary, output_path = run_traditional_value_exit_account_backtest(
            **common_kwargs,
            **account_kwargs,
        )
    else:
        summary, output_path = run_traditional_value_exit_backtest(
            **common_kwargs,
        )

    run_key = output_path.stem
    run_obj = TraditionalBacktestRun.objects.filter(run_key=run_key).first()
    return {
        "run_id": int(run_obj.id) if run_obj is not None else None,
        "run_key": run_key,
        "summary": (summary or {}).get("account") or (summary or {}).get("combined") or {},
        "output_file": str(output_path),
    }


def _resolve_run_payload(run_id: int):
    model_run = TraditionalBacktestRun.objects.filter(
        id=run_id,
        strategy_name__in=["traditional_value_exit", "traditional_value_exit_account"],
    ).first()
    if model_run is not None:
        result_payload = model_run.result_json or {}
        file_payload = {}
        if model_run.result_file:
            file_path = Path(settings.BASE_DIR) / str(model_run.result_file)
            if file_path.exists() and file_path.is_file():
                file_payload = _safe_read_json(file_path)
        if not result_payload and file_payload:
            result_payload = file_payload
        params_payload = _merge_run_params(model_run.params_json, [file_payload, result_payload])
        return {
            "run_id": int(model_run.id),
            "run_key": model_run.run_key,
            "summary": model_run.summary_json or {},
            "params": params_payload,
            "result": result_payload,
            "meta": {
                "filename": Path(str(model_run.result_file or "")).name,
                "updated_at": _format_dt(model_run.updated_at),
                "result_file": model_run.result_file,
            },
        }

    candidates = _list_traditional_backtest_files(strategy_name="traditional_value_exit")
    candidates += _list_traditional_backtest_files(strategy_name="traditional_value_exit_account")
    selected = None
    for path in candidates:
        if _stable_run_id(path.name) == int(run_id):
            selected = path
            break
    if selected is None:
        return None

    payload = _safe_read_json(selected)
    row = _build_run_row(selected)
    return {
        "run_id": row["id"],
        "run_key": row["run_key"],
        "summary": row.get("summary") or {},
        "params": row.get("params") or _extract_params_from_result(payload),
        "result": payload,
        "meta": {
            "filename": row.get("filename"),
            "updated_at": row.get("updated_at"),
        },
    }


def _build_replay_params(payload):
    if not isinstance(payload, dict):
        return {}

    raw_params = {}
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    strategy_payload = result_payload.get("strategy") if isinstance(result_payload.get("strategy"), dict) else {}
    params_payload = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    raw_params.update(strategy_payload)
    raw_params.update(params_payload)

    try:
        normalized = _normalize_run_request(raw_params)
    except (ValueError, TypeError):
        return {}

    replay = dict(normalized)
    for key in ("start_date", "end_date", "entry_end_date"):
        value = replay.get(key)
        if hasattr(value, "isoformat"):
            replay[key] = value.isoformat()
        elif value is None:
            replay[key] = None
        else:
            replay[key] = str(value)
    return replay


def _compute_trade_mae_drawdown_pct_map(sample_trades):
    trade_mae = {}
    if not isinstance(sample_trades, list) or not sample_trades:
        return trade_mae

    grouped_windows = defaultdict(list)
    for idx, row in enumerate(sample_trades):
        if not isinstance(row, dict):
            continue
        ts_code = str(row.get("ts_code") or "").strip().upper()
        entry_date = _parse_iso_date_optional(row.get("entry_date"))
        exit_date = _parse_iso_date_optional(row.get("exit_date"))
        entry_price = _safe_float(row.get("entry_price"), None)
        if not ts_code or entry_date is None or exit_date is None or entry_price is None or entry_price <= 0:
            continue
        start_date, end_date = (entry_date, exit_date) if entry_date <= exit_date else (exit_date, entry_date)
        grouped_windows[ts_code].append((idx, start_date, end_date, float(entry_price)))

    for ts_code, windows in grouped_windows.items():
        start_date = min(item[1] for item in windows)
        end_date = max(item[2] for item in windows)
        history_rows = list(
            StockTradingHistory.objects.filter(
                ts_code=ts_code,
                freq="D",
                trade_date__gte=start_date,
                trade_date__lte=end_date,
            )
            .values("trade_date", "low_qfq", "low")
            .order_by("trade_date")
        )

        low_by_date = {}
        for item in history_rows:
            trade_date = item.get("trade_date")
            if trade_date is None:
                continue
            low_price = _safe_float(item.get("low_qfq"), None)
            if low_price is None:
                low_price = _safe_float(item.get("low"), None)
            if low_price is None:
                continue
            low_by_date[trade_date] = float(low_price)

        for idx, entry_date, exit_date, entry_price in windows:
            lows = [
                low_px
                for trade_date, low_px in low_by_date.items()
                if entry_date <= trade_date <= exit_date
            ]
            if not lows:
                continue
            min_low = min(lows)
            mae_pct = max(0.0, (entry_price - float(min_low)) / entry_price * 100.0)
            trade_mae[idx] = round(mae_pct, 4)

    return trade_mae


def _summarize_trades_by_stock(sample_trades):
    trade_mae_map = _compute_trade_mae_drawdown_pct_map(sample_trades)
    grouped = defaultdict(list)
    for idx, row in enumerate(sample_trades):
        if not isinstance(row, dict):
            continue
        mae_drawdown_pct = trade_mae_map.get(idx)
        if mae_drawdown_pct is not None:
            row["_mae_drawdown_pct"] = mae_drawdown_pct
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code:
            continue
        grouped[ts_code].append(row)

    code_list = list(grouped.keys())
    name_map = {
        str(row.get("ts_code") or "").strip().upper(): str(row.get("name") or "").strip()
        for row in Corporation.objects.filter(ts_code__in=code_list).values("ts_code", "name")
    }

    stock_rows = []
    for ts_code, rows in grouped.items():
        returns = [_safe_float(item.get("return_pct"), 0.0) for item in rows]
        holding_days = [_safe_float(item.get("holding_days"), 0.0) for item in rows]
        drawdowns = []
        for item in rows:
            mae_drawdown = _safe_float(item.get("_mae_drawdown_pct"), None)
            if mae_drawdown is not None:
                drawdowns.append(mae_drawdown)
                continue
            historical_drawdown = _safe_float(item.get("max_drawdown_pct"), None)
            if historical_drawdown is not None:
                drawdowns.append(historical_drawdown)
        worst_trade_return = min(returns) if returns else None
        fallback_drawdown = abs(min(worst_trade_return, 0.0)) if worst_trade_return is not None else None
        wins = sum(1 for value in returns if value > 0)
        losses = sum(1 for value in returns if value <= 0)
        entry_dates = [_parse_iso_date_optional(item.get("entry_date")) for item in rows]
        exit_dates = [_parse_iso_date_optional(item.get("exit_date")) for item in rows]
        valid_entry_dates = [d for d in entry_dates if d is not None]
        valid_exit_dates = [d for d in exit_dates if d is not None]

        stock_rows.append(
            {
                "ts_code": ts_code,
                "stock_name": name_map.get(ts_code, ""),
                "trade_count": len(rows),
                "win_count": wins,
                "loss_count": losses,
                "win_rate_pct": round(wins / len(rows) * 100.0, 2) if rows else 0.0,
                "avg_return_pct": round(sum(returns) / len(returns), 4) if returns else 0.0,
                "total_return_pct": round(sum(returns), 4),
                "max_drawdown_pct": round(max(drawdowns), 4) if drawdowns else round(fallback_drawdown, 4),
                "avg_holding_days": round(sum(holding_days) / len(holding_days), 2) if holding_days else 0.0,
                "first_entry_date": min(valid_entry_dates).isoformat() if valid_entry_dates else None,
                "last_exit_date": max(valid_exit_dates).isoformat() if valid_exit_dates else None,
            }
        )

    stock_rows.sort(key=lambda item: (item.get("total_return_pct") or 0.0), reverse=True)
    return stock_rows


def _load_stock_name(ts_code: str) -> str:
    code = str(ts_code or "").strip().upper()
    if not code:
        return ""
    row = Corporation.objects.filter(ts_code=code).values("name").first()
    return str((row or {}).get("name") or "").strip()


def _build_valuation_history(ts_code: str, start_date, end_date, max_rows: int = 240):
    code = str(ts_code or "").strip().upper()
    if not code:
        return []

    rows = (
        StockValuationSnapshot.objects.filter(
            ts_code=code,
            market="CN",
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        .values(
            "trade_date",
            "valuation_method",
            "valuation_price",
            "valuation_market_cap",
            "valuation_variant",
            "source",
            "match_score",
            "updated_at",
        )
        .order_by("trade_date", "-updated_at")
    )

    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("trade_date")].append(row)

    out = []
    for trade_date in sorted(grouped.keys()):
        picked = _pick_snapshot_payload(grouped.get(trade_date, []))
        if not picked:
            continue
        out.append(
            {
                "trade_date": trade_date.isoformat() if trade_date is not None else None,
                "valuation_price": _safe_float(picked.get("valuation_price")),
                "valuation_market_cap": _safe_float(picked.get("valuation_market_cap")),
                "valuation_method": picked.get("valuation_method"),
                "valuation_variant": picked.get("valuation_variant"),
                "valuation_source": picked.get("source"),
                "match_score": _safe_float(picked.get("match_score")),
            }
        )
        if len(out) >= max_rows:
            break

    return out


def _load_kline_rows(ts_code, start_date, end_date):
    rows = list(
        StockTradingHistory.objects.filter(
            ts_code=str(ts_code or "").strip().upper(),
            freq="D",
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        .order_by("trade_date")
        .values(
            "trade_date",
            "open_qfq",
            "high_qfq",
            "low_qfq",
            "close_qfq",
            "open",
            "high",
            "low",
            "close",
            "vol",
        )
    )

    atr_by_date = {}
    if rows and pd is not None:
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = calculate_atr(
                df=frame,
                period=20,
                high_col="high_qfq",
                low_col="low_qfq",
                close_col="close_qfq",
            )
            for idx, row in enumerate(rows):
                trade_date = row.get("trade_date")
                if trade_date is None or idx >= len(frame):
                    continue
                atr = _safe_float(frame.at[idx, "atr"] if "atr" in frame.columns else None)
                close_qfq = _safe_float(frame.at[idx, "close_qfq"] if "close_qfq" in frame.columns else None)
                if atr is None or close_qfq is None:
                    atr_by_date[trade_date] = {"sl1": None, "sl2": None, "tp1": None, "tp2": None}
                    continue
                atr = round(atr, 4)
                atr_by_date[trade_date] = {
                    "sl1": round(close_qfq - atr, 4),
                    "sl2": round(close_qfq - 2 * atr, 4),
                    "tp1": round(close_qfq + atr, 4),
                    "tp2": round(close_qfq + 2 * atr, 4),
                }

    out = []
    for row in rows:
        open_px = _safe_float(row.get("open_qfq"), _safe_float(row.get("open")))
        high_px = _safe_float(row.get("high_qfq"), _safe_float(row.get("high")))
        low_px = _safe_float(row.get("low_qfq"), _safe_float(row.get("low")))
        close_px = _safe_float(row.get("close_qfq"), _safe_float(row.get("close")))
        if close_px is None:
            continue
        if open_px is None:
            open_px = close_px
        if high_px is None:
            high_px = max(open_px, close_px)
        if low_px is None:
            low_px = min(open_px, close_px)

        bands = atr_by_date.get(row.get("trade_date"), {})
        out.append(
            {
                "trade_date": row["trade_date"].isoformat() if row.get("trade_date") is not None else None,
                "open": round(open_px, 4),
                "high": round(high_px, 4),
                "low": round(low_px, 4),
                "close": round(close_px, 4),
                "sl1": bands.get("sl1"),
                "sl2": bands.get("sl2"),
                "tp1": bands.get("tp1"),
                "tp2": bands.get("tp2"),
                "volume": int(row.get("vol") or 0),
            }
        )
    return out


def _build_trade_markers(trades):
    markers = []
    for item in trades:
        if not isinstance(item, dict):
            continue
        entry_date = str(item.get("entry_date") or "").strip()
        exit_date = str(item.get("exit_date") or "").strip()
        entry_price = _safe_float(item.get("entry_price"))
        exit_price = _safe_float(item.get("exit_price"))
        if entry_date and entry_price is not None:
            markers.append(
                {
                    "type": "buy",
                    "trade_date": entry_date,
                    "price": round(entry_price, 4),
                    "label": "买",
                }
            )
        if exit_date and exit_price is not None:
            markers.append(
                {
                    "type": "sell",
                    "trade_date": exit_date,
                    "price": round(exit_price, 4),
                    "label": "卖",
                }
            )
    return markers


def _build_buy_candidate_markers(payload, ts_code: str):
    normalized_code = str(ts_code or "").strip().upper()
    if not normalized_code:
        return []

    result_payload = payload.get("result") if isinstance(payload, dict) else {}
    cached_markers_map = (result_payload or {}).get("buy_candidate_markers") if isinstance(result_payload, dict) else None
    if isinstance(cached_markers_map, dict):
        cached_rows = cached_markers_map.get(normalized_code)
        if isinstance(cached_rows, list):
            out = []
            has_valuation_overlay = False
            for row in cached_rows:
                if not isinstance(row, dict):
                    continue
                trade_date = str(row.get("trade_date") or "").strip()
                price = _safe_float(row.get("price"))
                if not trade_date or price is None:
                    continue
                composite_price = _safe_float(row.get("composite_price"))
                conservative_price = _safe_float(row.get("conservative_price"))
                if composite_price is not None or conservative_price is not None:
                    has_valuation_overlay = True
                out.append(
                    {
                        "type": "buy_candidate",
                        "trade_date": trade_date,
                        "price": round(float(price), 4),
                        "composite_price": composite_price,
                        "label": "可买",
                        "conservative_price": conservative_price,
                    }
                )
            # Older runs may have cached markers without valuation overlay fields.
            # In that case, fall back to recomputing markers below.
            if out and has_valuation_overlay:
                return out

    strategy_payload = (result_payload or {}).get("strategy") if isinstance(result_payload, dict) else {}
    params_payload = payload.get("params") if isinstance(payload, dict) else {}
    merged_raw = {}
    if isinstance(params_payload, dict):
        merged_raw.update(params_payload)
    if isinstance(strategy_payload, dict):
        merged_raw.update(strategy_payload)

    params = _normalize_run_request(merged_raw)
    allowed_risk_levels = _normalize_risk_levels(params.get("risk_level"))
    if not allowed_risk_levels:
        return []

    if params["entry_date_source"] == "history":
        entry_dates = _resolve_history_entry_dates(
            scope=params["scope"],
            market=params["market"],
            start_date=params["start_date"],
            end_date=params["end_date"],
        )
    else:
        entry_dates = _resolve_entry_dates(
            scope=params["scope"],
            start_date=params["start_date"],
            end_date=params["end_date"],
            snapshot_only=True,
            rebalance_step=1,
        )
    if params["entry_end_date"] is not None:
        entry_dates = [trade_date for trade_date in entry_dates if trade_date is not None and trade_date <= params["entry_end_date"]]
    entry_dates = sorted([trade_date for trade_date in entry_dates if trade_date is not None])
    if not entry_dates:
        return []

    price_history = _build_price_history(
        scope=params["scope"],
        start_date=params["start_date"],
        end_date=params["end_date"],
        freq="D",
    )
    if not price_history:
        return []

    date_price_map = _build_date_price_map(price_history)
    risk_map = _build_risk_map(
        entry_dates=entry_dates,
        market=params["market"],
        valuation_variant=params["valuation_variant"] if params["risk_variant_policy"] == "specific" else None,
    )
    financial_filters_enabled = (
        params["min_netprofit_yoy"] is not None
        or params["min_ebit_yoy"] is not None
        or params["require_positive_prev_netprofit"]
        or params["require_positive_prev_ebit"]
    )
    financial_panel_map = _load_financial_panel_map(price_history.keys(), params["end_date"]) if financial_filters_enabled else {}
    financial_metric_cache = {}

    markers = []
    for trade_date in entry_dates:
        date_prices = date_price_map.get(trade_date, {})
        current_price = _safe_price(date_prices.get(normalized_code))
        if current_price is None:
            continue

        if params["valuation_source"] == "history":
            method_map = _build_history_method_map(ts_codes=[normalized_code], trade_date=trade_date, market=params["market"])
        else:
            method_map = _build_snapshot_method_map(ts_codes=[normalized_code], trade_date=trade_date, market=params["market"])

        summary = _summarize_buy_candidate(
            current_price=current_price,
            method_map=method_map.get(normalized_code, {}),
            band_pct=params["band_pct"],
        )
        if not summary.get("buy_candidate"):
            continue

        score = summary.get("undervalue_score")
        conservative_price = _safe_price(summary.get("conservative_valuation_price"))
        if score is None or float(score) < float(params["min_score"]):
            continue
        if conservative_price is None or current_price > conservative_price:
            continue

        risk_payload = risk_map.get((trade_date, normalized_code)) or {}
        if params["risk_variant_policy"] == "specific":
            matched_risk_level = risk_payload.get("selected_variant_risk_level")
            passes_risk = matched_risk_level in allowed_risk_levels
        else:
            risk_levels = risk_payload.get("risk_levels") or []
            passes_risk = any(level in risk_levels for level in allowed_risk_levels)
        if not passes_risk:
            continue

        if financial_filters_enabled:
            financial_payload = _resolve_financial_metrics(
                financial_panel_map=financial_panel_map,
                ts_code=normalized_code,
                trade_date=trade_date,
                cache=financial_metric_cache,
            )
            if not _passes_financial_filters(
                financial_payload,
                min_netprofit_yoy=params["min_netprofit_yoy"],
                min_ebit_yoy=params["min_ebit_yoy"],
                financial_filter_mode=params["financial_filter_mode"],
                require_positive_prev_netprofit=params["require_positive_prev_netprofit"],
                require_positive_prev_ebit=params["require_positive_prev_ebit"],
            ):
                continue

        markers.append(
            {
                "type": "buy_candidate",
                "trade_date": trade_date.isoformat(),
                "price": round(float(current_price), 4),
                "composite_price": round(float(summary.get("composite_valuation_price")), 4),
                "conservative_price": round(float(conservative_price), 4),
                "label": "可买",
            }
        )
    return markers


def _compute_backtesting_stats(kline_rows, trades):
    fallback = {
        "start_date": kline_rows[0]["trade_date"] if kline_rows else None,
        "end_date": kline_rows[-1]["trade_date"] if kline_rows else None,
        "kline_days": len(kline_rows),
        "trade_count": len(trades),
        "avg_return_pct": round(
            sum(_safe_float(item.get("return_pct"), 0.0) for item in trades) / len(trades),
            4,
        )
        if trades
        else 0.0,
        "win_rate_pct": round(
            sum(1 for item in trades if _safe_float(item.get("return_pct"), 0.0) > 0) / len(trades) * 100.0,
            2,
        )
        if trades
        else 0.0,
        "profit_factor": None,
        "expectancy_pct": None,
        "avg_trade_pct": None,
        "best_trade_pct": None,
        "worst_trade_pct": None,
        "sortino_ratio": None,
        "calmar_ratio": None,
        "max_drawdown_pct": None,
        "avg_drawdown_pct": None,
        "buy_hold_return_pct": None,
        "exposure_time_pct": None,
        "equity_final": None,
        "equity_peak": None,
        "sqn": None,
    }

    if not kline_rows or pd is None or Backtest is None:
        return {
            "mode": "fallback",
            **fallback,
            "warning": "backtesting package unavailable or no kline rows",
        }

    try:
        signal_map = {}
        for trade in trades:
            entry = str(trade.get("entry_date") or "").strip()
            exit_date = str(trade.get("exit_date") or "").strip()
            if entry:
                signal_map[entry] = 1
            if exit_date:
                signal_map[exit_date] = -1

        frame = pd.DataFrame(kline_rows)
        frame["Date"] = pd.to_datetime(frame["trade_date"])
        frame = frame.set_index("Date")
        frame = frame.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
        signal_by_date = signal_map

        class ReplayStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                current_date = str(self.data.index[-1].date())
                signal = signal_by_date.get(current_date)
                if signal == 1 and not self.position:
                    self.buy()
                elif signal == -1 and self.position:
                    self.position.close()

        bt = Backtest(frame, ReplayStrategy, cash=100000, commission=0.0005, trade_on_close=True, exclusive_orders=True)
        stats = bt.run()
        return {
            "mode": "backtesting",
            "start_date": fallback["start_date"],
            "end_date": fallback["end_date"],
            "kline_days": fallback["kline_days"],
            "trade_count": int(stats.get("# Trades", fallback["trade_count"])),
            "return_pct": round(_safe_float(stats.get("Return [%]"), 0.0), 4),
            "buy_hold_return_pct": round(_safe_float(stats.get("Buy & Hold Return [%]"), 0.0), 4),
            "win_rate_pct": round(_safe_float(stats.get("Win Rate [%]"), fallback["win_rate_pct"]), 4),
            "max_drawdown_pct": round(_safe_float(stats.get("Max. Drawdown [%]"), 0.0), 4),
            "avg_drawdown_pct": round(_safe_float(stats.get("Avg. Drawdown [%]"), 0.0), 4),
            "sharpe_ratio": round(_safe_float(stats.get("Sharpe Ratio"), 0.0), 4),
            "sortino_ratio": round(_safe_float(stats.get("Sortino Ratio"), 0.0), 4),
            "calmar_ratio": round(_safe_float(stats.get("Calmar Ratio"), 0.0), 4),
            "profit_factor": round(_safe_float(stats.get("Profit Factor"), 0.0), 4),
            "expectancy_pct": round(_safe_float(stats.get("Expectancy [%]"), 0.0), 4),
            "avg_trade_pct": round(_safe_float(stats.get("Avg. Trade [%]"), 0.0), 4),
            "best_trade_pct": round(_safe_float(stats.get("Best Trade [%]"), 0.0), 4),
            "worst_trade_pct": round(_safe_float(stats.get("Worst Trade [%]"), 0.0), 4),
            "exposure_time_pct": round(_safe_float(stats.get("Exposure Time [%]"), 0.0), 4),
            "equity_final": round(_safe_float(stats.get("Equity Final [$]"), 0.0), 2),
            "equity_peak": round(_safe_float(stats.get("Equity Peak [$]"), 0.0), 2),
            "sqn": round(_safe_float(stats.get("SQN"), 0.0), 4),
        }
    except (ValueError, TypeError, KeyError) as exc:
        return {
            "mode": "fallback",
            **fallback,
            "warning": f"backtesting failed: {exc}",
        }


def _serialize_scan_task(task_obj: TraditionalBacktestScanTask):
    total = int(task_obj.total_jobs or 0)
    completed = int(task_obj.completed_jobs or 0)
    failed = int(task_obj.failed_jobs or 0)
    percent = round((completed + failed) / total * 100.0, 2) if total > 0 else 0.0
    return {
        "id": int(task_obj.id),
        "task_key": task_obj.task_key,
        "status": task_obj.status,
        "strategy_name": task_obj.strategy_name,
        "total_jobs": total,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "progress_pct": percent,
        "params": task_obj.params_json or {},
        "result": task_obj.result_json or {},
        "error_message": task_obj.error_message,
        "created_at": _format_dt(task_obj.created_at),
        "updated_at": _format_dt(task_obj.updated_at),
    }


def _append_scan_event(events, *, step_type, message, index=None, ts_code=None, trade_date=None, level="info", extra=None):
    row = {
        "ts": timezone.now().isoformat(),
        "level": str(level or "info"),
        "step_type": str(step_type or "info"),
        "message": str(message or ""),
    }
    if index is not None:
        row["index"] = int(index)
    if ts_code is not None:
        row["ts_code"] = str(ts_code)
    if trade_date is not None:
        row["trade_date"] = str(trade_date)
    if isinstance(extra, dict) and extra:
        row["extra"] = extra
    events.append(row)


def _extract_scan_events_from_run_file(output_file):
    out = []
    payload = _safe_read_json(Path(str(output_file)))
    if not isinstance(payload, dict):
        return out

    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    buy_candidates = payload.get("buy_candidates_summary") if isinstance(payload.get("buy_candidates_summary"), list) else []
    trades = payload.get("sample_trades") if isinstance(payload.get("sample_trades"), list) else []

    out.append(
        {
            "step_type": "run_summary",
            "message": (
                "run summary: buy_signals={} buys={} partial_tps={} trades={}"
            ).format(
                int(diagnostics.get("buy_signal_count_before_score_and_risk") or 0),
                int(diagnostics.get("buy_executed_count") or 0),
                int(diagnostics.get("take_profit_partial_count") or 0),
                int(diagnostics.get("closed_trade_count") or 0),
            ),
            "extra": {
                "buy_signal_count": int(diagnostics.get("buy_signal_count_before_score_and_risk") or 0),
                "buy_executed_count": int(diagnostics.get("buy_executed_count") or 0),
                "take_profit_partial_count": int(diagnostics.get("take_profit_partial_count") or 0),
                "closed_trade_count": int(diagnostics.get("closed_trade_count") or 0),
            },
        }
    )

    for row in buy_candidates[:8]:
        if not isinstance(row, dict):
            continue
        ts_code = str(row.get("ts_code") or "").strip()
        if not ts_code:
            continue
        out.append(
            {
                "step_type": "candidate_found",
                "message": "candidate {} hits={} max_score={}".format(
                    ts_code,
                    int(row.get("hit_count") or 0),
                    row.get("max_score"),
                ),
                "ts_code": ts_code,
                "trade_date": row.get("last_hit_date"),
                "extra": {
                    "hit_count": int(row.get("hit_count") or 0),
                    "max_score": row.get("max_score"),
                    "best_discount_pct": row.get("best_discount_pct"),
                },
            }
        )

    exit_map = {
        "target_hit": "take_profit",
        "take_profit_pct_hit": "take_profit",
        "trend_take_profit_hit": "take_profit",
        "trailing_stop_hit": "stop_loss",
        "stop_loss_pct_hit": "stop_loss",
        "account_stop_loss_pct_hit": "stop_loss",
        "end_of_period": "eop_exit",
    }
    for row in trades[:24]:
        if not isinstance(row, dict):
            continue
        ts_code = str(row.get("ts_code") or "").strip()
        entry_date = row.get("entry_date")
        exit_date = row.get("exit_date")
        if ts_code and entry_date:
            out.append(
                {
                    "step_type": "buy_open",
                    "message": "buy {} entry={} price={} shares={}".format(
                        ts_code,
                        entry_date,
                        row.get("entry_price"),
                        row.get("shares"),
                    ),
                    "ts_code": ts_code,
                    "trade_date": entry_date,
                    "extra": {
                        "entry_price": row.get("entry_price"),
                        "shares": row.get("shares"),
                    },
                }
            )
        if ts_code and exit_date:
            exit_reason = str(row.get("exit_reason") or "").strip()
            out.append(
                {
                    "step_type": exit_map.get(exit_reason, "sell_exit"),
                    "message": "sell {} exit={} reason={} price={}".format(
                        ts_code,
                        exit_date,
                        exit_reason or "unknown",
                        row.get("exit_price"),
                    ),
                    "ts_code": ts_code,
                    "trade_date": exit_date,
                    "extra": {
                        "exit_reason": exit_reason,
                        "exit_price": row.get("exit_price"),
                        "return_pct": row.get("return_pct"),
                        "shares": row.get("shares"),
                    },
                }
            )
    return out


def _execute_scan_task(task_id, base_params, combo_overrides):
    task = TraditionalBacktestScanTask.objects.filter(id=task_id).first()
    if task is None:
        return

    if str(task.status or "").strip().lower() in {"cancel_requested", "canceled"}:
        task.status = "canceled"
        task.error_message = "task canceled before execution"
        task.save(update_fields=["status", "error_message", "updated_at"])
        return

    task.status = "running"
    task.error_message = ""
    task.completed_jobs = 0
    task.failed_jobs = 0
    events = []
    task.result_json = {"runs": [], "failures": [], "events": events}
    task.save(update_fields=["status", "error_message", "completed_jobs", "failed_jobs", "result_json", "updated_at"])

    run_rows = []
    failures = []
    completed = 0
    failed = 0
    max_events = 800

    for idx, override in enumerate(combo_overrides, 1):
        latest_task = TraditionalBacktestScanTask.objects.filter(id=task_id).values("status").first() or {}
        latest_status = str(latest_task.get("status") or "").strip().lower()
        if latest_status in {"cancel_requested", "canceled"}:
            _append_scan_event(
                events,
                step_type="task_canceled",
                message="task canceled by user at run #{}/{}".format(idx, len(combo_overrides)),
                index=idx,
                level="warning",
            )
            break

        merged_params = dict(base_params)
        merged_params.update(override or {})
        _append_scan_event(
            events,
            step_type="run_started",
            message="run #{}/{} started".format(idx, len(combo_overrides)),
            index=idx,
            extra={"mode": merged_params.get("mode"), "scope": merged_params.get("scope")},
        )
        try:
            normalized = _normalize_run_request(merged_params)
            output_file = Path(settings.BASE_DIR) / "output" / "backtests" / "traditional_value_exit_scan" / task.task_key / f"{task.task_key}_run_{idx:03d}.json"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            run_payload = _run_one_task_item(normalized, output_json=str(output_file))
            _append_scan_event(
                events,
                step_type="run_finished",
                message="run #{}/{} finished run_id={}".format(idx, len(combo_overrides), run_payload.get("run_id")),
                index=idx,
                extra={"run_id": run_payload.get("run_id"), "run_key": run_payload.get("run_key")},
            )
            for event_row in _extract_scan_events_from_run_file(run_payload.get("output_file")):
                if not isinstance(event_row, dict):
                    continue
                _append_scan_event(
                    events,
                    step_type=event_row.get("step_type"),
                    message=event_row.get("message"),
                    index=idx,
                    ts_code=event_row.get("ts_code"),
                    trade_date=event_row.get("trade_date"),
                    extra=event_row.get("extra"),
                )
            run_rows.append({
                "index": idx,
                "params": merged_params,
                **run_payload,
            })
            completed += 1
        except (ValueError, TypeError) as exc:
            _append_scan_event(
                events,
                step_type="run_failed",
                message="run #{}/{} failed: {}".format(idx, len(combo_overrides), str(exc)),
                index=idx,
                level="error",
            )
            failures.append(
                {
                    "index": idx,
                    "params": merged_params,
                    "error": str(exc),
                }
            )
            failed += 1

        TraditionalBacktestScanTask.objects.filter(id=task_id).update(
            completed_jobs=completed,
            failed_jobs=failed,
            result_json={"runs": run_rows, "failures": failures, "events": events[-max_events:]},
            updated_at=timezone.now(),
        )

    final = TraditionalBacktestScanTask.objects.filter(id=task_id).first()
    if final is None:
        return

    latest_final_status = str(final.status or "").strip().lower()
    if latest_final_status in {"cancel_requested", "canceled"}:
        final.status = "canceled"
    elif completed > 0 and failed == 0:
        final.status = "success"
    elif completed > 0 and failed > 0:
        final.status = "partial_success"
    else:
        final.status = "failed"

    if failed > 0 and completed == 0 and failures:
        final.error_message = failures[0].get("error") or "scan failed"

    _append_scan_event(
        events,
        step_type="task_finished",
        message="task finished status={} completed={} failed={}".format(final.status, completed, failed),
        extra={"status": final.status, "completed": completed, "failed": failed},
    )
    final.result_json = {"runs": run_rows, "failures": failures, "events": events[-max_events:]}
    final.completed_jobs = completed
    final.failed_jobs = failed
    final.save(update_fields=["status", "result_json", "completed_jobs", "failed_jobs", "error_message", "updated_at"])


@api_view(["POST"])
def cancel_traditional_backtest_scan_task(_request, task_id: int):
    try:
        task = TraditionalBacktestScanTask.objects.filter(id=task_id).first()
    except (ProgrammingError, OperationalError):
        return Response({"ok": False, "error": _SCAN_TASK_TABLE_MISSING_HINT}, status=503)

    if task is None:
        return Response({"ok": False, "error": "task not found"}, status=404)

    status_text = str(task.status or "").strip().lower()
    if status_text in {"success", "failed", "partial_success", "canceled"}:
        return Response({"ok": True, "task_id": int(task.id), "status": task.status, "message": "task already finished"})

    result_payload = task.result_json if isinstance(task.result_json, dict) else {}
    events = result_payload.get("events") if isinstance(result_payload.get("events"), list) else []
    _append_scan_event(
        events,
        step_type="task_cancel_requested",
        message="task cancel requested by user",
        level="warning",
    )
    result_payload["events"] = events[-800:]

    task.status = "cancel_requested"
    task.result_json = result_payload
    task.save(update_fields=["status", "result_json", "updated_at"])

    return Response({"ok": True, "task_id": int(task.id), "status": task.status})


def _build_run_row_from_model(run_obj: TraditionalBacktestRun):
    result_file = str(run_obj.result_file or "")
    result_payload = run_obj.result_json or {}
    file_payload = {}
    if result_file:
        file_path = Path(settings.BASE_DIR) / result_file
        if file_path.exists() and file_path.is_file():
            file_payload = _safe_read_json(file_path)
    params_payload = _merge_run_params(run_obj.params_json, [file_payload, result_payload])
    return {
        "id": int(run_obj.id),
        "run_key": run_obj.run_key,
        "batch_key": run_obj.batch_key,
        "status": run_obj.status,
        "start_date": run_obj.start_date.isoformat() if run_obj.start_date else "",
        "end_date": run_obj.end_date.isoformat() if run_obj.end_date else "",
        "created_at": _format_dt(run_obj.created_at),
        "updated_at": _format_dt(run_obj.updated_at),
        "filename": Path(result_file).name if result_file else "",
        "summary": run_obj.summary_json or {},
        "params": params_payload,
    }


def _list_traditional_backtest_files(strategy_name: str = "traditional_value_exit"):
    base_dir = _resolve_traditional_backtest_output_dir(strategy_name=strategy_name)
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    files = [
        item for item in base_dir.glob(f"{strategy_name}_*.json")
        if item.is_file()
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _list_archived_traditional_backtest_files(strategy_name: str = "traditional_value_exit"):
    archive_root = Path(settings.BASE_DIR) / "output" / "archive"
    if not archive_root.exists() or not archive_root.is_dir():
        return []

    pattern = f"**/backtests/{strategy_name}/{strategy_name}_*.json"
    files = [item for item in archive_root.glob(pattern) if item.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _build_run_row_from_archive_dict(row: dict):
    result_file = str((row or {}).get("result_file") or "")
    run_key = str((row or {}).get("run_key") or "")
    params_payload = (row or {}).get("params_json") or (row or {}).get("params") or {}
    return {
        "id": int((row or {}).get("id") or _stable_run_id(run_key or result_file or "archive_row")),
        "run_key": run_key,
        "batch_key": str((row or {}).get("batch_key") or (row or {}).get("strategy_name") or "traditional_value_exit"),
        "status": str((row or {}).get("status") or "success"),
        "start_date": str((row or {}).get("start_date") or (params_payload.get("start_date") if isinstance(params_payload, dict) else "") or ""),
        "end_date": str((row or {}).get("end_date") or (params_payload.get("end_date") if isinstance(params_payload, dict) else "") or ""),
        "created_at": str((row or {}).get("created_at") or ""),
        "updated_at": str((row or {}).get("updated_at") or ""),
        "filename": Path(result_file).name if result_file else "",
        "summary": (row or {}).get("summary_json") or {},
        "params": params_payload,
    }


def _is_scan_like_run_key(run_key: str) -> bool:
    return bool(re.search(r"_run_\d+$", str(run_key or "")))


def _is_single_scan_task_run(task, run_row):
    """Treat single-job scan submissions as manual execute history."""
    if task is None or not isinstance(run_row, dict):
        return False

    try:
        total_jobs = int(getattr(task, "total_jobs", 0) or 0)
    except (TypeError, ValueError):
        total_jobs = 0

    combo_index = run_row.get("index")
    if combo_index in (None, ""):
        combo_index = run_row.get("combo_index")
    try:
        combo_index_num = int(combo_index) if combo_index not in (None, "") else 1
    except (TypeError, ValueError):
        combo_index_num = 1

    return total_jobs <= 1 and combo_index_num <= 1


def _build_manual_row_from_scan_task(task, run_row):
    params_payload = run_row.get("params") if isinstance(run_row.get("params"), dict) else {}
    summary_payload = run_row.get("summary") if isinstance(run_row.get("summary"), dict) else {}
    run_key = str(run_row.get("run_key") or "")
    run_id = int(run_row.get("run_id") or _stable_run_id(run_key or f"scan_task_{task.id}_single"))
    return {
        "id": run_id,
        "run_id": run_id,
        "run_key": run_key,
        "batch_key": str(task.strategy_name or "traditional_value_exit"),
        "status": str(task.status or "success"),
        "source": "manual",
        "task_id": int(task.id),
        "task_key": task.task_key,
        "strategy_name": task.strategy_name,
        "combo_index": None,
        "start_date": str(params_payload.get("start_date") or ""),
        "end_date": str(params_payload.get("end_date") or ""),
        "created_at": str(run_row.get("created_at") or _format_dt(task.created_at) or ""),
        "updated_at": str(run_row.get("updated_at") or _format_dt(task.updated_at) or ""),
        "summary": summary_payload,
        "params": params_payload,
    }


def _collect_manual_backtest_rows(*, limit: int, offset: int = 0, account_only: bool = False, include_archive: bool = False):
    queryset = TraditionalBacktestRun.objects.filter(
        strategy_name__in=["traditional_value_exit", "traditional_value_exit_account"],
    ).order_by("-updated_at", "-id")
    db_rows = [_build_run_row_from_model(item) for item in queryset]

    file_candidates = _list_traditional_backtest_files(strategy_name="traditional_value_exit")
    file_candidates += _list_traditional_backtest_files(strategy_name="traditional_value_exit_account")
    file_rows = [_build_run_row(path) for path in file_candidates]

    archive_file_rows = []
    archive_db_rows = []
    if include_archive:
        archive_file_candidates = _list_archived_traditional_backtest_files(strategy_name="traditional_value_exit")
        archive_file_candidates += _list_archived_traditional_backtest_files(strategy_name="traditional_value_exit_account")
        archive_file_rows = [_build_run_row(path) for path in archive_file_candidates]
        archive_db_rows = _load_archived_db_run_rows(["traditional_value_exit", "traditional_value_exit_account"])

    merged = []
    seen_run_keys = set()
    for row in db_rows + file_rows + archive_file_rows + archive_db_rows:
        run_key = str((row or {}).get("run_key") or "")
        if _is_scan_like_run_key(run_key):
            continue
        unique_key = run_key or f"id:{(row or {}).get('id')}"
        if unique_key in seen_run_keys:
            continue
        seen_run_keys.add(unique_key)
        merged.append(row)

    try:
        scan_tasks = list(TraditionalBacktestScanTask.objects.order_by("-updated_at", "-id"))
    except (ProgrammingError, OperationalError):
        scan_tasks = []

    for task in scan_tasks:
        result_payload = task.result_json if isinstance(task.result_json, dict) else {}
        run_rows = result_payload.get("runs") if isinstance(result_payload.get("runs"), list) else []
        for run_row in run_rows:
            if not _is_single_scan_task_run(task, run_row):
                continue
            manual_row = _build_manual_row_from_scan_task(task, run_row)
            run_key = str((manual_row or {}).get("run_key") or "")
            unique_key = run_key or f"id:{(manual_row or {}).get('id')}"
            if unique_key in seen_run_keys:
                continue
            seen_run_keys.add(unique_key)
            merged.append(manual_row)

    if account_only:
        filtered = []
        for row in merged:
            summary = (row or {}).get("summary") or {}
            initial_capital, ending_capital = _extract_account_capitals(summary)
            if initial_capital is not None and ending_capital is not None:
                filtered.append(row)
        merged = filtered

    merged.sort(key=lambda row: str((row or {}).get("updated_at") or ""), reverse=True)
    total = len(merged)
    return merged[offset:offset + limit], total


def _collect_scan_backtest_rows(*, limit: int, offset: int = 0):
    try:
        tasks = list(TraditionalBacktestScanTask.objects.order_by("-updated_at", "-id"))
    except (ProgrammingError, OperationalError):
        return [], 0, _SCAN_TASK_TABLE_MISSING_HINT

    rows = []
    for task in tasks:
        result_payload = task.result_json if isinstance(task.result_json, dict) else {}
        run_rows = result_payload.get("runs") if isinstance(result_payload.get("runs"), list) else []
        for run in run_rows:
            if not isinstance(run, dict):
                continue
            if _is_single_scan_task_run(task, run):
                continue
            params_payload = run.get("params") if isinstance(run.get("params"), dict) else {}
            summary_payload = run.get("summary") if isinstance(run.get("summary"), dict) else {}
            run_key = str(run.get("run_key") or "")
            rows.append({
                "id": int(run.get("run_id") or _stable_run_id(run_key or f"scan_task_{task.id}_{run.get('index') or 0}")),
                "run_id": int(run.get("run_id") or 0),
                "run_key": run_key,
                "batch_key": str(task.strategy_name or "traditional_value_exit"),
                "status": str(task.status or "success"),
                "source": "scan",
                "task_id": int(task.id),
                "task_key": task.task_key,
                "strategy_name": task.strategy_name,
                "combo_index": run.get("index"),
                "start_date": str(params_payload.get("start_date") or ""),
                "end_date": str(params_payload.get("end_date") or ""),
                "created_at": str(run.get("created_at") or _format_dt(task.created_at) or ""),
                "updated_at": str(run.get("updated_at") or _format_dt(task.updated_at) or ""),
                "summary": summary_payload,
                "params": params_payload,
            })

    rows.sort(key=lambda row: str((row or {}).get("updated_at") or ""), reverse=True)
    total = len(rows)
    return rows[offset:offset + limit], total, None


def _load_archived_db_run_rows(strategy_names):
    archive_root = Path(settings.BASE_DIR) / "output" / "archive"
    if not archive_root.exists() or not archive_root.is_dir():
        return []

    rows = []
    for file_path in archive_root.glob("db_backtest_runs_cleanup_*/traditional_backtest_runs.json"):
        payload = _safe_read_json(file_path)
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("strategy_name") or "") not in set(strategy_names):
                continue
            rows.append(_build_run_row_from_archive_dict(item))
    return rows


def _coerce_positive_float_or_none(value):
    try:
        parsed = float(value)
        if math.isfinite(parsed) and parsed > 0:
            return parsed
    except (TypeError, ValueError):
        return None
    return None


def _extract_account_capitals(summary):
    summary_payload = summary if isinstance(summary, dict) else {}
    initial = (
        summary_payload.get("starting_capital")
        if summary_payload.get("starting_capital") not in (None, "")
        else summary_payload.get("initial_capital")
    )
    if initial in (None, ""):
        initial = summary_payload.get("initial_cash")

    ending = (
        summary_payload.get("ending_capital")
        if summary_payload.get("ending_capital") not in (None, "")
        else summary_payload.get("final_capital")
    )
    if ending in (None, ""):
        ending = summary_payload.get("final_asset")

    return _coerce_positive_float_or_none(initial), _coerce_positive_float_or_none(ending)


@api_view(["GET"])
def list_traditional_backtest_runs(request):
    try:
        limit = int(request.GET.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 200))
    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    kind = str(request.GET.get("kind") or "manual").strip().lower()
    account_only = str(request.GET.get("account_only") or "").strip().lower() in {"1", "true", "yes"}
    include_archive = str(request.GET.get("include_archive") or "0").strip().lower() in {"1", "true", "yes", "on"}

    if kind == "scan":
        rows, total, warning = _collect_scan_backtest_rows(limit=limit, offset=offset)
        payload = {"ok": True, "data": rows, "total": total}
        if warning:
            payload["warning"] = warning
        return Response(payload)

    rows, total = _collect_manual_backtest_rows(
        limit=limit,
        offset=offset,
        account_only=account_only,
        include_archive=include_archive,
    )
    return Response({"ok": True, "data": rows, "total": total})


@api_view(["GET"])
def list_traditional_backtest_templates(_request):
    rows = []
    for key, params in TRADITIONAL_TEMPLATE_MAP.items():
        rows.append(
            {
                "template_id": key,
                "template_name": key,
                "params": params,
            }
        )
    return Response({"ok": True, "data": rows, "total": len(rows)})


@api_view(["POST"])
def run_traditional_backtest(request):
    payload = request.data if isinstance(request.data, dict) else {}
    template_id = str(payload.get("template_id") or "").strip()
    template_params = TRADITIONAL_TEMPLATE_MAP.get(template_id, {}) if template_id else {}
    merged_payload = dict(template_params)
    merged_payload.update(payload)

    mode = str(merged_payload.get("mode") or "account").strip().lower()
    if mode not in {"signal", "account"}:
        return Response({"ok": False, "error": "mode must be signal or account"}, status=400)

    try:
        start_date = _parse_date_or_raise(merged_payload.get("start_date") or "2025-01-01", "start_date")
        end_date = _parse_date_or_raise(merged_payload.get("end_date") or "2025-12-31", "end_date")
        if start_date > end_date:
            raise ValueError("start_date must be <= end_date")

        scope = str(merged_payload.get("scope") or "ALL").strip().upper()
        market = str(merged_payload.get("market") or "CN").strip().upper()
        risk_level = str(merged_payload.get("risk_level") or "LOW").strip().upper()
        valuation_variant = str(merged_payload.get("valuation_variant") or "").strip()
        risk_variant_policy = str(merged_payload.get("risk_variant_policy") or "any").strip().lower()
        financial_filter_mode = str(merged_payload.get("financial_filter_mode") or "all").strip().lower()

        band_pct = float(merged_payload.get("valuation_band_pct") or merged_payload.get("band_pct") or 0.1)
        min_score = float(merged_payload.get("min_score") or 90)
        min_netprofit_yoy = merged_payload.get("min_netprofit_yoy")
        min_ebit_yoy = merged_payload.get("min_ebit_yoy")
        require_positive_prev_netprofit = _parse_bool_or_default(merged_payload.get("require_positive_prev_netprofit"), True)
        require_positive_prev_ebit = _parse_bool_or_default(merged_payload.get("require_positive_prev_ebit"), True)
        take_profit_mode = str(merged_payload.get("take_profit_mode") or "fixed").strip().lower()
        take_profit_tiers = _parse_take_profit_tiers(merged_payload.get("take_profit_tiers"))
        trend_take_profit_enabled = _parse_bool_or_default(merged_payload.get("trend_take_profit_enabled"), False)
        trend_position_pct = float(merged_payload.get("trend_position_pct") or 0.0)
        trend_activation_profit = float(merged_payload.get("trend_activation_profit") or 0.0)
        trend_ma_period = _parse_int_or_default(merged_payload.get("trend_ma_period"), 20)
        trend_confirm_days = _parse_int_or_default(merged_payload.get("trend_confirm_days"), 2)
        take_profit_pct = max(0.0, float(merged_payload.get("take_profit_pct") or 0.0))
        stop_loss_mode = str(merged_payload.get("stop_loss_mode") or "fixed").strip().lower()
        stop_loss_pct = max(0.0, float(merged_payload.get("stop_loss_pct") or 0.0))
        trailing_stop_pct = max(0.0, float(merged_payload.get("trailing_stop_pct") or 0.0))
        stop_loss_scope = str(merged_payload.get("stop_loss_scope") or "position").strip().lower()
        apply_moneyflow_filters = _parse_bool_or_default(merged_payload.get("apply_moneyflow_filters"), False)
        moneyflow_net_inflow_days_window = _parse_int_or_default(merged_payload.get("moneyflow_net_inflow_days_window"), 10)
        disable_target_hit = _parse_bool_or_default(merged_payload.get("disable_target_hit"), False)
        if stop_loss_scope not in {"position", "account"}:
            raise ValueError("stop_loss_scope must be position or account")
        if trend_position_pct < 0 or trend_position_pct > 1:
            raise ValueError("trend_position_pct must be within [0, 1]")
        if trend_activation_profit < 0 or trend_activation_profit > 1:
            raise ValueError("trend_activation_profit must be within [0, 1]")
        _validate_take_profit_allocation(
            take_profit_mode=take_profit_mode,
            take_profit_tiers=take_profit_tiers,
            trend_take_profit_enabled=trend_take_profit_enabled,
            trend_position_pct=trend_position_pct,
        )

        output_json = str(merged_payload.get("output_json") or "").strip()
        if not output_json:
            strategy_name = "traditional_value_exit_account" if mode == "account" else "traditional_value_exit"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path(settings.BASE_DIR) / "output" / "backtests" / strategy_name / f"{strategy_name}_{start_date.isoformat()}_{end_date.isoformat()}_api_{timestamp}.json"
            output_json = str(output_path)

        common_kwargs = {
            "scope": scope,
            "market": market,
            "start_date": start_date,
            "end_date": end_date,
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
            "take_profit_pct": take_profit_pct,
            "stop_loss_mode": stop_loss_mode,
            "stop_loss_pct": stop_loss_pct,
            "trailing_stop_pct": trailing_stop_pct,
            "stop_loss_scope": stop_loss_scope,
            "apply_moneyflow_filters": apply_moneyflow_filters,
            "moneyflow_net_inflow_days_window": moneyflow_net_inflow_days_window,
            "disable_target_hit": disable_target_hit,
            "output_json": output_json,
            "stdout": None,
        }

        if mode == "account":
            summary, output_path = run_traditional_value_exit_account_backtest(
                **common_kwargs,
                starting_capital=float(merged_payload.get("starting_capital") or 200000.0),
                commission_rate=float(merged_payload.get("commission_rate") or 0.0005),
                valuation_source=str(merged_payload.get("valuation_source") or "history").strip().lower(),
                entry_date_source=str(merged_payload.get("entry_date_source") or "history").strip().lower(),
                entry_end_date=_parse_date_or_raise(merged_payload.get("entry_end_date"), "entry_end_date") if merged_payload.get("entry_end_date") else None,
                max_buy_per_day=int(merged_payload.get("max_buy_per_day") or 3),
                max_position_pct=float(merged_payload.get("max_position_pct") or 0.2),
                buy_weight_ladder=merged_payload.get("buy_weight_ladder") or [],
                first_entry_pct=float(merged_payload.get("first_entry_pct") or 0.1),
                add_on_drop_pct=float(merged_payload.get("add_on_drop_pct") or 0.0),
                add_on_entry_pct=float(merged_payload.get("add_on_entry_pct") or 0.0),
                add_on2_drop_pct=float(merged_payload.get("add_on2_drop_pct") or 0.0),
                max_holding_days=int(merged_payload.get("max_holding_days") or 0),
                add_on2_fill_remaining=bool(merged_payload.get("add_on2_fill_remaining")),
                disable_eop_exit=bool(merged_payload.get("disable_eop_exit")),
                priority_policy=str(merged_payload.get("priority_policy") or "score_desc").strip().lower(),
            )
        else:
            summary, output_path = run_traditional_value_exit_backtest(
                **common_kwargs,
                progress_every=max(1, int(merged_payload.get("progress_every") or 50)),
            )

        run_key = Path(output_path).stem
        run_obj = TraditionalBacktestRun.objects.filter(run_key=run_key).first()
        return Response(
            {
                "ok": True,
                "run_id": int(run_obj.id) if run_obj is not None else None,
                "run_key": run_key,
                "summary": summary.get("account") or summary.get("combined") or {},
                "output_file": str(output_path),
            }
        )
    except (ValueError, TypeError) as exc:
        return Response({"ok": False, "error": str(exc)}, status=400)


execute_traditional_backtest = run_traditional_backtest


@api_view(["POST"])
def submit_traditional_backtest_scan(request):
    payload = request.data if isinstance(request.data, dict) else {}
    template_id = str(payload.get("template_id") or "").strip()
    template_params = TRADITIONAL_TEMPLATE_MAP.get(template_id, {}) if template_id else {}

    base_params = dict(template_params)
    base_params.update(payload.get("base_params") or {})
    scan_grid = payload.get("scan_grid") or {}
    combos = _parse_scan_grid(scan_grid)

    max_jobs = 120
    if len(combos) > max_jobs:
        return Response(
            {
                "ok": False,
                "error": f"scan combinations too many: {len(combos)} > {max_jobs}",
            },
            status=400,
        )

    strategy_name = "traditional_value_exit"
    requested_mode = str(base_params.get("mode") or "account").strip().lower()
    if requested_mode == "account":
        strategy_name = "traditional_value_exit_account"

    try:
        task = TraditionalBacktestScanTask.objects.create(
            task_key=_build_task_key(),
            status="pending",
            strategy_name=strategy_name,
            total_jobs=len(combos),
            completed_jobs=0,
            failed_jobs=0,
            params_json={
                "template_id": template_id or None,
                "base_params": base_params,
                "scan_grid": scan_grid,
                "combinations": len(combos),
            },
            result_json={"runs": [], "failures": []},
            error_message="",
        )
    except (ProgrammingError, OperationalError):
        return Response({"ok": False, "error": _SCAN_TASK_TABLE_MISSING_HINT}, status=503)

    _SCAN_EXECUTOR.submit(_execute_scan_task, int(task.id), base_params, combos)

    return Response(
        {
            "ok": True,
            "task_id": int(task.id),
            "task_key": task.task_key,
            "status": task.status,
            "total_jobs": int(task.total_jobs),
        }
    )


@api_view(["GET"])
def list_traditional_backtest_scan_tasks(request):
    try:
        limit = int(request.GET.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    try:
        queryset = TraditionalBacktestScanTask.objects.order_by("-updated_at", "-id")[:limit]
        rows = [_serialize_scan_task(item) for item in queryset]
    except (ProgrammingError, OperationalError):
        return Response({"ok": True, "data": [], "total": 0, "warning": _SCAN_TASK_TABLE_MISSING_HINT})
    return Response({"ok": True, "data": rows, "total": len(rows)})


@api_view(["GET"])
def get_traditional_backtest_scan_task_detail(_request, task_id: int):
    try:
        task = TraditionalBacktestScanTask.objects.filter(id=task_id).first()
    except (ProgrammingError, OperationalError):
        return Response({"ok": False, "error": _SCAN_TASK_TABLE_MISSING_HINT}, status=503)
    if task is None:
        return Response({"ok": False, "error": "task not found"}, status=404)
    return Response({"ok": True, "data": _serialize_scan_task(task)})


@api_view(["GET"])
def get_traditional_backtest_run_detail(_request, run_id: int):
    payload = _resolve_run_payload(run_id=run_id)
    if payload is None:
        return Response({"ok": False, "error": "run not found"}, status=404)

    replay_params = _build_replay_params(payload)
    return Response({"ok": True, **payload, "replay_params": replay_params})


@api_view(["GET"])
def list_traditional_backtest_run_stocks(_request, run_id: int):
    payload = _resolve_run_payload(run_id=run_id)
    if payload is None:
        return Response({"ok": False, "error": "run not found"}, status=404)

    sample_trades = (payload.get("result") or {}).get("sample_trades")
    trade_rows = sample_trades if isinstance(sample_trades, list) else []
    stock_rows = _summarize_trades_by_stock(trade_rows)

    return Response(
        {
            "ok": True,
            "run_id": int(payload.get("run_id")),
            "run_key": payload.get("run_key"),
            "data": stock_rows,
            "total": len(stock_rows),
        }
    )


def _build_buyable_universe_rows(payload, max_rows: int = 500, force_recompute: bool = False):
    result_payload = payload.get("result") if isinstance(payload, dict) else {}
    cached_rows = (result_payload or {}).get("buy_candidates_summary") if isinstance(result_payload, dict) else None
    if not force_recompute and isinstance(cached_rows, list):
        normalized = []
        for row in cached_rows:
            if not isinstance(row, dict):
                continue
            normalized.append(
                {
                    "ts_code": str(row.get("ts_code") or "").strip().upper(),
                    "stock_name": str(row.get("stock_name") or "").strip(),
                    "hit_count": int(row.get("hit_count") or 0),
                    "first_hit_date": row.get("first_hit_date"),
                    "last_hit_date": row.get("last_hit_date"),
                    "latest_entry_price": round(float(row.get("latest_entry_price") or 0.0), 4),
                    "latest_conservative_price": round(float(row.get("latest_conservative_price") or 0.0), 4),
                    "best_discount_pct": round(float(row.get("best_discount_pct") or 0.0), 4),
                    "max_score": round(float(row.get("max_score") or 0.0), 2),
                }
            )
        if normalized:
            normalized.sort(
                key=lambda row: (
                    -int(row.get("hit_count") or 0),
                    -float(row.get("max_score") or 0.0),
                    -float(row.get("best_discount_pct") or 0.0),
                    str(row.get("ts_code") or ""),
                )
            )
            return normalized[:max_rows]

    strategy_payload = (result_payload or {}).get("strategy") if isinstance(result_payload, dict) else {}
    params_payload = payload.get("params") if isinstance(payload, dict) else {}
    merged_raw = {}
    if isinstance(params_payload, dict):
        merged_raw.update(params_payload)
    if isinstance(strategy_payload, dict):
        merged_raw.update(strategy_payload)

    params = _normalize_run_request(merged_raw)
    allowed_risk_levels = _normalize_risk_levels(params.get("risk_level"))
    if not allowed_risk_levels:
        return []

    if params["entry_date_source"] == "history":
        entry_dates = _resolve_history_entry_dates(
            scope=params["scope"],
            market=params["market"],
            start_date=params["start_date"],
            end_date=params["end_date"],
        )
    else:
        entry_dates = _resolve_entry_dates(
            scope=params["scope"],
            start_date=params["start_date"],
            end_date=params["end_date"],
            snapshot_only=True,
            rebalance_step=1,
        )
    if params["entry_end_date"] is not None:
        entry_dates = [trade_date for trade_date in entry_dates if trade_date is not None and trade_date <= params["entry_end_date"]]
    entry_dates = sorted([trade_date for trade_date in entry_dates if trade_date is not None])
    if not entry_dates:
        return []

    price_history = _build_price_history(
        scope=params["scope"],
        start_date=params["start_date"],
        end_date=params["end_date"],
        freq="D",
    )
    if not price_history:
        return []

    date_price_map = _build_date_price_map(price_history)
    latest_risk_map = {}
    risk_map = _build_risk_map(
        entry_dates=entry_dates,
        market=params["market"],
        valuation_variant=params["valuation_variant"] if params["risk_variant_policy"] == "specific" else None,
    )
    financial_filters_enabled = (
        params["min_netprofit_yoy"] is not None
        or params["min_ebit_yoy"] is not None
        or params["require_positive_prev_netprofit"]
        or params["require_positive_prev_ebit"]
    )
    financial_panel_map = _load_financial_panel_map(price_history.keys(), params["end_date"]) if financial_filters_enabled else {}
    financial_metric_cache = {}

    agg_map = {}
    for trade_date in entry_dates:
        date_prices = date_price_map.get(trade_date, {})
        ts_codes = sorted(date_prices.keys())
        if not ts_codes:
            continue
        if params["valuation_source"] == "history":
            method_map = _build_history_method_map(ts_codes=ts_codes, trade_date=trade_date, market=params["market"])
        else:
            method_map = _build_snapshot_method_map(ts_codes=ts_codes, trade_date=trade_date, market=params["market"])

        for ts_code in ts_codes:
            current_price = _safe_price(date_prices.get(ts_code))
            if current_price is None:
                continue

            summary = _summarize_buy_candidate(
                current_price=current_price,
                method_map=method_map.get(ts_code, {}),
                band_pct=params["band_pct"],
            )
            if not summary.get("buy_candidate"):
                continue

            score = summary.get("undervalue_score")
            conservative_price = _safe_price(summary.get("conservative_valuation_price"))
            composite_price = _safe_price(summary.get("composite_valuation_price"))
            if score is None or float(score) < float(params["min_score"]):
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
                "legacy",
            )
            if params["risk_variant_policy"] == "specific":
                passes_risk = risk_alignment["matched_risk_level"] in allowed_risk_levels
            else:
                passes_risk = any(level in risk_alignment["risk_levels"] for level in allowed_risk_levels)
            if not passes_risk:
                continue

            financial_payload = None
            if financial_filters_enabled:
                financial_payload = _resolve_financial_metrics(
                    financial_panel_map=financial_panel_map,
                    ts_code=ts_code,
                    trade_date=trade_date,
                    cache=financial_metric_cache,
                )
                if not _passes_financial_filters(
                    financial_payload,
                    min_netprofit_yoy=params["min_netprofit_yoy"],
                    min_ebit_yoy=params["min_ebit_yoy"],
                    financial_filter_mode=params["financial_filter_mode"],
                    require_positive_prev_netprofit=params["require_positive_prev_netprofit"],
                    require_positive_prev_ebit=params["require_positive_prev_ebit"],
                ):
                    continue

            discount_pct = ((float(conservative_price) / float(current_price)) - 1.0) * 100.0 if float(current_price) > 0 else 0.0
            entry = agg_map.setdefault(
                ts_code,
                {
                    "ts_code": ts_code,
                    "hit_count": 0,
                    "first_hit_date": trade_date,
                    "last_hit_date": trade_date,
                    "latest_entry_price": float(current_price),
                    "latest_conservative_price": float(conservative_price),
                    "best_discount_pct": float(discount_pct),
                    "max_score": float(score),
                },
            )
            entry["hit_count"] += 1
            entry["first_hit_date"] = min(entry["first_hit_date"], trade_date)
            entry["last_hit_date"] = max(entry["last_hit_date"], trade_date)
            entry["latest_entry_price"] = float(current_price)
            entry["latest_conservative_price"] = float(conservative_price)
            entry["best_discount_pct"] = max(float(entry.get("best_discount_pct") or 0.0), float(discount_pct))
            entry["max_score"] = max(float(entry.get("max_score") or 0.0), float(score))

    if not agg_map:
        return []

    code_list = list(agg_map.keys())
    name_map = {
        str(row.get("ts_code") or "").strip().upper(): str(row.get("name") or "").strip()
        for row in Corporation.objects.filter(ts_code__in=code_list).values("ts_code", "name")
    }

    rows = []
    for ts_code, item in agg_map.items():
        rows.append(
            {
                "ts_code": ts_code,
                "stock_name": name_map.get(ts_code, ""),
                "hit_count": int(item.get("hit_count") or 0),
                "first_hit_date": item.get("first_hit_date").isoformat() if item.get("first_hit_date") else None,
                "last_hit_date": item.get("last_hit_date").isoformat() if item.get("last_hit_date") else None,
                "latest_entry_price": round(float(item.get("latest_entry_price") or 0.0), 4),
                "latest_conservative_price": round(float(item.get("latest_conservative_price") or 0.0), 4),
                "best_discount_pct": round(float(item.get("best_discount_pct") or 0.0), 4),
                "max_score": round(float(item.get("max_score") or 0.0), 2),
            }
        )

    rows.sort(key=lambda row: (-int(row.get("hit_count") or 0), -float(row.get("max_score") or 0.0), -float(row.get("best_discount_pct") or 0.0), str(row.get("ts_code") or "")))
    return rows[:max_rows]


@api_view(["GET"])
def list_traditional_backtest_run_buy_candidates(request, run_id: int):
    payload = _resolve_run_payload(run_id=run_id)
    if payload is None:
        return Response({"ok": False, "error": "run not found"}, status=404)

    try:
        limit = int(request.GET.get("limit", 500))
    except (TypeError, ValueError):
        limit = 500
    limit = max(50, min(limit, 3000))
    force_recompute = _parse_bool_or_default(request.GET.get("force_recompute"), default=False)

    rows = _build_buyable_universe_rows(payload, max_rows=limit, force_recompute=force_recompute)

    return Response(
        {
            "ok": True,
            "run_id": int(payload.get("run_id")),
            "run_key": payload.get("run_key"),
            "force_recompute": force_recompute,
            "data": rows,
            "total": len(rows),
        }
    )


@api_view(["GET"])
def get_traditional_backtest_run_stock_detail(request, run_id: int, ts_code: str):
    payload = _resolve_run_payload(run_id=run_id)
    if payload is None:
        return Response({"ok": False, "error": "run not found"}, status=404)

    normalized_code = str(ts_code or "").strip().upper()
    if not normalized_code:
        return Response({"ok": False, "error": "ts_code is required"}, status=400)

    result_payload = payload.get("result") or {}
    sample_trades = result_payload.get("sample_trades") if isinstance(result_payload, dict) else []
    trade_rows = [
        item for item in (sample_trades if isinstance(sample_trades, list) else [])
        if str((item or {}).get("ts_code") or "").strip().upper() == normalized_code
    ]
    trade_rows.sort(key=lambda item: (str(item.get("entry_date") or ""), str(item.get("exit_date") or "")))

    markers = _build_trade_markers(trade_rows)
    candidate_markers = _build_buy_candidate_markers(payload, normalized_code)
    valuation_history = []
    stats = {}

    if trade_rows:
        entry_dates = [_parse_iso_date_optional(item.get("entry_date")) for item in trade_rows]
        exit_dates = [_parse_iso_date_optional(item.get("exit_date")) for item in trade_rows]
        valid_entry_dates = [d for d in entry_dates if d is not None]
        valid_exit_dates = [d for d in exit_dates if d is not None]
        if not valid_entry_dates or not valid_exit_dates:
            return Response({"ok": False, "error": "invalid trade dates in sample_trades"}, status=400)
    else:
        candidate_markers = _build_buy_candidate_markers(payload, normalized_code)
        if not candidate_markers:
            return Response({"ok": False, "error": "no trades or buy candidates for ts_code"}, status=404)
        markers = candidate_markers
        valid_entry_dates = [_parse_iso_date_optional(item.get("trade_date")) for item in candidate_markers]
        valid_entry_dates = [d for d in valid_entry_dates if d is not None]
        valid_exit_dates = list(valid_entry_dates)

    lookback_days = max(10, min(180, int(request.GET.get("lookback_days", 40))))
    forward_days = max(5, min(120, int(request.GET.get("forward_days", 20))))
    start_date = min(valid_entry_dates) - timedelta(days=lookback_days)
    end_date = max(valid_exit_dates) + timedelta(days=forward_days)
    end_date = max(end_date, date(2025, 12, 31))

    kline_rows = _load_kline_rows(normalized_code, start_date=start_date, end_date=end_date)
    stats = _compute_backtesting_stats(kline_rows=kline_rows, trades=trade_rows)
    if not trade_rows:
        stats = {
            **(stats or {}),
            "mode": "buy_candidate_only",
            "warning": "仅展示策略可买触发点，无实际成交交易。",
        }
    stock_name = _load_stock_name(normalized_code)
    if trade_rows:
        valuation_history = _build_valuation_history(normalized_code, start_date=start_date, end_date=end_date)
    if candidate_markers:
        markers.extend(candidate_markers)

    return Response(
        {
            "ok": True,
            "run_id": int(payload.get("run_id")),
            "run_key": payload.get("run_key"),
            "ts_code": normalized_code,
            "stock_name": stock_name,
            "range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "kline": kline_rows,
            "trades": trade_rows,
            "markers": markers,
            "stats": stats,
            "valuation_history": valuation_history,
        }
    )
