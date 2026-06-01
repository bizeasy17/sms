from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    identifier = str(name or "").strip()
    if not _IDENT_RE.match(identifier):
        raise CommandError(f"unsafe SQL identifier: {name}")
    return f'"{identifier}"'


def _attach_audit_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    now_utc = datetime.now(timezone.utc)
    out["created_at"] = now_utc
    out["updated_at"] = now_utc
    return out


class Command(BaseCommand):
    help = "Sync ETL trading/fundamental/corporation/industry tables into local earnings DB mirrors."

    def add_arguments(self, parser):
        parser.add_argument("--config", type=str, help="Path to pipeline yaml config")
        parser.add_argument(
            "--mode",
            choices=["range", "full", "delta"],
            default="range",
            help="range: refresh by date range; full: truncate and full reload; delta: incremental by max trade_date",
        )
        parser.add_argument("--start-date", type=str, help="Start trade_date YYYY-MM-DD")
        parser.add_argument("--end-date", type=str, help="End trade_date YYYY-MM-DD")
        parser.add_argument("--freq", type=str, default="D", help="Frequency filter, e.g. D/W/M")
        parser.add_argument("--chunk-size", type=int, default=50000, help="Rows per source chunk")
        parser.add_argument(
            "--retention-years",
            type=int,
            default=0,
            help="Keep only recent N years in target trading/fundamental tables (0 to disable)",
        )
        parser.add_argument(
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Only print planned actions and row counts",
        )

    def _load_config(self, config_override: Optional[str]) -> dict:
        if config_override:
            cfg_path = Path(config_override)
        else:
            cfg_path = Path(getattr(settings, "EARNINGS_CONFIG_PATH", str(Path(settings.BASE_DIR) / "configs" / "default.yaml")))
        if not cfg_path.is_absolute():
            cfg_path = Path(settings.BASE_DIR) / cfg_path
        if not cfg_path.exists():
            raise CommandError(f"Config not found: {cfg_path}")
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return data

    @staticmethod
    def _delete_target_rows(
        target_engine,
        table: str,
        mode: str,
        start_date: Optional[str],
        end_date: Optional[str],
        freq: str,
    ) -> None:
        with target_engine.begin() as conn:
            if mode == "full":
                conn.execute(text(f"TRUNCATE TABLE {_safe_ident(table)}"))
                return

            where = ["freq = :freq"]
            params = {"freq": freq}
            if start_date:
                where.append("trade_date >= :start_date")
                params["start_date"] = start_date
            if end_date:
                where.append("trade_date <= :end_date")
                params["end_date"] = end_date
            conn.execute(text(f"DELETE FROM {_safe_ident(table)} WHERE {' AND '.join(where)}"), params)

    def _sync_dim_table(
        self,
        source_engine,
        target_engine,
        source_table: str,
        target_table: str,
        select_sql: str,
        dry_run: bool,
    ) -> int:
        try:
            frame = pd.read_sql_query(select_sql, source_engine)
        except SQLAlchemyError as exc:
            raise CommandError(f"read source table failed: {source_table}: {exc}") from exc

        if frame is None or frame.empty:
            self.stdout.write(f"{target_table}: source empty")
            return 0

        if dry_run:
            self.stdout.write(f"[dry-run] {target_table}: rows={len(frame)}")
            return len(frame)

        frame = _attach_audit_columns(frame)

        with target_engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {_safe_ident(target_table)}"))

        frame.to_sql(target_table, target_engine, if_exists="append", index=False, method="multi", chunksize=10000)
        return len(frame)

    def _sync_fact_table(
        self,
        source_engine,
        target_engine,
        source_table: str,
        target_table: str,
        columns: list[str],
        mode: str,
        start_date: Optional[str],
        end_date: Optional[str],
        freq: str,
        chunk_size: int,
        dry_run: bool,
    ) -> int:
        def _max_trade_date(engine, table: str, freq_value: str) -> Optional[str]:
            try:
                with engine.begin() as conn:
                    value = conn.execute(
                        text(f"SELECT MAX(trade_date) FROM {_safe_ident(table)} WHERE freq = :freq"),
                        {"freq": freq_value},
                    ).scalar()
            except SQLAlchemyError:
                return None
            if value is None:
                return None
            text_value = str(value).strip()
            return text_value or None

        cols = ", ".join(columns)
        where_parts = ["freq = :freq"]
        params: dict[str, str] = {"freq": freq}

        effective_start = start_date
        if mode == "delta":
            source_max = _max_trade_date(source_engine, source_table, freq)
            target_max = _max_trade_date(target_engine, target_table, freq)
            self.stdout.write(
                f"{target_table}: delta check target_max={target_max or '-'} source_max={source_max or '-'}"
            )
            if source_max is None:
                self.stdout.write(f"{target_table}: source empty for freq={freq}, skip delta sync")
                return 0
            if target_max and source_max <= target_max:
                self.stdout.write(f"{target_table}: no newer source rows, skip delta sync")
                return 0
            # Reload from current target max date (one-point overlap) to handle same-date corrections.
            effective_start = target_max or start_date

        if mode in {"range", "delta"}:
            if effective_start:
                where_parts.append("trade_date >= :start_date")
                params["start_date"] = effective_start
            if end_date:
                where_parts.append("trade_date <= :end_date")
                params["end_date"] = end_date

        where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        sql = text(f"SELECT {cols} FROM {source_table}{where_sql}")

        total_rows = 0
        chunk_index = 0
        started_at = time.perf_counter()
        if not dry_run:
            delete_mode = "range" if mode == "delta" else mode
            self._delete_target_rows(target_engine, target_table, delete_mode, effective_start, end_date, freq)

        try:
            chunks = pd.read_sql_query(sql, source_engine, params=params, chunksize=chunk_size)
            for chunk in chunks:
                if chunk is None or chunk.empty:
                    continue
                chunk_index += 1
                chunk_rows = len(chunk)
                total_rows += len(chunk)
                if not dry_run:
                    chunk = _attach_audit_columns(chunk)
                    chunk.to_sql(target_table, target_engine, if_exists="append", index=False, method="multi", chunksize=10000)
                elapsed = time.perf_counter() - started_at
                prefix = "[dry-run] " if dry_run else ""
                self.stdout.write(
                    f"{prefix}{target_table}: chunk={chunk_index} rows={chunk_rows} total={total_rows} elapsed_sec={elapsed:.2f}"
                )
        except SQLAlchemyError as exc:
            raise CommandError(f"sync failed for {source_table}: {exc}") from exc

        return total_rows

    @staticmethod
    def _prune_target_rows(
        target_engine,
        table: str,
        freq: str,
        cutoff_date: str,
        dry_run: bool,
    ) -> int:
        if dry_run:
            with target_engine.begin() as conn:
                result = conn.execute(
                    text(f"SELECT COUNT(1) FROM {_safe_ident(table)} WHERE freq = :freq AND trade_date < :cutoff_date"),
                    {"freq": freq, "cutoff_date": cutoff_date},
                )
                return int(result.scalar() or 0)

        with target_engine.begin() as conn:
            result = conn.execute(
                text(f"DELETE FROM {_safe_ident(table)} WHERE freq = :freq AND trade_date < :cutoff_date"),
                {"freq": freq, "cutoff_date": cutoff_date},
            )
            return int(result.rowcount or 0)

    def handle(self, *args, **options):
        cfg = self._load_config(options.get("config"))
        data_cfg = (cfg or {}).get("data") or {}

        source_db_url = str(data_cfg.get("etl_db_url") or data_cfg.get("db_url") or "").strip()
        if not source_db_url:
            raise CommandError("Missing source ETL db_url in config data.etl_db_url or data.db_url")
        target_db_url = str(data_cfg.get("financial_db_url") or "").strip()
        if not target_db_url:
            raise CommandError("Missing target DB url in config data.financial_db_url")

        mode = str(options.get("mode") or "range").strip().lower()
        start_date = options.get("start_date") or data_cfg.get("start_date")
        end_date = options.get("end_date") or data_cfg.get("end_date")
        freq = str(options.get("freq") or data_cfg.get("freq") or "D").strip().upper()
        chunk_size = max(1000, int(options.get("chunk_size") or 50000))
        retention_years = max(0, int(options.get("retention_years") or 0))
        dry_run = bool(options.get("dry_run", False))

        trading_source = str(data_cfg.get("etl_trading_table") or "stockdata_stocktradinghistory").strip()
        fundamental_source = str(data_cfg.get("etl_fundamental_table") or "stockdata_stockfundamentalhistory").strip()
        corp_source = str(data_cfg.get("etl_corporation_table") or "stockdata_corporation").strip()
        industry_source = str(data_cfg.get("etl_industry_table") or "stockdata_industry").strip()

        trading_target = str(data_cfg.get("trading_table") or "earnings_mkt_trading_history").strip()
        fundamental_target = str(data_cfg.get("fundamental_table") or "earnings_mkt_fundamental_history").strip()
        corp_target = str(data_cfg.get("industry_map_table") or "earnings_dim_corporation").strip()
        industry_target = str(data_cfg.get("industry_dim_table") or "earnings_dim_industry").strip()

        source_engine = create_engine(source_db_url)
        target_engine = create_engine(target_db_url)

        self.stdout.write(
            f"start sync_market_local mode={mode} freq={freq} range=[{start_date or '-'} ~ {end_date or '-'}]"
        )

        dim_ind_rows = self._sync_dim_table(
            source_engine=source_engine,
            target_engine=target_engine,
            source_table=industry_source,
            target_table=industry_target,
            select_sql=f"SELECT id, name FROM {industry_source}",
            dry_run=dry_run,
        )
        self.stdout.write(f"industry synced: {dim_ind_rows}")

        dim_corp_rows = self._sync_dim_table(
            source_engine=source_engine,
            target_engine=target_engine,
            source_table=corp_source,
            target_table=corp_target,
            select_sql=f"SELECT ts_code, industry_id FROM {corp_source}",
            dry_run=dry_run,
        )
        self.stdout.write(f"corporation synced: {dim_corp_rows}")

        trading_rows = self._sync_fact_table(
            source_engine=source_engine,
            target_engine=target_engine,
            source_table=trading_source,
            target_table=trading_target,
            columns=["ts_code", "trade_date", "freq", "close", "pct_change", "vol"],
            mode=mode,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
            chunk_size=chunk_size,
            dry_run=dry_run,
        )
        self.stdout.write(f"trading synced: {trading_rows}")

        fundamental_rows = self._sync_fact_table(
            source_engine=source_engine,
            target_engine=target_engine,
            source_table=fundamental_source,
            target_table=fundamental_target,
            columns=["ts_code", "trade_date", "freq", "pe", "pb", "ps", "total_mv", "circ_mv", "turnover_rate"],
            mode=mode,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
            chunk_size=chunk_size,
            dry_run=dry_run,
        )
        self.stdout.write(f"fundamental synced: {fundamental_rows}")

        pruned_trading = 0
        pruned_fundamental = 0
        cutoff_date = None
        if retention_years > 0:
            cutoff_date = str((pd.Timestamp(datetime.now(timezone.utc)) - pd.DateOffset(years=retention_years)).date())
            pruned_trading = self._prune_target_rows(
                target_engine=target_engine,
                table=trading_target,
                freq=freq,
                cutoff_date=cutoff_date,
                dry_run=dry_run,
            )
            pruned_fundamental = self._prune_target_rows(
                target_engine=target_engine,
                table=fundamental_target,
                freq=freq,
                cutoff_date=cutoff_date,
                dry_run=dry_run,
            )
            tag = "[dry-run] " if dry_run else ""
            self.stdout.write(
                f"{tag}retention pruned (<{cutoff_date}): trading={pruned_trading}, fundamental={pruned_fundamental}"
            )

        self.stdout.write(
            f"sync_market_local done: industry={dim_ind_rows}, corporation={dim_corp_rows}, "
            f"trading={trading_rows}, fundamental={fundamental_rows}, "
            f"retention_years={retention_years}, cutoff={cutoff_date or '-'}, "
            f"pruned_trading={pruned_trading}, pruned_fundamental={pruned_fundamental}"
        )
