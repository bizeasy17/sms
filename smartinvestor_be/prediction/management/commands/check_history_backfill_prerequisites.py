import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import Min, Max

from datastore.models import Corporation, CorporationBasic, StockTradingHistory
from valuation.models import ExternalValuationSnapshot
from valuation.services.validation_loader import ValuationConfig


def parse_date(value, option_name):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"{option_name} must be YYYY-MM-DD") from exc


class Command(BaseCommand):
    help = "Strict read-only prerequisite check for traditional valuation history backfill."

    def add_arguments(self, parser):
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument(
            "--scope",
            default="60,00,30,68",
            help="Stock code prefixes; defaults to the training universe and excludes BSE 92xxxx.BJ",
        )
        parser.add_argument("--report-file", required=True)
        parser.add_argument(
            "--max-missing-codes",
            type=int,
            default=20,
            help="Block only when a code-coverage gap exceeds this threshold",
        )

    def handle(self, *args, **options):
        start_date = parse_date(options["start_date"], "--start-date")
        end_date = parse_date(options["end_date"], "--end-date")
        if end_date < start_date:
            raise CommandError("--end-date must not be before --start-date")
        max_missing_codes = max(0, int(options["max_missing_codes"]))

        prefixes = [] if options["scope"].upper() == "ALL" else [
            item.strip().upper() for item in options["scope"].split(",") if item.strip()
        ]
        corporations = Corporation.objects.all()
        if prefixes:
            from django.db.models import Q

            prefix_filter = Q()
            for prefix in prefixes:
                prefix_filter |= Q(ts_code__startswith=prefix)
            corporations = corporations.filter(prefix_filter)
        codes = list(corporations.values_list("ts_code", flat=True))
        failures = []
        if not codes:
            failures.append({"requirement": "corporations", "detail": "no target corporations"})

        snapshot_table = ExternalValuationSnapshot._meta.db_table
        if "valuation" not in connections.databases:
            failures.append(
                {
                    "requirement": "valuation_database_alias",
                    "detail": "missing database alias: valuation",
                }
            )
        elif snapshot_table not in connections["valuation"].introspection.table_names():
            failures.append(
                {
                    "requirement": "valuation_snapshot_table",
                    "detail": f"missing valuation database table: {snapshot_table}",
                }
            )

        daily_qs = StockTradingHistory.objects.filter(
            ts_code__in=codes, freq="D", close__isnull=False
        )
        date_bounds = daily_qs.aggregate(min_date=Min("trade_date"), max_date=Max("trade_date"))
        covered_codes = daily_qs.filter(
            trade_date__range=(start_date, end_date)
        ).values("ts_code").distinct().count()
        if date_bounds["min_date"] is None or date_bounds["min_date"] > start_date or date_bounds["max_date"] < end_date:
            failures.append({
                "requirement": "daily_history_window",
                "expected_start": start_date.isoformat(),
                "expected_end": end_date.isoformat(),
                "actual_start": str(date_bounds["min_date"] or ""),
                "actual_end": str(date_bounds["max_date"] or ""),
            })
        missing_daily_codes = len(codes) - covered_codes
        if missing_daily_codes > max_missing_codes:
            failures.append(
                {
                    "requirement": "daily_history_coverage",
                    "expected_codes": len(codes),
                    "covered_codes": covered_codes,
                    "missing_codes": missing_daily_codes,
                    "max_missing_codes": max_missing_codes,
                }
            )

        basic_codes = set(
            CorporationBasic.objects.filter(ts_code__in=codes).values_list("ts_code", flat=True)
        )
        missing_basic_codes = len(set(codes) - basic_codes)
        if missing_basic_codes > max_missing_codes:
            failures.append(
                {
                    "requirement": "corporation_basic",
                    "missing_codes": missing_basic_codes,
                    "max_missing_codes": max_missing_codes,
                }
            )

        try:
            config = ValuationConfig(settings.BASE_DIR / "static", market="CN")
            invalid_params = 0
            for code in codes:
                params = config.get_sw_params_by_tscode(code)
                if not params.get("params"):
                    invalid_params += 1
            if invalid_params > max_missing_codes:
                failures.append(
                    {
                        "requirement": "sw_valuation_params",
                        "missing_codes": invalid_params,
                        "max_missing_codes": max_missing_codes,
                    }
                )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            failures.append({"requirement": "valuation_configuration", "detail": str(exc)})

        required_financial_tables = [
            "earnings_fin_income",
            "earnings_fin_fina_indicator_vip",
            "earnings_fin_balancesheet_vip",
            "earnings_fin_cashflow_vip",
        ]
        try:
            with connections["earnings"].cursor() as cursor:
                for table_name in required_financial_tables:
                    cursor.execute("SELECT to_regclass(%s)", [f"public.{table_name}"])
                    if cursor.fetchone()[0] is None:
                        failures.append({"requirement": "earnings_financial_table", "detail": table_name})
                        continue
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    if cursor.fetchone()[0] == 0:
                        failures.append({"requirement": "earnings_financial_rows", "detail": table_name})
        except Exception as exc:
            failures.append({"requirement": "earnings_database_alias", "detail": str(exc)})

        report = {
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "scope": options["scope"],
            "max_missing_codes": max_missing_codes,
            "target_codes": len(codes),
            "daily_covered_codes": covered_codes,
            "missing_corporation_basic_codes": missing_basic_codes,
            "daily_date_bounds": {key: str(value or "") for key, value in date_bounds.items()},
            "failures": failures,
        }
        report_path = Path(options["report_file"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"report={report_path} failures={len(failures)}")
        if failures:
            raise CommandError("Traditional history prerequisites failed; see report.")