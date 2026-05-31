from django.core.management.base import BaseCommand, CommandError

from backtest.services import run_traditional_value_exit_account_backtest, run_traditional_value_exit_backtest
from prediction.management.commands.backtestbuycandidates import _parse_date_text


class Command(BaseCommand):
    help = "Backtest traditional valuation buy-and-exit strategy (signal mode or account mode)."

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
        parser.add_argument(
            "--risk-alignment-mode",
            type=str,
            default="legacy",
            help="Risk alignment mode: legacy or current",
        )
        parser.add_argument("--min-netprofit-yoy", type=float, default=None, help="Minimum net profit YoY percent")
        parser.add_argument("--min-ebit-yoy", type=float, default=None, help="Minimum EBIT YoY percent")
        parser.add_argument("--take-profit-pct", type=float, default=0.0, help="Take-profit threshold as decimal, e.g. 0.1 for 10%%")
        parser.add_argument(
            "--financial-filter-mode",
            type=str,
            default="all",
            help="Financial filter mode when multiple thresholds are set: all or any",
        )
        parser.add_argument("--progress-every", type=int, default=50, help="Progress print interval by trade date")
        parser.add_argument("--output-json", type=str, default="", help="Optional output json path")
        parser.add_argument(
            "--mode",
            type=str,
            default="signal",
            help="Backtest mode: signal or account",
        )
        parser.add_argument(
            "--starting-capital",
            type=float,
            default=200000.0,
            help="Starting capital for account mode",
        )
        parser.add_argument(
            "--commission-rate",
            type=float,
            default=0.0005,
            help="Commission rate per side for account mode",
        )
        parser.add_argument(
            "--valuation-source",
            type=str,
            default="history",
            help="Valuation source for account mode: history or snapshot",
        )
        parser.add_argument(
            "--entry-date-source",
            type=str,
            default="history",
            help="Entry date source for account mode: history or snapshot",
        )
        parser.add_argument(
            "--entry-end-date",
            type=str,
            default="",
            help="Optional entry cutoff date YYYY-MM-DD for account mode (positions can still be held until end-date)",
        )
        parser.add_argument(
            "--max-buy-per-day",
            type=int,
            default=5,
            help="Max new buys per day in account mode; set 0 for no limit",
        )
        parser.add_argument(
            "--max-position-pct",
            type=float,
            default=1.0,
            help="Max position size per stock as fraction of current equity in account mode, e.g. 0.2",
        )
        parser.add_argument(
            "--buy-weight-ladder",
            type=str,
            default="",
            help="Optional ranked buy weights, e.g. 0.5,0.3,0.2 (high score to low score)",
        )
        parser.add_argument(
            "--first-entry-pct",
            type=float,
            default=1.0,
            help="Initial entry tranche as equity fraction per stock, e.g. 0.1",
        )
        parser.add_argument(
            "--add-on-drop-pct",
            type=float,
            default=0.0,
            help="Add-on trigger drawdown from initial entry, e.g. 0.1 means -10%",
        )
        parser.add_argument(
            "--add-on-entry-pct",
            type=float,
            default=0.0,
            help="Add-on tranche as equity fraction per stock when triggered, e.g. 0.1",
        )
        parser.add_argument(
            "--add-on2-drop-pct",
            type=float,
            default=0.0,
            help="Second add-on trigger drawdown from initial entry, e.g. 0.15",
        )
        parser.add_argument(
            "--add-on2-fill-remaining",
            action="store_true",
            help="On second trigger, fill remaining position capacity to max-position-pct",
        )
        parser.add_argument(
            "--disable-eop-exit",
            action="store_true",
            help="Disable end-of-period forced liquidation in account mode",
        )

    def handle(self, *_args, **options):
        risk_level = str(options.get("risk_level") or "LOW").strip().upper()
        risk_variant_policy = str(options.get("risk_variant_policy") or "any").strip().lower()
        risk_alignment_mode = str(options.get("risk_alignment_mode") or "legacy").strip().lower()
        financial_filter_mode = str(options.get("financial_filter_mode") or "all").strip().lower()
        mode = str(options.get("mode") or "signal").strip().lower()
        valuation_source = str(options.get("valuation_source") or "history").strip().lower()
        entry_date_source = str(options.get("entry_date_source") or "history").strip().lower()

        if mode not in {"signal", "account"}:
            raise CommandError("--mode must be signal or account")
        if valuation_source not in {"snapshot", "history"}:
            raise CommandError("--valuation-source must be snapshot or history")
        if entry_date_source not in {"snapshot", "history"}:
            raise CommandError("--entry-date-source must be snapshot or history")
        if risk_variant_policy not in {"any", "specific"}:
            raise CommandError("--risk-variant-policy must be any or specific")
        if risk_alignment_mode not in {"legacy", "current"}:
            raise CommandError("--risk-alignment-mode must be legacy or current")
        if financial_filter_mode not in {"all", "any"}:
            raise CommandError("--financial-filter-mode must be all or any")
        if risk_variant_policy == "specific" and not str(options.get("valuation_variant") or "").strip():
            raise CommandError("--valuation-variant is required when --risk-variant-policy=specific")

        try:
            start_date = _parse_date_text(options.get("start_date"))
            end_date = _parse_date_text(options.get("end_date"))
        except Exception as exc:
            raise CommandError(f"Invalid date format: {exc}") from exc

        entry_end_date_text = str(options.get("entry_end_date") or "").strip()
        entry_end_date = None
        if entry_end_date_text:
            try:
                entry_end_date = _parse_date_text(entry_end_date_text)
            except Exception as exc:
                raise CommandError(f"Invalid --entry-end-date format: {exc}") from exc

        if start_date > end_date:
            raise CommandError("--start-date must be <= --end-date")
        if entry_end_date is not None and entry_end_date < start_date:
            raise CommandError("--entry-end-date must be >= --start-date")
        if entry_end_date is not None and entry_end_date > end_date:
            raise CommandError("--entry-end-date must be <= --end-date")

        try:
            common_kwargs = {
                "scope": str(options.get("scope") or "ALL").strip().upper(),
                "market": str(options.get("market") or "CN").strip().upper(),
                "start_date": start_date,
                "end_date": end_date,
                "band_pct": float(options.get("valuation_band_pct") or 0.1),
                "min_score": float(options.get("min_score") or 90),
                "risk_level": risk_level,
                "valuation_variant": str(options.get("valuation_variant") or "").strip(),
                "risk_variant_policy": risk_variant_policy,
                "risk_alignment_mode": risk_alignment_mode,
                "min_netprofit_yoy": options.get("min_netprofit_yoy"),
                "min_ebit_yoy": options.get("min_ebit_yoy"),
                "financial_filter_mode": financial_filter_mode,
                "take_profit_pct": max(0.0, float(options.get("take_profit_pct") or 0.0)),
                "output_json": str(options.get("output_json") or "").strip() or None,
                "stdout": self.stdout,
            }

            if mode == "account":
                weight_text = str(options.get("buy_weight_ladder") or "").strip()
                weight_ladder = []
                if weight_text:
                    weight_ladder = [float(item.strip()) for item in weight_text.split(",") if item.strip()]
                summary, output_path = run_traditional_value_exit_account_backtest(
                    **common_kwargs,
                    starting_capital=float(options.get("starting_capital") or 200000.0),
                    commission_rate=float(options.get("commission_rate") or 0.0005),
                    valuation_source=valuation_source,
                    entry_date_source=entry_date_source,
                    entry_end_date=entry_end_date,
                    max_buy_per_day=int(options.get("max_buy_per_day") or 0),
                    max_position_pct=float(options.get("max_position_pct") or 1.0),
                    buy_weight_ladder=weight_ladder,
                    first_entry_pct=float(options.get("first_entry_pct") or 1.0),
                    add_on_drop_pct=float(options.get("add_on_drop_pct") or 0.0),
                    add_on_entry_pct=float(options.get("add_on_entry_pct") or 0.0),
                    add_on2_drop_pct=float(options.get("add_on2_drop_pct") or 0.0),
                    add_on2_fill_remaining=bool(options.get("add_on2_fill_remaining")),
                    disable_eop_exit=bool(options.get("disable_eop_exit")),
                )
            else:
                summary, output_path = run_traditional_value_exit_backtest(
                    **common_kwargs,
                    progress_every=max(1, int(options.get("progress_every") or 50)),
                )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"combined={summary['combined']}")
        if "account" in summary:
            self.stdout.write(f"account={summary['account']}")
        self.stdout.write(f"by_year={summary['by_year']}")
        self.stdout.write(f"saved {output_path}")
