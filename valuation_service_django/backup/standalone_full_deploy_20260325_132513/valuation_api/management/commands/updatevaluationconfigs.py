import json
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


DEFAULT_SCHEDULE = {
    "version": "1.0",
    "market": "CN",
    "tasks": {
        "sw_mapping_sync": {
            "enabled": True,
            "cadence_days": 14,
            "description": "Refresh SW hierarchy mapping file.",
            "steps": [
                {
                    "command": "syncswvaluation",
                    "kwargs": {"mapping_only": True, "request_interval": 0.45},
                }
            ],
        },
        "sw_params_refresh": {
            "enabled": True,
            "cadence_days": 30,
            "description": "Refresh SW valuation parameter templates.",
            "steps": [
                {
                    "command": "syncswvaluation",
                    "kwargs": {"params_only": True, "sample_size": 3, "history_years": "3,5,10", "history_quantile": 0.5, "history_min_samples": 120, "request_interval": 0.45},
                }
            ],
        },
        "sw_params_refresh_reference": {
            "enabled": True,
            "cadence_days": 30,
            "description": "Refresh 5/10/20 SW valuation parameter templates as reference/fallback.",
            "steps": [
                {
                    "command": "syncswvaluation",
                    "kwargs": {"params_only": True, "sample_size": 3, "history_years": "5,10,20", "history_quantile": 0.5, "history_min_samples": 120, "params_output_suffix": "ref_5_10_20", "request_interval": 0.45},
                }
            ],
        },
        "valuation_snapshot_prefill": {
            "enabled": True,
            "cadence_days": 30,
            "description": "Prefill valuation snapshots using prefix-batched full-market scopes.",
            "steps": [
                {"command": "prefillvaluationsnapshot", "kwargs": {"scope": "60", "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm", "express_max_age_days": 180, "request_interval": 0.2}},
                {"command": "prefillvaluationsnapshot", "kwargs": {"scope": "68", "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm", "express_max_age_days": 180, "request_interval": 0.2}},
                {"command": "prefillvaluationsnapshot", "kwargs": {"scope": "00", "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm", "express_max_age_days": 180, "request_interval": 0.2}},
                {"command": "prefillvaluationsnapshot", "kwargs": {"scope": "30", "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm", "express_max_age_days": 180, "request_interval": 0.2}},
                {"command": "prefillvaluationsnapshot", "kwargs": {"scope": "8", "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm", "express_max_age_days": 180, "request_interval": 0.2}},
            ],
        },
        "daily_market_data_sync": {
            "enabled": True,
            "cadence_days": 1,
            "description": "Sync trading/fundamental incrementally from ETL source starting next trade date.",
            "steps": [
                {
                    "command": "syncdailymarketdata",
                    "kwargs": {
                        "source_db_name": "smartinvestor_etl",
                        "source_table_prefix": "stockdata",
                        "trading_freq": "D",
                        "fundamental_freq": "D",
                    },
                }
            ],
        },
        "express_vip_sync": {
            "enabled": False,
            "cadence_days": 1,
            "description": "Sync local express vip cache for local-first valuation path.",
            "steps": [
                {
                    "command": "syncexpressvip",
                    "kwargs": {
                        "limit_per_stock": 8,
                        "request_interval": 0.25,
                    },
                }
            ],
        },
        "keyword_rules_refresh": {
            "enabled": True,
            "cadence_days": 90,
            "description": "Refresh CITIC suggestions and apply high-confidence mappings.",
            "steps": [
                {"command": "exportciticsuggestions", "kwargs": {"level": "L2"}},
                {"command": "applyciticsuggestions", "kwargs": {"min_similarity": 0.95}},
            ],
        },
    },
}


