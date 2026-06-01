import json
from datetime import datetime
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datastore.models import Corporation, StockCostHistory, StockFundamentalHistory, StockTradingHistory
from prediction.management.commands.backtestmarketstylebatch import INDUSTRY_KEYWORDS, _pick_stocks_for_industry


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _parse_trade_date(value):
    if not value:
        return None
    text = str(value)
    try:
        if "T" in text:
            text = text.split("T", 1)[0]
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _upsert_rows(model_cls, corp, freq, rows, unique_keys, start_date=None, end_date=None, dry_run=False):
    valid_fields = {field.name for field in model_cls._meta.get_fields()}
    excluded = {"id", "created_at", "updated_at"}

    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        trade_date = _parse_trade_date(row.get("trade_date"))
        if trade_date is None:
            skipped += 1
            continue
        if start_date and trade_date < start_date:
            continue
        if end_date and trade_date > end_date:
            continue

        payload = {k: v for k, v in row.items() if k in valid_fields and k not in excluded}
        payload["trade_date"] = trade_date
        payload["ts_code"] = corp.ts_code
        payload["corporation"] = corp
        if "freq" in valid_fields:
            payload["freq"] = freq

        if any(payload.get(key) is None for key in unique_keys):
            skipped += 1
            continue

        lookups = {key: payload.get(key) for key in unique_keys}
        defaults = {k: v for k, v in payload.items() if k not in unique_keys}

        if dry_run:
            continue

        _, was_created = model_cls.objects.update_or_create(**lookups, defaults=defaults)
        if was_created:
            created += 1
        else:
            updated += 1

    return created, updated, skipped


