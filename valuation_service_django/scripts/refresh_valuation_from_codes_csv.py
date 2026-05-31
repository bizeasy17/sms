from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "valuation_service.settings")

import django  # noqa: E402

django.setup()

from django.core.management.base import CommandError  # noqa: E402
from django.db.models import Max  # noqa: E402
from django.utils import timezone  # noqa: E402

from valuation_api.live_valuation import get_local_valuation_snapshot, test_valuation_local_light  # noqa: E402
from valuation_api.management.commands.prefillvaluationsnapshot import (  # noqa: E402
    _build_profit_trace_fields,
    _bulk_upsert_valuation_rows,
    _extract_method_rows,
    _load_business_match_contexts,
    _normalize_method_name,
)
from valuation_api.models import StockTradingHistory, ValuationSnapshot  # noqa: E402


def _read_codes(csv_path: Path) -> list[str]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        codes = []
        for row in reader:
            code = str((row or {}).get("ts_code") or "").strip().upper()
            if code:
                codes.append(code)
    deduped = sorted(set(codes))
    return deduped


def _resolve_trade_date(freq: str, trade_date: str | None) -> str:
    if trade_date:
        return trade_date
    latest = StockTradingHistory.objects.filter(freq=freq).aggregate(latest_date=Max("trade_date")).get("latest_date")
    if latest is None:
        raise CommandError("未找到交易数据，无法推断 trade-date")
    return latest.strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh valuation snapshot for codes in csv")
    parser.add_argument("--csv", required=True, help="CSV path containing ts_code column")
    parser.add_argument("--trade-date", default="", help="Trade date YYYY-MM-DD")
    parser.add_argument("--freq", default="D")
    parser.add_argument("--market", default="CN")
    parser.add_argument("--methods", default="sw_history,pe,pb,ps,peg,fcff_dcf,ddm")
    parser.add_argument("--strict-express-match", action="store_true", default=False)
    parser.add_argument("--express-max-age-days", type=int, default=180)
    parser.add_argument("--business-match-topn", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=20)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    freq = str(args.freq or "D").strip().upper() or "D"
    market = str(args.market or "CN").strip().upper() or "CN"
    trade_date = _resolve_trade_date(freq=freq, trade_date=(args.trade_date or "").strip() or None)
    strict_express_match = bool(args.strict_express_match)
    express_max_age_days = int(args.express_max_age_days or 180)
    business_match_topn = max(0, int(args.business_match_topn or 0))
    progress_every = int(args.progress_every or 0)

    methods = [_normalize_method_name(item) for item in str(args.methods or "").split(",") if item.strip()]
    methods = [m for m in methods if m]
    if not methods:
        raise ValueError("No methods provided")

    codes = _read_codes(csv_path)
    if not codes:
        raise ValueError("No ts_code found in csv")

    counters = {
        "selected": len(codes),
        "processed": 0,
        "evaluated": 0,
        "written": 0,
        "skipped_no_price": 0,
        "errors": 0,
    }
    failed_codes: list[str] = []

    t0 = time.perf_counter()
    print(f"start valuation refresh: selected={len(codes)} trade_date={trade_date} freq={freq} methods={','.join(methods)}")

    for idx, ts_code in enumerate(codes, start=1):
        counters["processed"] += 1
        try:
            contexts = _load_business_match_contexts(ts_code=ts_code, market=market, top_n=business_match_topn)
            if not contexts:
                contexts = [
                    {
                        "compare_group": None,
                        "industry_level": None,
                        "industry_code": None,
                        "industry_name": None,
                        "match_score": None,
                        "valuation_variant": "default",
                        "params": {},
                    }
                ]

            outputs = {method: [] for method in methods}
            trace_fields = {}
            stock_snapshot = get_local_valuation_snapshot(
                ts_code=ts_code,
                trade_date=trade_date,
                freq=freq,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
            )
            for context in contexts:
                valuation_result = test_valuation_local_light(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    freq=freq,
                    strict_express_match=strict_express_match,
                    express_max_age_days=express_max_age_days,
                    snapshot=stock_snapshot,
                    persist_context=context,
                    persist_result=False,
                    **(context.get("params") or {}),
                )
                if context is contexts[0]:
                    snapshot_data = valuation_result.get("snapshot") or {}
                    trace_fields = _build_profit_trace_fields(snapshot_data)
                context_outputs = _extract_method_rows(valuation_result, methods, context)
                for method in methods:
                    outputs[method].extend(context_outputs.get(method) or [])

            counters["evaluated"] += 1
            timestamp = timezone.now()
            snapshot_rows = []
            latest_rows = []
            write_count = 0

            for method in methods:
                seen_variants = set()
                for row in outputs.get(method) or []:
                    variant = str(row.get("valuation_variant") or "default")
                    if variant in seen_variants:
                        continue
                    seen_variants.add(variant)
                    snapshot_defaults = {
                        "valuation_price": row.get("implied_price"),
                        "valuation_market_cap": row.get("equity_value"),
                        "source": "prefill_command",
                        "industry_level": row.get("industry_level"),
                        "industry_code": row.get("industry_code"),
                        "industry_name": row.get("industry_name"),
                        "compare_group": row.get("compare_group"),
                        "match_score": row.get("match_score"),
                        **(trace_fields or {}),
                    }
                    snapshot_rows.append(
                        ValuationSnapshot(
                            ts_code=ts_code,
                            trade_date=trade_date,
                            market=market,
                            valuation_method=method,
                            valuation_variant=variant,
                            created_at=timestamp,
                            updated_at=timestamp,
                            **snapshot_defaults,
                        )
                    )
                    from valuation_api.models import ValuationSnapshotLatest

                    latest_rows.append(
                        ValuationSnapshotLatest(
                            ts_code=ts_code,
                            market=market,
                            valuation_method=method,
                            valuation_variant=variant,
                            latest_trade_date=trade_date,
                            updated_at=timestamp,
                            **snapshot_defaults,
                        )
                    )
                    write_count += 1

            if write_count == 0:
                counters["skipped_no_price"] += 1
            else:
                _bulk_upsert_valuation_rows(snapshot_rows, latest_rows)
                counters["written"] += write_count

        except Exception as exc:
            counters["errors"] += 1
            failed_codes.append(ts_code)
            print(f"[{idx}/{len(codes)}] {ts_code} failed: {exc}")

        if progress_every > 0 and idx % progress_every == 0:
            print(f"progress {idx}/{len(codes)} written={counters['written']} errors={counters['errors']}")

    elapsed = time.perf_counter() - t0
    print("valuation refresh done")
    for k, v in counters.items():
        print(f"{k}={v}")
    print(f"elapsed_sec={elapsed:.3f}")

    if failed_codes:
        fail_path = BASE_DIR / "outputs" / "local_valuation_checks" / "refresh_valuation_failed_codes.csv"
        fail_path.parent.mkdir(parents=True, exist_ok=True)
        with fail_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["ts_code"])
            for code in failed_codes:
                writer.writerow([code])
        print(f"failed_codes_file={fail_path}")


if __name__ == "__main__":
    main()
