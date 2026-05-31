import datetime
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from valuation_api.models import Corporation, StockExpressVip


def _parse_any_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    text = text.replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _safe_decimal(value, max_abs=None):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if max_abs is not None and abs(number) >= float(max_abs):
        return None
    return number


def _get_tushare_pro_client():
    try:
        import tushare as ts
    except ImportError as exc:
        raise CommandError("tushare is not installed in current environment") from exc

    token = (
        os.getenv("TUSHARE_TOKEN")
        or os.getenv("TUSHARE_PRO_TOKEN")
        or str(getattr(settings, "TUSHARE_TOKEN", "") or "").strip()
    )
    if token:
        ts.set_token(token)

    try:
        return ts.pro_api()
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        raise CommandError(f"failed to initialize tushare pro client: {exc}") from exc


class Command(BaseCommand):
    help = "Sync local valuation_express_vip from Tushare express_vip endpoint."

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, default="", help="Single ts_code to sync")
        parser.add_argument("--scope", type=str, default="", help="Prefix filter, e.g. 60/68/00/30/8")
        parser.add_argument("--code-offset", type=int, default=0)
        parser.add_argument("--code-limit", type=int, default=0)
        parser.add_argument("--limit-per-stock", type=int, default=8)
        parser.add_argument("--request-interval", type=float, default=0.25)
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *_args, **options):
        tscode = str(options.get("tscode") or "").strip().upper()
        scope = str(options.get("scope") or "").strip()
        offset = max(0, int(options.get("code_offset") or 0))
        limit = max(0, int(options.get("code_limit") or 0))
        limit_per_stock = max(1, int(options.get("limit_per_stock") or 8))
        request_interval = max(0.0, float(options.get("request_interval") or 0.0))
        dry_run = bool(options.get("dry_run"))

        if tscode and scope:
            raise CommandError("use either --tscode or --scope, not both")

        pro = _get_tushare_pro_client()

        qs = Corporation.objects.order_by("ts_code")
        if tscode:
            qs = qs.filter(ts_code=tscode)
        else:
            listed_qs = qs.filter(list_status="L")
            if listed_qs.exists():
                qs = listed_qs
            if scope:
                qs = qs.filter(ts_code__startswith=scope)
            if offset:
                qs = qs[offset:]
            if limit:
                qs = qs[:limit]

        ts_codes = list(qs.values_list("ts_code", flat=True))
        if not ts_codes:
            self.stdout.write("No target ts_code selected.")
            return

        total_codes = len(ts_codes)
        fetched_codes = 0
        inserted_rows = 0
        failed_codes = 0

        for idx, code in enumerate(ts_codes, start=1):
            try:
                df = pro.express_vip(ts_code=code, limit=limit_per_stock)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                failed_codes += 1
                self.stderr.write(f"[{idx}/{total_codes}] {code} fetch failed: {exc}")
                continue

            if df is None or df.empty:
                if request_interval:
                    time.sleep(request_interval)
                continue

            records = df.fillna("").to_dict(orient="records")
            payload = []
            for row in records:
                ann_date = _parse_any_date(row.get("ann_date"))
                end_date = _parse_any_date(row.get("end_date"))
                if ann_date is None and end_date is None:
                    continue
                payload.append(
                    StockExpressVip(
                        ts_code=code,
                        ann_date=ann_date,
                        end_date=end_date,
                        revenue=_safe_decimal(row.get("revenue")),
                        total_revenue=_safe_decimal(row.get("total_revenue")),
                        oper_rev=_safe_decimal(row.get("oper_rev")),
                        n_income=_safe_decimal(row.get("n_income")),
                        n_income_attr_p=_safe_decimal(row.get("n_income_attr_p")),
                        profit_dedt=_safe_decimal(row.get("profit_dedt")),
                        # yoy fields map to Decimal(12,4); drop out-of-range values to keep sync resilient.
                        yoy_net_profit=_safe_decimal(row.get("yoy_net_profit"), max_abs=1e8),
                        yoy_dedu_np=_safe_decimal(row.get("yoy_dedu_np"), max_abs=1e8),
                        yoy_sales=_safe_decimal(row.get("yoy_sales"), max_abs=1e8),
                        yoy_np=_safe_decimal(row.get("yoy_np"), max_abs=1e8),
                        netprofit_yoy=_safe_decimal(row.get("netprofit_yoy"), max_abs=1e8),
                        tr_yoy=_safe_decimal(row.get("tr_yoy"), max_abs=1e8),
                        or_yoy=_safe_decimal(row.get("or_yoy"), max_abs=1e8),
                    )
                )

            if payload and not dry_run:
                StockExpressVip.objects.bulk_create(
                    payload,
                    batch_size=1000,
                    update_conflicts=True,
                    unique_fields=["ts_code", "ann_date", "end_date"],
                    update_fields=[
                        "revenue",
                        "total_revenue",
                        "oper_rev",
                        "n_income",
                        "n_income_attr_p",
                        "profit_dedt",
                        "yoy_net_profit",
                        "yoy_dedu_np",
                        "yoy_sales",
                        "yoy_np",
                        "netprofit_yoy",
                        "tr_yoy",
                        "or_yoy",
                        "updated_at",
                    ],
                )

            if payload:
                fetched_codes += 1
                inserted_rows += len(payload)

            if idx % 50 == 0 or idx == total_codes:
                self.stdout.write(
                    f"progress {idx}/{total_codes} fetched_codes={fetched_codes} rows={inserted_rows} failed={failed_codes}"
                )

            if request_interval:
                time.sleep(request_interval)

        self.stdout.write(
            "syncexpressvip done: "
            f"codes={total_codes} fetched_codes={fetched_codes} rows={inserted_rows} failed_codes={failed_codes} dry_run={dry_run}"
        )
