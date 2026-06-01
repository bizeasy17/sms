from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import EarningsBacktestRun, EarningsSignalSnapshot, EarningsSignalSnapshotHistory, FinancialIncomeRecord
from .services import EarningsForecastPipeline, run_predictive_valuation_backtest


def _resolve_config_path(request) -> Path:
    override = request.GET.get("config") or request.POST.get("config")
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    default_path = getattr(settings, "EARNINGS_CONFIG_PATH", "configs/default.yaml")
    path = Path(default_path)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    return path


@require_GET
def health(_request):
    return JsonResponse({"ok": True, "service": "tushare_earnings_service"})


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_end_date_token(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _to_prev_year_end_date(value: str | None) -> str:
    normalized = _normalize_end_date_token(value)
    if not normalized:
        return ""
    try:
        dt = datetime.strptime(normalized, "%Y-%m-%d")
        return dt.replace(year=dt.year - 1).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _normalize_end_date_candidates(value: str | None) -> set[str]:
    normalized = _normalize_end_date_token(value)
    if not normalized:
        return set()
    return {normalized, normalized.replace("-", "")}


def _lookup_prev_year_income_sign(ts_code: str, financial_end_date: str | None) -> bool | None:
    prev_year_end_date = _to_prev_year_end_date(financial_end_date)
    if not prev_year_end_date:
        return None

    rows = FinancialIncomeRecord.objects.filter(
        ts_code=str(ts_code or "").upper(),
        end_date__in=list(_normalize_end_date_candidates(prev_year_end_date)),
    ).values("ann_date", "n_income", "n_income_attr_p").order_by("-ann_date")

    row = rows.first()
    if not row:
        return None
    n_income = _to_float_or_none(row.get("n_income"))
    if n_income is None:
        n_income = _to_float_or_none(row.get("n_income_attr_p"))
    if n_income is None:
        return None
    return bool(n_income >= 0)


def _build_prev_year_income_sign_map(snapshots: list[EarningsSignalSnapshot]) -> dict[tuple[str, str], bool | None]:
    lookup_keys: set[tuple[str, str]] = set()
    ts_codes: set[str] = set()
    prev_date_tokens: set[str] = set()

    for snap in snapshots:
        raw = snap.raw_result or {}
        prev_end = _to_prev_year_end_date(raw.get("financial_end_date") if isinstance(raw, dict) else "")
        if not prev_end:
            continue
        key = (str(snap.ts_code or "").upper(), prev_end)
        lookup_keys.add(key)
        ts_codes.add(key[0])
        prev_date_tokens.add(prev_end)
        prev_date_tokens.add(prev_end.replace("-", ""))

    if not lookup_keys:
        return {}

    rows = FinancialIncomeRecord.objects.filter(
        ts_code__in=list(ts_codes),
        end_date__in=list(prev_date_tokens),
    ).values("ts_code", "end_date", "ann_date", "n_income", "n_income_attr_p")

    latest_map: dict[tuple[str, str], tuple[str, float | None]] = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "").upper()
        end_date = _normalize_end_date_token(row.get("end_date"))
        if not ts_code or not end_date:
            continue
        key = (ts_code, end_date)
        ann_date = str(row.get("ann_date") or "")
        n_income = _to_float_or_none(row.get("n_income"))
        if n_income is None:
            n_income = _to_float_or_none(row.get("n_income_attr_p"))
        current = latest_map.get(key)
        if current is None or ann_date > current[0]:
            latest_map[key] = (ann_date, n_income)

    out: dict[tuple[str, str], bool | None] = {}
    for key in lookup_keys:
        value = latest_map.get(key)
        if value is None or value[1] is None:
            out[key] = None
            continue
        out[key] = bool(value[1] >= 0)
    return out


def _normalize_report_type(value, allow_all: bool = False) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return "ALL" if allow_all else ""
    alias = {
        "ANNUAL": "FY",
        "FULL_YEAR": "FY",
        "A": "FY",
    }
    normalized = alias.get(text, text)
    valid = {"Q1", "H1", "Q3", "FY", "FUSION"}
    if allow_all:
        valid.add("ALL")
    return normalized if normalized in valid else ("ALL" if allow_all else "")


