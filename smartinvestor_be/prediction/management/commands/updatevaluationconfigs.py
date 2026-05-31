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
                    "kwargs": {
                        "mapping_only": True,
                        "request_interval": 0.45,
                    },
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
                    "kwargs": {
                        "params_only": True,
                        "sample_size": 3,
                        "request_interval": 0.45,
                    },
                }
            ],
        },
        "valuation_snapshot_prefill": {
            "enabled": True,
            "cadence_days": 30,
            "description": "Prefill valuation snapshots using prefix-batched full-market scopes to improve stock-pick latency.",
            "steps": [
                {
                    "command": "prefillvaluationsnapshot",
                    "kwargs": {
                        "scope": "60",
                        "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay",
                        "express_max_age_days": 180,
                        "profit_buckets": "both",
                        "request_interval": 0.2,
                    },
                },
                {
                    "command": "prefillvaluationsnapshot",
                    "kwargs": {
                        "scope": "68",
                        "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay",
                        "express_max_age_days": 180,
                        "profit_buckets": "both",
                        "request_interval": 0.2,
                    },
                },
                {
                    "command": "prefillvaluationsnapshot",
                    "kwargs": {
                        "scope": "00",
                        "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay",
                        "express_max_age_days": 180,
                        "profit_buckets": "both",
                        "request_interval": 0.2,
                    },
                },
                {
                    "command": "prefillvaluationsnapshot",
                    "kwargs": {
                        "scope": "30",
                        "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay",
                        "express_max_age_days": 180,
                        "profit_buckets": "both",
                        "request_interval": 0.2,
                    },
                },
                {
                    "command": "prefillvaluationsnapshot",
                    "kwargs": {
                        "scope": "8",
                        "methods": "sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay",
                        "express_max_age_days": 180,
                        "profit_buckets": "both",
                        "request_interval": 0.2,
                    },
                }
            ],
        },
        "keyword_rules_refresh": {
            "enabled": True,
            "cadence_days": 90,
            "description": "Refresh CITIC suggestions and apply high-confidence mappings.",
            "steps": [
                {
                    "command": "exportciticsuggestions",
                    "kwargs": {
                        "level": "L2",
                    },
                },
                {
                    "command": "applyciticsuggestions",
                    "kwargs": {
                        "min_similarity": 0.95,
                    },
                },
            ],
        },
    },
}


