import json
from pathlib import Path
from uuid import uuid4
import zlib

from django.conf import settings
from django.core.management.base import BaseCommand

from earnings_forecast.models import EarningsBacktestRun


def _normalize_run_key(value):
    text = str(value or "").strip()
    if not text:
        return f"imp_{uuid4().hex[:24]}"
    if len(text) <= 64:
        return text
    suffix = f"_{zlib.crc32(text.encode('utf-8')) & 0xFFFFFFFF:08x}"
    return text[: 64 - len(suffix)] + suffix


def _normalize_batch_key(value):
    text = str(value or "").strip()
    if not text:
        return "imported"
    return text[:64]


def _normalize_predictive_result(payload):
    if not isinstance(payload, dict):
        return None

    if isinstance(payload.get("metrics"), list) and "pool_size" in payload:
        return payload, payload.get("params") if isinstance(payload.get("params"), dict) else {}

    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("metrics"), list) and "pool_size" in result:
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        return result, params

    return None


def _build_summary(result):
    metrics = result.get("metrics") if isinstance(result.get("metrics"), list) else []
    avg_annualized = 0.0
    if metrics:
        avg_annualized = sum(float(item.get("annualized_return") or 0.0) for item in metrics) / len(metrics)
    return {
        "years": len(metrics),
        "avg_annualized_return": avg_annualized,
        "pool_size": int(result.get("pool_size") or 0),
    }


class Command(BaseCommand):
    help = "Import historical predictive valuation backtest JSON files into database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--glob",
            action="append",
            dest="globs",
            default=[],
            help="Glob pattern under BASE_DIR, can be provided multiple times.",
        )
        parser.add_argument("--dry-run", action="store_true", default=False)
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *_args, **options):
        base_dir = Path(settings.BASE_DIR)
        patterns = options.get("globs") or [
            "outputs/*backtest*.json",
            "outputs/**/*backtest*.json",
        ]
        dry_run = bool(options.get("dry_run"))
        limit = max(0, int(options.get("limit") or 0))

        candidates = []
        for pattern in patterns:
            candidates.extend(base_dir.glob(str(pattern)))
        files = sorted({item for item in candidates if item.is_file()})
        if limit:
            files = files[:limit]

        created = 0
        updated = 0
        skipped = 0
        failed = 0

        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                failed += 1
                self.stdout.write(f"WARN failed read: {path} ({exc})")
                continue

            normalized = _normalize_predictive_result(payload)
            if normalized is None:
                skipped += 1
                continue

            result, params = normalized
            batch_key = _normalize_batch_key(result.get("batch_key") or payload.get("batch_key") or "imported")
            run_key = str(payload.get("run_key") or "").strip()
            if not run_key:
                run_key = f"imp_{path.stem}_{uuid4().hex[:8]}"
            run_key = _normalize_run_key(run_key)

            summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else _build_summary(result)

            if not params:
                params = {
                    "batch_key": batch_key,
                    "min_score": result.get("min_score"),
                    "max_risk": result.get("max_risk"),
                    "report_type": result.get("report_type"),
                    "stop_mode": result.get("stop_mode"),
                    "global_stop_dd": result.get("global_stop_dd"),
                    "single_stop_dd": result.get("single_stop_dd"),
                }

            if dry_run:
                self.stdout.write(f"dry-run import: {path}")
                continue

            _, was_created = EarningsBacktestRun.objects.update_or_create(  # type: ignore[attr-defined]
                run_key=run_key,
                defaults={
                    "batch_key": batch_key,
                    "status": "success",
                    "params": params,
                    "summary": summary,
                    "result": result,
                    "error_message": "",
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            f"done files={len(files)} created={created} updated={updated} skipped={skipped} failed={failed} dry_run={dry_run}"
        )
