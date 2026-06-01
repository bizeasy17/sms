from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from typing import Iterable, Optional

import pandas as pd
import tushare as ts
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import FloatField, IntegerField, BigIntegerField
from django.utils import timezone

from earnings_forecast.models import FinancialCacheImportRun, get_financial_endpoint_model


DEFAULT_APIS = [
    "income",
    "balancesheet_vip",
    "cashflow_vip",
    "forecast_vip",
    "express_vip",
    "dividend",
    "fina_indicator_vip",
    "fina_audit",
    "fina_mainbz_vip",
    "disclosure_date",
]


def _normalize_api_list(raw: str) -> list[str]:
    items = [str(item).strip() for item in str(raw or "").split(",") if str(item).strip()]
    return items or list(DEFAULT_APIS)


def _normalize_ts_codes(ts_codes: list[str], scope: str, limit: Optional[int], resume: Optional[str]) -> list[str]:
    scope = str(scope or "ALL").strip().upper()
    out = list(ts_codes)

    if scope != "ALL":
        prefixes = [part.strip() for part in scope.split(",") if part.strip()]
        if prefixes:
            out = [code for code in out if any(str(code).startswith(prefix) for prefix in prefixes)]

    if resume:
        out = [code for code in out if str(code) >= str(resume)]

    if limit is not None and limit > 0:
        out = out[:limit]

    return out


