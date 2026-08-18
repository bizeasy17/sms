from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db.models import Count, Max, Min
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import EarningsBacktestRun, EarningsSignalSnapshot, EarningsSignalSnapshotHistory, FinancialIncomeRecord
from .services import EarningsForecastPipeline, LiveFeatureUnavailableError, run_predictive_valuation_backtest


def _parse_bool(value, default=False):
    text = str(value or "").strip().lower()
    if not text:
        return bool(default)
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


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


def _parse_token_date(value: str | None) -> date | None:
    normalized = _normalize_end_date_token(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return None


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
    quant_target = quant_target if isinstance(quant_target, dict) else {}
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
        "target_return_low_pct": _to_float_or_none(quant_target.get("target_return_low_pct")),
        "target_return_high_pct": _to_float_or_none(quant_target.get("target_return_high_pct")),
        "target_price_low": _to_float_or_none(quant_target.get("target_price_low")),
        "target_price_high": _to_float_or_none(quant_target.get("target_price_high")),
        "target_market_cap_low": _to_float_or_none(quant_target.get("target_market_cap_low")),
        "target_market_cap_high": _to_float_or_none(quant_target.get("target_market_cap_high")),
        "action": str(snapshot.action or "HOLD").upper(),
        "risk_level": str(snapshot.risk_level or "MEDIUM").upper(),
        "model_version": snapshot.model_version or None,
        "trade_date": snapshot.asof_date.isoformat() if snapshot.asof_date else None,
        "asof_date": snapshot.asof_date.isoformat() if snapshot.asof_date else None,
        "feature_data_source": snapshot.feature_data_source or None,
        "refresh_reason": snapshot.refresh_reason or None,
        "refresh_detail": snapshot.refresh_detail or None,
        "market_regime": snapshot.market_regime or None,
        "stock_regime": snapshot.stock_regime or None,
        "triggered_at": snapshot.triggered_at.isoformat() if snapshot.triggered_at else None,
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
        "quantitative_target": quant_target,
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
    quant_target = quant_target if isinstance(quant_target, dict) else {}
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
        "target_return_low_pct": _to_float_or_none(quant_target.get("target_return_low_pct")),
        "target_return_high_pct": _to_float_or_none(quant_target.get("target_return_high_pct")),
        "target_price_low": _to_float_or_none(quant_target.get("target_price_low")),
        "target_price_high": _to_float_or_none(quant_target.get("target_price_high")),
        "target_market_cap_low": _to_float_or_none(quant_target.get("target_market_cap_low")),
        "target_market_cap_high": _to_float_or_none(quant_target.get("target_market_cap_high")),
        "action": str(snapshot.action or "HOLD").upper(),
        "risk_level": str(snapshot.risk_level or "MEDIUM").upper(),
        "model_version": snapshot.model_version or None,
        "trade_date": snapshot.asof_date.isoformat() if snapshot.asof_date else None,
        "asof_date": snapshot.asof_date.isoformat() if snapshot.asof_date else None,
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
        "quantitative_target": quant_target,
        "be_payload": {
            "signal_score": _to_float_or_none(snapshot.signal_score),
            "target_return_pct": _to_float_or_none(snapshot.target_return_pct),
            "target_price": _to_float_or_none(snapshot.target_price),
            "target_market_cap": _to_float_or_none(snapshot.target_market_cap),
            "action": str(snapshot.action or "HOLD").upper(),
            "risk_level": str(snapshot.risk_level or "MEDIUM").upper(),
        },
    }


