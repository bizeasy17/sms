from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import tushare as ts
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stockdata.models import Corporation


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


def _normalize_ts_codes(scope: str, limit: Optional[int], resume: Optional[str]) -> list[str]:
    scope = str(scope or "ALL").strip().upper()
    qs = Corporation.objects.filter(list_status="L").values_list("ts_code", flat=True).order_by("ts_code")
    ts_codes = list(qs)

    if scope != "ALL":
        prefixes = [part.strip() for part in scope.split(",") if part.strip()]
        if prefixes:
            ts_codes = [code for code in ts_codes if any(str(code).startswith(prefix) for prefix in prefixes)]

    if resume:
        ts_codes = [code for code in ts_codes if str(code) >= str(resume)]

    if limit is not None and limit > 0:
        ts_codes = ts_codes[:limit]

    return ts_codes


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

    # Different endpoints accept different date fields. Try common signatures progressively.
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
        except Exception:
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


def _write_frame(df: pd.DataFrame, output_root: Path, api_name: str, ts_code: str) -> Path:
    endpoint_dir = output_root / api_name
    endpoint_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = endpoint_dir / f"{ts_code}.parquet"
    csv_path = endpoint_dir / f"{ts_code}.csv"

    if df is None or df.empty:
        # Keep a lightweight marker file to indicate the symbol was scanned.
        csv_path.write_text("", encoding="utf-8")
        return csv_path

    try:
        df.to_parquet(parquet_path, index=False)
        return parquet_path
    except Exception:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        return csv_path


class Command(BaseCommand):
    help = "批量缓存 Tushare 财务类数据到 analysis/financial_cache（parquet 优先，失败回退 csv）"

    def add_arguments(self, parser):
        parser.add_argument("--apis", type=str, default=",".join(DEFAULT_APIS), help="逗号分隔接口名")
        parser.add_argument("--scope", type=str, default="ALL", help="ALL 或 ts_code 前缀，如 60,00,30")
        parser.add_argument("--tscode", type=str, help="仅处理单个 ts_code")
        parser.add_argument("--start-date", type=str, help="起始日期 YYYYMMDD")
        parser.add_argument("--end-date", type=str, help="结束日期 YYYYMMDD")
        parser.add_argument("--limit", type=int, help="最多处理股票数量")
        parser.add_argument("--resume", type=str, help="从某个 ts_code 开始")
        parser.add_argument("--api-limit", type=int, default=2000, help="单次拉取条数（分页大小）")
        parser.add_argument("--max-pages", type=int, default=50, help="单接口单股票最大分页数")
        parser.add_argument(
            "--latest-only",
            action="store_true",
            default=False,
            help="仅拉取最新一页（关闭全历史分页）",
        )
        parser.add_argument("--output-dir", type=str, default="analysis/financial_cache", help="输出目录（相对 BASE_DIR）")

    def handle(self, *args, **options):
        apis = _normalize_api_list(options.get("apis"))
        tscode = options.get("tscode")
        start_date = options.get("start_date")
        end_date = options.get("end_date")
        api_limit = int(options.get("api_limit") or 2000)
        max_pages = int(options.get("max_pages") or 50)
        latest_only = bool(options.get("latest_only", False))

        output_dir = Path(options.get("output_dir") or "analysis/financial_cache")
        if not output_dir.is_absolute():
            output_dir = Path(settings.BASE_DIR) / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if tscode:
            ts_codes = [str(tscode).strip()]
        else:
            ts_codes = _normalize_ts_codes(
                scope=options.get("scope"),
                limit=options.get("limit"),
                resume=options.get("resume"),
            )

        if not ts_codes:
            raise CommandError("没有可处理的股票代码")

        token = (
            os.getenv("TUSHARE_TOKEN")
            or os.getenv("TUSHARE_PRO_TOKEN")
            or str(getattr(settings, "TUSHARE_TOKEN", "") or "").strip()
        )
        if not token:
            raise CommandError("缺少 Tushare Token，请在环境变量或 .env 中配置 TUSHARE_TOKEN")

        ts.set_token(token)
        pro = ts.pro_api()
        total = len(ts_codes)
        self.stdout.write(self.style.SUCCESS(f"start cache financials: total_codes={total}, apis={','.join(apis)}"))
        self.stdout.write(
            f"mode: {'latest_only' if latest_only else 'full_history'} | api_limit={api_limit} | max_pages={max_pages}"
        )

        for idx, code in enumerate(ts_codes, start=1):
            self.stdout.write(f"[{idx}/{total}] {code}")
            for api_name in apis:
                try:
                    if latest_only:
                        df = _safe_call_api(
                            pro=pro,
                            api_name=api_name,
                            ts_code=code,
                            start_date=start_date,
                            end_date=end_date,
                            limit=api_limit,
                            offset=None,
                        )
                    else:
                        df = _pull_full_history(
                            pro=pro,
                            api_name=api_name,
                            ts_code=code,
                            start_date=start_date,
                            end_date=end_date,
                            api_limit=api_limit,
                            max_pages=max_pages,
                        )
                    target = _write_frame(df, output_dir, api_name, code)
                    self.stdout.write(f"  - {api_name}: rows={0 if df is None else len(df)} -> {target}")
                except Exception as exc:
                    self.stderr.write(f"  - {api_name}: failed ({exc})")

        self.stdout.write(self.style.SUCCESS(f"cache financials done: {output_dir}"))