def _snapshot_to_payload(snapshot: EarningsSignalSnapshot, prev_year_income_sign_map: dict[tuple[str, str], bool | None] | None = None) -> dict:
    explain = snapshot.explain or {}
    raw_result = snapshot.raw_result or {}
    quant_target = raw_result.get("quantitative_target") if isinstance(raw_result, dict) else None
    financial_end_date = raw_result.get("financial_end_date") if isinstance(raw_result, dict) else None
    prev_year_end_date = _to_prev_year_end_date(financial_end_date)
    prev_year_netprofit_non_negative = None
    if prev_year_income_sign_map is not None and prev_year_end_date:
        prev_year_netprofit_non_negative = prev_year_income_sign_map.get((str(snapshot.ts_code or "").upper(), prev_year_end_date))
    return {
        "ts_code": snapshot.ts_code,
        "report_type": str(snapshot.report_type or "UNKNOWN").upper(),
        "pred_earnings_growth": _to_float_or_none(raw_result.get("pred_earnings_growth")) if isinstance(raw_result, dict) else None,
        "signal_score": _to_float_or_none(snapshot.signal_score),
        "target_return_pct": _to_float_or_none(snapshot.target_return_pct),
        "target_price": _to_float_or_none(snapshot.target_price),
        "target_market_cap": _to_float_or_none(snapshot.target_market_cap),
        "action": str(snapshot.action or "HOLD").upper(),
        "risk_level": str(snapshot.risk_level or "MEDIUM").upper(),
        "model_version": snapshot.model_version or None,
        "trade_date": snapshot.asof_date.isoformat() if snapshot.asof_date else None,
        "feature_data_source": snapshot.feature_data_source or None,
        "financial_fiscal_year": raw_result.get("financial_fiscal_year") if isinstance(raw_result, dict) else None,
        "financial_ann_date": raw_result.get("financial_ann_date") if isinstance(raw_result, dict) else None,
        "financial_end_date": financial_end_date,
        "prev_year_netprofit_non_negative": prev_year_netprofit_non_negative,
        "valuation_mapping": {
            "stance": explain.get("stance") or str(snapshot.action or "HOLD").upper(),
            "confidence": explain.get("confidence") or "LOW",
            "prob_component": _to_float_or_none(explain.get("prob_component")),
            "earnings_component": _to_float_or_none(explain.get("earnings_component")),
        },
        "quantitative_target": quant_target if isinstance(quant_target, dict) else {},
        "be_payload": {
            "signal_score": _to_float_or_none(snapshot.signal_score),
            "target_return_pct": _to_float_or_none(snapshot.target_return_pct),
            "target_price": _to_float_or_none(snapshot.target_price),
            "target_market_cap": _to_float_or_none(snapshot.target_market_cap),
            "action": str(snapshot.action or "HOLD").upper(),
            "risk_level": str(snapshot.risk_level or "MEDIUM").upper(),
        },
    }


def _history_to_payload(snapshot: EarningsSignalSnapshotHistory) -> dict:
    explain = snapshot.explain or {}
    raw_result = snapshot.raw_result or {}
    quant_target = raw_result.get("quantitative_target") if isinstance(raw_result, dict) else None
    financial_end_date = (
        raw_result.get("financial_end_date") if isinstance(raw_result, dict) else None
    ) or snapshot.financial_end_date
    prev_year_netprofit_non_negative = _lookup_prev_year_income_sign(snapshot.ts_code, financial_end_date)

    return {
        "ts_code": snapshot.ts_code,
        "report_type": str(snapshot.report_type or "UNKNOWN").upper(),
        "pred_earnings_growth": _to_float_or_none(raw_result.get("pred_earnings_growth")) if isinstance(raw_result, dict) else None,
        "signal_score": _to_float_or_none(snapshot.signal_score),
        "target_return_pct": _to_float_or_none(snapshot.target_return_pct),
        "target_price": _to_float_or_none(snapshot.target_price),
        "target_market_cap": _to_float_or_none(snapshot.target_market_cap),
        "action": str(snapshot.action or "HOLD").upper(),
        "risk_level": str(snapshot.risk_level or "MEDIUM").upper(),
        "model_version": snapshot.model_version or None,
        "trade_date": snapshot.asof_date.isoformat() if snapshot.asof_date else None,
        "feature_data_source": snapshot.feature_data_source or None,
        "financial_fiscal_year": raw_result.get("financial_fiscal_year") if isinstance(raw_result, dict) else snapshot.financial_fiscal_year,
        "financial_ann_date": raw_result.get("financial_ann_date") if isinstance(raw_result, dict) else snapshot.financial_ann_date,
        "financial_end_date": financial_end_date,
        "prev_year_netprofit_non_negative": prev_year_netprofit_non_negative,
        "valuation_mapping": {
            "stance": explain.get("stance") or str(snapshot.action or "HOLD").upper(),
            "confidence": explain.get("confidence") or "LOW",
            "prob_component": _to_float_or_none(explain.get("prob_component")),
            "earnings_component": _to_float_or_none(explain.get("earnings_component")),
        },
        "quantitative_target": quant_target if isinstance(quant_target, dict) else {},
        "be_payload": {
            "signal_score": _to_float_or_none(snapshot.signal_score),
            "target_return_pct": _to_float_or_none(snapshot.target_return_pct),
            "target_price": _to_float_or_none(snapshot.target_price),
            "target_market_cap": _to_float_or_none(snapshot.target_market_cap),
            "action": str(snapshot.action or "HOLD").upper(),
            "risk_level": str(snapshot.risk_level or "MEDIUM").upper(),
        },
    }