def _select_payload_by_financial_end_date(
    ts_code: str,
    report_type: str,
    financial_end_date: str | None,
    snapshots: list[EarningsSignalSnapshot] | None = None,
    prev_year_income_sign_map: dict[tuple[str, str], bool | None] | None = None,
    asof_date: str | None = None,
) -> dict | None:
    target_end_date = _normalize_end_date_token(financial_end_date)
    if not target_end_date:
        return None

    target_asof = _parse_token_date(asof_date)

    matched_snapshots = []
    for snapshot in snapshots or []:
        raw_result = snapshot.raw_result or {}
        snapshot_end_date = _normalize_end_date_token(raw_result.get("financial_end_date") if isinstance(raw_result, dict) else None)
        if snapshot_end_date == target_end_date:
            matched_snapshots.append(snapshot)

    if matched_snapshots:
        if target_asof is None:
            return _snapshot_to_payload(matched_snapshots[0], prev_year_income_sign_map)

        exact = next((s for s in matched_snapshots if s.asof_date == target_asof), None)
        if exact is not None:
            return _snapshot_to_payload(exact, prev_year_income_sign_map)

        before = [s for s in matched_snapshots if s.asof_date is not None and s.asof_date <= target_asof]
        if before:
            before.sort(key=lambda s: (s.asof_date, s.updated_at or s.created_at), reverse=True)
            return _snapshot_to_payload(before[0], prev_year_income_sign_map)

    history_qs = EarningsSignalSnapshotHistory.objects.filter(
        ts_code=str(ts_code or "").strip().upper(),
        report_type=str(report_type or "").strip().upper(),
    )

    history_target_qs = history_qs.filter(
        financial_end_date__in=list(_normalize_end_date_candidates(target_end_date)),
    )

    if target_asof is None:
        history_row = history_target_qs.order_by("-created_at").first()
        if history_row is not None:
            return _history_to_payload(history_row)
    else:
        exact = history_target_qs.filter(asof_date=target_asof).order_by("-created_at").first()
        if exact is not None:
            return _history_to_payload(exact)

        before = history_target_qs.filter(asof_date__isnull=False, asof_date__lte=target_asof).order_by("-asof_date", "-created_at").first()
        if before is not None:
            return _history_to_payload(before)

        after = history_target_qs.filter(asof_date__isnull=False, asof_date__gte=target_asof).order_by("asof_date", "-created_at").first()
        if after is not None:
            return _history_to_payload(after)

        history_row = history_target_qs.order_by("-created_at").first()
        if history_row is not None:
            return _history_to_payload(history_row)

        # Compatibility fallback: many legacy rows do not persist financial_end_date.
        # In that case, pin by report_type and choose nearest snapshot around asof_date.
        history_fuzzy_qs = history_qs.filter(financial_end_date__in=["", None])
        fuzzy_exact = history_fuzzy_qs.filter(asof_date=target_asof).order_by("-created_at").first()
        if fuzzy_exact is not None:
            return _history_to_payload(fuzzy_exact)

        fuzzy_before = history_fuzzy_qs.filter(asof_date__isnull=False, asof_date__lte=target_asof).order_by("-asof_date", "-created_at").first()
        fuzzy_after = history_fuzzy_qs.filter(asof_date__isnull=False, asof_date__gte=target_asof).order_by("asof_date", "-created_at").first()
        if fuzzy_before is not None and fuzzy_after is not None:
            before_gap = abs((target_asof - fuzzy_before.asof_date).days)
            after_gap = abs((fuzzy_after.asof_date - target_asof).days)
            return _history_to_payload(fuzzy_before if before_gap <= after_gap else fuzzy_after)
        if fuzzy_before is not None:
            return _history_to_payload(fuzzy_before)
        if fuzzy_after is not None:
            return _history_to_payload(fuzzy_after)

    for history_row in history_qs.order_by("-created_at")[:50]:
        raw_result = history_row.raw_result or {}
        history_end_date = _normalize_end_date_token(
            (raw_result.get("financial_end_date") if isinstance(raw_result, dict) else None)
            or history_row.financial_end_date
        )
        if history_end_date == target_end_date:
            return _history_to_payload(history_row)
    return None


def _select_announcement_anchor_history(ts_code: str, report_type: str, financial_end_date: str | None = None) -> EarningsSignalSnapshotHistory | None:
    expected_end_date = _normalize_end_date_token(financial_end_date)
    candidates = []
    for snapshot in (
        EarningsSignalSnapshotHistory.objects.filter(
            ts_code=str(ts_code or "").strip().upper(),
            report_type=str(report_type or "").strip().upper(),
        )
        .order_by("-created_at")[:500]
    ):
        raw = snapshot.raw_result if isinstance(snapshot.raw_result, dict) else {}
        snapshot_end_date = _normalize_end_date_token(raw.get("financial_end_date") or snapshot.financial_end_date)
        if expected_end_date and snapshot_end_date != expected_end_date:
            continue
        announcement_date = _parse_token_date(raw.get("financial_ann_date") or snapshot.financial_ann_date)
        anchor_date = snapshot.asof_date or _parse_token_date(raw.get("trade_date"))
        if announcement_date is None or anchor_date is None:
            continue
        candidates.append((snapshot, announcement_date, anchor_date))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            abs((item[2] - item[1]).days),
            1 if item[2] < item[1] else 0,
            0 if str(item[0].anchor_mode or "").lower() == "ann" else 1,
            -item[2].toordinal(),
            -item[0].created_at.timestamp(),
        )
    )
    return candidates[0][0]


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
    asof_date = _normalize_end_date_token(request.GET.get("asof_date"))
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
            asof_date=asof_date,
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


@require_GET
def signal_persisted_snapshot(request):
    """Return an already persisted signal only; never invoke prediction or build a fallback."""
    ts_code = str(request.GET.get("ts_code") or "").strip().upper()
    report_type = _normalize_report_type(request.GET.get("report_type"), allow_all=False)
    if not ts_code or not report_type:
        return JsonResponse({"ok": False, "error": "ts_code and report_type are required"}, status=400)
    require_refresh_reason = _parse_bool(request.GET.get("require_refresh_reason"), default=False)
    view = str(request.GET.get("view") or "latest").strip().lower()
    financial_end_date = _normalize_end_date_token(request.GET.get("financial_end_date"))
    if view == "report_anchor":
        snapshot = _select_announcement_anchor_history(ts_code, report_type, financial_end_date)
        if snapshot is None:
            return JsonResponse({"ok": False, "error": "announcement-anchor snapshot not found"}, status=404)
        return JsonResponse({"ok": True, "result": _history_to_payload(snapshot)})
    query = EarningsSignalSnapshot.objects.filter(ts_code=ts_code, report_type=report_type)
    if require_refresh_reason:
        query = query.exclude(refresh_reason="")
    snapshot = query.order_by("-updated_at").first()
    if snapshot is None:
        return JsonResponse({"ok": False, "error": "persisted snapshot not found"}, status=404)
    payload = _snapshot_to_payload(snapshot, _build_prev_year_income_sign_map([snapshot]))
    return JsonResponse({"ok": True, "result": payload})


