import datetime
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEV_ROOT = BASE_DIR.parent
if str(DEV_ROOT) not in sys.path:
    sys.path.insert(0, str(DEV_ROOT))
if str(DEV_ROOT / "tushare_earnings_service") not in sys.path:
    sys.path.insert(0, str(DEV_ROOT / "tushare_earnings_service"))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import transaction  # noqa: E402

from datastore.models import StockTradingHistory  # noqa: E402
from valuation.models import StockValuationSnapshot  # noqa: E402
from valuation_risk.management.commands.prefillvaluationrisk import (  # noqa: E402
    _load_indicator_profile,
    _to_float,
)
from valuation_risk.models import ValuationRiskFactor, ValuationRiskSnapshot  # noqa: E402
from valuation_risk.services import build_valuation_risk_payload  # noqa: E402

POOL_CODES = [
    "689009.SH",
    "002787.SZ",
    "600009.SH",
    "688578.SH",
    "000426.SZ",
    "603379.SH",
    "600066.SH",
    "002901.SZ",
    "688355.SH",
    "600299.SH",
    "600217.SH",
    "688155.SH",
    "000601.SZ",
    "300492.SZ",
    "601633.SH",
    "601127.SH",
    "603929.SH",
    "002150.SZ",
    "688076.SH",
    "300758.SZ",
]

START_DATE = datetime.date(2024, 1, 1)
END_DATE = datetime.date(2025, 12, 31)
MARKET = "CN"
FREQ = "D"
VALUATION_BAND_PCT = 0.10


def load_trade_dates() -> list[datetime.date]:
    qs = (
        StockTradingHistory.objects.filter(
            ts_code__in=POOL_CODES,
            freq=FREQ,
            trade_date__gte=START_DATE,
            trade_date__lte=END_DATE,
        )
        .values_list("trade_date", flat=True)
        .distinct()
        .order_by("trade_date")
    )
    return list(qs)


def prefill_valuation_snapshots(trade_dates: list[datetime.date], codes_file: Path) -> None:
    total = len(trade_dates)
    for idx, trade_date in enumerate(trade_dates, start=1):
        call_command(
            "prefillvaluationsnapshot",
            trade_date=trade_date.isoformat(),
            freq=FREQ,
            codes_file=str(codes_file),
            scope="ALL",
            market=MARKET,
            refresh_policy="missing",
            request_interval=0.0,
            business_match_topn=0,
            profit_buckets="both",
            verbosity=0,
        )
        if idx == 1 or idx == total or idx % 20 == 0:
            print(f"[valuation] progress {idx}/{total} trade_date={trade_date}", flush=True)


