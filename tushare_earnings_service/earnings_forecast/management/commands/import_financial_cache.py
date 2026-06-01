from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import FloatField, IntegerField, BigIntegerField
from django.utils import timezone

from earnings_forecast.models import FinancialCacheImportRun, get_financial_endpoint_model


def _normalize_endpoints(raw: str) -> list[str]:
    items = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    return items


def _row_signature(payload: dict) -> str:
    stable = repr(sorted(payload.items())).encode("utf-8", errors="ignore")
    return hashlib.sha1(stable).hexdigest()


def _pick_date_value(row: dict, candidates: Iterable[str]) -> str:
    for key in candidates:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def _normalize_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value) if not isinstance(value, (str, int, float, bool)) else value


def _normalize_for_field(value, field_obj):
    v = _normalize_value(value)
    if v is None:
        if field_obj is not None and not getattr(field_obj, "null", True):
            default = field_obj.get_default() if hasattr(field_obj, "get_default") else ""
            return "" if default is None else default
        return None
    if isinstance(field_obj, (FloatField,)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if isinstance(field_obj, (IntegerField, BigIntegerField)):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    return v


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    text = str(name or "").strip()
    if not _IDENT_RE.match(text):
        raise CommandError(f"unsafe SQL identifier: {name}")
    return f'"{text}"'


class Command(BaseCommand):
    help = "Import ETL financial cache files into earnings service DB tables"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cache-dir",
            type=str,
            default="c:/Users/HANJ29/Development/code/sms/smartinvestor_etl/analysis/financial_cache",
            help="Financial cache root directory",
        )
        parser.add_argument("--endpoints", type=str, default="", help="Comma separated endpoints to import")
        parser.add_argument("--limit-files", type=int, default=0, help="Limit number of files for smoke test")
        parser.add_argument("--batch-size", type=int, default=1000, help="Bulk upsert batch size")
        parser.add_argument(
            "--strict-fields",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Fail fast when source file contains unmapped columns",
        )

    def handle(self, *args, **options):
        cache_dir = Path(str(options.get("cache_dir") or "")).expanduser().resolve()
        if not cache_dir.exists():
            raise CommandError(f"cache dir not found: {cache_dir}")

        endpoint_filter = set(_normalize_endpoints(options.get("endpoints")))
        limit_files = int(options.get("limit_files") or 0)
        batch_size = max(100, int(options.get("batch_size") or 1000))
        strict_fields = bool(options.get("strict_fields", True))

        run = FinancialCacheImportRun.objects.create(
            cache_dir=str(cache_dir),
            endpoints=",".join(sorted(endpoint_filter)) if endpoint_filter else "ALL",
            status="running",
        )

        files_scanned = 0
        rows_parsed = 0
        rows_upserted = 0

        try:
            endpoint_dirs = [p for p in cache_dir.iterdir() if p.is_dir()]
            endpoint_dirs.sort(key=lambda p: p.name)

            for endpoint_dir in endpoint_dirs:
                endpoint = endpoint_dir.name
                if endpoint_filter and endpoint not in endpoint_filter:
                    continue
                endpoint_model = get_financial_endpoint_model(endpoint)
                if endpoint_model is None:
                    self.stdout.write(self.style.WARNING(f"skip unsupported endpoint: {endpoint}"))
                    continue
                model_fields = {f.name: f for f in endpoint_model._meta.fields}

                file_paths = sorted(list(endpoint_dir.glob("*.parquet")) + list(endpoint_dir.glob("*.csv")))
                if limit_files > 0:
                    file_paths = file_paths[:limit_files]

                for file_path in file_paths:
                    files_scanned += 1

                    if file_path.suffix.lower() == ".parquet":
                        frame = pd.read_parquet(file_path)
                    else:
                        frame = pd.read_csv(file_path)

                    if frame is None or frame.empty:
                        continue

                    ts_code = file_path.stem
                    table_name = endpoint_model._meta.db_table
                    incoming_cols = [str(c).strip() for c in frame.columns if str(c).strip()]

                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
                            [table_name],
                        )
                        existing_cols = {str(r[0]) for r in cursor.fetchall()}

                        key_cols = ["ts_code", "ann_date", "end_date", "period", "row_signature"]
                        meta_cols = ["source_file"]
                        incoming_data_cols = [c for c in incoming_cols if c not in set(key_cols + meta_cols)]

                        missing_cols = [c for c in incoming_data_cols if c not in existing_cols]
                        if strict_fields and missing_cols:
                            self.stdout.write(self.style.WARNING(f"auto add columns for endpoint={endpoint}: {missing_cols[:20]}"))
                        for col in missing_cols:
                            cursor.execute(
                                f"ALTER TABLE {_safe_ident(table_name)} ADD COLUMN IF NOT EXISTS {_safe_ident(col)} text"
                            )

                    required_model_cols = [
                        f.name
                        for f in endpoint_model._meta.fields
                        if (not getattr(f, "null", True)) and f.name not in {"id", "imported_at"}
                    ]
                    extra_required_cols = [c for c in required_model_cols if c not in set(key_cols + incoming_data_cols + meta_cols)]

                    all_cols = key_cols + incoming_data_cols + extra_required_cols + meta_cols
                    update_cols = [c for c in all_cols if c not in key_cols]
                    col_sql = ", ".join(_safe_ident(c) for c in all_cols)
                    val_sql = ", ".join(["%s"] * len(all_cols))
                    set_sql = ", ".join(f"{_safe_ident(c)}=EXCLUDED.{_safe_ident(c)}" for c in update_cols)
                    sql = (
                        f"INSERT INTO {_safe_ident(table_name)} ({col_sql}, imported_at) VALUES ({val_sql}, NOW()) "
                        f"ON CONFLICT ({', '.join(_safe_ident(c) for c in key_cols)}) DO UPDATE SET {set_sql}, imported_at=NOW()"
                    )

                    rows = []
                    for row in frame.to_dict(orient="records"):
                        payload = {k: ("" if pd.isna(v) else v) for k, v in row.items()}
                        values = {
                            "ts_code": ts_code,
                            "ann_date": _pick_date_value(payload, ["ann_date", "f_ann_date", "publish_date"]),
                            "end_date": _pick_date_value(payload, ["end_date", "report_date"]),
                            "period": _pick_date_value(payload, ["period", "report_type", "comp_type"]),
                            "row_signature": _row_signature(payload),
                            "source_file": str(file_path),
                        }
                        for c in incoming_data_cols:
                            values[c] = _normalize_for_field(row.get(c), model_fields.get(c)) if c in model_fields else _normalize_value(row.get(c))
                        for c in extra_required_cols:
                            field_obj = model_fields.get(c)
                            if c not in values:
                                default = field_obj.get_default() if (field_obj is not None and hasattr(field_obj, "get_default")) else ""
                                values[c] = "" if default is None else default
                        rows.append(tuple(values.get(c) for c in all_cols))

                    rows_parsed += len(rows)
                    if not rows:
                        continue

                    for i in range(0, len(rows), batch_size):
                        chunk = rows[i : i + batch_size]
                        with connection.cursor() as cursor:
                            cursor.executemany(sql, chunk)
                        rows_upserted += len(chunk)

            run.status = "success"
            run.files_scanned = files_scanned
            run.rows_parsed = rows_parsed
            run.rows_upserted = rows_upserted
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "files_scanned", "rows_parsed", "rows_upserted", "finished_at"])
        except Exception as exc:
            run.status = "failed"
            run.files_scanned = files_scanned
            run.rows_parsed = rows_parsed
            run.rows_upserted = rows_upserted
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "files_scanned",
                    "rows_parsed",
                    "rows_upserted",
                    "error_message",
                    "finished_at",
                ]
            )
            raise

        self.stdout.write(
            self.style.SUCCESS(
                f"import done: files={files_scanned}, rows_parsed={rows_parsed}, rows_upserted={rows_upserted}"
            )
        )
