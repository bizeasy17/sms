from django.core.management.base import BaseCommand, CommandError

from backtest.services import run_traditional_value_exit_backtest
from prediction.management.commands.backtestbuycandidates import _parse_date_text


class Command(BaseCommand):
    help = "Backtest traditional valuation buy-and-exit strategy using snapshot history."

    def add_arguments(self, parser):
        parser.add_argument("--scope", type=str, default="ALL", help="ALL or ts_code prefix list such as 60,0,3")
        parser.add_argument("--market", type=str, default="CN", help="Market code")
        parser.add_argument("--start-date", type=str, default="2024-01-01", help="Start date YYYY-MM-DD")
        parser.add_argument("--end-date", type=str, default="2025-12-31", help="End date YYYY-MM-DD")
        parser.add_argument("--valuation-band-pct", type=float, default=0.1, help="Valuation band percent")
        parser.add_argument("--min-score", type=float, default=90, help="Minimum undervalue score")
        parser.add_argument("--risk-level", type=str, default="LOW", help="Required risk level(s), comma-separated such as LOW or LOW,MEDIUM")
        parser.add_argument(
            "--valuation-variant",
            type=str,
            default="",
            help="Risk snapshot variant used when risk-variant-policy=specific",
        )
        parser.add_argument(
            "--risk-variant-policy",
            type=str,
            default="any",
            help="Risk filter policy: any or specific",
        )
        parser.add_argument("--min-netprofit-yoy", type=float, default=None, help="Minimum net profit YoY percent")
        parser.add_argument("--min-ebit-yoy", type=float, default=None, help="Minimum EBIT YoY percent")
        parser.add_argument("--take-profit-pct", type=float, default=0.0, help="Take-profit threshold as decimal, e.g. 0.1 for 10%")
        parser.add_argument(
            "--financial-filter-mode",
            type=str,
            default="all",
            help="Financial filter mode when multiple thresholds are set: all or any",
        )
        parser.add_argument("--progress-every", type=int, default=50, help="Progress print interval by trade date")
        parser.add_argument("--output-json", type=str, default="", help="Optional output json path")

    def handle(self, *_args, **options):
        risk_level = str(options.get("risk_level") or "LOW").strip().upper()
        risk_variant_policy = str(options.get("risk_variant_policy") or "any").strip().lower()
        financial_filter_mode = str(options.get("financial_filter_mode") or "all").strip().lower()
        if risk_variant_policy not in {"any", "specific"}:
            raise CommandError("--risk-variant-policy must be any or specific")
        if financial_filter_mode not in {"all", "any"}:
            raise CommandError("--financial-filter-mode must be all or any")
        if risk_variant_policy == "specific" and not str(options.get("valuation_variant") or "").strip():
            raise CommandError("--valuation-variant is required when --risk-variant-policy=specific")

        try:
            start_date = _parse_date_text(options.get("start_date"))
            end_date = _parse_date_text(options.get("end_date"))
        except Exception as exc:
            raise CommandError(f"Invalid date format: {exc}") from exc

        if start_date > end_date:
            raise CommandError("--start-date must be <= --end-date")

        try:
            summary, output_path = run_traditional_value_exit_backtest(
                scope=str(options.get("scope") or "ALL").strip().upper(),
                market=str(options.get("market") or "CN").strip().upper(),
                start_date=start_date,
                end_date=end_date,
                band_pct=float(options.get("valuation_band_pct") or 0.1),
                min_score=float(options.get("min_score") or 90),
                risk_level=risk_level,
                valuation_variant=str(options.get("valuation_variant") or "").strip(),
                risk_variant_policy=risk_variant_policy,
                min_netprofit_yoy=options.get("min_netprofit_yoy"),
                min_ebit_yoy=options.get("min_ebit_yoy"),
                financial_filter_mode=financial_filter_mode,
                take_profit_pct=max(0.0, float(options.get("take_profit_pct") or 0.0)),
                progress_every=max(1, int(options.get("progress_every") or 50)),
                output_json=str(options.get("output_json") or "").strip() or None,
                stdout=self.stdout,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"combined={summary['combined']}")
        self.stdout.write(f"by_year={summary['by_year']}")
        self.stdout.write(f"saved {output_path}")