def backfill_risk_snapshots() -> None:
    rows = list(
        StockValuationSnapshot.objects.filter(
            ts_code__in=POOL_CODES,
            market=MARKET,
            trade_date__gte=START_DATE,
            trade_date__lte=END_DATE,
            valuation_variant="default",
        )
        .order_by(
            "ts_code",
            "trade_date",
            "valuation_variant",
            "profit_report_type",
            "profit_report_end_date",
            "valuation_method",
            "-updated_at",
        )
        .values(
            "ts_code",
            "trade_date",
            "valuation_variant",
            "valuation_method",
            "valuation_price",
            "profit_report_type",
            "profit_report_end_date",
            "profit_report_ann_date",
            "profit_data_source",
        )
    )

    grouped: dict[tuple, dict[str, dict]] = defaultdict(dict)
    anchors: dict[tuple, dict] = {}
    for row in rows:
        key = (
            row.get("ts_code"),
            row.get("trade_date"),
            row.get("valuation_variant") or "default",
            row.get("profit_report_type"),
            row.get("profit_report_end_date"),
        )
        method = str(row.get("valuation_method") or "").strip().lower()
        if not method:
            continue
        if method not in grouped[key]:
            grouped[key][method] = row
        if key not in anchors:
            anchors[key] = row

    keys = list(grouped.keys())
    total = len(keys)
    created = 0
    updated = 0
    factor_written = 0

    indicator_cache: dict[tuple[str, datetime.date | None], dict] = {}

    for idx, key in enumerate(keys, start=1):
        ts_code, trade_date, valuation_variant, profit_report_type, profit_report_end_date = key
        method_rows = list(grouped[key].values())
        method_rows.sort(key=lambda item: str(item.get("valuation_method") or ""))
        anchor = anchors.get(key) or {}

        profile_cache_key = (ts_code, profit_report_end_date)
        if profile_cache_key not in indicator_cache:
            indicator_cache[profile_cache_key] = _load_indicator_profile(
                ts_code,
                report_end_date=profit_report_end_date,
            )
        indicator_profile = indicator_cache[profile_cache_key]

        payload = build_valuation_risk_payload(
            ts_code=ts_code,
            market=MARKET,
            trade_date=trade_date,
            valuation_variant=valuation_variant,
            profit_report_type=profit_report_type,
            profit_report_end_date=profit_report_end_date,
            profit_report_ann_date=anchor.get("profit_report_ann_date"),
            profit_data_source=anchor.get("profit_data_source"),
            rows=[
                {
                    "valuation_method": row.get("valuation_method"),
                    "valuation_price": _to_float(row.get("valuation_price")),
                }
                for row in method_rows
            ],
            financial_profile=indicator_profile,
            base_band_pct=VALUATION_BAND_PCT,
        )

        defaults = {
            "risk_score": payload.get("risk_score"),
            "risk_level": payload.get("risk_level") or "UNKNOWN",
            "confidence": payload.get("confidence"),
            "summary": payload.get("summary") or "",
            "engine_version": payload.get("engine_version") or "v1_5_ruleset_20260411",
            "status": payload.get("status") or "READY",
            "metadata": payload.get("metadata") or {},
            "profit_report_end_date": payload.get("profit_report_end_date"),
            "profit_report_ann_date": payload.get("profit_report_ann_date"),
            "profit_data_source": payload.get("profit_data_source"),
        }

        with transaction.atomic():
            snapshot, created_flag = ValuationRiskSnapshot.objects.update_or_create(
                ts_code=ts_code,
                trade_date=payload.get("trade_date"),
                market=MARKET,
                valuation_variant=valuation_variant,
                profit_report_type=profit_report_type,
                defaults=defaults,
            )
            if created_flag:
                created += 1
            else:
                updated += 1

            snapshot.factors.all().delete()
            factors = payload.get("factors") or []
            factor_objects = []
            for factor_idx, factor in enumerate(factors):
                factor_objects.append(
                    ValuationRiskFactor(
                        snapshot=snapshot,
                        dimension=str(factor.get("dimension") or ""),
                        factor_code=str(factor.get("factor_code") or ""),
                        factor_name=str(factor.get("factor_name") or ""),
                        severity=str(factor.get("severity") or "INFO"),
                        factor_score=factor.get("factor_score"),
                        factor_value=str(factor.get("factor_value") or ""),
                        threshold=str(factor.get("threshold") or ""),
                        reason=str(factor.get("reason") or ""),
                        is_triggered=bool(factor.get("is_triggered")),
                        sort_order=factor_idx,
                        payload=factor.get("payload") or {},
                    )
                )
            if factor_objects:
                ValuationRiskFactor.objects.bulk_create(factor_objects)
                factor_written += len(factor_objects)

        if idx == 1 or idx == total or idx % 200 == 0:
            print(f"[risk] progress {idx}/{total}", flush=True)

    print(
        json.dumps(
            {
                "risk_created": created,
                "risk_updated": updated,
                "risk_factors": factor_written,
                "risk_groups": total,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )


def verify_coverage() -> None:
    valuation_count = StockValuationSnapshot.objects.filter(
        ts_code__in=POOL_CODES,
        trade_date__gte=START_DATE,
        trade_date__lte=END_DATE,
        valuation_variant="default",
    ).count()
    risk_count = ValuationRiskSnapshot.objects.filter(
        ts_code__in=POOL_CODES,
        trade_date__gte=START_DATE,
        trade_date__lte=END_DATE,
        valuation_variant="default",
    ).count()
    print(
        json.dumps(
            {
                "valuation_snapshot_rows": valuation_count,
                "risk_snapshot_rows": risk_count,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )


def main() -> None:
    trade_dates = load_trade_dates()
    if not trade_dates:
        print(json.dumps({"error": "No trade dates for pool in 2024-2025"}, ensure_ascii=True), flush=True)
        return

    codes_file = BASE_DIR / "tmp" / "pool_codes_20_for_backfill.txt"
    codes_file.parent.mkdir(parents=True, exist_ok=True)
    codes_file.write_text("\n".join(POOL_CODES) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "step": "start",
                "trade_dates": len(trade_dates),
                "codes": len(POOL_CODES),
                "start": START_DATE.isoformat(),
                "end": END_DATE.isoformat(),
            },
            ensure_ascii=True,
        ),
        flush=True,
    )

    prefill_valuation_snapshots(trade_dates, codes_file)
    backfill_risk_snapshots()
    verify_coverage()


if __name__ == "__main__":
    main()
