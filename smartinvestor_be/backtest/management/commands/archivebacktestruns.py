import json
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from backtest.models import TraditionalBacktestRun


class Command(BaseCommand):
    help = "Archive old traditional backtest runs and keep recent working-set runs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retention-days",
            type=int,
            default=14,
            help="Keep runs updated within N days in working set. Default: 14",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview archive candidates without moving files or deleting DB rows.",
        )

    def handle(self, *args, **options):
        retention_days = max(1, int(options.get("retention_days") or 14))
        dry_run = bool(options.get("dry_run"))
        cutoff_dt = timezone.now() - timedelta(days=retention_days)

        strategy_names = ["traditional_value_exit", "traditional_value_exit_account"]
        queryset = (
            TraditionalBacktestRun.objects.filter(strategy_name__in=strategy_names, updated_at__lt=cutoff_dt)
            .order_by("updated_at", "id")
        )
        runs = list(queryset)

        self.stdout.write(
            f"archivebacktestruns start: retention_days={retention_days} cutoff={cutoff_dt.isoformat()} candidates={len(runs)} dry_run={dry_run}"
        )

        if not runs:
            self.stdout.write("no candidates")
            return

        base_dir = Path(settings.BASE_DIR)
        archive_root = base_dir / "output" / "archive"
        stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        archive_batch_dir = archive_root / f"db_backtest_runs_cleanup_{stamp}"
        archived_db_file = archive_batch_dir / "traditional_backtest_runs.json"

        move_total = 0
        move_ok = 0
        move_missing = 0
        move_failed = 0
        deletable_ids = []
        archived_rows = []

        for run in runs:
            row = {
                "id": int(run.id),
                "run_key": run.run_key,
                "batch_key": run.batch_key,
                "strategy_name": run.strategy_name,
                "status": run.status,
                "scope": run.scope,
                "market": run.market,
                "start_date": run.start_date.isoformat() if run.start_date else "",
                "end_date": run.end_date.isoformat() if run.end_date else "",
                "created_at": run.created_at.isoformat() if run.created_at else "",
                "updated_at": run.updated_at.isoformat() if run.updated_at else "",
                "result_file": run.result_file or "",
                "params_json": run.params_json or {},
                "summary_json": run.summary_json or {},
                "result_json": run.result_json or {},
                "error_message": run.error_message or "",
                "archive_meta": {},
            }

            result_file_text = str(run.result_file or "").strip()
            can_delete = True
            if result_file_text:
                move_total += 1
                src_path = (base_dir / result_file_text).resolve()
                strategy_dir = archive_root / "backtests" / str(run.strategy_name or "traditional_value_exit")
                dest_path = strategy_dir / src_path.name

                row["archive_meta"]["result_file_src"] = str(src_path)
                row["archive_meta"]["result_file_dest"] = str(dest_path)

                if not src_path.exists() or not src_path.is_file():
                    move_missing += 1
                    row["archive_meta"]["result_file_status"] = "missing"
                else:
                    # Avoid accidental overwrite when file names collide.
                    if dest_path.exists():
                        stem = dest_path.stem
                        suffix = dest_path.suffix
                        dest_path = strategy_dir / f"{stem}_run{run.id}{suffix}"
                        row["archive_meta"]["result_file_dest"] = str(dest_path)

                    if dry_run:
                        move_ok += 1
                        row["archive_meta"]["result_file_status"] = "would_move"
                    else:
                        try:
                            strategy_dir.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(src_path), str(dest_path))
                            move_ok += 1
                            row["archive_meta"]["result_file_status"] = "moved"
                            row["result_file"] = str(dest_path.relative_to(base_dir)).replace("\\", "/")
                        except OSError as exc:
                            move_failed += 1
                            can_delete = False
                            row["archive_meta"]["result_file_status"] = "move_failed"
                            row["archive_meta"]["result_file_error"] = str(exc)

            if can_delete:
                deletable_ids.append(int(run.id))
            archived_rows.append(row)

        if dry_run:
            self.stdout.write(
                f"dry-run summary: candidates={len(runs)} deletable={len(deletable_ids)} file_move_total={move_total} file_move_ok={move_ok} file_missing={move_missing} file_move_failed={move_failed}"
            )
            return

        archive_batch_dir.mkdir(parents=True, exist_ok=True)
        archived_db_file.write_text(
            json.dumps(archived_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        deleted = 0
        if deletable_ids:
            deleted, _ = TraditionalBacktestRun.objects.filter(id__in=deletable_ids).delete()

        self.stdout.write(
            f"archivebacktestruns done: archived_json={archived_db_file} deleted={deleted} candidates={len(runs)} file_move_total={move_total} file_move_ok={move_ok} file_missing={move_missing} file_move_failed={move_failed}"
        )
