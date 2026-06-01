import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from backtest.models import TraditionalBacktestRun


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    return None


def _is_traditional_payload(payload):
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("combined"), dict):
        return False
    if "by_year" not in payload:
        return False
    strategy = payload.get("strategy")
    if isinstance(strategy, dict):
        buy_rule = str(strategy.get("buy_rule") or "").strip().lower()
        sell_rule = str(strategy.get("sell_rule") or "").strip().lower()
        if "buy" in buy_rule and "sell" in sell_rule:
            return True
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    strategy_name = str(metadata.get("strategy") or "").strip().lower()
    return strategy_name == "traditional_value_exit"


class Command(BaseCommand):
    help = "Import historical traditional valuation backtest JSON files into database."

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
            "output/backtests/traditional_value_exit/*.json",
            "output/local_valuation_checks/traditional*.json",
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

            if not _is_traditional_payload(payload):
                skipped += 1
                continue

            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            strategy = payload.get("strategy") if isinstance(payload.get("strategy"), dict) else {}
            strategy_name = str(metadata.get("strategy") or "traditional_value_exit").strip() or "traditional_value_exit"
            run_key = path.stem
            summary_json = payload.get("combined") if isinstance(payload.get("combined"), dict) else {}

            try:
                result_file = str(path.relative_to(base_dir))
            except ValueError:
                result_file = str(path)

            defaults = {
                "batch_key": strategy_name,
                "strategy_name": strategy_name,
                "status": "success",
                "scope": str(strategy.get("scope") or "ALL"),
                "market": str(strategy.get("market") or "CN"),
                "start_date": _parse_date(strategy.get("start_date")),
                "end_date": _parse_date(strategy.get("end_date")),
                "params_json": strategy,
                "summary_json": summary_json,
                "result_json": payload,
                "result_file": result_file,
                "error_message": "",
            }

            if dry_run:
                self.stdout.write(f"dry-run import: {result_file}")
                continue

            _, was_created = TraditionalBacktestRun.objects.update_or_create(
                run_key=run_key,
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            f"done files={len(files)} created={created} updated={updated} skipped={skipped} failed={failed} dry_run={dry_run}"
        )