class Command(BaseCommand):
    help = "Backfill 2022-2023 historical trading/fundamental (and optional cost) data for market-style backtest universes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--industries",
            type=str,
            default="银行,半导体,小金属,煤炭,有色,白酒,医药,消费电子,军工,光伏",
            help="Comma-separated industry groups used to pick stock universe",
        )
        parser.add_argument("--per-industry", type=int, default=5, help="Stocks per industry")
        parser.add_argument("--selection-year", type=int, default=2024, help="Year used for stock universe selection")
        parser.add_argument("--min-trade-days", type=int, default=160, help="Minimum trading days in selection year")
        parser.add_argument("--freq", type=str, default="D", help="Frequency")
        parser.add_argument("--start-date", type=str, default="2022-01-01", help="Backfill start date, format YYYY-MM-DD")
        parser.add_argument("--end-date", type=str, default="2023-12-31", help="Backfill end date, format YYYY-MM-DD")
        parser.add_argument("--limit", type=int, default=1200, help="ETL limit per stock per dtype")
        parser.add_argument("--include-cost", action="store_true", help="Also backfill cost history")
        parser.add_argument("--dry-run", action="store_true", help="Only evaluate scope, do not write DB")

    def handle(self, *args, **options):
        industries = [item.strip() for item in str(options.get("industries") or "").split(",") if item.strip()]
        per_industry = int(options.get("per_industry") or 5)
        selection_year = int(options.get("selection_year") or 2024)
        min_trade_days = int(options.get("min_trade_days") or 160)
        freq = str(options.get("freq") or "D").strip().upper() or "D"
        start_date_text = str(options.get("start_date") or "2022-01-01").strip()
        end_date_text = str(options.get("end_date") or "2023-12-31").strip()
        limit = int(options.get("limit") or 1200)
        include_cost = bool(options.get("include_cost"))
        dry_run = bool(options.get("dry_run"))

        try:
            start_date = datetime.strptime(start_date_text, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid date format: {exc}")

        if end_date < start_date:
            raise CommandError("--end-date must be >= --start-date")
        if per_industry <= 0:
            raise CommandError("--per-industry must be > 0")
        if limit <= 0:
            raise CommandError("--limit must be > 0")

        etl_base = str(getattr(settings, "ETL_BASE_URL", "") or "").rstrip("/")
        if not etl_base:
            raise CommandError("ETL_BASE_URL is not configured")

        selected = {}
        stock_universe = []
        for industry_name in industries:
            keywords = INDUSTRY_KEYWORDS.get(industry_name) or [industry_name]
            picks = _pick_stocks_for_industry(
                industry_name=industry_name,
                keywords=keywords,
                per_industry=per_industry,
                year=selection_year,
                min_trade_days=min_trade_days,
                valuation_source="recompute",
                allow_st=False,
            )
            selected[industry_name] = picks
            stock_universe.extend(picks)

        if not stock_universe:
            raise CommandError("No stocks selected for backfill. Please adjust constraints.")

        # De-duplicate by ts_code while keeping original order.
        dedup_codes = []
        seen = set()
        for row in stock_universe:
            code = row.get("ts_code")
            if code and code not in seen:
                seen.add(code)
                dedup_codes.append(code)

        corp_map = {c.ts_code: c for c in Corporation.objects.filter(ts_code__in=dedup_codes)}

        dtype_defs = [
            ("trading", StockTradingHistory, ("ts_code", "trade_date", "freq"), "stocks/{ts_code}/trades/{freq}/{anchor}/limit/{limit}/?format=json"),
            ("fundamental", StockFundamentalHistory, ("ts_code", "trade_date", "freq"), "stocks/{ts_code}/fundamentals/{freq}/{anchor}/limit/{limit}/?format=json"),
        ]
        if include_cost:
            dtype_defs.append(
                ("cost", StockCostHistory, ("ts_code", "trade_date"), "stocks/{ts_code}/cost/{freq}/{anchor}/limit/{limit}/?format=json")
            )

        summary = {
            "meta": {
                "industries": industries,
                "per_industry": per_industry,
                "selection_year": selection_year,
                "min_trade_days": min_trade_days,
                "freq": freq,
                "start_date": start_date_text,
                "end_date": end_date_text,
                "limit": limit,
                "include_cost": include_cost,
                "dry_run": dry_run,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
            "selected": selected,
            "results": [],
        }

        for ts_code in dedup_codes:
            corp = corp_map.get(ts_code)
            if not corp:
                summary["results"].append({"ts_code": ts_code, "ok": False, "error": "corporation_not_found"})
                continue

            stock_result = {"ts_code": ts_code, "ok": True, "dtypes": {}}
            for dtype, model_cls, unique_keys, path_template in dtype_defs:
                url = f"{etl_base}/" + path_template.format(
                    ts_code=ts_code,
                    freq=freq,
                    anchor=end_date_text,
                    limit=limit,
                )
                try:
                    response = requests.get(url, timeout=60)
                    response.raise_for_status()
                    rows = response.json()
                    if not isinstance(rows, list):
                        rows = []
                    created, updated, skipped = _upsert_rows(
                        model_cls=model_cls,
                        corp=corp,
                        freq=freq,
                        rows=rows,
                        unique_keys=unique_keys,
                        start_date=start_date,
                        end_date=end_date,
                        dry_run=dry_run,
                    )
                    stock_result["dtypes"][dtype] = {
                        "url": url,
                        "fetched_rows": len(rows),
                        "created": created,
                        "updated": updated,
                        "skipped": skipped,
                    }
                except Exception as exc:  # noqa: BLE001
                    stock_result["ok"] = False
                    stock_result["dtypes"][dtype] = {"url": url, "error": str(exc)}

            summary["results"].append(stock_result)

        output_dir = PROJECT_ROOT / "output" / "local_valuation_checks"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"market_style_history_backfill_{start_date_text}_{end_date_text}.json"
        output_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        ok_count = len([row for row in summary["results"] if row.get("ok")])
        self.stdout.write(f"{output_file}")
        self.stdout.write(f"backfill_done total={len(summary['results'])} ok={ok_count} dry_run={dry_run}")
