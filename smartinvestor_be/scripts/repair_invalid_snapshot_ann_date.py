#!/usr/bin/env python
"""Repair invalid valuation snapshot announcement dates.

Invalid means either:
- profit_report_ann_date < profit_report_end_date
- profit_report_ann_date > trade_date

Usage examples:
  python scripts/repair_invalid_snapshot_ann_date.py --dry-run
  python scripts/repair_invalid_snapshot_ann_date.py --limit 2000
  python scripts/repair_invalid_snapshot_ann_date.py --ts-codes 600050.SH,600062.SH --refresh-risk
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from typing import Iterable, List

from django.core.management import call_command
from django.db.models import F, Q


def _bootstrap_django() -> None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")

    import django

    django.setup()


def _parse_csv_text(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_bad_pairs_queryset(ts_codes: Iterable[str], trade_date_text: str | None):
    from prediction.models import StockValuationSnapshot

    qs = StockValuationSnapshot.objects.filter(
        Q(profit_report_ann_date__lt=F("profit_report_end_date"))
        | Q(profit_report_ann_date__gt=F("trade_date"))
    )
    ts_codes = list(ts_codes)
    if ts_codes:
        qs = qs.filter(ts_code__in=ts_codes)
    if trade_date_text:
        qs = qs.filter(trade_date=trade_date_text)

    return qs.values("ts_code", "trade_date").distinct().order_by("trade_date", "ts_code")


def _is_valid_ann_date(ann_date: date | None, report_end_date: date | None, trade_date: date | None) -> bool:
    if ann_date is None:
        return False
    if report_end_date is not None and ann_date < report_end_date:
        return False
    if trade_date is not None and ann_date > trade_date:
        return False
    return True


def main() -> int:
    _bootstrap_django()

    parser = argparse.ArgumentParser(description="Repair invalid snapshot announcement dates in bulk")
    parser.add_argument("--dry-run", action="store_true", help="Only scan and print what would be updated")
    parser.add_argument("--limit", type=int, default=0, help="Max number of (ts_code, trade_date) pairs to process")
    parser.add_argument("--offset", type=int, default=0, help="Offset for pair scanning")
    parser.add_argument("--ts-codes", type=str, default="", help="Comma-separated ts_code list")
    parser.add_argument("--trade-date", type=str, default="", help="Filter by one trade date, e.g. 2026-03-27")
    parser.add_argument("--refresh-risk", action="store_true", help="Refresh valuation risk after snapshot repair")
    parser.add_argument("--progress-every", type=int, default=200, help="Progress print interval")
    args = parser.parse_args()

    from prediction.models import StockValuationSnapshot, StockValuationSnapshotLatest
    from prediction.management.commands.prefillvaluationsnapshot import _build_profit_trace_fields
    from valuation.services.valuation_engine import get_stock_valuation_snapshot

    ts_codes = _parse_csv_text(args.ts_codes)
    bad_pairs_qs = _build_bad_pairs_queryset(ts_codes=ts_codes, trade_date_text=args.trade_date or None)

    total_pairs = bad_pairs_qs.count()
    if total_pairs == 0:
        print("No invalid pairs found.")
        return 0

    start = max(0, int(args.offset or 0))
    if int(args.limit or 0) > 0:
        stop = start + int(args.limit)
        pairs = list(bad_pairs_qs[start:stop])
    else:
        pairs = list(bad_pairs_qs[start:])

    print(f"Found invalid pairs total={total_pairs}, selected={len(pairs)}, offset={start}")

    updated_snapshot_rows = 0
    updated_latest_rows = 0
    repaired_pairs = 0
    skipped_pairs = 0
    risk_refreshed = 0

    for idx, pair in enumerate(pairs, start=1):
        ts_code = pair["ts_code"]
        trade_date = pair["trade_date"]
        trade_date_text = trade_date.strftime("%Y-%m-%d")

        snapshot = get_stock_valuation_snapshot(ts_code=ts_code, trade_date=trade_date_text)
        trace = _build_profit_trace_fields(snapshot)

        ann_date = trace.get("profit_report_ann_date")
        trade_date_obj = snapshot.get("trade_date")
        normalized_trade_date = trade_date_obj if isinstance(trade_date_obj, date) else trade_date

        invalid_rows_qs = StockValuationSnapshot.objects.filter(
            ts_code=ts_code,
            trade_date=trade_date,
        ).filter(
            Q(profit_report_ann_date__lt=F("profit_report_end_date"))
            | Q(profit_report_ann_date__gt=F("trade_date"))
        )

        invalid_rows = list(
            invalid_rows_qs.values(
                "id",
                "profit_report_end_date",
            )
        )

        latest_rows = list(
            StockValuationSnapshotLatest.objects.filter(
                ts_code=ts_code,
                latest_trade_date=trade_date,
            ).values(
                "id",
                "profit_report_end_date",
            )
        )

        if args.dry_run:
            print(
                f"[dry-run] {ts_code} {trade_date_text} invalid_snapshot_rows={len(invalid_rows)} "
                f"latest_rows={len(latest_rows)} ann_candidate={ann_date}"
            )
            repaired_pairs += 1
        else:
            n1 = 0
            for row in invalid_rows:
                row_report_end = row.get("profit_report_end_date")
                row_ann = ann_date if _is_valid_ann_date(ann_date, row_report_end, normalized_trade_date) else None
                n1 += StockValuationSnapshot.objects.filter(id=row["id"]).update(
                    profit_data_source=trace.get("profit_data_source"),
                    profit_report_ann_date=row_ann,
                    express_end_date=trace.get("express_end_date"),
                    express_ann_date=trace.get("express_ann_date"),
                    express_apply_reason=trace.get("express_apply_reason"),
                    express_block_reason=trace.get("express_block_reason"),
                    strict_express_match=trace.get("strict_express_match"),
                    express_max_age_days=trace.get("express_max_age_days"),
                )

            n2 = 0
            for row in latest_rows:
                row_report_end = row.get("profit_report_end_date")
                row_ann = ann_date if _is_valid_ann_date(ann_date, row_report_end, normalized_trade_date) else None
                n2 += StockValuationSnapshotLatest.objects.filter(id=row["id"]).update(
                    profit_data_source=trace.get("profit_data_source"),
                    profit_report_ann_date=row_ann,
                    express_end_date=trace.get("express_end_date"),
                    express_ann_date=trace.get("express_ann_date"),
                    express_apply_reason=trace.get("express_apply_reason"),
                    express_block_reason=trace.get("express_block_reason"),
                    strict_express_match=trace.get("strict_express_match"),
                    express_max_age_days=trace.get("express_max_age_days"),
                )

            if n1 == 0 and n2 == 0:
                skipped_pairs += 1
            else:
                repaired_pairs += 1
            updated_snapshot_rows += n1
            updated_latest_rows += n2

            if args.refresh_risk:
                call_command(
                    "prefillvaluationrisk",
                    ts_code=ts_code,
                    trade_date=trade_date_text,
                    verbosity=0,
                )
                risk_refreshed += 1

        if args.progress_every > 0 and idx % args.progress_every == 0:
            print(
                f"progress {idx}/{len(pairs)} repaired_pairs={repaired_pairs} "
                f"snapshot_rows={updated_snapshot_rows} latest_rows={updated_latest_rows}"
            )

    print("Done.")
    print(f"repaired_pairs={repaired_pairs}")
    print(f"skipped_pairs={skipped_pairs}")
    print(f"updated_snapshot_rows={updated_snapshot_rows}")
    print(f"updated_latest_rows={updated_latest_rows}")
    print(f"risk_refreshed={risk_refreshed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
