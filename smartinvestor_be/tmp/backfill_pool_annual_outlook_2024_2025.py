import datetime
import json
import os
import sys
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

from datastore.models import StockTradingHistory  # noqa: E402
from valuation.models import AnnualOutlookSnapshot  # noqa: E402

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
FREQ = "D"
OUTLOOK_VERSION = "annual_pool_backfill_20260503_v1"


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


def main() -> None:
    codes_file = BASE_DIR / "tmp" / "pool_codes_20_for_backfill.txt"
    codes_file.parent.mkdir(parents=True, exist_ok=True)
    codes_file.write_text("\n".join(POOL_CODES) + "\n", encoding="utf-8")

    trade_dates = load_trade_dates()
    if not trade_dates:
        print(json.dumps({"error": "No trade dates for pool in 2024-2025"}, ensure_ascii=True), flush=True)
        return

    total = len(trade_dates)
    print(
        json.dumps(
            {
                "step": "start",
                "codes": len(POOL_CODES),
                "trade_dates": total,
                "start": START_DATE.isoformat(),
                "end": END_DATE.isoformat(),
                "version": OUTLOOK_VERSION,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )

    for idx, trade_date in enumerate(trade_dates, start=1):
        call_command(
            "annualoutlook",
            trade_date=trade_date.isoformat(),
            scope="ALL",
            codes_file=str(codes_file),
            freq=FREQ,
            outlook_version=OUTLOOK_VERSION,
            persist=True,
            top=5,
            verbosity=0,
        )
        if idx == 1 or idx == total or idx % 20 == 0:
            print(f"[annualoutlook] progress {idx}/{total} trade_date={trade_date}", flush=True)

    row_count = AnnualOutlookSnapshot.objects.filter(
        ts_code__in=POOL_CODES,
        trade_date__gte=START_DATE,
        trade_date__lte=END_DATE,
        outlook_version=OUTLOOK_VERSION,
        freq=FREQ,
    ).count()

    print(
        json.dumps(
            {
                "annual_outlook_rows": row_count,
                "codes": len(POOL_CODES),
                "trade_dates": total,
                "version": OUTLOOK_VERSION,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