@require_GET
def signal_refresh_history(request):
    ts_code = str(request.GET.get("ts_code") or "").strip().upper()
    if not ts_code:
        return JsonResponse({"ok": False, "error": "ts_code is required"}, status=400)
    try:
        limit = max(1, min(int(request.GET.get("limit") or 100), 200))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "limit must be an integer"}, status=400)
    rows = list(
        EarningsSignalSnapshotHistory.objects.filter(ts_code=ts_code)
        .filter(refresh_reason__in=["MARKET_REGIME_SWITCH", "STOCK_REGIME_SWITCH"])
        .order_by("-triggered_at", "-created_at", "-id")[:limit]
    )
    selected_by_batch = {}
    for row in rows:
        batch_identity = (str(row.batch_key or ""), str(row.refresh_reason or ""), str(row.triggered_at or row.created_at or ""))
        existing = selected_by_batch.get(batch_identity)
        if existing is None:
            selected_by_batch[batch_identity] = row
            continue
        existing_is_fusion = str(existing.report_type or "").upper() == "FUSION"
        row_is_fusion = str(row.report_type or "").upper() == "FUSION"
        if existing_is_fusion and not row_is_fusion:
            selected_by_batch[batch_identity] = row
        elif not existing.financial_end_date and row.financial_end_date:
            selected_by_batch[batch_identity] = row

    items = []
    for row in sorted(selected_by_batch.values(), key=lambda item: (item.triggered_at or item.created_at, item.created_at), reverse=True):
        raw = row.raw_result if isinstance(row.raw_result, dict) else {}
        items.append(
            {
                "ts_code": row.ts_code,
                "report_type": str(row.report_type or "UNKNOWN").upper(),
                "financial_report_type": str(row.financial_report_type or row.report_type or "UNKNOWN").upper(),
                "financial_end_date": row.financial_end_date or raw.get("financial_end_date") or None,
                "financial_ann_date": row.financial_ann_date or raw.get("financial_ann_date") or None,
                "refresh_reason": row.refresh_reason,
                "refresh_detail": row.refresh_detail or None,
                "market_regime": row.market_regime or None,
                "stock_regime": row.stock_regime or None,
                "triggered_at": row.triggered_at.isoformat() if row.triggered_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "signal_score": _to_float_or_none(row.signal_score),
                "target_price": _to_float_or_none(row.target_price),
                "target_return_pct": _to_float_or_none(row.target_return_pct),
                "action": str(row.action or "HOLD").upper(),
                "risk_level": str(row.risk_level or "MEDIUM").upper(),
            }
        )
    return JsonResponse({"ok": True, "items": items, "total": len(items)})


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

    raw_batch_key_map = payload.get("batch_key_map")
    batch_key_map = {}
    if raw_batch_key_map is not None:
        if not isinstance(raw_batch_key_map, dict):
            return {}, "batch_key_map must be an object"
        for raw_key, raw_value in raw_batch_key_map.items():
            report_type_key = str(raw_key or "").strip().upper()
            mapped_batch_key = str(raw_value or "").strip()
            if not report_type_key or not mapped_batch_key:
                continue
            if report_type_key not in {"Q1", "H1", "Q3", "FY", "FUSION"}:
                continue
            batch_key_map[report_type_key] = mapped_batch_key

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
        min_score = float(payload.get("min_score", 90.0))
        global_stop_dd = float(payload.get("global_stop_dd", 0.0))
        single_stop_dd = float(payload.get("single_stop_dd", 0.1))
        take_profit_pct = float(payload.get("take_profit_pct", 0.0))
        stop_loss_pct = float(payload.get("stop_loss_pct", 0.0))
        starting_capital = float(payload.get("starting_capital", 200000.0))
        max_position_pct = float(payload.get("max_position_pct", 0.2))
        first_entry_pct = float(payload.get("first_entry_pct", 0.1))
    except (TypeError, ValueError):
        return {}, "min_score/global_stop_dd/single_stop_dd/take_profit_pct/stop_loss_pct/starting_capital/max_position_pct/first_entry_pct must be numeric"

    try:
        max_holding_days = int(payload.get("max_holding_days", 0))
        max_buy_per_day = int(payload.get("max_buy_per_day", 3))
    except (TypeError, ValueError):
        return {}, "max_holding_days/max_buy_per_day must be integers"

    mode = str(payload.get("mode", "signal") or "signal").strip().lower()
    if mode not in {"signal", "account"}:
        mode = "signal"

    max_risk = str(payload.get("max_risk", "MEDIUM") or "MEDIUM").strip().upper()
    if max_risk not in {"LOW", "MEDIUM", "HIGH"}:
        max_risk = "MEDIUM"

    stop_mode = str(payload.get("stop_mode", "none") or "none").strip().lower()
    if stop_mode not in {"none", "global", "single"}:
        stop_mode = "none"

    sell_strategy = str(payload.get("sell_strategy", "optimistic_price") or "optimistic_price").strip().lower()
    if sell_strategy not in {"next_day", "optimistic_price", "take_profit_pct", "optimistic_or_take_profit"}:
        sell_strategy = "optimistic_price"

    report_type = str(payload.get("report_type", "ALL") or "ALL").strip().upper()
    if report_type in {"", "*"}:
        report_type = "ALL"

    return {
        "batch_key": batch_key,
        "batch_key_map": batch_key_map,
        "ts_codes": ts_codes,
        "mode": mode,
        "starting_capital": max(1.0, starting_capital),
        "max_position_pct": min(1.0, max(0.0, max_position_pct)),
        "first_entry_pct": min(1.0, max(0.0, first_entry_pct)),
        "max_buy_per_day": max(1, max_buy_per_day),
        "start_year": start_year,
        "end_year": end_year,
        "min_score": min_score,
        "max_risk": max_risk,
        "stop_mode": stop_mode,
        "global_stop_dd": global_stop_dd,
        "single_stop_dd": single_stop_dd,
        "sell_strategy": sell_strategy,
        "take_profit_pct": max(0.0, take_profit_pct),
        "stop_loss_pct": max(0.0, stop_loss_pct),
        "max_holding_days": max(0, max_holding_days),
        "report_type": report_type,
    }, None


