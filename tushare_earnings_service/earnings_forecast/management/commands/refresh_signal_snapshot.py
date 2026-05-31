from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from earnings_forecast.models import (
    EarningsSignalSnapshot,
    EarningsSignalSnapshotHistory,
    FINANCIAL_ENDPOINT_MODEL_MAP,
    LocalFundamentalHistory,
    LocalCorporation,
    LocalTradingHistory,
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
    encoding = str(getattr(sys.stderr, "encoding", None) or "utf-8").strip() or "utf-8"
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


def _normalize_anchor_mode(mode: str) -> str:
    text = str(mode or "ann").strip().lower()
    if text in {"live", "live_latest", "latest"}:
        return "live_latest"
    return "ann"


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
    if text == "LATEST":
        return ["LATEST"]

    out: list[str] = []
    for token in text.split(","):
        rt = _normalize_report_type(token)
        if rt in {"Q1", "H1", "Q3", "FY", "FUSION", "LATEST"} and rt not in out:
            out.append(rt)
    return out or ["Q1", "H1", "Q3", "FY"]


def _load_ts_codes_from_file(path: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            code = str(raw or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
    return out


def _resolve_asof_dates(options) -> list:
    asof_date = _parse_asof_date(options.get("asof_date"))
    if asof_date is not None:
        return [asof_date]

    start_date = _parse_asof_date(options.get("asof_start_date"))
    end_date = _parse_asof_date(options.get("asof_end_date"))
    if start_date is None and end_date is None:
        return [None]
    if start_date is None:
        start_date = end_date
    if end_date is None:
        end_date = start_date

    freq = str(options.get("asof_freq") or "D").strip().upper() or "D"
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if end_ts < start_ts:
        start_ts, end_ts = end_ts, start_ts

    dates = [ts.date() for ts in pd.date_range(start=start_ts, end=end_ts, freq=freq)]
    return dates or [start_ts.date()]


def _derive_target_market_cap(target_price, current_price, current_market_cap):
    tp = _to_float_or_none(target_price)
    cp = _to_float_or_none(current_price)
    cm = _to_float_or_none(current_market_cap)
    if tp is None or cp is None or cm is None:
        return None
    if tp <= 0 or cp <= 0 or cm <= 0:
        return None
    return cm * (tp / cp)


def _resolve_market_anchor(ts_code: str, asof_date):
    code = str(ts_code or "").strip().upper()
    if not code:
        return None, None

    trading_qs = LocalTradingHistory.objects.filter(ts_code=code, freq="D")
    fundamental_qs = LocalFundamentalHistory.objects.filter(ts_code=code, freq="D")
    if asof_date is not None:
        trading_qs = trading_qs.filter(trade_date__lte=asof_date)
        fundamental_qs = fundamental_qs.filter(trade_date__lte=asof_date)

    trading_row = trading_qs.order_by("-trade_date").values("close").first()
    fundamental_row = fundamental_qs.order_by("-trade_date").values("total_mv").first()

    current_price = _to_float_or_none((trading_row or {}).get("close"))
    current_market_cap = _to_float_or_none((fundamental_row or {}).get("total_mv"))
    return current_price, current_market_cap


def _save_history_snapshot(ts_code: str, payload: dict):
    """Upsert history rows by (ts_code, report_type, asof_date) to avoid duplicate daily records."""
    asof_date = payload.get("asof_date")
    report_type = str(payload.get("report_type") or "").strip().upper()
    if asof_date is not None and report_type:
        filters = {
            "ts_code": ts_code,
            "report_type": report_type,
            "asof_date": asof_date,
        }
        defaults = dict(payload)
        defaults["report_type"] = report_type

        qs = EarningsSignalSnapshotHistory.objects.filter(**filters).order_by("-created_at", "-id")
        head = qs.first()
        if head is None:
            EarningsSignalSnapshotHistory.objects.create(ts_code=ts_code, **defaults)
            return

        # Keep newest row and update it; remove stale duplicates under the same key.
        for k, v in defaults.items():
            setattr(head, k, v)
        head.save()
        qs.exclude(id=head.id).delete()
        return

    # Fallback for rows without asof_date/report_type where uniqueness cannot be inferred safely.
    EarningsSignalSnapshotHistory.objects.create(ts_code=ts_code, **payload)


def _enrich_target_market_cap_fields(result: dict, ts_code: str):
    if not isinstance(result, dict):
        return

    be_payload = result.get("be_payload") if isinstance(result.get("be_payload"), dict) else {}
    quant_target = result.get("quantitative_target") if isinstance(result.get("quantitative_target"), dict) else {}

    if not be_payload:
        be_payload = {}
        result["be_payload"] = be_payload
    if result.get("quantitative_target") is None:
        result["quantitative_target"] = quant_target

    asof_date = _parse_asof_date(result.get("trade_date"))
    current_price, current_market_cap = _resolve_market_anchor(ts_code=ts_code, asof_date=asof_date)
    if current_price is None or current_market_cap is None:
        return

    direct_cap = _to_float_or_none(be_payload.get("target_market_cap"))
    if direct_cap is None:
        direct_cap = _to_float_or_none(result.get("target_market_cap"))
    if direct_cap is None:
        direct_cap = _to_float_or_none(quant_target.get("target_market_cap"))
    if direct_cap is None:
        direct_cap = _derive_target_market_cap(
            be_payload.get("target_price") or result.get("target_price") or quant_target.get("target_price"),
            current_price,
            current_market_cap,
        )
    if direct_cap is not None:
        result["target_market_cap"] = direct_cap
        be_payload["target_market_cap"] = direct_cap
        quant_target["target_market_cap"] = quant_target.get("target_market_cap") or direct_cap

    low_cap = _to_float_or_none(quant_target.get("target_market_cap_low"))
    if low_cap is None:
        low_cap = _derive_target_market_cap(quant_target.get("target_price_low"), current_price, current_market_cap)
    if low_cap is not None:
        quant_target["target_market_cap_low"] = low_cap

    high_cap = _to_float_or_none(quant_target.get("target_market_cap_high"))
    if high_cap is None:
        high_cap = _derive_target_market_cap(quant_target.get("target_price_high"), current_price, current_market_cap)
    if high_cap is not None:
        quant_target["target_market_cap_high"] = high_cap


class Command(BaseCommand):
    help = "Refresh persisted signal snapshot table by running batch prediction in earnings service."

    def add_arguments(self, parser):
        parser.add_argument("--scope", type=str, default="ALL", help="ALL or ts_code prefixes, e.g. 60,00,30,68")
        parser.add_argument("--ts-code", type=str, help="Single ts_code")
        parser.add_argument("--tscodes-file", type=str, help="Text file with one ts_code per line")
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
        parser.add_argument("--anchor-mode", type=str, default="ann", help="Anchor mode: ann or live_latest")
        parser.add_argument(
            "--no-align-latest",
            action="store_true",
            default=False,
            help="Disable default latest-alignment mode and keep historical asof/anchor behavior.",
        )
        parser.add_argument("--store-mode", type=str, default="both", help="Persist mode: latest, history, or both")
        parser.add_argument("--asof-date", type=str, default="", help="Historical as-of trade date, e.g. 2025-05-08")
        parser.add_argument("--asof-start-date", type=str, default="", help="Historical as-of start date for range replay")
        parser.add_argument("--asof-end-date", type=str, default="", help="Historical as-of end date for range replay")
        parser.add_argument("--asof-freq", type=str, default="D", help="Historical as-of frequency when start/end are provided")
        parser.add_argument(
            "--report-types",
            type=str,
            default="Q1,H1,Q3,FY",
            help="Comma-separated report types, e.g. Q1,FY,FUSION or LATEST",
        )

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

        tscodes_file = str(options.get("tscodes_file") or "").strip()
        if tscodes_file:
            return _load_ts_codes_from_file(tscodes_file)

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

    def handle(self, *_args, **options):
        ts_codes = self._resolve_ts_codes(options)
        if not ts_codes:
            self.stdout.write("no ts_code resolved")
            return

        has_explicit_asof = bool(
            str(options.get("asof_date") or "").strip()
            or str(options.get("asof_start_date") or "").strip()
            or str(options.get("asof_end_date") or "").strip()
        )
        align_latest = not bool(options.get("no_align_latest"))
        if has_explicit_asof and align_latest:
            self.stdout.write(
                "explicit asof backfill args detected; disable latest-alignment for this run"
            )
            align_latest = False

        asof_dates = [None] if align_latest else _resolve_asof_dates(options)
        batch_key = str(options.get("batch_key") or "").strip() or datetime.now().strftime("monthly_%Y%m")
        run_key = datetime.now().strftime("sig_%Y%m%d_%H%M%S")
        sleep_ms = max(0, int(options.get("sleep_ms") or 0))
        strict = bool(options.get("strict"))
        model_version_arg = str(options.get("model_version") or "").strip()
        serving_slot = _normalize_serving_slot(options.get("serving_slot"))
        requested_anchor_mode = _normalize_anchor_mode(options.get("anchor_mode"))
        anchor_mode = "live_latest" if align_latest else requested_anchor_mode
        store_mode = _normalize_store_mode(options.get("store_mode"))
        target_report_types = _resolve_target_report_types(options.get("report_types"))
        persist_latest = store_mode in {"latest", "both"}
        persist_history = store_mode in {"history", "both"}

        pipeline_root = Path(__file__).resolve().parents[3]
        pipeline = EarningsForecastPipeline(config_path=pipeline_root / "configs" / "default.yaml")

        start = time.time()
        ok_count = 0
        fail_count = 0
        self.stdout.write(
            "refresh signal snapshot start: "
            f"symbols={len(ts_codes)} batch={batch_key} store_mode={store_mode} "
            f"model_version={model_version_arg or '<serving:' + serving_slot + '>'} "
            f"report_types={target_report_types} anchor_mode={anchor_mode} align_latest={align_latest}"
        )
        self.stdout.write(f"asof_dates={','.join([d.isoformat() if d is not None else 'current' for d in asof_dates])}")

        for asof_date in asof_dates:
            asof_label = asof_date.isoformat() if asof_date is not None else "current"
            self.stdout.write(f"asof replay start: {asof_label}")
            for idx, code in enumerate(ts_codes, start=1):
                symbol_start = time.time()
                self.stdout.write(f"processing: {idx}/{len(ts_codes)} ts_code={code} asof_date={asof_label}")
                for requested_report_type in target_report_types:
                    rt_start = time.time()
                    try:
                        if requested_report_type == "FUSION":
                            result = pipeline.predict_fusion(
                                code,
                                model_version=model_version_arg or None,
                                serving_slot=serving_slot,
                                anchor_mode=anchor_mode,
                                asof_date=asof_date,
                            )
                        elif requested_report_type == "LATEST":
                            result = pipeline.predict(
                                code,
                                model_version=model_version_arg or None,
                                serving_slot=serving_slot,
                                requested_report_type=None,
                                anchor_mode=anchor_mode,
                                asof_date=asof_date,
                            )
                        else:
                            result = pipeline.predict(
                                code,
                                model_version=model_version_arg or None,
                                serving_slot=serving_slot,
                                requested_report_type=requested_report_type,
                                anchor_mode=anchor_mode,
                                asof_date=asof_date,
                            )
                        _enrich_target_market_cap_fields(result, code)
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
                            "asof_date": _parse_asof_date(result.get("trade_date") or asof_date),
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
                            history_payload = dict(payload)
                            history_payload.update(
                                {
                                    "snapshot_source": str(result.get("model_source") or "")[:32],
                                    "anchor_mode": str(anchor_mode or "")[:16],
                                    "market_regime": str(
                                        result.get("market_regime")
                                        or result.get("regime")
                                        or ""
                                    )[:16],
                                    "run_key": run_key,
                                    "is_backfill": asof_date is not None,
                                    "backfill_run_id": f"{batch_key}:{asof_label}" if asof_date is not None else "",
                                }
                            )
                            _save_history_snapshot(ts_code=code, payload=history_payload)
                        ok_count += 1
                        rt_elapsed = round(time.time() - rt_start, 2)
                        resolved_asof = payload.get("asof_date")
                        resolved_financial_end_date = _parse_asof_date(
                            result.get("financial_end_date")
                            or result.get("served_financial_end_date")
                            or result.get("latest_available_end_date")
                        )
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
                                f"asof_date={asof_label} "
                                f"resolved_trade_date={resolved_asof or 'UNKNOWN'} "
                                f"resolved_fin_end={resolved_financial_end_date or 'UNKNOWN'} "
                                f"rt_elapsed_sec={rt_elapsed}"
                            )
                        )
                    except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
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
                            "asof_date": asof_date,
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
                            failed_history_payload = dict(failed_payload)
                            failed_history_payload.update(
                                {
                                    "snapshot_source": "",
                                    "anchor_mode": str(anchor_mode or "")[:16],
                                    "market_regime": "",
                                    "run_key": run_key,
                                    "is_backfill": asof_date is not None,
                                    "backfill_run_id": f"{batch_key}:{asof_label}" if asof_date is not None else "",
                                }
                            )
                            _save_history_snapshot(ts_code=code, payload=failed_history_payload)
                        rt_elapsed = round(time.time() - rt_start, 2)
                        self.stderr.write(
                            f"[warn] {code} report_type={requested_report_type} asof_date={asof_label} rt_elapsed_sec={rt_elapsed} failed: {safe_err}"
                        )
                        if strict:
                            raise

                symbol_elapsed = round(time.time() - symbol_start, 2)
                self.stdout.write(f"[symbol] {code} asof_date={asof_label} elapsed_sec={symbol_elapsed}")

                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000.0)
                if idx % 100 == 0 or idx == len(ts_codes):
                    self.stdout.write(f"progress: {idx}/{len(ts_codes)} ok={ok_count} fail={fail_count} asof_date={asof_label}")

            self.stdout.write(f"asof replay done: {asof_label}")

        elapsed = round(time.time() - start, 2)
        self.stdout.write(f"refresh signal snapshot done: total={len(ts_codes)} ok={ok_count} fail={fail_count} elapsed_sec={elapsed} batch={batch_key}")
        if fail_count > 0 and ok_count == 0:
            raise CommandError(
                "refresh_signal_snapshot finished with all predictions failed "
                f"(ok={ok_count}, fail={fail_count})."
            )
