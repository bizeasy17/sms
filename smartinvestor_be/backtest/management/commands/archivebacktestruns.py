import json
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from backtest.models import TraditionalBacktestRun, TraditionalBacktestScanTask


class Command(BaseCommand):
    help = "Archive old traditional backtest runs/scan tasks and keep recent working-set data."

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
        run_queryset = (
            TraditionalBacktestRun.objects.filter(strategy_name__in=strategy_names, updated_at__lt=cutoff_dt)
            .order_by("updated_at", "id")
        )
        scan_task_queryset = (
            TraditionalBacktestScanTask.objects.filter(strategy_name__in=strategy_names, updated_at__lt=cutoff_dt)
            .order_by("updated_at", "id")
        )
        runs = list(run_queryset)
        scan_tasks = list(scan_task_queryset)

        self.stdout.write(
            f"archivebacktestruns start: retention_days={retention_days} cutoff={cutoff_dt.isoformat()} run_candidates={len(runs)} scan_task_candidates={len(scan_tasks)} dry_run={dry_run}"
        )

        base_dir = Path(settings.BASE_DIR)
        archive_root = base_dir / "output" / "archive"
        stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        archive_batch_dir = archive_root / f"db_backtest_runs_cleanup_{stamp}"
        archived_db_file = archive_batch_dir / "traditional_backtest_runs.json"
        archived_scan_task_db_file = archive_batch_dir / "traditional_backtest_scan_tasks.json"

        move_total = 0
        move_ok = 0
        move_missing = 0
        move_failed = 0
        orphan_file_total = 0
        orphan_file_ok = 0
        orphan_file_failed = 0
        deletable_ids = []
        archived_rows = []
        moved_src_paths = set()

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
                            moved_src_paths.add(str(src_path))
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

        # Also archive orphan result files older than retention window, even without DB rows.
        orphan_file_rows = []
        for strategy_name in strategy_names:
            src_dir = base_dir / "output" / "backtests" / strategy_name
            if not src_dir.exists() or not src_dir.is_dir():
                continue

            for src_path in sorted(src_dir.glob(f"{strategy_name}_*.json")):
                if not src_path.is_file():
                    continue
                src_resolved = str(src_path.resolve())
                if src_resolved in moved_src_paths:
                    continue

                mtime_dt = timezone.make_aware(
                    timezone.datetime.fromtimestamp(src_path.stat().st_mtime),
                    timezone.get_current_timezone(),
                )
                if mtime_dt >= cutoff_dt:
                    continue

                orphan_file_total += 1
                strategy_dir = archive_root / "backtests" / strategy_name
                dest_path = strategy_dir / src_path.name
                if dest_path.exists():
                    dest_path = strategy_dir / f"{src_path.stem}_orphan{src_path.suffix}"

                row = {
                    "strategy_name": strategy_name,
                    "src": str(src_path),
                    "dest": str(dest_path),
                    "updated_at": mtime_dt.isoformat(),
                    "status": "",
                    "error": "",
                }
                if dry_run:
                    orphan_file_ok += 1
                    row["status"] = "would_move"
                else:
                    try:
                        strategy_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src_path), str(dest_path))
                        orphan_file_ok += 1
                        row["status"] = "moved"
                    except OSError as exc:
                        orphan_file_failed += 1
                        row["status"] = "move_failed"
                        row["error"] = str(exc)
                orphan_file_rows.append(row)

        archived_scan_task_rows = []
        deletable_scan_task_ids = []
        for task in scan_tasks:
            row = {
                "id": int(task.id),
                "task_key": task.task_key,
                "status": task.status,
                "strategy_name": task.strategy_name,
                "total_jobs": int(task.total_jobs or 0),
                "completed_jobs": int(task.completed_jobs or 0),
                "failed_jobs": int(task.failed_jobs or 0),
                "created_at": task.created_at.isoformat() if task.created_at else "",
                "updated_at": task.updated_at.isoformat() if task.updated_at else "",
                "params_json": task.params_json or {},
                "result_json": task.result_json or {},
                "error_message": task.error_message or "",
            }
            deletable_scan_task_ids.append(int(task.id))
            archived_scan_task_rows.append(row)

        if not runs and not scan_tasks and orphan_file_total == 0:
            self.stdout.write("no candidates")
            return

        if dry_run:
            self.stdout.write(
                f"dry-run summary: run_candidates={len(runs)} run_deletable={len(deletable_ids)} scan_task_candidates={len(scan_tasks)} scan_task_deletable={len(deletable_scan_task_ids)} file_move_total={move_total} file_move_ok={move_ok} file_missing={move_missing} file_move_failed={move_failed} orphan_file_total={orphan_file_total} orphan_file_ok={orphan_file_ok} orphan_file_failed={orphan_file_failed}"
            )
            return

        archive_batch_dir.mkdir(parents=True, exist_ok=True)
        archived_db_file.write_text(
            json.dumps(archived_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        archived_scan_task_db_file.write_text(
            json.dumps(archived_scan_task_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        orphan_file_report = archive_batch_dir / "traditional_backtest_orphan_files.json"
        orphan_file_report.write_text(
            json.dumps(orphan_file_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        deleted_runs = 0
        if deletable_ids:
            deleted_runs, _ = TraditionalBacktestRun.objects.filter(id__in=deletable_ids).delete()

        deleted_scan_tasks = 0
        if deletable_scan_task_ids:
            deleted_scan_tasks, _ = TraditionalBacktestScanTask.objects.filter(id__in=deletable_scan_task_ids).delete()

        self.stdout.write(
            f"archivebacktestruns done: archived_runs_json={archived_db_file} archived_scan_tasks_json={archived_scan_task_db_file} orphan_file_report={orphan_file_report} deleted_runs={deleted_runs} deleted_scan_tasks={deleted_scan_tasks} run_candidates={len(runs)} scan_task_candidates={len(scan_tasks)} file_move_total={move_total} file_move_ok={move_ok} file_missing={move_missing} file_move_failed={move_failed} orphan_file_total={orphan_file_total} orphan_file_ok={orphan_file_ok} orphan_file_failed={orphan_file_failed}"
        )