def _sanitize_backtest_param_value(value, *, depth: int = 0):
    if depth > 4:
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_sanitize_backtest_param_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            out[normalized_key] = _sanitize_backtest_param_value(item, depth=depth + 1)
        return out
    return str(value)


def _build_persisted_backtest_params(raw_payload: dict, effective_params: dict) -> dict:
    # Keep full replay context from request payload while forcing canonical execution params.
    persisted = {}
    source = raw_payload if isinstance(raw_payload, dict) else {}
    for key, value in source.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        persisted[normalized_key] = _sanitize_backtest_param_value(value)

    for key, value in (effective_params or {}).items():
        persisted[key] = _sanitize_backtest_param_value(value)

    if isinstance(persisted.get("batch_key_map"), dict):
        normalized_batch_key_map = {}
        for report_type, mapped_key in persisted["batch_key_map"].items():
            report_type_key = str(report_type or "").strip().upper()
            mapped_batch_key = str(mapped_key or "").strip()
            if report_type_key and mapped_batch_key:
                normalized_batch_key_map[report_type_key] = mapped_batch_key
        persisted["batch_key_map"] = normalized_batch_key_map

    return persisted


def _infer_backtest_year_range(batch_key: str) -> tuple[int, int] | None:
    years = list(
        EarningsSignalSnapshotHistory.objects.filter(batch_key=batch_key)
        .exclude(asof_date__isnull=True)
        .dates("asof_date", "year")
    )
    if not years:
        return None
    values = sorted(item.year for item in years)
    return values[0], values[-1]


def _infer_backtest_ts_codes(batch_key: str, start_year: int, end_year: int) -> list[str]:
    queryset = EarningsSignalSnapshotHistory.objects.filter(batch_key=batch_key)
    if start_year <= end_year:
        queryset = queryset.filter(
            asof_date__gte=date(start_year, 1, 1),
            asof_date__lte=date(end_year, 12, 31),
        )
    return list(
        queryset.order_by()
        .values_list("ts_code", flat=True)
        .distinct()
    )


def _parse_year_param(value, field_name: str) -> tuple[int | None, str | None]:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} must be an integer"
    if year < 1990 or year > 2100:
        return None, f"{field_name} out of range"
    return year, None


@require_GET
def list_backtest_batch_candidates(request):
    start_year_raw = request.GET.get("start_year")
    end_year_raw = request.GET.get("end_year")
    if start_year_raw in (None, "") or end_year_raw in (None, ""):
        return JsonResponse({"ok": False, "error": "start_year and end_year are required"}, status=400)

    start_year, start_year_error = _parse_year_param(start_year_raw, "start_year")
    if start_year_error:
        return JsonResponse({"ok": False, "error": start_year_error}, status=400)
    end_year, end_year_error = _parse_year_param(end_year_raw, "end_year")
    if end_year_error:
        return JsonResponse({"ok": False, "error": end_year_error}, status=400)
    if start_year is None or end_year is None:
        return JsonResponse({"ok": False, "error": "invalid year range"}, status=400)
    if start_year > end_year:
        return JsonResponse({"ok": False, "error": "start_year cannot be greater than end_year"}, status=400)

    report_type = str(request.GET.get("report_type") or "ALL").strip().upper()
    valid_report_types = {"Q1", "H1", "Q3", "FY", "FUSION"}
    if report_type in {"", "*"}:
        report_type = "ALL"
    if report_type != "ALL" and report_type not in valid_report_types:
        return JsonResponse({"ok": False, "error": "report_type must be ALL/Q1/H1/Q3/FY/FUSION"}, status=400)

    try:
        limit_per_report_type = int(request.GET.get("limit_per_report_type", 30))
    except (TypeError, ValueError):
        limit_per_report_type = 30
    limit_per_report_type = max(1, min(limit_per_report_type, 200))

    queryset = EarningsSignalSnapshotHistory.objects.filter(
        asof_date__gte=date(start_year, 1, 1),
        asof_date__lte=date(end_year, 12, 31),
    ).exclude(
        asof_date__isnull=True,
    ).exclude(
        batch_key__isnull=True,
    ).exclude(
        batch_key="",
    )

    if report_type != "ALL":
        queryset = queryset.filter(report_type=report_type)
    else:
        queryset = queryset.filter(report_type__in=valid_report_types)

    grouped_rows = list(
        queryset.values("report_type", "batch_key")
        .annotate(
            record_count=Count("id"),
            first_asof_date=Min("asof_date"),
            last_asof_date=Max("asof_date"),
            latest_created_at=Max("created_at"),
        )
        .order_by("report_type", "-record_count", "-latest_created_at", "batch_key")
    )

    buckets: dict[str, list[dict[str, object]]] = {key: [] for key in sorted(valid_report_types)}
    bucket_counts: dict[str, int] = {key: 0 for key in valid_report_types}
    options: list[dict[str, object]] = []

    for row in grouped_rows:
        rt = str(row.get("report_type") or "").strip().upper()
        if rt not in valid_report_types:
            continue
        if bucket_counts[rt] >= limit_per_report_type:
            continue

        candidate = {
            "report_type": rt,
            "batch_key": str(row.get("batch_key") or "").strip(),
            "record_count": int(row.get("record_count") or 0),
            "first_asof_date": row.get("first_asof_date").isoformat() if row.get("first_asof_date") else None,
            "last_asof_date": row.get("last_asof_date").isoformat() if row.get("last_asof_date") else None,
            "latest_created_at": row.get("latest_created_at").isoformat() if row.get("latest_created_at") else None,
        }
        buckets[rt].append(candidate)
        options.append(candidate)
        bucket_counts[rt] += 1

    if report_type != "ALL":
        buckets = {report_type: buckets.get(report_type, [])}

    return JsonResponse(
        {
            "ok": True,
            "start_year": start_year,
            "end_year": end_year,
            "report_type": report_type,
            "limit_per_report_type": limit_per_report_type,
            "buckets": buckets,
            "options": options,
            "count": len(options),
        }
    )


