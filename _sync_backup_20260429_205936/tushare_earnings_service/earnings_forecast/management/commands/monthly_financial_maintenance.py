from __future__ import annotations

import time
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Monthly financial maintenance pipeline: sync endpoint tables first, "
        "then rebuild financial panel and latest snapshot."
    )

    def add_arguments(self, parser):
        parser.add_argument("--scope", type=str, default="60,00,30,68", help="ALL or ts_code prefixes")
        parser.add_argument(
            "--apis",
            type=str,
            default="income,balancesheet_vip,cashflow_vip,forecast_vip,express_vip,fina_indicator_vip,dividend",
            help="Comma separated financial endpoints for sync_financials_direct",
        )
        parser.add_argument("--start-date", type=str, help="Optional YYYYMMDD for sync window")
        parser.add_argument("--end-date", type=str, help="Optional YYYYMMDD for sync window")
        parser.add_argument("--limit", type=int, help="Limit symbols for smoke tests")
        parser.add_argument("--batch-size", type=int, default=1000, help="Bulk upsert batch size")
        parser.add_argument("--api-limit", type=int, default=2000, help="Tushare page size")
        parser.add_argument("--max-pages", type=int, default=200, help="Max pages per endpoint/symbol")
        parser.add_argument("--resume", type=str, help="Resume from ts_code")
        parser.add_argument(
            "--latest-only",
            action="store_true",
            default=True,
            help="Fetch latest page per endpoint/symbol during monthly run",
        )
        parser.add_argument(
            "--skip-sync",
            action="store_true",
            default=False,
            help="Skip endpoint sync and only rebuild panel/snapshot",
        )
        parser.add_argument(
            "--skip-panel",
            action="store_true",
            default=False,
            help="Skip build_financial_feature_panel",
        )
        parser.add_argument(
            "--skip-snapshot",
            action="store_true",
            default=False,
            help="Skip build_financial_feature_snapshot",
        )

    def handle(self, *args, **options):
        started = time.time()
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        scope = str(options.get("scope") or "ALL").strip()
        apis = str(options.get("apis") or "").strip()
        start_date = str(options.get("start_date") or "").strip() or None
        end_date = str(options.get("end_date") or "").strip() or None
        limit = options.get("limit")
        batch_size = max(100, int(options.get("batch_size") or 1000))
        api_limit = max(100, int(options.get("api_limit") or 2000))
        max_pages = max(1, int(options.get("max_pages") or 200))
        resume = str(options.get("resume") or "").strip() or None
        latest_only = bool(options.get("latest_only"))
        skip_sync = bool(options.get("skip_sync"))
        skip_panel = bool(options.get("skip_panel"))
        skip_snapshot = bool(options.get("skip_snapshot"))

        self.stdout.write(
            self.style.SUCCESS(
                "monthly financial maintenance start: "
                f"run_id={run_id} scope={scope} apis={apis} latest_only={latest_only}"
            )
        )

        if not skip_sync:
            sync_kwargs = {
                "scope": scope,
                "apis": apis,
                "api_limit": api_limit,
                "max_pages": max_pages,
                "batch_size": batch_size,
            }
            if start_date:
                sync_kwargs["start_date"] = start_date
            if end_date:
                sync_kwargs["end_date"] = end_date
            if limit is not None:
                sync_kwargs["limit"] = int(limit)
            if resume:
                sync_kwargs["resume"] = resume
            if latest_only:
                sync_kwargs["latest_only"] = True

            self.stdout.write("[step] sync_financials_direct")
            call_command("sync_financials_direct", **sync_kwargs)
        else:
            self.stdout.write("[skip] sync_financials_direct")

        if not skip_panel:
            panel_kwargs = {"batch_size": batch_size}
            if limit is not None:
                panel_kwargs["limit"] = int(limit)
            self.stdout.write("[step] build_financial_feature_panel")
            call_command("build_financial_feature_panel", **panel_kwargs)
        else:
            self.stdout.write("[skip] build_financial_feature_panel")

        if not skip_snapshot:
            snapshot_kwargs = {"batch_size": batch_size}
            if limit is not None:
                snapshot_kwargs["limit"] = int(limit)
            self.stdout.write("[step] build_financial_feature_snapshot")
            call_command("build_financial_feature_snapshot", **snapshot_kwargs)
        else:
            self.stdout.write("[skip] build_financial_feature_snapshot")

        elapsed = round(time.time() - started, 2)
        self.stdout.write(self.style.SUCCESS(f"monthly financial maintenance done: run_id={run_id} elapsed_sec={elapsed}"))