def _select_payload_by_financial_end_date(ts_code: str, report_type: str, financial_end_date: str | None, snapshots: list[EarningsSignalSnapshot] | None = None, prev_year_income_sign_map: dict[tuple[str, str], bool | None] | None = None) -> dict | None:
    target_end_date = _normalize_end_date_token(financial_end_date)
    if not target_end_date:
        return None

    for snapshot in snapshots or []:
        raw_result = snapshot.raw_result or {}
        snapshot_end_date = _normalize_end_date_token(raw_result.get("financial_end_date") if isinstance(raw_result, dict) else None)
        if snapshot_end_date == target_end_date:
            return _snapshot_to_payload(snapshot, prev_year_income_sign_map)

    history_qs = EarningsSignalSnapshotHistory.objects.filter(
        ts_code=str(ts_code or "").strip().upper(),
        report_type=str(report_type or "").strip().upper(),
    ).order_by("-created_at")

    history_row = history_qs.filter(
        financial_end_date__in=list(_normalize_end_date_candidates(target_end_date)),
    ).first()
    if history_row is not None:
        return _history_to_payload(history_row)

    for history_row in history_qs[:50]:
        raw_result = history_row.raw_result or {}
        history_end_date = _normalize_end_date_token(
            (raw_result.get("financial_end_date") if isinstance(raw_result, dict) else None)
            or history_row.financial_end_date
        )
        if history_end_date == target_end_date:
            return _history_to_payload(history_row)
    return None


