from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from earnings_forecast.models import FinancialDisclosureDateRecord


def _parse_yyyymmdd(value: str) -> datetime.date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty date")
    return datetime.strptime(text, "%Y%m%d").date()


def _iter_dates(start_date: datetime.date, end_date: datetime.date):
    cur = start_date
    while cur <= end_date:
        yield cur
        cur = cur + timedelta(days=1)


def _normalize_scope(scope: str) -> list[str]:
    text = str(scope or "ALL").strip().upper()
    if text == "ALL":
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def _row_signature(payload: dict) -> str:
    stable = repr(sorted(payload.items())).encode("utf-8", errors="ignore")
    return hashlib.sha1(stable).hexdigest()


def _text(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() == "nan":
        return ""
    return s


class Command(BaseCommand):
    help = "Sync disclosure_date records by ann_date range without full symbol scan."

    def add_arguments(self, parser):
        parser.add_argument("--start-date", type=str, help="Start date YYYYMMDD, default today")
        parser.add_argument("--end-date", type=str, help="End date YYYYMMDD, default start-date")
        parser.add_argument("--scope", type=str, default="ALL", help="ALL or ts_code prefixes")
        parser.add_argument("--api-limit", type=int, default=2000, help="Tushare page size")
        parser.add_argument("--batch-size", type=int, default=1000, help="DB upsert batch size")

    def handle(self, *args, **options):
        token = (os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_PRO_TOKEN") or "").strip()
        if not token:
            raise CommandError("Missing TUSHARE_TOKEN/TUSHARE_PRO_TOKEN")

        ts.set_token(token)
        pro = ts.pro_api()

        today = timezone.localdate()
        start_text = str(options.get("start_date") or "").strip() or today.strftime("%Y%m%d")
        end_text = str(options.get("end_date") or "").strip() or start_text

        try:
            start_date = _parse_yyyymmdd(start_text)
            end_date = _parse_yyyymmdd(end_text)
        except ValueError as exc:
            raise CommandError(f"invalid date: {exc}")

        if end_date < start_date:
            raise CommandError("end-date must be >= start-date")

        prefixes = _normalize_scope(options.get("scope"))
        api_limit = max(100, int(options.get("api_limit") or 2000))
        batch_size = max(100, int(options.get("batch_size") or 1000))

        total_rows = 0
        total_upserted = 0

        self.stdout.write(
            self.style.SUCCESS(
                f"sync disclosure by ann_date start: start={start_date} end={end_date} scope={prefixes or 'ALL'}"
            )
        )

        for d in _iter_dates(start_date, end_date):
            ann_date = d.strftime("%Y%m%d")
            offset = 0
            date_rows = 0
            date_upserted = 0

            while True:
                df = pro.disclosure_date(ann_date=ann_date, limit=api_limit, offset=offset)
                if df is None or df.empty:
                    break

                rows = []
                for payload in df.to_dict(orient="records"):
                    ts_code = _text(payload.get("ts_code")).upper()
                    if not ts_code:
                        continue
                    if prefixes and not any(ts_code.startswith(p) for p in prefixes):
                        continue

                    ann = _text(payload.get("ann_date"))
                    end = _text(payload.get("end_date"))
                    pre = _text(payload.get("pre_date"))
                    actual = _text(payload.get("actual_date"))
                    modify = _text(payload.get("modify_date"))
                    period = end
                    sign = _row_signature(
                        {
                            "ts_code": ts_code,
                            "ann_date": ann,
                            "end_date": end,
                            "pre_date": pre,
                            "actual_date": actual,
                            "modify_date": modify,
                        }
                    )

                    rows.append(
                        FinancialDisclosureDateRecord(
                            ts_code=ts_code,
                            ann_date=ann,
                            end_date=end,
                            period=period,
                            row_signature=sign,
                            source_file="tushare-disclosure-ann-date",
                            pre_date=pre,
                            actual_date=actual,
                            modify_date=modify,
                        )
                    )

                if rows:
                    for i in range(0, len(rows), batch_size):
                        chunk = rows[i : i + batch_size]
                        FinancialDisclosureDateRecord.objects.bulk_create(
                            chunk,
                            update_conflicts=True,
                            unique_fields=["ts_code", "ann_date", "end_date", "period", "row_signature"],
                            update_fields=["source_file", "pre_date", "actual_date", "modify_date", "imported_at"],
                        )
                        date_upserted += len(chunk)

                fetched = len(df)
                date_rows += fetched
                if fetched < api_limit:
                    break
                offset += api_limit

            total_rows += date_rows
            total_upserted += date_upserted
            self.stdout.write(f"ann_date={ann_date} rows={date_rows} upserted={date_upserted}")

        self.stdout.write(
            self.style.SUCCESS(
                f"sync disclosure by ann_date done: rows={total_rows} upserted={total_upserted}"
            )
        )