class Command(BaseCommand):
    help = "Run valuation update tasks on a schedule (mapping, templates, snapshot prefill)."

    def add_arguments(self, parser):
        parser.add_argument("--market", type=str, default="CN")
        parser.add_argument("--run-due", action="store_true", default=False)
        parser.add_argument("--run-all", action="store_true", default=False)
        parser.add_argument("--tasks", type=str, help="Comma-separated task names to run")
        parser.add_argument("--today", type=str, help="Override current date YYYY-MM-DD")
        parser.add_argument("--dry-run", action="store_true", default=False)
        parser.add_argument("--init-config", action="store_true", default=False)

    def handle(self, *_args, **options):
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        base_dir = Path(settings.BASE_DIR) / "static" / "valuation_config"
        config_path = base_dir / f"update_schedule_{market}.json"
        state_path = base_dir / f"update_schedule_state_{market}.json"

        if options.get("init_config") and not config_path.exists():
            self._write_json(config_path, self._default_schedule_for_market(market))
            self.stdout.write(f"Initialized schedule config: {config_path}")

        if not config_path.exists():
            raise CommandError(f"Schedule config not found: {config_path}. Run with --init-config once.")

        config = self._read_json(config_path)
        state = self._read_json(state_path) if state_path.exists() else {"market": market, "tasks": {}, "history": []}
        today = self._resolve_today(options.get("today"))
        plan = self._build_plan(config=config, state=state, today=today)

        requested_tasks = self._parse_tasks(options.get("tasks"))
        if options.get("run_all"):
            selected = [item["task_name"] for item in plan if item["enabled"]]
        elif requested_tasks:
            selected = requested_tasks
        elif options.get("run_due"):
            selected = [item["task_name"] for item in plan if item["enabled"] and item["is_due"]]
        else:
            selected = []

        self._print_plan(plan=plan, selected=set(selected), today=today)
        if not selected:
            self.stdout.write("No task selected for execution.")
            return

        unknown = [task for task in selected if task not in {item["task_name"] for item in plan}]
        if unknown:
            raise CommandError(f"Unknown task name(s): {', '.join(unknown)}")

        if options.get("dry_run"):
            self.stdout.write("Dry run mode: no command executed, no state updated.")
            return

        failures = 0
        for task_name in selected:
            task_cfg = config.get("tasks", {}).get(task_name, {})
            if not task_cfg.get("enabled", True):
                self.stdout.write(f"Skip disabled task: {task_name}")
                continue
            ok, err = self._run_task(task_name=task_name, task_cfg=task_cfg)
            self._update_state(state=state, task_name=task_name, today=today, ok=ok, err=err)
            if not ok:
                failures += 1

        state["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state["market"] = market
        state["history"] = state.get("history", [])[-120:]
        self._write_json(state_path, state)
        self.stdout.write(f"State saved: {state_path}")

        if failures:
            raise CommandError(f"Completed with {failures} failed task(s).")
        self.stdout.write("All selected update tasks completed.")

    @staticmethod
    def _default_schedule_for_market(market):
        schedule = deepcopy(DEFAULT_SCHEDULE)
        schedule["market"] = market
        return schedule

    @staticmethod
    def _parse_tasks(task_string):
        if not task_string:
            return []
        return [item.strip() for item in str(task_string).split(",") if item.strip()]

    @staticmethod
    def _resolve_today(today_override):
        if not today_override:
            return date.today()
        try:
            return datetime.strptime(str(today_override), "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid --today: {today_override}") from exc

    def _build_plan(self, config, state, today):
        plan = []
        state_tasks = state.get("tasks", {})
        for task_name, task_cfg in (config.get("tasks") or {}).items():
            enabled = bool(task_cfg.get("enabled", True))
            cadence_days = int(task_cfg.get("cadence_days", 0) or 0)
            task_state = state_tasks.get(task_name, {})
            last_run_text = task_state.get("last_success_date") or task_state.get("last_run_date")
            last_run_date = None
            if last_run_text:
                try:
                    last_run_date = datetime.strptime(str(last_run_text), "%Y-%m-%d").date()
                except ValueError:
                    last_run_date = None
            days_since = None if last_run_date is None else (today - last_run_date).days
            is_due = enabled and (last_run_date is None or cadence_days <= 0 or days_since >= cadence_days)
            plan.append(
                {
                    "task_name": task_name,
                    "enabled": enabled,
                    "cadence_days": cadence_days,
                    "last_run_date": last_run_date.isoformat() if last_run_date else None,
                    "days_since": days_since,
                    "is_due": is_due,
                    "description": task_cfg.get("description"),
                }
            )
        return plan

    def _print_plan(self, plan, selected, today):
        self.stdout.write(f"Schedule date: {today.isoformat()}")
        for item in plan:
            marker = "*" if item["task_name"] in selected else "-"
            self.stdout.write(
                f"{marker} {item['task_name']}: enabled={item['enabled']} due={item['is_due']} cadence_days={item['cadence_days']} last_run={item['last_run_date']}"
            )

    def _run_task(self, task_name, task_cfg):
        self.stdout.write(f"Running task: {task_name}")
        for idx, step in enumerate(task_cfg.get("steps") or [], start=1):
            command_name = step.get("command")
            kwargs = step.get("kwargs") or {}
            self.stdout.write(f"  step[{idx}]: {command_name} {kwargs}")
            started_at = time.time()
            try:
                call_command(command_name, **kwargs)
            except (CommandError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                self.stderr.write(f"Task {task_name} failed on step {idx}: {exc}")
                return False, str(exc)
            elapsed = time.time() - started_at
            self.stdout.write(f"  step[{idx}] done in {elapsed:.2f}s")
        return True, None

    @staticmethod
    def _update_state(state, task_name, today, ok, err=None):
        tasks = state.setdefault("tasks", {})
        task_state = tasks.setdefault(task_name, {})
        task_state["last_run_date"] = today.isoformat()
        task_state["last_status"] = "ok" if ok else "error"
        task_state["last_error"] = err
        if ok:
            task_state["last_success_date"] = today.isoformat()
        history = state.setdefault("history", [])
        history.append(
            {
                "task_name": task_name,
                "date": today.isoformat(),
                "status": "ok" if ok else "error",
                "error": err,
            }
        )

    @staticmethod
    def _read_json(path):
        with path.open("r", encoding="utf-8") as file_obj:
            return json.load(file_obj)

    @staticmethod
    def _write_json(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)
            file_obj.write("\n")