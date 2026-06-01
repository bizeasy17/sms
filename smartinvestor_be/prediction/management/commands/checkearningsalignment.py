from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Case, IntegerField, Value, When

from api.views import (
    _fetch_earnings_signal_batch,
    _normalize_earnings_report_type_with_all,
    _normalize_valuation_profit_report_type,
    _parse_date_like,
)
from datastore.models import StockTradingHistory
from prediction.models import StockValuationSnapshotLatest


SUPPORTED_REPORT_TYPES = {"Q1", "H1", "Q3", "FY", "ANNUAL", "FUSION", "EXP", "EXPRESS"}
SIGNAL_REPORT_TYPES = {"Q1", "H1", "Q3", "FY"}
METHOD_PRIORITY = [
    "market_cap",
    "sw_history",
    "pe",
    "pb",
    "ps",
    "peg",
    "fcff_dcf",
    "ddm",
    "scarcity_overlay",
]


def _parse_codes(ts_codes_text: str, file_path: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for raw in str(ts_codes_text or "").split(","):
        code = str(raw or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)

    file_path = str(file_path or "").strip()
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise CommandError(f"tscodes-file not found: {path}")
        for raw in path.read_text(encoding="utf-8").splitlines():
            code = str(raw or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)

    return out


def _parse_report_types(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").split(","):
        rt = str(raw or "").strip().upper()
        if not rt:
            continue
        if rt in {"A", "FULL_YEAR"}:
            rt = "ANNUAL"
        if rt in seen:
            continue
        seen.add(rt)
        out.append(rt)
    return out


class Command(BaseCommand):
    help = "Check valuation report period alignment against earnings signal service."

    def add_arguments(self, parser):
        parser.add_argument("--ts-codes", type=str, default="", help="Comma-separated ts_code list")
        parser.add_argument("--tscodes-file", type=str, default="", help="Optional file with one ts_code per line")
        parser.add_argument(
            "--report-types",
            type=str,
            default="Q1,H1,Q3,FY,FUSION",
            help="Comma-separated report types to check",
        )
        parser.add_argument("--trade-date", type=str, default="", help="Trade date in YYYY-MM-DD")
        parser.add_argument("--freq", type=str, default="D", help="Trading frequency for latest trade-date fallback")
        parser.add_argument("--market", type=str, default="CN", help="Market code")
        parser.add_argument("--valuation-method", type=str, default="", help="Optional valuation method filter")
        parser.add_argument("--output-file", type=str, default="", help="Optional output json file")

    def _resolve_trade_date(self, trade_date_text: str, freq: str):
        parsed = _parse_date_like(trade_date_text)
        if parsed is not None:
            return parsed
        latest = (
            StockTradingHistory.objects.filter(freq=freq)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
        )
        if latest is None:
            raise CommandError("no trading history found to infer trade-date")
        return latest

    def _pick_latest_snapshot_row(self, ts_code: str, trade_date, market: str, valuation_method: str, report_type: str) -> dict:
        valuation_report_type = _normalize_valuation_profit_report_type(report_type)
        normalized_signal_rt = _normalize_earnings_report_type_with_all(report_type)

        qs = StockValuationSnapshotLatest.objects.filter(ts_code=ts_code, market=market)
        if trade_date is not None:
            qs = qs.filter(latest_trade_date=trade_date)
        if valuation_method:
            qs = qs.filter(valuation_method=valuation_method)

        if normalized_signal_rt == "FUSION":
            qs = qs.filter(profit_data_source__startswith="express")
        elif valuation_report_type:
            qs = qs.filter(profit_report_type=valuation_report_type).exclude(profit_data_source__startswith="express")

        if not qs.exists():
            qs = StockValuationSnapshotLatest.objects.filter(ts_code=ts_code, market=market)
            if valuation_method:
                qs = qs.filter(valuation_method=valuation_method)
            if normalized_signal_rt == "FUSION":
                qs = qs.filter(profit_data_source__startswith="express")
            elif valuation_report_type:
                qs = qs.filter(profit_report_type=valuation_report_type).exclude(profit_data_source__startswith="express")

        method_rank_cases = [
            When(valuation_method=name, then=Value(idx))
            for idx, name in enumerate(METHOD_PRIORITY)
        ]

        qs = qs.annotate(
            _method_rank=Case(
                *method_rank_cases,
                default=Value(999),
                output_field=IntegerField(),
            ),
            _variant_rank=Case(
                When(valuation_variant="default", then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("_method_rank", "_variant_rank", "-latest_trade_date", "-updated_at")

        row = qs.values(
            "ts_code",
            "latest_trade_date",
            "valuation_method",
            "valuation_variant",
            "profit_data_source",
            "profit_report_type",
            "profit_report_end_date",
            "profit_report_ann_date",
        ).first()
        return row or {}

    def _fetch_signal_result(self, ts_code: str, report_type: str, forced_end_date):
        normalized_rt = _normalize_earnings_report_type_with_all(report_type)
        kwargs = {
            "ts_codes": [ts_code],
            "report_type": normalized_rt,
        }
        if forced_end_date is not None and normalized_rt in SIGNAL_REPORT_TYPES:
            kwargs["financial_end_date_map"] = {ts_code: forced_end_date}

        result = _fetch_earnings_signal_batch(**kwargs)
        payload = result.get(ts_code) if isinstance(result, dict) else None
        return payload if isinstance(payload, dict) else None

    def handle(self, *_args, **options):
        ts_codes = _parse_codes(options.get("ts_codes"), options.get("tscodes_file"))
        if not ts_codes:
            raise CommandError("please provide --ts-codes or --tscodes-file")

        report_types = _parse_report_types(options.get("report_types"))
        if not report_types:
            raise CommandError("no valid report-types provided")

        unsupported = [rt for rt in report_types if rt not in SUPPORTED_REPORT_TYPES]
        if unsupported:
            raise CommandError(f"unsupported report-types: {unsupported}")

        market = str(options.get("market") or "CN").strip().upper()
        freq = str(options.get("freq") or "D").strip().upper()
        valuation_method = str(options.get("valuation_method") or "").strip()
        trade_date = self._resolve_trade_date(options.get("trade_date"), freq)

        self.stdout.write(
            f"check earnings alignment start: codes={len(ts_codes)} report_types={report_types} "
            f"trade_date={trade_date} market={market} method={valuation_method} "
            f"service={getattr(settings, 'EARNINGS_SERVICE_BASE_URL', '')}"
        )

        rows: list[dict] = []
        mismatch_count = 0
        strict_missing_count = 0

        for code in ts_codes:
            for report_type in report_types:
                valuation_row = self._pick_latest_snapshot_row(
                    ts_code=code,
                    trade_date=trade_date,
                    market=market,
                    valuation_method=valuation_method,
                    report_type=report_type,
                )

                valuation_end_date = valuation_row.get("profit_report_end_date")
                valuation_end_date_text = (
                    valuation_end_date.strftime("%Y-%m-%d") if valuation_end_date is not None else None
                )

                default_result = None
                strict_result = None
                default_error = None
                strict_error = None

                try:
                    default_result = self._fetch_signal_result(code, report_type, forced_end_date=None)
                except Exception as exc:
                    default_error = str(exc)

                if valuation_end_date_text:
                    try:
                        strict_result = self._fetch_signal_result(
                            code,
                            report_type,
                            forced_end_date=valuation_end_date_text,
                        )
                    except Exception as exc:
                        strict_error = str(exc)

                default_signal_end = _parse_date_like((default_result or {}).get("financial_end_date"))
                strict_signal_end = _parse_date_like((strict_result or {}).get("financial_end_date"))

                default_signal_end_text = (
                    default_signal_end.strftime("%Y-%m-%d") if default_signal_end is not None else None
                )
                strict_signal_end_text = (
                    strict_signal_end.strftime("%Y-%m-%d") if strict_signal_end is not None else None
                )

                aligned_default = (
                    valuation_end_date_text is not None
                    and default_signal_end_text is not None
                    and valuation_end_date_text == default_signal_end_text
                )
                aligned_strict = (
                    valuation_end_date_text is not None
                    and strict_signal_end_text is not None
                    and valuation_end_date_text == strict_signal_end_text
                )

                if valuation_end_date_text and not aligned_default:
                    mismatch_count += 1
                if valuation_end_date_text and strict_result is None:
                    strict_missing_count += 1

                row = {
                    "ts_code": code,
                    "report_type": report_type,
                    "valuation_trade_date": str(valuation_row.get("latest_trade_date") or trade_date),
                    "valuation_profit_data_source": valuation_row.get("profit_data_source"),
                    "valuation_profit_report_type": valuation_row.get("profit_report_type"),
                    "valuation_profit_report_end_date": valuation_end_date_text,
                    "default_signal_end_date": default_signal_end_text,
                    "default_signal_report_type": (default_result or {}).get("report_type"),
                    "default_signal_fiscal_year": (default_result or {}).get("financial_fiscal_year"),
                    "strict_signal_end_date": strict_signal_end_text,
                    "strict_signal_report_type": (strict_result or {}).get("report_type"),
                    "strict_signal_fiscal_year": (strict_result or {}).get("financial_fiscal_year"),
                    "aligned_default": aligned_default,
                    "aligned_strict": aligned_strict,
                    "default_error": default_error,
                    "strict_error": strict_error,
                }
                rows.append(row)

                self.stdout.write(
                    f"[{code}][{report_type}] valuation_end={valuation_end_date_text} "
                    f"default_end={default_signal_end_text} strict_end={strict_signal_end_text} "
                    f"aligned_default={aligned_default} aligned_strict={aligned_strict}"
                )

        summary = {
            "total_checks": len(rows),
            "mismatch_count": mismatch_count,
            "strict_missing_count": strict_missing_count,
            "rows": rows,
        }

        output_file = str(options.get("output_file") or "").strip()
        if output_file:
            output_path = Path(output_file)
            if not output_path.is_absolute():
                output_path = Path(settings.BASE_DIR) / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"alignment report written: {output_path}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"alignment check done: total={summary['total_checks']} mismatches={mismatch_count} "
                f"strict_missing={strict_missing_count}"
            )
        )
