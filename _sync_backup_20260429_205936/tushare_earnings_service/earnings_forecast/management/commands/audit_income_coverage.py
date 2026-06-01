from __future__ import annotations

import tempfile
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from earnings_forecast.models import FinancialDisclosureDateRecord, FinancialIncomeRecord


A_SHARE_DEFAULT_SCOPE = "60,00,30,68"


def _normalize_end_date(value: str) -> str:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        raise CommandError("--end-date must be YYYYMMDD")
    return text


def _normalize_prefixes(scope: str) -> list[str]:
    raw = str(scope or "ALL").strip().upper()
    if raw == "ALL":
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _load_codes_from_file(path: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            code = str(raw or "").strip().lstrip("\ufeff").upper()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
    return out


class Command(BaseCommand):
    help = (
        "Audit income coverage for a report period using disclosure records as expected set, "
        "and optionally auto-fix missing symbols."
    )

    def add_arguments(self, parser):
        parser.add_argument("--end-date", type=str, required=True, help="Target report end_date, YYYYMMDD")
        parser.add_argument("--scope", type=str, default=A_SHARE_DEFAULT_SCOPE, help="ALL or ts_code prefixes")
        parser.add_argument("--tscodes-file", type=str, help="Optional symbol whitelist file, one ts_code per line")
        parser.add_argument("--limit", type=int, default=0, help="Limit symbols after filtering, for smoke checks")
        parser.add_argument(
            "--auto-fix",
            action="store_true",
            default=False,
            help="Sync missing symbols from Tushare income endpoint",
        )
        parser.add_argument(
            "--rebuild-features",
            action="store_true",
            default=False,
            help="After auto-fix, rebuild panel and snapshot for missing symbols",
        )
        parser.add_argument(
            "--output-file",
            type=str,
            help="Optional output file for missing symbols",
        )

    def _resolve_candidates(self, end_date: str, prefixes: list[str], tscodes_file: str | None, limit: int) -> list[str]:
        today = datetime.now().strftime("%Y%m%d")

        if tscodes_file:
            # Whitelist mode: audit provided symbols directly.
            codes = sorted({str(x).strip().upper() for x in _load_codes_from_file(tscodes_file) if str(x).strip()})
        else:
            disclosure_codes = set(
                FinancialDisclosureDateRecord._default_manager.filter(end_date=end_date)
                .exclude(ts_code="")
                .exclude(ts_code__isnull=True)
                .exclude(actual_date="")
                .exclude(actual_date__isnull=True)
                .filter(actual_date__lte=today)
                .values_list("ts_code", flat=True)
                .distinct()
            )
            codes = sorted({str(x).strip().upper() for x in disclosure_codes if str(x).strip()})

        if prefixes:
            codes = [code for code in codes if any(code.startswith(prefix) for prefix in prefixes)]

        if limit > 0:
            codes = codes[:limit]

        return codes

    def _existing_income_codes(self, end_date: str, candidates: list[str]) -> set[str]:
        if not candidates:
            return set()
        return {
            str(x).strip().upper()
            for x in FinancialIncomeRecord._default_manager.filter(end_date=end_date, ts_code__in=candidates)
            .exclude(ts_code="")
            .exclude(ts_code__isnull=True)
            .values_list("ts_code", flat=True)
            .distinct()
        }

    def handle(self, *args, **options):
        end_date = _normalize_end_date(options.get("end_date"))
        prefixes = _normalize_prefixes(options.get("scope"))
        tscodes_file = options.get("tscodes_file")
        limit = max(0, int(options.get("limit") or 0))
        auto_fix = bool(options.get("auto_fix"))
        rebuild_features = bool(options.get("rebuild_features"))
        output_file = str(options.get("output_file") or "").strip()

        candidates = self._resolve_candidates(end_date, prefixes, tscodes_file, limit)
        existing = self._existing_income_codes(end_date, candidates)
        missing = sorted(set(candidates) - existing)

        self.stdout.write(
            f"income coverage audit: end_date={end_date} candidates={len(candidates)} "
            f"existing={len(existing)} missing={len(missing)}"
        )

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                for code in missing:
                    f.write(code + "\n")
            self.stdout.write(f"missing list written: {output_file}")

        for code in missing[:30]:
            self.stdout.write(f"MISSING {code}")
        if len(missing) > 30:
            self.stdout.write(f"... ({len(missing) - 30} more)")

        if not auto_fix or not missing:
            return

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix="_missing_income.txt") as tmp:
            for code in missing:
                tmp.write(code + "\n")
            tmp_path = tmp.name

        self.stdout.write(f"auto-fix begin: missing={len(missing)} file={tmp_path}")

        call_command(
            "sync_financials_direct",
            tscodes_file=tmp_path,
            apis="income",
            latest_only=True,
        )

        if rebuild_features:
            call_command("build_financial_feature_panel", tscodes_file=tmp_path)
            call_command("build_financial_feature_snapshot", tscodes_file=tmp_path)

        existing_after = self._existing_income_codes(end_date, candidates)
        remaining = sorted(set(candidates) - existing_after)

        self.stdout.write(
            f"auto-fix done: end_date={end_date} existing_after={len(existing_after)} remaining_missing={len(remaining)}"
        )

        if remaining:
            for code in remaining[:30]:
                self.stdout.write(f"STILL_MISSING {code}")
            if len(remaining) > 30:
                self.stdout.write(f"... ({len(remaining) - 30} more)")