def _load_ts_codes_from_file(path: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            code = str(raw or "").strip().upper()
            if not code:
                continue
            if code in seen:
                continue
            seen.add(code)
            out.append(code)
    return out


def _safe_call_api(
    pro,
    api_name: str,
    ts_code: str,
    start_date: Optional[str],
    end_date: Optional[str],
    limit: int,
    offset: Optional[int] = None,
):
    func = getattr(pro, api_name, None)
    if func is None:
        raise ValueError(f"Unsupported tushare endpoint: {api_name}")

    candidates: Iterable[dict] = [
        {
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "offset": offset,
        },
        {
            "ts_code": ts_code,
            "ann_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "offset": offset,
        },
        {
            "ts_code": ts_code,
            "period": start_date,
            "limit": limit,
            "offset": offset,
        },
        {
            "ts_code": ts_code,
            "limit": limit,
            "offset": offset,
        },
    ]

    for kwargs in candidates:
        cleaned = {k: v for k, v in kwargs.items() if v not in (None, "")}
        try:
            df = func(**cleaned)
            if df is None:
                return pd.DataFrame()
            return df
        except TypeError:
            continue

    return pd.DataFrame()


def _pull_full_history(
    pro,
    api_name: str,
    ts_code: str,
    start_date: Optional[str],
    end_date: Optional[str],
    api_limit: int,
    max_pages: int,
) -> pd.DataFrame:
    page = 0
    offset = 0
    frames: list[pd.DataFrame] = []
    seen_signatures: set[str] = set()

    while page < max_pages:
        df = _safe_call_api(
            pro=pro,
            api_name=api_name,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            limit=api_limit,
            offset=offset,
        )

        if df is None or df.empty:
            break

        signature = ""
        try:
            signature = str(df.iloc[0].to_dict())
        except (ValueError, TypeError, KeyError, IndexError):
            signature = f"rows={len(df)}"

        if signature in seen_signatures:
            break
        seen_signatures.add(signature)

        frames.append(df)

        if len(df) < api_limit:
            break

        page += 1
        offset += api_limit

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates().reset_index(drop=True)
    return merged


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
    # Keep DB writes robust for non-scalar API values.
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
    help = "Directly sync Tushare financial history into earnings service DB (no file cache)."

    def add_arguments(self, parser):
        parser.add_argument("--apis", type=str, default=",".join(DEFAULT_APIS), help="Comma separated endpoints")
        parser.add_argument("--scope", type=str, default="ALL", help="ALL or ts_code prefixes like 60,00,30")
        parser.add_argument("--tscode", type=str, help="Single ts_code")
        parser.add_argument("--tscodes-file", type=str, help="Text file with one ts_code per line")
        parser.add_argument("--start-date", type=str, help="Start date YYYYMMDD")
        parser.add_argument("--end-date", type=str, help="End date YYYYMMDD")
        parser.add_argument("--limit", type=int, help="Limit number of symbols")
        parser.add_argument("--resume", type=str, help="Resume from ts_code")
        parser.add_argument("--api-limit", type=int, default=2000, help="Page size for each API call")
        parser.add_argument("--max-pages", type=int, default=200, help="Max pages per endpoint/symbol")
        parser.add_argument("--batch-size", type=int, default=1000, help="DB upsert batch size")
        parser.add_argument(
            "--latest-only",
            action="store_true",
            default=False,
            help="Only fetch latest page for each endpoint/symbol",
        )
        parser.add_argument(
            "--strict-fields",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Fail fast when endpoint response contains unmapped columns",
        )

    def _resolve_ts_codes(
        self,
        pro,
        single_code: Optional[str],
        ts_codes_file: Optional[str],
        scope: str,
        limit: Optional[int],
        resume: Optional[str],
    ) -> list[str]:
        if single_code:
            return [str(single_code).strip()]

        if ts_codes_file:
            file_codes = _load_ts_codes_from_file(ts_codes_file)
            return _normalize_ts_codes(file_codes, scope=scope, limit=limit, resume=resume)

        base = pro.stock_basic(list_status="L", fields="ts_code")
        if base is None or base.empty:
            raise CommandError("Unable to fetch symbol list from Tushare stock_basic")

        ts_codes = sorted({str(x).strip() for x in base["ts_code"].dropna().tolist() if str(x).strip()})
        return _normalize_ts_codes(ts_codes, scope=scope, limit=limit, resume=resume)

    def _upsert_records(self, endpoint: str, ts_code: str, frame: pd.DataFrame, batch_size: int, strict_fields: bool) -> int:
        if frame is None or frame.empty:
            return 0
        endpoint_model = get_financial_endpoint_model(endpoint)
        if endpoint_model is None:
            return 0
        model_fields = {f.name: f for f in endpoint_model._meta.fields}

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

            # Auto-expand raw endpoint tables so columns keep parity with API fields.
            missing_cols = [c for c in incoming_data_cols if c not in existing_cols]
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

        rows: list[tuple] = []
        for row in frame.to_dict(orient="records"):
            payload = {k: ("" if pd.isna(v) else v) for k, v in row.items()}
            ann_date = _pick_date_value(payload, ["ann_date", "f_ann_date", "publish_date"])
            end_date = _pick_date_value(payload, ["end_date", "report_date"])
            period = _pick_date_value(payload, ["period", "report_type", "comp_type"])
            sign = _row_signature(payload)

            values = {
                "ts_code": ts_code,
                "ann_date": ann_date,
                "end_date": end_date,
                "period": period,
                "row_signature": sign,
                "source_file": "tushare-direct",
            }
            for c in incoming_data_cols:
                values[c] = _normalize_for_field(row.get(c), model_fields.get(c)) if c in model_fields else _normalize_value(row.get(c))
            for c in extra_required_cols:
                field_obj = model_fields.get(c)
                if c not in values:
                    default = field_obj.get_default() if (field_obj is not None and hasattr(field_obj, "get_default")) else ""
                    values[c] = "" if default is None else default
            rows.append(tuple(values.get(c) for c in all_cols))

        upserted = 0
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            with connection.cursor() as cursor:
                cursor.executemany(sql, chunk)
            upserted += len(chunk)

        return upserted

    def handle(self, *args, **options):
        token = (os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_PRO_TOKEN") or "").strip()
        if not token:
            raise CommandError("Missing TUSHARE_TOKEN/TUSHARE_PRO_TOKEN")

        ts.set_token(token)
        pro = ts.pro_api()

        apis = _normalize_api_list(options.get("apis"))
        latest_only = bool(options.get("latest_only", False))
        strict_fields = bool(options.get("strict_fields", True))
        api_limit = int(options.get("api_limit") or 2000)
        max_pages = int(options.get("max_pages") or 200)
        batch_size = max(100, int(options.get("batch_size") or 1000))

        ts_codes = self._resolve_ts_codes(
            pro=pro,
            single_code=options.get("tscode"),
            ts_codes_file=options.get("tscodes_file"),
            scope=options.get("scope"),
            limit=options.get("limit"),
            resume=options.get("resume"),
        )
        if not ts_codes:
            raise CommandError("No symbols to process")

        FinancialCacheImportRun.objects.filter(
            cache_dir="tushare-direct",
            status="running",
            finished_at__isnull=True,
        ).update(
            status="aborted",
            error_message="superseded by newer direct sync run",
            finished_at=timezone.now(),
        )

        run = FinancialCacheImportRun.objects.create(
            cache_dir="tushare-direct",
            endpoints=",".join(apis),
            status="running",
        )

        files_scanned = 0
        rows_parsed = 0
        rows_upserted = 0
        api_errors: list[str] = []

        try:
            total = len(ts_codes)
            self.stdout.write(self.style.SUCCESS(f"start direct sync: total_codes={total}, apis={','.join(apis)}"))
            self.stdout.write(
                f"mode: {'latest_only' if latest_only else 'full_history'} | api_limit={api_limit} | max_pages={max_pages}"
            )

            for idx, code in enumerate(ts_codes, start=1):
                self.stdout.write(f"[{idx}/{total}] {code}")
                for api_name in apis:
                    if get_financial_endpoint_model(api_name) is None:
                        self.stderr.write(f"  - {api_name}: skipped (unsupported endpoint table)")
                        continue
                    try:
                        if latest_only:
                            df = _safe_call_api(
                                pro=pro,
                                api_name=api_name,
                                ts_code=code,
                                start_date=options.get("start_date"),
                                end_date=options.get("end_date"),
                                limit=api_limit,
                                offset=None,
                            )
                        else:
                            df = _pull_full_history(
                                pro=pro,
                                api_name=api_name,
                                ts_code=code,
                                start_date=options.get("start_date"),
                                end_date=options.get("end_date"),
                                api_limit=api_limit,
                                max_pages=max_pages,
                            )

                        files_scanned += 1
                        row_count = 0 if df is None else len(df)
                        rows_parsed += row_count
                        inserted = self._upsert_records(
                            endpoint=api_name,
                            ts_code=code,
                            frame=df,
                            batch_size=batch_size,
                            strict_fields=strict_fields,
                        )
                        rows_upserted += inserted
                        self.stdout.write(f"  - {api_name}: rows={row_count}, upserted={inserted}")
                    except Exception as exc:
                        msg = f"{code}:{api_name}:{exc}"
                        api_errors.append(msg)
                        self.stderr.write(f"  - {api_name}: failed ({exc})")

                run.files_scanned = files_scanned
                run.rows_parsed = rows_parsed
                run.rows_upserted = rows_upserted
                run.save(update_fields=["files_scanned", "rows_parsed", "rows_upserted"])

            run.status = "success" if not api_errors else "failed"
            run.files_scanned = files_scanned
            run.rows_parsed = rows_parsed
            run.rows_upserted = rows_upserted
            run.error_message = "\n".join(api_errors[:20])
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "files_scanned", "rows_parsed", "rows_upserted", "error_message", "finished_at"])
        except Exception as exc:
            run.status = "failed"
            run.files_scanned = files_scanned
            run.rows_parsed = rows_parsed
            run.rows_upserted = rows_upserted
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "files_scanned", "rows_parsed", "rows_upserted", "error_message", "finished_at"])
            raise

        self.stdout.write(
            self.style.SUCCESS(
                f"direct sync done: api_calls={files_scanned}, rows_parsed={rows_parsed}, rows_upserted={rows_upserted}"
            )
        )