class Command(BaseCommand):
    help = "Run valuation config updates on a schedule (mapping, templates, keyword rules)."

    def add_arguments(self, parser):
        parser.add_argument("--market", type=str, default="CN", help="Market code, default CN")
        parser.add_argument(
            "--run-due",
            action="store_true",
            default=False,
            help="Run tasks that are due based on cadence and state file",
        )
        parser.add_argument(
            "--run-all",
            action="store_true",
            default=False,
            help="Run all enabled tasks regardless of cadence",
        )
        parser.add_argument(
            "--tasks",
            type=str,
            help="Comma-separated task names to run (overrides --run-due)",
        )
        parser.add_argument(
            "--today",
            type=str,
            help="Override current date (YYYY-MM-DD), useful for testing",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show plan only, do not execute commands or persist state",
        )
        parser.add_argument(
            "--init-config",
            action="store_true",
            default=False,
            help="Create default schedule config file if missing",
        )

    def handle(self, *_args, **options):
        market = options["market"]
        base_dir = Path(settings.BASE_DIR) / "static" / "valuation_config"
        config_path = base_dir / f"update_schedule_{market}.json"
        state_path = base_dir / f"update_schedule_state_{market}.json"

        if options["init_config"] and not config_path.exists():
            self._write_json(config_path, self._default_schedule_for_market(market))
            self.stdout.write(self.style.SUCCESS(f"Initialized schedule config: {config_path}"))

        if not config_path.exists():
            raise CommandError(
                f"Schedule config not found: {config_path}. Run with --init-config once."
            )

        config = self._read_json(config_path)
        state = self._read_json(state_path) if state_path.exists() else {"market": market, "tasks": {}, "history": []}

        today = self._resolve_today(options.get("today"))
        plan = self._build_plan(config=config, state=state, today=today)

        requested_tasks = self._parse_tasks(options.get("tasks"))
        run_due = options["run_due"]
        run_all = options["run_all"]
        dry_run = options["dry_run"]

        if run_all:
            selected = [item["task_name"] for item in plan if item["enabled"]]
        elif requested_tasks:
            selected = requested_tasks
        elif run_due:
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

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run mode: no command executed, no state updated."))
            return

        failures = 0
        for task_name in selected:
            task_cfg = config.get("tasks", {}).get(task_name, {})
            if not task_cfg.get("enabled", True):
                self.stdout.write(self.style.WARNING(f"Skip disabled task: {task_name}"))
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

        self.stdout.write(self.style.SUCCESS("All selected update tasks completed."))

    @staticmethod
    def _default_schedule_for_market(market):
        schedule = deepcopy(DEFAULT_SCHEDULE)
        schedule["market"] = market
        return schedule

    @staticmethod
    def _parse_tasks(task_string):
        if not task_string:
            return []
        return [item.strip() for item in task_string.split(",") if item.strip()]

    @staticmethod
    def _resolve_today(raw_today):
        if not raw_today:
            return date.today()
        try:
            return datetime.strptime(raw_today, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("--today must be in format YYYY-MM-DD") from exc

    def _build_plan(self, config, state, today):
        plan = []
        task_states = state.get("tasks", {})
        for task_name, task_cfg in config.get("tasks", {}).items():
            cadence_days = int(task_cfg.get("cadence_days", 0) or 0)
            enabled = bool(task_cfg.get("enabled", True))
            last_success_raw = (task_states.get(task_name, {}) or {}).get("last_success")
            last_success_date = self._parse_date(last_success_raw)
            due_in_days = 0
            is_due = False
            if cadence_days <= 0:
                is_due = True
                due_in_days = 0
            elif last_success_date is None:
                is_due = True
                due_in_days = 0
            else:
                elapsed = (today - last_success_date).days
                is_due = elapsed >= cadence_days
                due_in_days = max(cadence_days - elapsed, 0)

            plan.append(
                {
                    "task_name": task_name,
                    "enabled": enabled,
                    "cadence_days": cadence_days,
                    "is_due": is_due,
                    "due_in_days": due_in_days,
                    "last_success": last_success_raw,
                    "description": task_cfg.get("description") or "",
                    "steps": task_cfg.get("steps", []),
                }
            )
        return plan

    def _run_task(self, task_name, task_cfg):
        self.stdout.write(self.style.WARNING(f"Running task: {task_name}"))
        start = time.time()
        try:
            for idx, step in enumerate(task_cfg.get("steps", []), start=1):
                command = step.get("command")
                kwargs = step.get("kwargs", {})
                if not command:
                    raise CommandError(f"Task {task_name} step {idx} missing command")
                self.stdout.write(
                    f"  Step {idx}: {command} kwargs={json.dumps(kwargs, ensure_ascii=False, sort_keys=True)}"
                )
                call_command(command, **kwargs)
            cost = round(time.time() - start, 2)
            self.stdout.write(self.style.SUCCESS(f"Task finished: {task_name} ({cost}s)"))
            return True, None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            cost = round(time.time() - start, 2)
            self.stdout.write(self.style.ERROR(f"Task failed: {task_name} ({cost}s): {exc}"))
            return False, str(exc)

    @staticmethod
    def _update_state(state, task_name, today, ok, err):
        task_states = state.setdefault("tasks", {})
        item = task_states.setdefault(task_name, {})
        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        item["last_attempt_at"] = now_iso
        item["last_status"] = "success" if ok else "failed"
        if ok:
            item["last_success"] = today.isoformat()
            item["last_error"] = None
        else:
            item["last_error"] = err

        history = state.setdefault("history", [])
        history.append(
            {
                "task": task_name,
                "date": today.isoformat(),
                "attempt_at": now_iso,
                "status": item["last_status"],
                "error": item.get("last_error"),
            }
        )

    def _print_plan(self, plan, selected, today):
        self.stdout.write(f"Schedule date: {today.isoformat()}")
        for item in plan:
            marker = "*" if item["task_name"] in selected else " "
            self.stdout.write(
                f"{marker} {item['task_name']} enabled={item['enabled']} due={item['is_due']} cadence_days={item['cadence_days']} last_success={item['last_success']} due_in_days={item['due_in_days']}"
            )
            if item["description"]:
                self.stdout.write(f"    {item['description']}")
            for idx, step in enumerate(item.get("steps", []), start=1):
                command = step.get("command")
                kwargs = step.get("kwargs", {})
                self.stdout.write(
                    f"    Step {idx}: {command} kwargs={json.dumps(kwargs, ensure_ascii=False, sort_keys=True)}"
                )

    @staticmethod
    def _read_json(path):
        with path.open("r", encoding="utf-8") as file_obj:
            return json.load(file_obj)

    @staticmethod
    def _write_json(path, data):
        with path.open("w", encoding="utf-8") as file_obj:
            json.dump(data, file_obj, ensure_ascii=False, indent=2)

    @staticmethod
    def _parse_date(raw):
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None
