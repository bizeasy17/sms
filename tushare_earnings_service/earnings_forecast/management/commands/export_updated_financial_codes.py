from __future__ import annotations

import os
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from earnings_forecast.models import FINANCIAL_ENDPOINT_MODEL_MAP


REMOTE_FINANCIAL_ANN_ENDPOINT_MAP = {
    "income": "income",
    "fina_indicator_vip": "fina_indicator_vip",
    "balancesheet_vip": "balancesheet",
    "cashflow_vip": "cashflow",
    "express_vip": "express_vip",
    "forecast_vip": "forecast_vip",
}


def _parse_dt(text: str):
    raw = str(text or "").strip()
    if not raw:
        return None
    fmts = (
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d",
        "%Y-%m-%d",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(raw, fmt)
            return timezone.make_aware(dt, timezone.get_current_timezone())
        except ValueError:
            continue
    return None


def _normalize_prefixes(scope: str) -> list[str]:
    text = str(scope or "ALL").strip().upper()
    if text == "ALL":
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def _iter_dates(start_dt, end_dt):
    current = start_dt.date()
    end_date = end_dt.date()
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _build_tushare_pro():
    token = (os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_PRO_TOKEN") or "").strip()
    if not token:
        raise CommandError("Missing TUSHARE_TOKEN/TUSHARE_PRO_TOKEN for remote event export")

    try:
        import tushare as ts
    except ImportError as exc:
        raise CommandError("tushare is required for remote event export") from exc

    ts.set_token(token)
    return ts.pro_api()


def _collect_remote_dividend_codes(changed_since, prefixes):
    pro = _build_tushare_pro()
    now = timezone.now()
    codes: set[str] = set()

    for field_name in ("ann_date", "record_date", "ex_date"):
        for day in _iter_dates(changed_since, now):
            day_text = day.strftime("%Y%m%d")
            df = pro.dividend(**{field_name: day_text})
            if df is None or df.empty or "ts_code" not in df.columns:
                continue
            for code in df["ts_code"].dropna().astype(str).str.upper().tolist():
                if prefixes and not any(code.startswith(prefix) for prefix in prefixes):
                    continue
                codes.add(code)
    return codes


def _normalize_remote_financial_ann_apis(text):
    raw = [item.strip() for item in str(text or "").split(",") if item.strip()]
    if not raw:
        raw = ["fina_indicator_vip"]
    apis = []
    seen = set()
    for api in raw:
        if api in REMOTE_FINANCIAL_ANN_ENDPOINT_MAP and api not in seen:
            apis.append(api)
            seen.add(api)
    return apis


def _collect_remote_financial_ann_codes(changed_since, prefixes, apis):
    pro = _build_tushare_pro()
    now = timezone.now()
    codes: set[str] = set()
    skipped_apis: list[str] = []

    for api in apis:
        endpoint_name = REMOTE_FINANCIAL_ANN_ENDPOINT_MAP.get(api)
        if not endpoint_name:
            continue
        endpoint = getattr(pro, endpoint_name, None)
        if endpoint is None:
            continue
        for day in _iter_dates(changed_since, now):
            day_text = day.strftime("%Y%m%d")
            try:
                df = endpoint(ann_date=day_text)
            except Exception as exc:
                message = str(exc)
                # Some endpoints (e.g. fina_indicator) require ts_code and cannot be scanned by ann_date globally.
                if "必填参数" in message and "ts_code" in message:
                    skipped_apis.append(api)
                    break
                continue
            if df is None or df.empty or "ts_code" not in df.columns:
                continue
            for code in df["ts_code"].dropna().astype(str).str.upper().tolist():
                if prefixes and not any(code.startswith(prefix) for prefix in prefixes):
                    continue
                codes.add(code)
    return codes, sorted(set(skipped_apis))


class Command(BaseCommand):
    help = "Export ts_codes updated since a timestamp from financial endpoint tables."

    def add_arguments(self, parser):
        parser.add_argument("--changed-since", type=str, required=True, help="Anchor datetime")
        parser.add_argument("--scope", type=str, default="ALL", help="ALL or ts_code prefixes")
        parser.add_argument("--apis", type=str, default="", help="Comma-separated endpoints; empty means all")
        parser.add_argument("--output-file", type=str, required=True, help="Output file path")
        parser.add_argument(
            "--include-remote-dividend-events",
            action="store_true",
            default=False,
            help="Also include ts_codes from remote dividend ann_date/record_date/ex_date events since anchor",
        )
        parser.add_argument(
            "--remote-dividend-lookback-days",
            type=int,
            default=0,
            help="Extra lookback days when querying remote dividend events",
        )
        parser.add_argument(
            "--include-remote-financial-ann-events",
            action="store_true",
            default=False,
            help="Also include ts_codes from remote financial ann_date events (income/fina_indicator etc.)",
        )
        parser.add_argument(
            "--remote-financial-ann-apis",
            type=str,
            default="fina_indicator_vip",
            help="Comma-separated apis for remote ann_date event scan",
        )
        parser.add_argument(
            "--remote-financial-lookback-days",
            type=int,
            default=0,
            help="Extra lookback days when querying remote financial ann_date events",
        )

    def handle(self, *args, **options):
        changed_since = _parse_dt(options.get("changed_since"))
        if changed_since is None:
            raise CommandError("invalid --changed-since")

        prefixes = _normalize_prefixes(options.get("scope"))
        api_text = str(options.get("apis") or "").strip()
        if api_text:
            apis = [x.strip() for x in api_text.split(",") if x.strip()]
        else:
            apis = list(FINANCIAL_ENDPOINT_MODEL_MAP.keys())

        changed_codes: set[str] = set()
        for api in apis:
            model = FINANCIAL_ENDPOINT_MODEL_MAP.get(api)
            if model is None:
                self.stderr.write(f"skip unknown api: {api}")
                continue
            qs = model.objects.exclude(ts_code__isnull=True).exclude(ts_code="").filter(imported_at__gt=changed_since)
            for code in qs.values_list("ts_code", flat=True).distinct():
                ts_code = str(code or "").strip().upper()
                if not ts_code:
                    continue
                if prefixes and not any(ts_code.startswith(p) for p in prefixes):
                    continue
                changed_codes.add(ts_code)

        if options.get("include_remote_dividend_events"):
            lookback_days = max(0, int(options.get("remote_dividend_lookback_days") or 0))
            remote_anchor = changed_since - timedelta(days=lookback_days)
            remote_codes = _collect_remote_dividend_codes(remote_anchor, prefixes)
            changed_codes.update(remote_codes)
            self.stdout.write(
                self.style.SUCCESS(
                    "included remote dividend event ts_codes: "
                    f"count={len(remote_codes)} lookback_days={lookback_days}"
                )
            )

        if options.get("include_remote_financial_ann_events"):
            ann_lookback_days = max(0, int(options.get("remote_financial_lookback_days") or 0))
            ann_anchor = changed_since - timedelta(days=ann_lookback_days)
            ann_apis = _normalize_remote_financial_ann_apis(options.get("remote_financial_ann_apis"))
            ann_codes, skipped_apis = _collect_remote_financial_ann_codes(ann_anchor, prefixes, ann_apis)
            changed_codes.update(ann_codes)
            self.stdout.write(
                self.style.SUCCESS(
                    "included remote financial ann_date event ts_codes: "
                    f"count={len(ann_codes)} lookback_days={ann_lookback_days} apis={','.join(ann_apis)}"
                )
            )
            if skipped_apis:
                self.stdout.write(
                    self.style.WARNING(
                        "skipped remote ann_date apis requiring ts_code: " + ",".join(skipped_apis)
                    )
                )

        out_path = str(options.get("output_file") or "").strip()
        if not out_path:
            raise CommandError("missing --output-file")

        ordered = sorted(changed_codes)
        with open(out_path, "w", encoding="utf-8") as f:
            for code in ordered:
                f.write(code + "\n")

        self.stdout.write(self.style.SUCCESS(f"exported updated ts_codes: count={len(ordered)} file={out_path}"))