def _build_effective_backtest_params(row: EarningsBacktestRun) -> dict[str, object]:
    payload = dict(row.params or {})
    batch_key = str(payload.get("batch_key") or row.batch_key or "").strip()

    start_year = payload.get("start_year")
    end_year = payload.get("end_year")
    try:
        start_year_value = int(start_year) if start_year is not None else None
    except (TypeError, ValueError):
        start_year_value = None
    try:
        end_year_value = int(end_year) if end_year is not None else None
    except (TypeError, ValueError):
        end_year_value = None

    if start_year_value is None or end_year_value is None:
        inferred_years = _infer_backtest_year_range(batch_key)
        if inferred_years is not None:
            start_year_value, end_year_value = inferred_years

    if start_year_value is None:
        start_year_value = 2024
    if end_year_value is None:
        end_year_value = max(start_year_value, 2025)

    raw_ts_codes = payload.get("ts_codes") or []
    if isinstance(raw_ts_codes, str):
        raw_ts_codes = [item.strip() for item in raw_ts_codes.split(",") if item.strip()]
    ts_codes = []
    seen = set()
    for item in raw_ts_codes if isinstance(raw_ts_codes, list) else []:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        ts_codes.append(code)
    if not ts_codes and batch_key:
        ts_codes = _infer_backtest_ts_codes(batch_key, start_year_value, end_year_value)

    return {
        "batch_key": batch_key,
        "batch_key_map": payload.get("batch_key_map") if isinstance(payload.get("batch_key_map"), dict) else {},
        "ts_codes": ts_codes,
        "mode": str(payload.get("mode", "signal") or "signal").strip().lower(),
        "starting_capital": max(1.0, float(payload.get("starting_capital", 200000.0) or 200000.0)),
        "max_position_pct": min(1.0, max(0.0, float(payload.get("max_position_pct", 0.2) or 0.2))),
        "first_entry_pct": min(1.0, max(0.0, float(payload.get("first_entry_pct", 0.1) or 0.1))),
        "max_buy_per_day": max(1, int(payload.get("max_buy_per_day", 3) or 3)),
        "start_year": start_year_value,
        "end_year": end_year_value,
        "min_score": max(90.0, float(payload.get("min_score", 90.0) or 90.0)),
        "max_risk": str(payload.get("max_risk", "MEDIUM") or "MEDIUM").strip().upper(),
        "stop_mode": str(payload.get("stop_mode", "none") or "none").strip().lower(),
        "global_stop_dd": float(payload.get("global_stop_dd", 0.0) or 0.0),
        "single_stop_dd": float(payload.get("single_stop_dd", 0.1) or 0.1),
        "sell_strategy": str(payload.get("sell_strategy", "optimistic_price") or "optimistic_price").strip().lower(),
        "take_profit_pct": max(0.0, float(payload.get("take_profit_pct", 0.0) or 0.0)),
        "stop_loss_pct": max(0.0, float(payload.get("stop_loss_pct", 0.0) or 0.0)),
        "max_holding_days": max(0, int(payload.get("max_holding_days", 0) or 0)),
        "report_type": str(payload.get("report_type", "ALL") or "ALL").strip().upper() or "ALL",
    }


