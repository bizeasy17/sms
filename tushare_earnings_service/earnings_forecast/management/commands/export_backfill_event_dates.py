from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import FieldError

from earnings_forecast.models import FINANCIAL_ENDPOINT_MODEL_MAP
from earnings_forecast.services.pipeline import EarningsForecastPipeline


DEFAULT_FINANCIAL_APIS = ["disclosure_date", "express_vip", "income", "fina_indicator_vip"]
FINANCIAL_EVENT_DATE_FIELDS = {
    # disclosure_date.ann_date/pre_date are often schedule-like placeholders;
    # only treat actual/modified disclosure dates as true update events.
    "disclosure_date": ["actual_date", "modify_date"],
    # end_date is report period label, not a data update timestamp.
    "express_vip": ["ann_date", "f_ann_date"],
    "income": ["ann_date", "f_ann_date"],
    "fina_indicator_vip": ["ann_date", "f_ann_date"],
}


def _parse_date(value: str | None, field_name: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise CommandError(f"missing --{field_name}")

    formats = ("%Y-%m-%d", "%Y%m%d")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise CommandError(f"invalid --{field_name}: {text}")


def _parse_date_like(value) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt in {"%Y-%m-%d", "%Y/%m/%d"} else "".join(ch for ch in text if ch.isdigit())[:8], fmt).date()
        except ValueError:
            continue

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _normalize_apis(raw: str | None) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return list(DEFAULT_FINANCIAL_APIS)

    out: list[str] = []
    seen: set[str] = set()
    for token in text.split(","):
        api = str(token or "").strip()
        if not api or api in seen:
            continue
        if api not in FINANCIAL_ENDPOINT_MODEL_MAP:
            continue
        seen.add(api)
        out.append(api)
    return out


