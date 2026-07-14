from __future__ import annotations

import datetime
import time
from typing import List

import pandas as pd
import tushare as ts
from django.core.management.base import BaseCommand
from django.db import connections, transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Backfill selected index_dailybasic history into earnings_mkt_index_dailybasic"

    def add_arguments(self, parser):
        parser.add_argument(
            "--index-codes",
            type=str,
            required=True,
            help="Comma-separated index codes, e.g. 000001.SH,399001.SZ",
        )
        parser.add_argument("--start-date", type=str, default="20040101")
        parser.add_argument("--end-date", type=str, default="")
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--sleep-ms", type=int, default=160)
        parser.add_argument("--max-retries", type=int, default=6)

    def handle(self, *args, **options):
        pro = ts.pro_api()
        index_codes = [c.strip().upper() for c in str(options["index_codes"] or "").split(",") if c.strip()]
        start_date = str(options["start_date"] or "20040101").strip()
        end_date = str(options["end_date"] or "").strip() or datetime.date.today().strftime("%Y%m%d")
        page_limit = max(100, int(options["limit"] or 5000))
        sleep_ms = max(0, int(options["sleep_ms"] or 0))
        max_retries = max(0, int(options["max_retries"] or 0))

        total_rows = 0
        for idx, code in enumerate(index_codes, start=1):
            frame = self._fetch_index_dailybasic_paged(
                pro=pro,
                index_code=code,
                start_date=start_date,
                end_date=end_date,
                page_limit=page_limit,
                sleep_ms=sleep_ms,
                max_retries=max_retries,
            )
            written = self._upsert_rows(frame)
            total_rows += written
            self.stdout.write(f"[{idx}/{len(index_codes)}] {code}: rows={written}")
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

        self.stdout.write(f"done total_rows={total_rows}")

    def _fetch_index_dailybasic_paged(self, pro, index_code: str, start_date: str, end_date: str, page_limit: int, sleep_ms: int, max_retries: int) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        cursor_end = datetime.datetime.strptime(end_date, "%Y%m%d").date()
        lower = datetime.datetime.strptime(start_date, "%Y%m%d").date()
        guard = 0

        while cursor_end >= lower and guard < 100:
            page = self._call_with_retry(
                pro=pro,
                ts_code=index_code,
                start_date=start_date,
                end_date=cursor_end.strftime("%Y%m%d"),
                limit=page_limit,
                sleep_ms=sleep_ms,
                max_retries=max_retries,
            )
            if page is None or page.empty:
                break
            frames.append(page)
            if "trade_date" not in page.columns:
                break
            trade_dates = pd.to_datetime(page["trade_date"].astype(str), format="%Y%m%d", errors="coerce").dropna()
            if trade_dates.empty:
                break
            oldest = trade_dates.min().date()
            if oldest <= lower:
                break
            next_end = oldest - datetime.timedelta(days=1)
            if next_end >= cursor_end:
                break
            cursor_end = next_end
            guard += 1
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

        if not frames:
            return pd.DataFrame()

        merged = pd.concat(frames, ignore_index=True)
        merged = merged.drop_duplicates(subset=["ts_code", "trade_date"], keep="first")
        merged = merged.sort_values("trade_date")
        return merged

    def _call_with_retry(self, pro, ts_code: str, start_date: str, end_date: str, limit: int, sleep_ms: int, max_retries: int):
        retry = 0
        while True:
            try:
                return pro.index_dailybasic(ts_code=ts_code, start_date=start_date, end_date=end_date, limit=limit)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                is_rate_limit = ("频率超限" in msg) or ("每分钟最多访问" in msg)
                if (not is_rate_limit) or retry >= max_retries:
                    raise
                retry += 1
                base = max(0.8, sleep_ms / 1000.0)
                time.sleep(base * (2 ** retry))

    def _upsert_rows(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0

        for column in ["pe", "pe_ttm", "pb", "turnover_rate_f"]:
            if column not in df.columns:
                df[column] = None
        now = timezone.now()
        payload = []
        for row in df.to_dict(orient="records"):
            trade_date_text = str(row.get("trade_date") or "").strip()
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if not ts_code or len(trade_date_text) != 8:
                continue
            payload.append(
                (
                    ts_code,
                    datetime.date(int(trade_date_text[:4]), int(trade_date_text[4:6]), int(trade_date_text[6:8])),
                    self._to_float_or_none(row.get("pe_ttm")),
                    self._to_float_or_none(row.get("pb")),
                    self._to_float_or_none(row.get("turnover_rate_f")),
                    now,
                    now,
                    self._to_float_or_none(row.get("pe")),
                )
            )
        if not payload:
            return 0

        sql = """
        INSERT INTO earnings_mkt_index_dailybasic
        (ts_code, trade_date, pe_ttm, pb, turnover_rate_f, created_at, updated_at, pe)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ts_code, trade_date)
        DO UPDATE SET
            pe_ttm = EXCLUDED.pe_ttm,
            pb = EXCLUDED.pb,
            turnover_rate_f = EXCLUDED.turnover_rate_f,
            updated_at = EXCLUDED.updated_at,
            pe = EXCLUDED.pe
        """
        with transaction.atomic(using="earnings"):
            with connections["earnings"].cursor() as cur:
                cur.executemany(sql, payload)
        return len(payload)

    @staticmethod
    def _to_float_or_none(value):
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except Exception:  # noqa: BLE001
            return None
