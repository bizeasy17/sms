from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from earnings_forecast.models import (
    EarningsSignalSnapshot,
    EarningsSignalSnapshotHistory,
    FINANCIAL_ENDPOINT_MODEL_MAP,
    LocalCorporation,
)
from earnings_forecast.services import EarningsForecastPipeline


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_console_text(value) -> str:
    text = str(value)
    encoding = (getattr(sys.stderr, "encoding", None) or "utf-8").strip() or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")


def _parse_asof_date(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _parse_changed_since_dt(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None

    parse_formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y%m%d%H%M%S",
        "%Y%m%d",
    )
    for fmt in parse_formats:
        try:
            dt = datetime.strptime(text, fmt)
            return timezone.make_aware(dt, timezone.get_current_timezone())
        except ValueError:
            continue
    return None


def _normalize_scope(scope_text: str) -> list[str]:
    text = str(scope_text or "ALL").strip().upper()
    if text == "ALL":
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def _normalize_store_mode(mode: str) -> str:
    text = str(mode or "both").strip().lower()
    if text not in {"latest", "history", "both"}:
        return "both"
    return text


def _normalize_serving_slot(slot: str) -> str:
    text = str(slot or "production").strip().lower()
    if text not in {"production", "candidate"}:
        return "production"
    return text


def _normalize_report_type(report_type: str) -> str:
    text = str(report_type or "").strip().upper()
    if text in {"ANNUAL", "FULL_YEAR", "A"}:
        return "FY"
    if text in {"Q1", "H1", "Q3", "FY", "FUSION"}:
        return text
    return text or "UNKNOWN"


def _resolve_target_report_types(raw: str) -> list[str]:
    text = str(raw or "").strip().upper()
    if not text or text == "ALL":
        return ["Q1", "H1", "Q3", "FY"]

    out: list[str] = []
    for token in text.split(","):
        rt = _normalize_report_type(token)
        if rt in {"Q1", "H1", "Q3", "FY", "FUSION"} and rt not in out:
            out.append(rt)
    return out or ["Q1", "H1", "Q3", "FY"]


class Command(BaseCommand):
    help = "Refresh persisted signal snapshot table by running batch prediction in earnings service."

    def add_arguments(self, parser):
        parser.add_argument("--scope", type=str, default="ALL", help="ALL or ts_code prefixes, e.g. 60,00,30,68")
        parser.add_argument("--ts-code", type=str, help="Single ts_code")
        parser.add_argument("--full-refresh", action="store_true", default=False, help="Force full symbol scan instead of auto incremental refresh")
        parser.add_argument("--changed-since", type=str, default="", help="Manual incremental anchor datetime, e.g. 2026-04-07 10:00:00")
        parser.add_argument("--changed-lookback-hours", type=int, default=72, help="Safety overlap hours for auto incremental mode")
        parser.add_argument("--offset", type=int, default=0, help="Offset after ts_code sort")
        parser.add_argument("--limit", type=int, help="Limit number of symbols")
        parser.add_argument("--batch-key", type=str, default="", help="Batch key for traceability")
        parser.add_argument("--sleep-ms", type=int, default=0, help="Sleep milliseconds between symbols")
        parser.add_argument("--strict", action="store_true", default=False, help="Stop on first error")
        parser.add_argument("--model-version", type=str, default="", help="Specify model version under output/model_versions")
        parser.add_argument("--serving-slot", type=str, default="production", help="Serving slot when model-version omitted: production or candidate")
        parser.add_argument("--store-mode", type=str, default="both", help="Persist mode: latest, history, or both")
        parser.add_argument("--report-types", type=str, default="Q1,H1,Q3,FY", help="Comma-separated report types, e.g. Q1,FY")

    def _build_prefix_query(self, prefixes: list[str]) -> Q:
        q_obj = Q()
        for p in prefixes:
            q_obj |= Q(ts_code__startswith=p)
        return q_obj

    def _resolve_incremental_ts_codes(self, options, prefixes: list[str]) -> list[str] | None:
        changed_since_text = str(options.get("changed_since") or "").strip()
        changed_since = _parse_changed_since_dt(changed_since_text)
        lookback_hours = max(0, int(options.get("changed_lookback_hours") or 0))

        if changed_since is None:
            last_history_at = EarningsSignalSnapshotHistory.objects.order_by("-created_at").values_list("created_at", flat=True).first()
            if last_history_at is None:
                return None
            changed_since = last_history_at

        if lookback_hours > 0:
            changed_since = changed_since - timedelta(hours=lookback_hours)

        changed_codes = set()
        prefix_q = self._build_prefix_query(prefixes) if prefixes else None
        for model in FINANCIAL_ENDPOINT_MODEL_MAP.values():
            queryset = model.objects.exclude(ts_code__isnull=True).exclude(ts_code="").filter(imported_at__gt=changed_since)
            if prefix_q is not None:
                queryset = queryset.filter(prefix_q)
            for ts_code in queryset.values_list("ts_code", flat=True).distinct():
                code = str(ts_code or "").strip().upper()
                if code:
                    changed_codes.add(code)

        return sorted(changed_codes)

    def _resolve_ts_codes(self, options) -> list[str]:
        single_code = str(options.get("ts_code") or "").strip().upper()
        if single_code:
            return [single_code]

        prefixes = _normalize_scope(options.get("scope"))
        full_refresh = bool(options.get("full_refresh"))

        if not full_refresh:
            incremental_codes = self._resolve_incremental_ts_codes(options, prefixes)
            if incremental_codes is None:
                self.stdout.write("no incremental anchor found, fallback to full refresh")
                ts_codes = sorted(
                    str(x).strip().upper()
                    for x in LocalCorporation.objects.exclude(ts_code__isnull=True).exclude(ts_code="").values_list("ts_code", flat=True)
                    if str(x).strip()
                )
                if prefixes:
                    ts_codes = [code for code in ts_codes if any(code.startswith(prefix) for prefix in prefixes)]
            else:
                ts_codes = incremental_codes
                self.stdout.write(f"auto incremental mode: changed_symbols={len(ts_codes)}")
        else:
            ts_codes = sorted(
                str(x).strip().upper()
                for x in LocalCorporation.objects.exclude(ts_code__isnull=True).exclude(ts_code="").values_list("ts_code", flat=True)
                if str(x).strip()
            )
            if prefixes:
                ts_codes = [code for code in ts_codes if any(code.startswith(prefix) for prefix in prefixes)]
            self.stdout.write(f"full refresh mode: symbols={len(ts_codes)}")

        offset = max(0, int(options.get("offset") or 0))
        limit = options.get("limit")
        if limit is not None:
            limit = max(1, int(limit))
            ts_codes = ts_codes[offset : offset + limit]
        else:
            ts_codes = ts_codes[offset:]
        return ts_codes

    def handle(self, *args, **options):
        ts_codes = self._resolve_ts_codes(options)
        if not ts_codes:
            self.stdout.write("no ts_code resolved")
            return

        batch_key = str(options.get("batch_key") or "").strip() or datetime.now().strftime("monthly_%Y%m")
        sleep_ms = max(0, int(options.get("sleep_ms") or 0))
        strict = bool(options.get("strict"))
        model_version_arg = str(options.get("model_version") or "").strip()
        serving_slot = _normalize_serving_slot(options.get("serving_slot"))
        store_mode = _normalize_store_mode(options.get("store_mode"))
        target_report_types = _resolve_target_report_types(options.get("report_types"))
        persist_latest = store_mode in {"latest", "both"}
        persist_history = store_mode in {"history", "both"}

        pipeline = EarningsForecastPipeline(config_path="configs/default.yaml")

        start = time.time()
        ok_count = 0
        fail_count = 0
        self.stdout.write(
            "refresh signal snapshot start: "
            f"symbols={len(ts_codes)} batch={batch_key} store_mode={store_mode} "
            f"model_version={model_version_arg or '<serving:' + serving_slot + '>'} "
            f"report_types={target_report_types}"
        )

        for idx, code in enumerate(ts_codes, start=1):
            symbol_start = time.time()
            self.stdout.write(f"processing: {idx}/{len(ts_codes)} ts_code={code}")
            for requested_report_type in target_report_types:
                rt_start = time.time()
                try:
                    if requested_report_type == "FUSION":
                        result = pipeline.predict_fusion(
                            code,
                            model_version=model_version_arg or None,
                            serving_slot=serving_slot,
                        )
                    else:
                        result = pipeline.predict(
                            code,
                            model_version=model_version_arg or None,
                            serving_slot=serving_slot,
                            requested_report_type=requested_report_type,
                        )
                    be_payload = result.get("be_payload") or {}
                    valuation_mapping = result.get("valuation_mapping") or {}

                    signal_score = be_payload.get("signal_score")
                    if signal_score is None:
                        signal_score = result.get("signal_score")

                    # Keep fusion snapshots keyed by FUSION, otherwise FE will keep reading stale FUSION rows.
                    if requested_report_type == "FUSION":
                        served_report_type = "FUSION"
                    else:
                        served_report_type = _normalize_report_type(
                            result.get("served_model_report_type")
                            or result.get("financial_report_type")
                            or result.get("latest_available_report_type")
                            or requested_report_type
                        )

                    effective_model_version = str(result.get("model_version") or model_version_arg or "")
                    payload = {
                        "report_type": served_report_type,
                        "signal_score": _to_float_or_none(signal_score),
                        "target_return_pct": _to_float_or_none(be_payload.get("target_return_pct") or result.get("target_return_pct")),
                        "target_price": _to_float_or_none(be_payload.get("target_price") or result.get("target_price")),
                        "target_market_cap": _to_float_or_none(be_payload.get("target_market_cap") or result.get("target_market_cap")),
                        "action": str(be_payload.get("action") or result.get("action") or "HOLD").upper(),
                        "risk_level": str(be_payload.get("risk_level") or result.get("risk_level") or "MEDIUM").upper(),
                        "model_version": effective_model_version,
                        "asof_date": _parse_asof_date(result.get("trade_date")),
                        "explain": {
                            "stance": valuation_mapping.get("stance"),
                            "confidence": valuation_mapping.get("confidence"),
                            "prob_component": _to_float_or_none(valuation_mapping.get("prob_component")),
                            "earnings_component": _to_float_or_none(valuation_mapping.get("earnings_component")),
                        },
                        "raw_result": result,
                        "feature_data_source": str(result.get("feature_data_source") or ""),
                        "batch_key": batch_key,
                        "last_error": "",
                    }

                    if persist_latest:
                        EarningsSignalSnapshot.objects.update_or_create(
                            ts_code=code,
                            report_type=served_report_type,
                            defaults=payload,
                        )
                    if persist_history:
                        EarningsSignalSnapshotHistory.objects.create(ts_code=code, **payload)
                    ok_count += 1
                    rt_elapsed = round(time.time() - rt_start, 2)
                    self.stdout.write(
                        _safe_console_text(
                            f"[ok] {code} req_rt={requested_report_type} "
                            f"latest_rt={result.get('latest_available_report_type') or 'UNKNOWN'} "
                            f"served_rt={result.get('served_model_report_type') or served_report_type or 'UNKNOWN'} "
                            f"model_version={effective_model_version or 'UNKNOWN'} "
                            f"source={result.get('model_source') or 'UNKNOWN'} "
                            f"score={payload.get('signal_score')} "
                            f"target={payload.get('target_price')} "
                            f"action={payload.get('action')} "
                            f"risk={payload.get('risk_level')} "
                            f"rt_elapsed_sec={rt_elapsed}"
                        )
                    )
                except Exception as exc:
                    fail_count += 1
                    safe_err = _safe_console_text(exc)
                    failed_payload = {
                        "report_type": requested_report_type,
                        "signal_score": None,
                        "target_return_pct": None,
                        "target_price": None,
                        "target_market_cap": None,
                        "action": "HOLD",
                        "risk_level": "MEDIUM",
                        "model_version": model_version_arg,
                        "asof_date": None,
                        "explain": {"stance": "HOLD", "confidence": "LOW", "prob_component": None, "earnings_component": None},
                        "raw_result": {},
                        "feature_data_source": "",
                        "batch_key": batch_key,
                        "last_error": safe_err,
                    }
                    if persist_latest:
                        EarningsSignalSnapshot.objects.update_or_create(
                            ts_code=code,
                            report_type=requested_report_type,
                            defaults=failed_payload,
                        )
                    if persist_history:
                        EarningsSignalSnapshotHistory.objects.create(ts_code=code, **failed_payload)
                    rt_elapsed = round(time.time() - rt_start, 2)
                    self.stderr.write(
                        f"[warn] {code} report_type={requested_report_type} rt_elapsed_sec={rt_elapsed} failed: {safe_err}"
                    )
                    if strict:
                        raise

            symbol_elapsed = round(time.time() - symbol_start, 2)
            self.stdout.write(f"[symbol] {code} elapsed_sec={symbol_elapsed}")

            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
            if idx % 100 == 0 or idx == len(ts_codes):
                self.stdout.write(f"progress: {idx}/{len(ts_codes)} ok={ok_count} fail={fail_count}")

        elapsed = round(time.time() - start, 2)
        self.stdout.write(f"refresh signal snapshot done: total={len(ts_codes)} ok={ok_count} fail={fail_count} elapsed_sec={elapsed} batch={batch_key}")