def _build_fusion_payload_from_snapshots(snapshots: list[EarningsSignalSnapshot]) -> dict | None:
    target_rts = ["Q1", "H1", "Q3", "FY"]
    by_rt = {}
    for snap in snapshots:
        rt = str(snap.report_type or "").upper()
        if rt in target_rts and rt not in by_rt:
            by_rt[rt] = snap
    if not by_rt:
        return None

    base_weights = {"Q1": 0.9, "H1": 1.0, "Q3": 1.1, "FY": 1.0}
    valid = []
    for rt in target_rts:
        snap = by_rt.get(rt)
        if snap is None:
            continue
        valid.append((rt, snap, float(base_weights.get(rt, 1.0))))
    if not valid:
        return None

    weight_sum = sum(item[2] for item in valid)
    if weight_sum <= 0:
        weight_sum = float(len(valid))

    def _weighted(attr: str):
        acc = 0.0
        used = 0.0
        for _, snap, w in valid:
            val = _to_float_or_none(getattr(snap, attr, None))
            if val is None:
                continue
            nw = w / weight_sum
            acc += nw * val
            used += nw
        if used <= 0:
            return None
        return acc / used

    score = _weighted("signal_score")
    target_return_pct = _weighted("target_return_pct")
    target_price = _weighted("target_price")
    target_market_cap = _weighted("target_market_cap")

    pred_growth_acc = 0.0
    pred_growth_used = 0.0
    for _, snap, w in valid:
        raw = snap.raw_result or {}
        pred_growth = _to_float_or_none(raw.get("pred_earnings_growth")) if isinstance(raw, dict) else None
        if pred_growth is None:
            continue
        nw = w / weight_sum
        pred_growth_acc += nw * pred_growth
        pred_growth_used += nw
    pred_earnings_growth = (pred_growth_acc / pred_growth_used) if pred_growth_used > 0 else None

    if score is None:
        action = "HOLD"
        risk = "MEDIUM"
    elif score >= 65:
        action = "BUY"
        risk = "LOW"
    elif score >= 50:
        action = "HOLD"
        risk = "MEDIUM"
    else:
        action = "SELL_PART"
        risk = "HIGH"

    return {
        "ts_code": valid[0][1].ts_code,
        "report_type": "FUSION",
        "pred_earnings_growth": pred_earnings_growth,
        "signal_score": score,
        "target_return_pct": target_return_pct,
        "target_price": target_price,
        "target_market_cap": target_market_cap,
        "action": action,
        "risk_level": risk,
        "model_version": "fusion",
        "trade_date": None,
        "feature_data_source": "fusion_from_snapshot",
        "financial_fiscal_year": None,
        "financial_ann_date": None,
        "financial_end_date": None,
        "valuation_mapping": {
            "stance": action,
            "confidence": "MEDIUM",
            "prob_component": None,
            "earnings_component": None,
        },
        "quantitative_target": {
            "target_return_pct": target_return_pct,
            "target_price": target_price,
            "target_market_cap": target_market_cap,
            "components": [
                {
                    "report_type": rt,
                    "weight": round(w / weight_sum, 6),
                    "signal_score": _to_float_or_none(snap.signal_score),
                    "action": str(snap.action or "HOLD").upper(),
                    "risk_level": str(snap.risk_level or "MEDIUM").upper(),
                }
                for rt, snap, w in valid
            ],
        },
        "be_payload": {
            "signal_score": score,
            "target_return_pct": target_return_pct,
            "target_price": target_price,
            "target_market_cap": target_market_cap,
            "action": action,
            "risk_level": risk,
        },
    }


def _select_effective_payload_from_snapshots(snapshots: list[EarningsSignalSnapshot]) -> dict | None:
    stored_fusion = next((x for x in snapshots if str(x.report_type or "").upper() == "FUSION"), None)
    if stored_fusion is not None:
        return _snapshot_to_payload(stored_fusion)

    fusion_payload = _build_fusion_payload_from_snapshots(snapshots)
    if fusion_payload is not None:
        return fusion_payload

    for report_type in ["FY", "Q3", "H1", "Q1"]:
        snap = next((x for x in snapshots if str(x.report_type or "").upper() == report_type), None)
        if snap is not None:
            return _snapshot_to_payload(snap)
    return None


def _build_default_payload(ts_code: str, report_type: str = "") -> dict:
    return {
        "ts_code": ts_code,
        "report_type": report_type or "UNKNOWN",
        "pred_earnings_growth": None,
        "signal_score": None,
        "target_return_pct": None,
        "target_price": None,
        "target_market_cap": None,
        "action": "HOLD",
        "risk_level": "MEDIUM",
        "model_version": None,
        "trade_date": None,
        "feature_data_source": None,
        "financial_fiscal_year": None,
        "financial_ann_date": None,
        "financial_end_date": None,
        "valuation_mapping": {
            "stance": "HOLD",
            "confidence": "LOW",
            "prob_component": None,
            "earnings_component": None,
        },
        "quantitative_target": {},
        "be_payload": {
            "signal_score": None,
            "target_return_pct": None,
            "target_price": None,
            "target_market_cap": None,
            "action": "HOLD",
            "risk_level": "MEDIUM",
        },
    }


