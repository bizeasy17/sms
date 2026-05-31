from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy import create_engine, text


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    ident = str(name or "").strip()
    if not _IDENT_RE.match(ident):
        raise CommandError(f"unsafe SQL identifier: {name}")
    return f'"{ident}"'


class Command(BaseCommand):
    help = "Sync Tushare index_dailybasic history into local table for fast market-overall adjustment."

    def add_arguments(self, parser):
        parser.add_argument("--config", type=str, help="Path to pipeline yaml config")
        parser.add_argument("--start-date", type=str, help="Start date YYYY-MM-DD")
        parser.add_argument("--end-date", type=str, help="End date YYYY-MM-DD")
        parser.add_argument("--lookback-years", type=int, default=8, help="Default lookback years when start-date is omitted")
        parser.add_argument(
            "--indexes",
            type=str,
            default="",
            help="Comma-separated ts_codes, default from valuation_mapping.market_overall_adjustment.index_weights",
        )
        parser.add_argument(
            "--full",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Delete target indexes rows in date window before writing",
        )
        parser.add_argument(
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Only print row counts",
        )
        parser.add_argument(
            "--page-limit",
            type=int,
            default=3000,
            help="Tushare page size per request (default 3000)",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=20,
            help="Maximum pages per index to fetch (default 20)",
        )

    def _load_config(self, override_path: str | None) -> dict:
        if override_path:
            cfg_path = Path(override_path)
        else:
            cfg_path = Path(
                getattr(
                    settings,
                    "EARNINGS_CONFIG_PATH",
                    str(Path(settings.BASE_DIR) / "configs" / "default.yaml"),
                )
            )
        if not cfg_path.is_absolute():
            cfg_path = Path(settings.BASE_DIR) / cfg_path
        if not cfg_path.exists():
            raise CommandError(f"Config not found: {cfg_path}")
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    @staticmethod
    def _normalize_ymd(value: str) -> str:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            raise CommandError(f"invalid date: {value}")
        return dt.strftime("%Y%m%d")

    @staticmethod
    def _fetch_index_dailybasic_all_pages(pro, ts_code: str, start_ymd: str, end_ymd: str, page_limit: int, max_pages: int):
        pages = []
        offset = 0
        hit_max_pages = False
        for _page in range(max_pages):
            frame = pro.index_dailybasic(
                ts_code=ts_code,
                start_date=start_ymd,
                end_date=end_ymd,
                fields="ts_code,trade_date,pe,pe_ttm,pb,turnover_rate_f",
                offset=offset,
                limit=page_limit,
            )
            if frame is None or frame.empty:
                break
            pages.append(frame)
            rows_count = int(frame.shape[0])
            if rows_count < page_limit:
                break
            offset += rows_count
        else:
            hit_max_pages = True

        if not pages:
            return pd.DataFrame(), hit_max_pages
        return pd.concat(pages, ignore_index=True), hit_max_pages

    def handle(self, *_args, **options):
        cfg = self._load_config(options.get("config"))
        data_cfg = (cfg.get("data") or {})
        val_cfg = ((cfg.get("valuation_mapping") or {}).get("market_overall_adjustment") or {})

        db_url = str(data_cfg.get("financial_db_url") or data_cfg.get("db_url") or "").strip()
        if not db_url:
            raise CommandError("Missing data.financial_db_url or data.db_url in config")

        table_name = str(data_cfg.get("index_dailybasic_table") or "earnings_mkt_index_dailybasic").strip()
        table_sql = _safe_ident(table_name)

        indexes_arg = str(options.get("indexes") or "").strip()
        if indexes_arg:
            index_codes = [x.strip().upper() for x in indexes_arg.split(",") if x.strip()]
        else:
            weights = val_cfg.get("index_weights") or {}
            index_codes = [str(x).strip().upper() for x in weights.keys() if str(x).strip()]
        if not index_codes:
            raise CommandError("No index ts_code provided and config index_weights is empty")

        end_date = options.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        end_ymd = self._normalize_ymd(end_date)

        start_date = options.get("start_date")
        if start_date:
            start_ymd = self._normalize_ymd(start_date)
        else:
            years = max(1, int(options.get("lookback_years") or 8))
            start_dt = pd.to_datetime(end_ymd, format="%Y%m%d") - timedelta(days=years * 370)
            start_ymd = start_dt.strftime("%Y%m%d")

        dry_run = bool(options.get("dry_run", False))
        full = bool(options.get("full", False))
        page_limit = max(100, int(options.get("page_limit") or 3000))
        max_pages = max(1, int(options.get("max_pages") or 20))

        try:
            import tushare as ts  # type: ignore
        except Exception as exc:
            raise CommandError(f"tushare import failed: {exc}") from exc

        token = str(settings.TUSHARE_TOKEN or "").strip() if hasattr(settings, "TUSHARE_TOKEN") else ""
        if not token:
            token = str(data_cfg.get("tushare_token") or "").strip()
        if not token:
            token = str(__import__("os").getenv("TUSHARE_TOKEN") or "").strip()
        if not token:
            raise CommandError("TUSHARE_TOKEN not found in settings/config/env")

        ts.set_token(token)
        pro = ts.pro_api()

        engine = create_engine(db_url)

        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_sql} (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            pe DOUBLE PRECISION,
            pe_ttm DOUBLE PRECISION,
            pb DOUBLE PRECISION,
            turnover_rate_f DOUBLE PRECISION,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ts_code, trade_date)
        )
        """

        with engine.begin() as conn:
            conn.execute(text(create_sql))
            # Forward-compatible with older tables created before `pe` was added.
            conn.execute(text(f"ALTER TABLE {table_sql} ADD COLUMN IF NOT EXISTS pe DOUBLE PRECISION"))

        total_rows = 0
        for code in index_codes:
            frame, hit_max_pages = self._fetch_index_dailybasic_all_pages(
                pro=pro,
                ts_code=code,
                start_ymd=start_ymd,
                end_ymd=end_ymd,
                page_limit=page_limit,
                max_pages=max_pages,
            )
            if frame is None or frame.empty:
                self.stdout.write(self.style.WARNING(f"{code}: empty"))
                continue
            if hit_max_pages:
                self.stdout.write(self.style.WARNING(f"{code}: reached max_pages={max_pages}, history may still be truncated"))

            local = frame[["ts_code", "trade_date", "pe", "pe_ttm", "pb", "turnover_rate_f"]].copy()
            local["trade_date"] = pd.to_datetime(local["trade_date"], errors="coerce")
            local = local.dropna(subset=["trade_date"])
            local["trade_date"] = local["trade_date"].dt.strftime("%Y-%m-%d")
            local["pe"] = pd.to_numeric(local["pe"], errors="coerce")
            local["pe_ttm"] = pd.to_numeric(local["pe_ttm"], errors="coerce")
            local["pb"] = pd.to_numeric(local["pb"], errors="coerce")
            local["turnover_rate_f"] = pd.to_numeric(local["turnover_rate_f"], errors="coerce")
            local = local.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")

            if local.empty:
                self.stdout.write(self.style.WARNING(f"{code}: empty after clean"))
                continue

            rows = local.to_dict(orient="records")
            if dry_run:
                self.stdout.write(f"[dry-run] {code}: rows={len(rows)}")
                total_rows += len(rows)
                continue

            with engine.begin() as conn:
                if full:
                    conn.execute(
                        text(
                            f"DELETE FROM {table_sql} WHERE ts_code = :ts_code AND trade_date >= :start_date AND trade_date <= :end_date"
                        ),
                        {"ts_code": code, "start_date": start_ymd, "end_date": end_ymd},
                    )
                upsert_sql = text(
                    f"""
                    INSERT INTO {table_sql} (ts_code, trade_date, pe, pe_ttm, pb, turnover_rate_f, created_at, updated_at)
                    VALUES (:ts_code, :trade_date, :pe, :pe_ttm, :pb, :turnover_rate_f, NOW(), NOW())
                    ON CONFLICT (ts_code, trade_date)
                    DO UPDATE SET
                        pe = EXCLUDED.pe,
                        pe_ttm = EXCLUDED.pe_ttm,
                        pb = EXCLUDED.pb,
                        turnover_rate_f = EXCLUDED.turnover_rate_f,
                        updated_at = NOW()
                    """
                )
                conn.execute(upsert_sql, rows)

            total_rows += len(rows)
            self.stdout.write(self.style.SUCCESS(f"{code}: upserted={len(rows)}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"sync_index_dailybasic_local done: indexes={len(index_codes)} rows={total_rows} range=[{start_ymd},{end_ymd}] dry_run={dry_run}"
            )
        )