def _ensure_backtest_result_details(row: EarningsBacktestRun) -> tuple[dict, dict]:
    effective_params = _build_effective_backtest_params(row)
    persisted_params = dict(row.params or {})
    result = dict(row.result or {})
    if result.get("sample_trades"):
        return persisted_params, result
    if row.status != "success":
        return persisted_params, result
    if not effective_params.get("batch_key") or not effective_params.get("ts_codes"):
        return persisted_params, result

    rebuilt = run_predictive_valuation_backtest(**effective_params)
    row.result = rebuilt
    rebuilt_combined = rebuilt.get("combined") if isinstance(rebuilt, dict) else {}
    if not isinstance(rebuilt_combined, dict):
        rebuilt_combined = {}
    if not row.summary:
        yearly = rebuilt.get("metrics") or []
        avg_annualized = (
            sum(float(item.get("annualized_return") or 0.0) for item in yearly) / len(yearly)
            if yearly else 0.0
        )
        row.summary = {
            "years": len(yearly),
            "avg_annualized_return": avg_annualized,
            "pool_size": int(rebuilt.get("pool_size") or 0),
            "trade_count": int(rebuilt_combined.get("trade_count") or 0),
            "avg_return_pct": float(rebuilt_combined.get("avg_return_pct") or 0.0),
            "median_return_pct": float(rebuilt_combined.get("median_return_pct") or 0.0),
            "win_rate_pct": float(rebuilt_combined.get("win_rate_pct") or 0.0),
        }
        row.save(update_fields=["result", "summary", "updated_at"])
    else:
        row.save(update_fields=["result", "updated_at"])
    return persisted_params, rebuilt


def _coalesce_metric(summary: dict, candidates: list[object], *, cast_int: bool = False):
    if not isinstance(summary, dict):
        return
    for candidate in candidates:
        value = _to_float_or_none(candidate)
        if value is None:
            continue
        summary_value = int(value) if cast_int else float(value)
        return summary_value
    return None


def _derive_total_return_pct_from_metrics(result_payload: dict) -> float | None:
    metrics = result_payload.get("metrics") if isinstance(result_payload, dict) else None
    if not isinstance(metrics, list) or not metrics:
        return None

    growth = 1.0
    has_value = False
    for item in metrics:
        if not isinstance(item, dict):
            continue
        cumulative = _to_float_or_none(item.get("cumulative_return"))
        if cumulative is None:
            continue
        growth *= (1.0 + cumulative)
        has_value = True
    if not has_value:
        return None
    return round((growth - 1.0) * 100.0, 4)


def _derive_trade_level_metrics(result_payload: dict) -> dict:
    sample_trades = result_payload.get("sample_trades") if isinstance(result_payload, dict) else None
    if not isinstance(sample_trades, list) or not sample_trades:
        return {}

    returns_pct = []
    drawdowns_pct = []
    entry_dates = []
    exit_dates = []
    for item in sample_trades:
        if not isinstance(item, dict):
            continue
        ret = _to_float_or_none(item.get("return_pct"))
        if ret is not None:
            returns_pct.append(ret)
        dd = _to_float_or_none(item.get("max_drawdown_pct"))
        if dd is not None:
            drawdowns_pct.append(dd)
        entry = str(item.get("entry_date") or "").strip()
        if entry:
            entry_dates.append(entry)
        exit_ = str(item.get("exit_date") or "").strip()
        if exit_:
            exit_dates.append(exit_)

    out: dict[str, object] = {}
    if entry_dates:
        out["start_date"] = min(entry_dates)
    if exit_dates:
        out["end_date"] = max(exit_dates)

    if not returns_pct:
        return out

    mean_pct = sum(returns_pct) / len(returns_pct)
    negative_returns = [value for value in returns_pct if value < 0]
    sum_profit = sum(value for value in returns_pct if value > 0)
    sum_loss = abs(sum(value for value in returns_pct if value < 0))
    max_drawdown_pct = min(drawdowns_pct) if drawdowns_pct else None

    variance = sum((value - mean_pct) ** 2 for value in returns_pct) / len(returns_pct)
    std_dev = math.sqrt(variance)
    sharpe = (mean_pct / std_dev) if std_dev > 0 else None

    downside_variance = sum((value - 0.0) ** 2 for value in negative_returns) / len(negative_returns) if negative_returns else 0.0
    downside_std = math.sqrt(downside_variance)
    sortino = (mean_pct / downside_std) if downside_std > 0 else None

    if sum_loss > 0:
        out["profit_factor"] = round(sum_profit / sum_loss, 4)
    out["expectancy_pct"] = round(mean_pct, 4)
    if max_drawdown_pct is not None:
        out["max_drawdown_pct"] = round(max_drawdown_pct, 4)
    if sharpe is not None:
        out["sharpe_ratio"] = round(sharpe, 4)
    if sortino is not None:
        out["sortino_ratio"] = round(sortino, 4)
    return out


