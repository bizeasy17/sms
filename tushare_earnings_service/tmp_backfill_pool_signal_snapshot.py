import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEV_ROOT = BASE_DIR.parent
if str(DEV_ROOT) not in sys.path:
    sys.path.insert(0, str(DEV_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tushare_earnings_service.settings")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from earnings_forecast.models import EarningsSignalSnapshot, EarningsSignalSnapshotHistory  # noqa: E402

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

BATCH_KEY = "pool20_signal_backfill_20260503"
REPORT_TYPES = "Q1,H1,Q3,FY"


def main() -> None:
    print(
        json.dumps(
            {
                "step": "start",
                "codes": len(POOL_CODES),
                "batch_key": BATCH_KEY,
                "report_types": REPORT_TYPES,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )

    for idx, code in enumerate(POOL_CODES, start=1):
        call_command(
            "refresh_signal_snapshot",
            ts_code=code,
            full_refresh=False,
            store_mode="both",
            report_types=REPORT_TYPES,
            batch_key=BATCH_KEY,
            strict=False,
            verbosity=0,
        )
        print(f"[signal] progress {idx}/{len(POOL_CODES)} ts_code={code}", flush=True)

    latest_rows = EarningsSignalSnapshot.objects.filter(ts_code__in=POOL_CODES).count()
    hist_rows = EarningsSignalSnapshotHistory.objects.filter(ts_code__in=POOL_CODES, batch_key=BATCH_KEY).count()

    print(
        json.dumps(
            {
                "latest_rows": latest_rows,
                "history_rows_for_batch": hist_rows,
                "batch_key": BATCH_KEY,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
