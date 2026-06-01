from __future__ import annotations

import argparse
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run backtesting jobs from CLI (scaffold command)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--config",
            type=str,
            default="",
            help="Path to backtesting config file (YAML/JSON).",
        )
        parser.add_argument(
            "--strategy",
            type=str,
            default="",
            help="Strategy name to run, e.g. sma_cross.",
        )
        parser.add_argument(
            "--symbol",
            type=str,
            default="",
            help="Single symbol to backtest, e.g. 600519.SH.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="Backtest start date, format: YYYY-MM-DD.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="",
            help="Backtest end date, format: YYYY-MM-DD.",
        )
        parser.add_argument(
            "--cash",
            type=float,
            default=100000.0,
            help="Initial cash amount.",
        )
        parser.add_argument(
            "--commission",
            type=float,
            default=0.001,
            help="Per-trade commission ratio.",
        )
        parser.add_argument(
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Validate input only, do not execute backtest.",
        )

    def handle(self, *args, **options):
        config = str(options.get("config") or "").strip()
        strategy = str(options.get("strategy") or "").strip()
        symbol = str(options.get("symbol") or "").strip().upper()
        start_date = str(options.get("start_date") or "").strip()
        end_date = str(options.get("end_date") or "").strip()
        cash = float(options.get("cash") or 100000.0)
        commission = float(options.get("commission") or 0.001)
        dry_run = bool(options.get("dry_run", False))

        if not config and not strategy:
            raise CommandError("Either --config or --strategy must be provided.")

        if config:
            cfg_path = Path(config)
            if not cfg_path.exists():
                raise CommandError(f"Config file not found: {cfg_path}")

        self.stdout.write("run_backtest scaffold command invoked")
        self.stdout.write(f"- config={config or '<none>'}")
        self.stdout.write(f"- strategy={strategy or '<none>'}")
        self.stdout.write(f"- symbol={symbol or '<none>'}")
        self.stdout.write(f"- start_date={start_date or '<none>'}")
        self.stdout.write(f"- end_date={end_date or '<none>'}")
        self.stdout.write(f"- cash={cash}")
        self.stdout.write(f"- commission={commission}")
        self.stdout.write(f"- dry_run={dry_run}")

        if dry_run:
            self.stdout.write("dry-run done")
            return

        # Placeholder for later integration with backtesting engine.
        self.stdout.write("backtesting execution is not implemented yet")