@require_GET
def signal_snapshot(request):
    ts_code = str(request.GET.get("ts_code") or "").strip().upper()
    if not ts_code:
        return JsonResponse({"ok": False, "error": "ts_code is required"}, status=400)

    report_type = str(request.GET.get("report_type") or "").strip().upper()
    financial_end_date = _normalize_end_date_token(request.GET.get("financial_end_date"))
    include_fusion = str(request.GET.get("include_fusion") or "").strip().lower() in {"1", "true", "yes"}

    query = EarningsSignalSnapshot.objects.filter(ts_code=ts_code)
    if report_type and report_type != "FUSION":
        query = query.filter(report_type=report_type)
    all_snaps = list(query.order_by("-updated_at"))
    prev_year_income_sign_map = _build_prev_year_income_sign_map(all_snaps)

    if report_type == "FUSION":
        stored_fusion = next((x for x in all_snaps if str(x.report_type or "").upper() == "FUSION"), None)
        if stored_fusion is not None:
            return JsonResponse({"ok": True, "result": _snapshot_to_payload(stored_fusion, prev_year_income_sign_map)})

        try:
            config_path = _resolve_config_path(request)
            pipeline = EarningsForecastPipeline(config_path=config_path)
            fusion = pipeline.predict_fusion(ts_code=ts_code)
            return JsonResponse({"ok": True, "result": fusion})
        except Exception as exc:
            snap_fusion = _build_fusion_payload_from_snapshots(all_snaps)
            if snap_fusion is not None:
                return JsonResponse({"ok": True, "result": snap_fusion})
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    if report_type in {"Q1", "H1", "Q3", "FY"} and financial_end_date:
        selected_payload = _select_payload_by_financial_end_date(
            ts_code=ts_code,
            report_type=report_type,
            financial_end_date=financial_end_date,
            snapshots=all_snaps,
            prev_year_income_sign_map=prev_year_income_sign_map,
        )
        if selected_payload is not None:
            payload = {"ok": True, "result": selected_payload}
            if include_fusion:
                payload["fusion_result"] = _build_fusion_payload_from_snapshots(all_snaps)
            return JsonResponse(payload)
        return JsonResponse(
            {
                "ok": False,
                "error": "snapshot not found for requested financial_end_date",
                "report_type": report_type,
                "financial_end_date": financial_end_date,
            },
            status=404,
        )

    snapshot = all_snaps[0] if all_snaps else None
    if snapshot is None:
        return JsonResponse({"ok": False, "error": "snapshot not found"}, status=404)

    payload = {"ok": True, "result": _snapshot_to_payload(snapshot, prev_year_income_sign_map)}
    if include_fusion:
        payload["fusion_result"] = _build_fusion_payload_from_snapshots(all_snaps)
    return JsonResponse(payload)