def _normalize_scope(scope_text: str | None) -> list[str]:
    text = str(scope_text or "ALL").strip().upper()
    if not text or text == "ALL":
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def _scope_match(ts_code: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    code = str(ts_code or "").strip().upper()
    if not code:
        return False
    return any(code.startswith(prefix) for prefix in prefixes)


def _iter_dates(start_date: date, end_date: date):
    cur = start_date
    while cur <= end_date:
        yield cur
        cur = cur + timedelta(days=1)


class Command(BaseCommand):
    help = "Export event-driven backfill dates from financial updates, regime switches, and optional fixed cadence."

    def add_arguments(self, parser):
        parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)")
        parser.add_argument("--end-date", type=str, required=True, help="End date (YYYY-MM-DD)")
        parser.add_argument("--output-file", type=str, required=True, help="Output date list file")
        parser.add_argument("--scope", type=str, default="ALL", help="ALL or ts_code prefixes, e.g. 60,00,30,68")

        parser.add_argument(
            "--financial-apis",
            type=str,
            default=",".join(DEFAULT_FINANCIAL_APIS),
            help="Comma-separated APIs to scan by financial disclosure/announcement dates",
        )
        parser.add_argument(
            "--disable-financial-events",
            action="store_true",
            default=False,
            help="Disable financial disclosure/announcement date triggers",
        )

        parser.add_argument(
            "--enable-regime-switch",
            action="store_true",
            default=False,
            help="Enable market regime switch trigger dates",
        )
        parser.add_argument(
            "--include-regime-init",
            action="store_true",
            default=False,
            help="Include start-date regime initialization as an event date",
        )
        parser.add_argument(
            "--config",
            type=str,
            default="configs/default.yaml",
            help="Pipeline config for regime detection",
        )

        parser.add_argument(
            "--cadence-days",
            type=int,
            default=0,
            help="If >0, add fixed cadence dates (e.g. 14 or 30)",
        )
        parser.add_argument(
            "--cadence-anchor-date",
            type=str,
            default="",
            help="Cadence anchor date; defaults to start-date",
        )
        parser.add_argument(
            "--monthday",
            type=int,
            default=0,
            help="If 1-31, include each month matching this day (month-end clipped)",
        )

        parser.add_argument(
            "--reasons-file",
            type=str,
            default="",
            help="Optional output file with date and trigger reasons",
        )
        parser.add_argument(
            "--financial-date-codes-dir",
            type=str,
            default="",
            help="Optional directory to output financial event ts_code files by date",
        )
        parser.add_argument(
            "--full-refresh-dates-file",
            type=str,
            default="",
            help="Optional file to output regime-switch full refresh dates",
        )

    def handle(self, *_args, **options):
        start_date = _parse_date(options.get("start_date"), "start-date")
        end_date = _parse_date(options.get("end_date"), "end-date")
        if end_date < start_date:
            start_date, end_date = end_date, start_date

        output_file = Path(str(options.get("output_file") or "").strip())
        if not output_file:
            raise CommandError("missing --output-file")
        scope_prefixes = _normalize_scope(options.get("scope"))

        reason_map: dict[date, set[str]] = {}
        financial_codes_by_date: dict[date, set[str]] = {}

        self._add_financial_event_dates(
            reason_map=reason_map,
            start_date=start_date,
            end_date=end_date,
            disabled=bool(options.get("disable_financial_events")),
            financial_apis=_normalize_apis(options.get("financial_apis")),
            scope_prefixes=scope_prefixes,
            financial_codes_by_date=financial_codes_by_date,
        )

        if bool(options.get("enable_regime_switch")):
            self._add_regime_switch_dates(
                reason_map=reason_map,
                start_date=start_date,
                end_date=end_date,
                config_text=str(options.get("config") or "configs/default.yaml").strip() or "configs/default.yaml",
                include_regime_init=bool(options.get("include_regime_init")),
            )

        cadence_days = max(0, int(options.get("cadence_days") or 0))
        cadence_anchor_text = str(options.get("cadence_anchor_date") or "").strip()
        cadence_anchor_date = _parse_date(cadence_anchor_text, "cadence-anchor-date") if cadence_anchor_text else start_date
        if cadence_days > 0:
            self._add_cadence_dates(
                reason_map=reason_map,
                start_date=start_date,
                end_date=end_date,
                cadence_days=cadence_days,
                anchor_date=cadence_anchor_date,
            )

        monthday = int(options.get("monthday") or 0)
        if 1 <= monthday <= 31:
            self._add_monthday_dates(
                reason_map=reason_map,
                start_date=start_date,
                end_date=end_date,
                monthday=monthday,
            )

        sorted_dates = sorted(reason_map.keys())
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            for d in sorted_dates:
                f.write(d.isoformat() + "\n")

        full_refresh_dates = sorted(
            d for d in sorted_dates if any(str(x).startswith("regime:") for x in (reason_map.get(d) or []))
        )

        reasons_file = Path(str(options.get("reasons_file") or "").strip()) if str(options.get("reasons_file") or "").strip() else None
        if reasons_file is not None:
            reasons_file.parent.mkdir(parents=True, exist_ok=True)
            with reasons_file.open("w", encoding="utf-8") as f:
                f.write("date,reasons\n")
                for d in sorted_dates:
                    f.write(f"{d.isoformat()},{'|'.join(sorted(reason_map.get(d) or []))}\n")

        code_dir_text = str(options.get("financial_date_codes_dir") or "").strip()
        if code_dir_text:
            code_dir = Path(code_dir_text)
            if not code_dir.is_absolute():
                code_dir = Path(settings.BASE_DIR).parent / code_dir
            code_dir.mkdir(parents=True, exist_ok=True)
            for d, codes in financial_codes_by_date.items():
                day_file = code_dir / f"{d.isoformat()}.txt"
                with day_file.open("w", encoding="utf-8") as f:
                    for code in sorted(codes):
                        f.write(code + "\n")

        full_refresh_file_text = str(options.get("full_refresh_dates_file") or "").strip()
        if full_refresh_file_text:
            full_refresh_file = Path(full_refresh_file_text)
            if not full_refresh_file.is_absolute():
                full_refresh_file = Path(settings.BASE_DIR).parent / full_refresh_file
            full_refresh_file.parent.mkdir(parents=True, exist_ok=True)
            with full_refresh_file.open("w", encoding="utf-8") as f:
                for d in full_refresh_dates:
                    f.write(d.isoformat() + "\n")

        self.stdout.write(
            self.style.SUCCESS(
                f"exported event dates: count={len(sorted_dates)} file={output_file}"
            )
        )

    def _add_financial_event_dates(
        self,
        reason_map,
        start_date: date,
        end_date: date,
        disabled: bool,
        financial_apis: list[str],
        scope_prefixes: list[str],
        financial_codes_by_date: dict[date, set[str]],
    ):
        if disabled:
            self.stdout.write("financial event trigger disabled")
            return

        if not financial_apis:
            self.stdout.write("no financial apis selected")
            return

        for api in financial_apis:
            model = FINANCIAL_ENDPOINT_MODEL_MAP.get(api)
            if model is None:
                continue
            candidate_fields = FINANCIAL_EVENT_DATE_FIELDS.get(api) or ["ann_date", "f_ann_date", "end_date"]
            used_fields: list[str] = []

            api_dates: set[date] = set()
            for field_name in candidate_fields:
                try:
                    values = (
                        model.objects.exclude(**{f"{field_name}__isnull": True})
                        .exclude(**{field_name: ""})
                        .values_list("ts_code", field_name)
                        .distinct()
                    )
                except FieldError:
                    continue
                used_fields.append(field_name)
                for ts_code, raw in values:
                    code = str(ts_code or "").strip().upper()
                    if not _scope_match(code, scope_prefixes):
                        continue
                    d = _parse_date_like(raw)
                    if d is None or d < start_date or d > end_date:
                        continue
                    api_dates.add(d)
                    reason_map.setdefault(d, set()).add(f"financial:{api}:{field_name}")
                    financial_codes_by_date.setdefault(d, set()).add(code)

            if not used_fields:
                self.stdout.write(f"financial api={api} event_dates=0 (no usable date fields)")
                continue

            self.stdout.write(
                f"financial api={api} event_dates={len(api_dates)} fields={','.join(used_fields)}"
            )

    def _add_regime_switch_dates(
        self,
        reason_map,
        start_date: date,
        end_date: date,
        config_text: str,
        include_regime_init: bool,
    ):
        config_path = Path(config_text)
        if not config_path.is_absolute():
            config_path = Path(settings.BASE_DIR) / config_path

        pipeline = EarningsForecastPipeline(config_path=str(config_path))

        prev_regime = None
        switch_count = 0
        for d in _iter_dates(start_date, end_date):
            meta = pipeline.detect_market_regime(asof_trade_date=d.isoformat())
            regime = str((meta or {}).get("regime") or "BALANCE").strip().upper() or "BALANCE"
            if prev_regime is None:
                if include_regime_init:
                    reason_map.setdefault(d, set()).add("regime:init")
            elif regime != prev_regime:
                reason_map.setdefault(d, set()).add(f"regime:{prev_regime}->{regime}")
                switch_count += 1
            prev_regime = regime

        self.stdout.write(f"regime switch dates={switch_count}")

    @staticmethod
    def _add_cadence_dates(reason_map, start_date: date, end_date: date, cadence_days: int, anchor_date: date):
        if cadence_days <= 0:
            return

        if anchor_date > end_date:
            return

        if anchor_date < start_date:
            delta = (start_date - anchor_date).days
            jump = (delta + cadence_days - 1) // cadence_days
            anchor_date = anchor_date + timedelta(days=jump * cadence_days)

        cur = anchor_date
        while cur <= end_date:
            if cur >= start_date:
                reason_map.setdefault(cur, set()).add(f"cadence:{cadence_days}d")
            cur = cur + timedelta(days=cadence_days)

    @staticmethod
    def _add_monthday_dates(reason_map, start_date: date, end_date: date, monthday: int):
        y = start_date.year
        m = start_date.month
        while True:
            if y > end_date.year or (y == end_date.year and m > end_date.month):
                break
            if m == 12:
                next_month = date(y + 1, 1, 1)
            else:
                next_month = date(y, m + 1, 1)
            last_day = (next_month - timedelta(days=1)).day
            day = min(monthday, last_day)
            d = date(y, m, day)
            if start_date <= d <= end_date:
                reason_map.setdefault(d, set()).add(f"monthday:{monthday}")

            if m == 12:
                y += 1
                m = 1
            else:
                m += 1
