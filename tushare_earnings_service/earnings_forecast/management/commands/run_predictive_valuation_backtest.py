import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from earnings_forecast.services import run_predictive_valuation_backtest


class Command(BaseCommand):
    help = "Run predictive valuation backtest from signal snapshot history."

    def add_arguments(self, parser):
        parser.add_argument("--batch-key", type=str, required=True)
        parser.add_argument("--tscodes-file", type=str, required=True)
        parser.add_argument("--min-score", type=float, default=70.0)
        parser.add_argument("--max-risk", type=str, default="MEDIUM", choices=["LOW", "MEDIUM", "HIGH"])
        parser.add_argument("--start-year", type=int, default=2024)
        parser.add_argument("--end-year", type=int, default=2025)
        parser.add_argument("--stop-mode", type=str, default="none", choices=["none", "global", "single"])
        parser.add_argument("--global-stop-dd", type=float, default=0.0)
        parser.add_argument("--single-stop-dd", type=float, default=0.1)
        parser.add_argument("--report-type", type=str, default="ALL")
        parser.add_argument("--output-json", type=str, default="")

    def _load_codes(self, path: str) -> list[str]:
        fp = Path(path)
        if not fp.exists() or not fp.is_file():
            raise CommandError(f"tscodes file not found: {path}")
        out = []
        seen = set()
        for raw in fp.read_text(encoding="utf-8").splitlines():
            code = str(raw or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
        return out

    def handle(self, *args, **options):
        ts_codes = self._load_codes(options["tscodes_file"])
        if not ts_codes:
            raise CommandError("No valid ts_codes loaded from tscodes file")

        result = run_predictive_valuation_backtest(
            batch_key=options["batch_key"],
            ts_codes=ts_codes,
            start_year=int(options["start_year"]),
            end_year=int(options["end_year"]),
            min_score=float(options["min_score"]),
            max_risk=str(options["max_risk"]).upper(),
            stop_mode=str(options["stop_mode"]).lower(),
            global_stop_dd=float(options["global_stop_dd"]),
            single_stop_dd=float(options["single_stop_dd"]),
            report_type=str(options["report_type"] or "ALL").upper(),
        )

        output_text = json.dumps(result, ensure_ascii=False, indent=2)
        self.stdout.write(output_text)

        output_json = str(options.get("output_json") or "").strip()
        if output_json:
            out_path = Path(output_json)
            if not out_path.is_absolute():
                out_path = Path.cwd() / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output_text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"saved: {out_path}"))