def _enrich_backtest_list_summary(summary_payload: dict, result_payload: dict) -> dict:
    summary = dict(summary_payload or {})
    result = result_payload if isinstance(result_payload, dict) else {}
    combined = result.get("combined") if isinstance(result.get("combined"), dict) else {}

    if summary.get("trade_count") is None:
        summary["trade_count"] = _coalesce_metric(
            summary,
            [combined.get("trade_count"), result.get("trade_count")],
            cast_int=True,
        )

    fallback_mapping = {
        "avg_return_pct": [combined.get("avg_return_pct"), summary.get("avg_trade_return_pct"), summary.get("return_pct")],
        "median_return_pct": [combined.get("median_return_pct")],
        "win_rate_pct": [combined.get("win_rate_pct")],
        "avg_holding_days": [combined.get("avg_holding_days")],
        "total_return_pct": [
            summary.get("total_return_pct"),
            result.get("total_return_pct"),
            result.get("account_return_pct"),
            combined.get("total_return_pct"),
        ],
        "max_drawdown_pct": [
            summary.get("max_drawdown_pct"),
            result.get("max_drawdown_pct"),
            combined.get("max_drawdown_pct"),
        ],
        "sharpe_ratio": [summary.get("sharpe_ratio"), result.get("sharpe_ratio"), combined.get("sharpe_ratio")],
        "sortino_ratio": [summary.get("sortino_ratio"), result.get("sortino_ratio"), combined.get("sortino_ratio")],
        "calmar_ratio": [summary.get("calmar_ratio"), result.get("calmar_ratio"), combined.get("calmar_ratio")],
        "profit_factor": [summary.get("profit_factor"), result.get("profit_factor"), combined.get("profit_factor")],
        "expectancy_pct": [summary.get("expectancy_pct"), result.get("expectancy_pct"), combined.get("expectancy_pct")],
    }

    for key, candidates in fallback_mapping.items():
        if summary.get(key) is not None:
            continue
        resolved = _coalesce_metric(summary, candidates)
        if resolved is not None:
            summary[key] = resolved

    for key, candidates in {
        "starting_capital": [
            summary.get("starting_capital"),
            summary.get("initial_capital"),
            summary.get("initial_cash"),
            result.get("starting_capital"),
        ],
        "ending_capital": [
            summary.get("ending_capital"),
            summary.get("final_capital"),
            summary.get("final_asset"),
            result.get("ending_capital"),
            result.get("final_capital"),
            result.get("final_asset"),
        ],
    }.items():
        if summary.get(key) is not None:
            continue
        resolved = _coalesce_metric(summary, candidates)
        if resolved is not None:
            summary[key] = resolved

    derived_trade_metrics = _derive_trade_level_metrics(result)
    for key in ["profit_factor", "expectancy_pct", "max_drawdown_pct", "sharpe_ratio", "sortino_ratio"]:
        if summary.get(key) is not None:
            continue
        if derived_trade_metrics.get(key) is not None:
            summary[key] = derived_trade_metrics.get(key)

    if summary.get("total_return_pct") is None:
        derived_total = _derive_total_return_pct_from_metrics(result)
        if derived_total is not None:
            summary["total_return_pct"] = derived_total

    if summary.get("calmar_ratio") is None:
        total_ret = _to_float_or_none(summary.get("total_return_pct"))
        max_dd = _to_float_or_none(summary.get("max_drawdown_pct"))
        if total_ret is not None and max_dd is not None and max_dd < 0:
            summary["calmar_ratio"] = round(total_ret / abs(max_dd), 4)

    if summary.get("ending_capital") is None:
        start_capital = _to_float_or_none(summary.get("starting_capital"))
        total_ret = _to_float_or_none(summary.get("total_return_pct"))
        if start_capital is not None and total_ret is not None:
            summary["ending_capital"] = round(start_capital * (1.0 + total_ret / 100.0), 4)

    if summary.get("start_date") is None and derived_trade_metrics.get("start_date") is not None:
        summary["start_date"] = derived_trade_metrics.get("start_date")
    if summary.get("end_date") is None and derived_trade_metrics.get("end_date") is not None:
        summary["end_date"] = derived_trade_metrics.get("end_date")

    return summary


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
    persisted_params = _build_persisted_backtest_params(payload, params)

    persist = str(payload.get("persist", "true")).strip().lower() not in {"0", "false", "no", "off"}
    run_record = None
    if persist:
        run_record = EarningsBacktestRun.objects.create(
            run_key=f"btr_{uuid4().hex[:24]}",
            batch_key=params["batch_key"],
            status="running",
            params=persisted_params,
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
            "trade_count": int(((result.get("combined") or {}).get("trade_count") or 0)),
            "avg_return_pct": float(((result.get("combined") or {}).get("avg_return_pct") or 0.0)),
            "median_return_pct": float(((result.get("combined") or {}).get("median_return_pct") or 0.0)),
            "win_rate_pct": float(((result.get("combined") or {}).get("win_rate_pct") or 0.0)),
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
    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    batch_key = str(request.GET.get("batch_key") or "").strip()
    qs = EarningsBacktestRun.objects.all().order_by("-started_at")
    if batch_key:
        qs = qs.filter(batch_key=batch_key)
    total = qs.count()

    rows = []
    for row in qs[offset:offset + limit]:
        params = dict(row.params or {})
        result_payload = row.result if isinstance(row.result, dict) else {}
        summary = _enrich_backtest_list_summary(dict(row.summary or {}), result_payload)

        start_date = str(params.get("start_date") or summary.get("start_date") or "").strip()
        end_date = str(params.get("end_date") or summary.get("end_date") or "").strip()
        if not start_date:
            start_year = params.get("start_year")
            if start_year is not None:
                start_date = f"{int(start_year)}-01-01"
        if not end_date:
            end_year = params.get("end_year")
            if end_year is not None:
                end_date = f"{int(end_year)}-12-31"

        rows.append(
            {
                "id": row.id,
                "run_id": row.id,
                "run_key": row.run_key,
                "batch_key": row.batch_key,
                "status": row.status,
                "params": params,
                "summary": summary,
                "start_date": start_date,
                "end_date": end_date,
                "created_at": row.started_at.isoformat() if row.started_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
        )
    return JsonResponse(
        {
            "ok": True,
            "count": len(rows),
            "total": total,
            "limit": limit,
            "offset": offset,
            "data": rows,
        }
    )


@require_GET
def get_backtest_run_detail(_request, run_id: int):
    row = EarningsBacktestRun.objects.filter(id=run_id).first()
    if row is None:
        return JsonResponse({"ok": False, "error": "run not found"}, status=404)
    params, result = _ensure_backtest_result_details(row)
    return JsonResponse(
        {
            "ok": True,
            "data": {
                "id": row.id,
                "run_key": row.run_key,
                "batch_key": row.batch_key,
                "status": row.status,
                "params": params,
                "summary": row.summary or {},
                "result": result,
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
        payload = {}
        if request.body:
            try:
                payload = json.loads(request.body.decode("utf-8")) or {}
            except Exception:
                payload = {}

        ts_code = request.GET.get("ts_code") or request.POST.get("ts_code")
        report_type = str(request.GET.get("report_type") or request.POST.get("report_type") or "").strip().upper()
        financial_end_date = str(request.GET.get("financial_end_date") or request.POST.get("financial_end_date") or "").strip()
        serving_slot = str(request.GET.get("serving_slot") or request.POST.get("serving_slot") or "production").strip().lower()
        model_version = str(request.GET.get("model_version") or request.POST.get("model_version") or "").strip()
        asof_date = str(request.GET.get("asof_date") or request.POST.get("asof_date") or "").strip()
        feature_source_preference = str(
            request.GET.get("feature_source_preference")
            or request.POST.get("feature_source_preference")
            or ""
        ).strip().lower()
        require_live_features = _parse_bool(
            request.GET.get("require_live_features") or request.POST.get("require_live_features"),
            default=False,
        )
        anchor_mode = str(request.GET.get("anchor_mode") or request.POST.get("anchor_mode") or "ann").strip().lower()
        if anchor_mode in {"live", "live_latest", "latest"}:
            anchor_mode = "live_latest"
        else:
            anchor_mode = "ann"

        ts_code = payload.get("ts_code") or ts_code
        report_type = str(payload.get("report_type") or report_type).strip().upper()
        financial_end_date = str(payload.get("financial_end_date") or financial_end_date).strip()
        serving_slot = str(payload.get("serving_slot") or serving_slot).strip().lower()
        model_version = str(payload.get("model_version") or model_version).strip()
        asof_date = str(payload.get("asof_date") or asof_date).strip()
        feature_source_preference = str(payload.get("feature_source_preference") or feature_source_preference).strip().lower()
        if "require_live_features" in payload:
            require_live_features = _parse_bool(payload.get("require_live_features"), default=require_live_features)
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

        normalized_financial_end_date = _normalize_end_date_token(financial_end_date)
        normalized_asof_date = _normalize_end_date_token(asof_date)
        if report_type in {"Q1", "H1", "Q3", "FY"} and anchor_mode == "ann":
            snapshot_query = EarningsSignalSnapshot.objects.filter(ts_code=str(ts_code).strip().upper(), report_type=report_type)
            snapshots = list(snapshot_query.order_by("-updated_at"))
            prev_year_income_sign_map = _build_prev_year_income_sign_map(snapshots)

            selected_payload = None
            if normalized_financial_end_date:
                selected_payload = _select_payload_by_financial_end_date(
                    ts_code=str(ts_code).strip().upper(),
                    report_type=report_type,
                    financial_end_date=normalized_financial_end_date,
                    snapshots=snapshots,
                    prev_year_income_sign_map=prev_year_income_sign_map,
                    asof_date=normalized_asof_date,
                )

            if selected_payload is None and snapshots:
                selected_payload = _snapshot_to_payload(snapshots[0], prev_year_income_sign_map)

            if selected_payload is not None:
                return JsonResponse({"ok": True, "result": selected_payload})

        config_path = _resolve_config_path(request)
        pipeline = EarningsForecastPipeline(config_path=config_path)
        if report_type == "FUSION":
            result = pipeline.predict_fusion(
                ts_code=ts_code,
                model_version=model_version or None,
                serving_slot=serving_slot,
                anchor_mode=anchor_mode,
                asof_date=asof_date or None,
                require_live_features=require_live_features,
                feature_source_preference=feature_source_preference or None,
            )
        else:
            result = pipeline.predict(
                ts_code=ts_code,
                model_version=model_version or None,
                serving_slot=serving_slot,
                requested_report_type=report_type or None,
                anchor_mode=anchor_mode,
                requested_financial_end_date=financial_end_date or None,
                asof_date=asof_date or None,
                require_live_features=require_live_features,
                feature_source_preference=feature_source_preference or None,
            )
        return JsonResponse({"ok": True, "result": result})
    except LiveFeatureUnavailableError as exc:
        payload = exc.to_payload()
        return JsonResponse({"ok": False, **payload}, status=422)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

# Create your views here.
