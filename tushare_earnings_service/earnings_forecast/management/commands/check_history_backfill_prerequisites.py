import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from earnings_forecast.models import (
    FinancialFeaturePanel,
    LocalCorporation,
    LocalFundamentalHistory,
    LocalIndustry,
    LocalTradingHistory,
)
from earnings_forecast.services.pipeline import EarningsForecastPipeline


def parse_date(value, option_name):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"{option_name} must be YYYY-MM-DD") from exc


class Command(BaseCommand):
    help = "Strict read-only prerequisite check for predictive valuation history backfill."

    def add_arguments(self, parser):
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument(
            "--scope",
            default="60,00,30,68",
            help="Stock code prefixes; defaults to the training universe and excludes BSE 92xxxx.BJ",
        )
        parser.add_argument("--config", default="configs/default.yaml")
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
        codes = list(LocalCorporation.objects.values_list("ts_code", flat=True))
        if prefixes:
            codes = [code for code in codes if any(code.startswith(prefix) for prefix in prefixes)]

        failures = []
        if not codes:
            failures.append({"requirement": "local_corporations", "detail": "no target corporations"})

        for model, field_name in (
            (LocalTradingHistory, "local_trading"),
            (LocalFundamentalHistory, "local_fundamental"),
            (FinancialFeaturePanel, "financial_feature_panel"),
        ):
            if not model.objects.filter(ts_code__in=codes).exists():
                failures.append({"requirement": field_name, "detail": "no rows for target corporations"})

        trading_coverage = LocalTradingHistory.objects.filter(
            ts_code__in=codes, freq="D", trade_date__range=(start_date, end_date), close__isnull=False
        ).values("ts_code").distinct().count()
        fundamental_coverage = LocalFundamentalHistory.objects.filter(
            ts_code__in=codes, freq="D", trade_date__range=(start_date, end_date), total_mv__isnull=False
        ).values("ts_code").distinct().count()
        feature_coverage = FinancialFeaturePanel.objects.filter(
            ts_code__in=codes, ann_date__lte=end_date.strftime("%Y%m%d")
        ).values("ts_code").distinct().count()
        for requirement, covered in (
            ("local_trading_coverage", trading_coverage),
            ("local_fundamental_coverage", fundamental_coverage),
            ("financial_feature_coverage", feature_coverage),
        ):
            missing_codes = len(codes) - covered
            if missing_codes > max_missing_codes:
                failures.append(
                    {
                        "requirement": requirement,
                        "expected_codes": len(codes),
                        "covered_codes": covered,
                        "missing_codes": missing_codes,
                        "max_missing_codes": max_missing_codes,
                    }
                )

        missing_industries = 0
        for corporation in LocalCorporation.objects.exclude(ts_code__in=[]):
            if corporation.ts_code not in codes:
                continue
            if not corporation.industry_id or not LocalIndustry.objects.filter(id=corporation.industry_id).exclude(name="").exists():
                missing_industries += 1
        if missing_industries > max_missing_codes:
            failures.append(
                {
                    "requirement": "industry_mapping",
                    "missing_codes": missing_industries,
                    "max_missing_codes": max_missing_codes,
                }
            )

        config_path = Path(options["config"])
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        try:
            pipeline = EarningsForecastPipeline(config_path=str(config_path))
            serving = pipeline._resolve_serving_entry("production")
            model_path = pipeline._resolve_predict_model_path(serving_slot="production")
            dataset_path = pipeline._resolve_predict_dataset_path(serving_slot="production")
            if not serving or not serving.get("model_version"):
                failures.append({"requirement": "production_serving", "detail": "missing production serving entry"})
            if not model_path.exists():
                failures.append({"requirement": "production_model", "detail": str(model_path)})
            if not dataset_path.exists():
                failures.append({"requirement": "production_dataset", "detail": str(dataset_path)})
        except (OSError, ValueError, TypeError) as exc:
            failures.append({"requirement": "production_serving", "detail": str(exc)})

        report = {
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "scope": options["scope"],
            "max_missing_codes": max_missing_codes,
            "target_codes": len(codes),
            "trading_covered_codes": trading_coverage,
            "fundamental_covered_codes": fundamental_coverage,
            "feature_covered_codes": feature_coverage,
            "failures": failures,
        }
        report_path = Path(options["report_file"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"report={report_path} failures={len(failures)}")
        if failures:
            raise CommandError("Predictive history prerequisites failed; see report.")