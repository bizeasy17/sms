from __future__ import annotations

import datetime
import time
from decimal import Decimal
from typing import List

import pandas as pd
import tushare as ts
from django.core.management.base import BaseCommand
from django.db import transaction

from datastore.models import StockTradingHistory


class Command(BaseCommand):
    help = "Backfill index daily history from Tushare into datastore.StockTradingHistory"

    def add_arguments(self, parser):
        parser.add_argument("--index-codes", type=str, default="", help="Comma-separated index codes")
        parser.add_argument(
            "--market",
            type=str,
            default="SSE,SZSE,CSI,CICC",
            help="Comma-separated markets for index_basic when --index-codes is empty",
        )
        parser.add_argument("--start-date", type=str, default="20000101", help="Start date YYYYMMDD")
        parser.add_argument("--end-date", type=str, default="", help="End date YYYYMMDD, default today")
        parser.add_argument("--batch-size", type=int, default=2000)
        parser.add_argument("--limit", type=int, default=5000, help="Tushare page size")
        parser.add_argument("--sleep-ms", type=int, default=160, help="Sleep ms between calls")
        parser.add_argument("--max-retries", type=int, default=6)
        parser.add_argument("--start-index", type=int, default=0)
        parser.add_argument("--max-indexes", type=int, default=0)
        parser.add_argument("--log-every", type=int, default=100, help="Print progress every N indexes")

    def handle(self, *args, **options):
        pro = ts.pro_api()
        start_date = str(options["start_date"] or "20000101").strip()
        end_date = str(options["end_date"] or "").strip() or datetime.date.today().strftime("%Y%m%d")
        batch_size = max(1, int(options["batch_size"] or 2000))
        page_limit = max(100, int(options["limit"] or 5000))
        sleep_ms = max(0, int(options["sleep_ms"] or 0))
        max_retries = max(0, int(options["max_retries"] or 0))
        start_index = max(0, int(options["start_index"] or 0))
        max_indexes = max(0, int(options["max_indexes"] or 0))
        log_every = max(1, int(options["log_every"] or 1))

        index_codes_raw = str(options["index_codes"] or "").strip()
        if index_codes_raw:
            index_codes = [c.strip().upper() for c in index_codes_raw.split(",") if c.strip()]
        else:
            index_codes = self._load_index_codes_from_basic(pro, str(options["market"] or ""), sleep_ms=sleep_ms)

        if not index_codes:
            self.stdout.write(self.style.WARNING("No index codes to sync."))
            return
        if start_index >= len(index_codes):
            self.stdout.write(self.style.WARNING("start-index exceeds code list length; nothing to do."))
            return

        run_codes = index_codes[start_index:]
        if max_indexes > 0:
            run_codes = run_codes[:max_indexes]

        self.stdout.write(
            f"Index count(total={len(index_codes)}, run={len(run_codes)}, start_index={start_index}, max_indexes={max_indexes})"
        )

        total_fetched = 0
        total_inserted = 0
        failed: List[str] = []

        for i, code in enumerate(run_codes, start=1):
            try:
                df = self._fetch_index_daily_paged(
                    pro=pro,
                    index_code=code,
                    start_date=start_date,
                    end_date=end_date,
                    page_limit=page_limit,
                    sleep_ms=sleep_ms,
                    max_retries=max_retries,
                )
                if df.empty:
                    if (i % log_every == 0) or i == 1 or i == len(run_codes):
                        self.stdout.write(f"[{i}/{len(run_codes)}] {code}: fetched=0 inserted=0")
                    continue

                fetched = int(len(df.index))
                inserted = int(self._save_rows(df, batch_size=batch_size))
                total_fetched += fetched
                total_inserted += inserted
                if (i % log_every == 0) or i == 1 or i == len(run_codes):
                    self.stdout.write(f"[{i}/{len(run_codes)}] {code}: fetched={fetched} inserted={inserted}")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{code}: {exc}")
                self.stderr.write(f"[{i}/{len(run_codes)}] {code}: FAILED {exc}")

            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

        self.stdout.write("---- Summary ----")
        self.stdout.write(f"indexes={len(run_codes)} fetched_rows={total_fetched} inserted_rows={total_inserted}")
        self.stdout.write(f"failed_indexes={len(failed)}")
        for item in failed[:50]:
            self.stderr.write(item)

    def _load_index_codes_from_basic(self, pro, market_csv: str, sleep_ms: int) -> List[str]:
        markets = [m.strip().upper() for m in market_csv.split(",") if m.strip()]
        codes: List[str] = []
        for market in markets:
            df = pro.index_basic(market=market)
            if df is None or df.empty or "ts_code" not in df.columns:
                continue
            codes.extend([str(v).strip().upper() for v in df["ts_code"].dropna().tolist()])
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

        seen = set()
        uniq: List[str] = []
        for code in codes:
            if not code or code in seen:
                continue
            seen.add(code)
            uniq.append(code)
        return uniq

    def _fetch_index_daily_paged(
        self,
        pro,
        index_code: str,
        start_date: str,
        end_date: str,
        page_limit: int,
        sleep_ms: int,
        max_retries: int,
    ) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        cursor_end = datetime.datetime.strptime(end_date, "%Y%m%d").date()
        lower = datetime.datetime.strptime(start_date, "%Y%m%d").date()
        guard = 0

        while cursor_end >= lower and guard < 200:
            page = self._call_index_daily_with_retry(
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

    def _call_index_daily_with_retry(
        self,
        pro,
        ts_code: str,
        start_date: str,
        end_date: str,
        limit: int,
        sleep_ms: int,
        max_retries: int,
    ) -> pd.DataFrame:
        retry = 0
        while True:
            try:
                return pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date, limit=limit)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                is_rate_limit = ("频率超限" in msg) or ("每分钟最多访问" in msg)
                if (not is_rate_limit) or (retry >= max_retries):
                    raise
                retry += 1
                base = max(0.8, sleep_ms / 1000.0)
                backoff = base * (2 ** retry)
                self.stderr.write(f"[WARN] rate limit for {ts_code} retry={retry} sleep={backoff:.1f}s")
                time.sleep(backoff)

    def _to_decimal_or_none(self, value):
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        if pd.isna(value):
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except Exception:  # noqa: BLE001
            return None

    def _save_rows(self, df: pd.DataFrame, batch_size: int) -> int:
        needed_cols = [
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        ]
        for col in needed_cols:
            if col not in df.columns:
                df[col] = None

        rows = []
        for r in df.to_dict(orient="records"):
            trade_date_text = str(r.get("trade_date") or "").strip()
            if len(trade_date_text) != 8:
                continue
            trade_date = datetime.date(int(trade_date_text[0:4]), int(trade_date_text[4:6]), int(trade_date_text[6:8]))
            ts_code = str(r.get("ts_code") or "").strip().upper()
            if not ts_code:
                continue

            open_v = self._to_decimal_or_none(r.get("open"))
            high_v = self._to_decimal_or_none(r.get("high"))
            low_v = self._to_decimal_or_none(r.get("low"))
            close_v = self._to_decimal_or_none(r.get("close"))
            pre_close_v = self._to_decimal_or_none(r.get("pre_close"))
            change_v = self._to_decimal_or_none(r.get("change"))
            pct_change_v = self._to_decimal_or_none(r.get("pct_chg"))
            amount_v = self._to_decimal_or_none(r.get("amount"))
            vol_raw = r.get("vol")
            vol_v = int(float(vol_raw)) if vol_raw is not None and not pd.isna(vol_raw) else None

            rows.append(
                StockTradingHistory(
                    ts_code=ts_code,
                    freq="D",
                    trade_date=trade_date,
                    open=open_v,
                    high=high_v,
                    low=low_v,
                    close=close_v,
                    pre_close=pre_close_v,
                    change=change_v,
                    pct_change=pct_change_v,
                    vol=vol_v,
                    amount=amount_v,
                    open_qfq=open_v,
                    high_qfq=high_v,
                    low_qfq=low_v,
                    close_qfq=close_v,
                    pre_close_qfq=pre_close_v,
                    open_hfq=open_v,
                    high_hfq=high_v,
                    low_hfq=low_v,
                    close_hfq=close_v,
                    pre_close_hfq=pre_close_v,
                )
            )

        if not rows:
            return 0

        with transaction.atomic():
            StockTradingHistory.objects.bulk_create(rows, ignore_conflicts=True, batch_size=batch_size)
        return len(rows)