@require_POST
@csrf_exempt
def signal_snapshot_batch(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid json body"}, status=400)

    raw_ts_codes = payload.get("ts_codes") or []
    if isinstance(raw_ts_codes, str):
        raw_ts_codes = [item.strip() for item in raw_ts_codes.split(",") if item.strip()]
    if not isinstance(raw_ts_codes, list):
        return JsonResponse({"ok": False, "error": "ts_codes must be a list or comma-separated string"}, status=400)

    ts_codes: list[str] = []
    seen = set()
    for item in raw_ts_codes:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        ts_codes.append(code)
    if not ts_codes:
        return JsonResponse({"ok": False, "error": "ts_codes is required"}, status=400)

    report_type = _normalize_report_type(payload.get("report_type"), allow_all=True)
    raw_financial_end_date_map = payload.get("financial_end_date_map")
    financial_end_date_map: dict[str, str] = {}
    if isinstance(raw_financial_end_date_map, dict):
        for code, end_date in raw_financial_end_date_map.items():
            normalized_code = str(code or "").strip().upper()
            normalized_end_date = _normalize_end_date_token(end_date)
            if normalized_code and normalized_end_date:
                financial_end_date_map[normalized_code] = normalized_end_date

    query = EarningsSignalSnapshot.objects.filter(ts_code__in=ts_codes)
    if report_type not in {"", "ALL", "FUSION"}:
        query = query.filter(report_type=report_type)

    snapshots = list(query.order_by("ts_code", "-updated_at"))
    prev_year_income_sign_map = _build_prev_year_income_sign_map(snapshots)
    grouped: dict[str, list[EarningsSignalSnapshot]] = {code: [] for code in ts_codes}
    for snapshot in snapshots:
        grouped.setdefault(snapshot.ts_code, []).append(snapshot)

    results: dict[str, dict] = {}
    for ts_code in ts_codes:
        all_snaps = grouped.get(ts_code) or []
        resolved = None
        if report_type == "FUSION":
            stored_fusion = next((x for x in all_snaps if str(x.report_type or "").upper() == "FUSION"), None)
            if stored_fusion is not None:
                resolved = _snapshot_to_payload(stored_fusion, prev_year_income_sign_map)
            else:
                resolved = _build_fusion_payload_from_snapshots(all_snaps)
        elif report_type in {"Q1", "H1", "Q3", "FY"}:
            target_end_date = financial_end_date_map.get(ts_code)
            if target_end_date:
                resolved = _select_payload_by_financial_end_date(
                    ts_code=ts_code,
                    report_type=report_type,
                    financial_end_date=target_end_date,
                    snapshots=all_snaps,
                    prev_year_income_sign_map=prev_year_income_sign_map,
                )
            else:
                snap = next((x for x in all_snaps if str(x.report_type or "").upper() == report_type), None)
                if snap is not None:
                    resolved = _snapshot_to_payload(snap, prev_year_income_sign_map)
        else:
            resolved = _select_effective_payload_from_snapshots(all_snaps)

        results[ts_code] = resolved or _build_default_payload(ts_code, report_type if report_type != "ALL" else "")

    return JsonResponse(
        {
            "ok": True,
            "report_type": report_type,
            "count": len(results),
            "results": results,
        }
    )


def _normalize_backtest_payload(payload: dict) -> tuple[dict, str | None]:
    batch_key = str(payload.get("batch_key") or "").strip()
    if not batch_key:
        return {}, "batch_key is required"

    raw_codes = payload.get("ts_codes") or []
    if isinstance(raw_codes, str):
        raw_codes = [item.strip() for item in raw_codes.split(",") if item.strip()]
    if not isinstance(raw_codes, list):
        return {}, "ts_codes must be a list or comma-separated string"

    ts_codes: list[str] = []
    seen = set()
    for item in raw_codes:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        ts_codes.append(code)
    if not ts_codes:
        return {}, "ts_codes is required"

    try:
        start_year = int(payload.get("start_year", 2024))
        end_year = int(payload.get("end_year", 2025))
    except (TypeError, ValueError):
        return {}, "start_year/end_year must be integers"
    if start_year > end_year:
        return {}, "start_year cannot be greater than end_year"

    try:
        min_score = float(payload.get("min_score", 70.0))
        global_stop_dd = float(payload.get("global_stop_dd", 0.0))
        single_stop_dd = float(payload.get("single_stop_dd", 0.1))
    except (TypeError, ValueError):
        return {}, "min_score/global_stop_dd/single_stop_dd must be numeric"

    max_risk = str(payload.get("max_risk", "MEDIUM") or "MEDIUM").strip().upper()
    if max_risk not in {"LOW", "MEDIUM", "HIGH"}:
        max_risk = "MEDIUM"

    stop_mode = str(payload.get("stop_mode", "none") or "none").strip().lower()
    if stop_mode not in {"none", "global", "single"}:
        stop_mode = "none"

    report_type = str(payload.get("report_type", "ALL") or "ALL").strip().upper()
    if report_type in {"", "*"}:
        report_type = "ALL"

    return {
        "batch_key": batch_key,
        "ts_codes": ts_codes,
        "start_year": start_year,
        "end_year": end_year,
        "min_score": min_score,
        "max_risk": max_risk,
        "stop_mode": stop_mode,
        "global_stop_dd": global_stop_dd,
        "single_stop_dd": single_stop_dd,
        "report_type": report_type,
    }, None


@require_POST
@csrf_exempt
def run_backtest(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid json body"}, status=400)

    params, error = _normalize_backtest_payload(payload if isinstance(payload, dict) else {})
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)

    persist = str(payload.get("persist", "true")).strip().lower() not in {"0", "false", "no", "off"}
    run_record = None
    if persist:
        run_record = EarningsBacktestRun.objects.create(
            run_key=f"btr_{uuid4().hex[:24]}",
            batch_key=params["batch_key"],
            status="running",
            params=params,
            summary={},
            result={},
        )

    try:
        result = run_predictive_valuation_backtest(**params)
        yearly = result.get("metrics") or []
        avg_annualized = (
            sum(float(item.get("annualized_return") or 0.0) for item in yearly) / len(yearly)
            if yearly else 0.0
        )
        summary = {
            "years": len(yearly),
            "avg_annualized_return": avg_annualized,
            "pool_size": int(result.get("pool_size") or 0),
        }

        if run_record is not None:
            run_record.status = "success"
            run_record.summary = summary
            run_record.result = result
            run_record.finished_at = timezone.now()
            run_record.save(update_fields=["status", "summary", "result", "finished_at", "updated_at"])

        return JsonResponse(
            {
                "ok": True,
                "run_id": run_record.id if run_record is not None else None,
                "run_key": run_record.run_key if run_record is not None else None,
                "summary": summary,
                "result": result,
            }
        )
    except Exception as exc:
        if run_record is not None:
            run_record.status = "failed"
            run_record.error_message = str(exc)
            run_record.finished_at = timezone.now()
            run_record.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@require_GET
def list_backtest_runs(request):
    try:
        limit = int(request.GET.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 200))

    batch_key = str(request.GET.get("batch_key") or "").strip()
    qs = EarningsBacktestRun.objects.all().order_by("-started_at")
    if batch_key:
        qs = qs.filter(batch_key=batch_key)

    rows = []
    for row in qs[:limit]:
        rows.append(
            {
                "id": row.id,
                "run_key": row.run_key,
                "batch_key": row.batch_key,
                "status": row.status,
                "summary": row.summary or {},
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
        )
    return JsonResponse({"ok": True, "count": len(rows), "data": rows})


@require_GET
def get_backtest_run_detail(_request, run_id: int):
    row = EarningsBacktestRun.objects.filter(id=run_id).first()
    if row is None:
        return JsonResponse({"ok": False, "error": "run not found"}, status=404)
    return JsonResponse(
        {
            "ok": True,
            "data": {
                "id": row.id,
                "run_key": row.run_key,
                "batch_key": row.batch_key,
                "status": row.status,
                "params": row.params or {},
                "summary": row.summary or {},
                "result": row.result or {},
                "error_message": row.error_message,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            },
        }
    )


@require_POST
def prepare_dataset(request):
    try:
        config_path = _resolve_config_path(request)
        pipeline = EarningsForecastPipeline(config_path=config_path)
        dataset_path = pipeline.prepare_dataset()
        return JsonResponse({"ok": True, "dataset_path": str(dataset_path)})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@require_POST
def train_model(request):
    try:
        config_path = _resolve_config_path(request)
        rebuild = str(request.GET.get("rebuild") or request.POST.get("rebuild") or "false").lower() in {"1", "true", "yes"}
        pipeline = EarningsForecastPipeline(config_path=config_path)
        metrics = pipeline.train(rebuild_dataset=rebuild)
        return JsonResponse({"ok": True, "metrics": metrics})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@require_POST
@csrf_exempt
def predict_latest(request):
    try:
        ts_code = request.GET.get("ts_code") or request.POST.get("ts_code")
        report_type = str(request.GET.get("report_type") or request.POST.get("report_type") or "").strip().upper()
        serving_slot = str(request.GET.get("serving_slot") or request.POST.get("serving_slot") or "production").strip().lower()
        model_version = str(request.GET.get("model_version") or request.POST.get("model_version") or "").strip()
        anchor_mode = str(request.GET.get("anchor_mode") or request.POST.get("anchor_mode") or "ann").strip().lower()
        if anchor_mode in {"live", "live_latest", "latest"}:
            anchor_mode = "live_latest"
        else:
            anchor_mode = "ann"
        if not ts_code and request.body:
            payload = json.loads(request.body.decode("utf-8"))
            ts_code = payload.get("ts_code")
            report_type = str(payload.get("report_type") or report_type).strip().upper()
            serving_slot = str(payload.get("serving_slot") or serving_slot).strip().lower()
            model_version = str(payload.get("model_version") or model_version).strip()
            payload_anchor_mode = str(payload.get("anchor_mode") or "").strip().lower()
            if payload_anchor_mode:
                if payload_anchor_mode in {"live", "live_latest", "latest"}:
                    anchor_mode = "live_latest"
                else:
                    anchor_mode = "ann"
        if not ts_code:
            return JsonResponse({"ok": False, "error": "ts_code is required"}, status=400)

        if serving_slot not in {"production", "candidate"}:
            serving_slot = "production"

        config_path = _resolve_config_path(request)
        pipeline = EarningsForecastPipeline(config_path=config_path)
        if report_type == "FUSION":
            result = pipeline.predict_fusion(
                ts_code=ts_code,
                model_version=model_version or None,
                serving_slot=serving_slot,
                anchor_mode=anchor_mode,
            )
        else:
            result = pipeline.predict(
                ts_code=ts_code,
                model_version=model_version or None,
                serving_slot=serving_slot,
                requested_report_type=report_type or None,
                anchor_mode=anchor_mode,
            )
        return JsonResponse({"ok": True, "result": result})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

# Create your views here.
