import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEV_ROOT = BASE_DIR.parent
if str(DEV_ROOT) not in sys.path:
    sys.path.insert(0, str(DEV_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tushare_earnings_service.settings")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Temporary wrapper: run the official predictive valuation backtest CLI")
    parser.add_argument("--batch-key", type=str, required=True)
    parser.add_argument("--tscodes-file", type=str, required=True)
    parser.add_argument("--min-score", type=float, default=70.0)
    parser.add_argument("--max-risk", type=str, default="MEDIUM", choices=["LOW", "MEDIUM", "HIGH"])
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument(
        "--stop-mode",
        type=str,
        default="none",
        choices=["none", "global", "single"],
        help="Stop mode: none/global/single",
    )
    parser.add_argument(
        "--global-stop-dd",
        type=float,
        default=0.0,
        help="Global stop drawdown threshold, e.g. 0.1 for 10%. Triggered year stays in cash.",
    )
    parser.add_argument(
        "--single-stop-dd",
        type=float,
        default=0.1,
        help="Single-stock stop drawdown threshold, e.g. 0.1 for 10%.",
    )
    parser.add_argument(
        "--report-type",
        type=str,
        default="ALL",
        help="Report type filter in history snapshot: ALL/Q1/H1/Q3/FY/FUSION",
    )
    parser.add_argument("--output-json", type=str, default="")
    args = parser.parse_args()

    # Delegate to the unified Django management command to keep only one backtest implementation.
    call_command(
        "run_predictive_valuation_backtest",
        batch_key=args.batch_key,
        tscodes_file=args.tscodes_file,
        min_score=float(args.min_score),
        max_risk=args.max_risk,
        start_year=int(args.start_year),
        end_year=int(args.end_year),
        stop_mode=args.stop_mode,
        global_stop_dd=float(args.global_stop_dd),
        single_stop_dd=float(args.single_stop_dd),
        report_type=args.report_type,
        output_json=args.output_json,
    )


if __name__ == "__main__":
    main()
