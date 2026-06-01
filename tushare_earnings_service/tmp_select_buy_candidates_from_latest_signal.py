import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from django.db.models import Max

BASE_DIR = Path(__file__).resolve().parent
DEV_ROOT = BASE_DIR.parent
if str(DEV_ROOT) not in sys.path:
    sys.path.insert(0, str(DEV_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tushare_earnings_service.settings")

import django  # noqa: E402

django.setup()

from earnings_forecast.models import EarningsSignalSnapshotHistory  # noqa: E402

RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
BUY_ACTIONS = {"BUY"}


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, date):
        return v
    text = str(v).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    return None


def _load_codes(path):
    out = []
    seen = set()
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            code = str(raw or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
    return out


def _risk_ok(risk_level, max_risk):
    a = RISK_ORDER.get(str(risk_level or "").upper(), 99)
    b = RISK_ORDER.get(str(max_risk or "").upper(), 99)
    return a <= b


def _pick_latest_report_row(rows):
    best = None
    best_key = None

    for row in rows:
        raw = row.raw_result if isinstance(row.raw_result, dict) else {}
        ann_date = _to_date(raw.get("financial_ann_date") or raw.get("ann_date") or row.asof_date)
        score = row.signal_score if row.signal_score is not None else -1
        report_type = str(row.report_type or "").upper()
        report_rank = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4, "FUSION": 5}.get(report_type, 0)
        key = (ann_date or date.min, report_rank, score)
        if best_key is None or key > best_key:
            best = row
            best_key = key

    return best


def main():
    parser = argparse.ArgumentParser(description="Select BUY candidates from latest asof + latest financial-ann signal")
    parser.add_argument("--batch-key", type=str, default="", help="Optional batch key filter")
    parser.add_argument("--tscodes-file", type=str, default="", help="Optional ts_code whitelist file")
    parser.add_argument("--min-score", type=float, default=70.0, help="Minimum signal_score")
    parser.add_argument("--max-risk", type=str, default="MEDIUM", choices=["LOW", "MEDIUM", "HIGH"], help="Max accepted risk level")
    parser.add_argument("--output-json", type=str, default="", help="Optional output JSON path")
    args = parser.parse_args()

    qs = EarningsSignalSnapshotHistory.objects.all()
    if args.batch_key:
        qs = qs.filter(batch_key=args.batch_key)

    whitelist = None
    if args.tscodes_file:
        whitelist = set(_load_codes(args.tscodes_file))
        qs = qs.filter(ts_code__in=whitelist)

    latest_rows = qs.values("ts_code").annotate(latest_asof=Max("asof_date"))
    latest_map = {item["ts_code"]: item["latest_asof"] for item in latest_rows}

    picked = []
    for ts_code, latest_asof in latest_map.items():
        rows = list(
            qs.filter(ts_code=ts_code, asof_date=latest_asof)
            .only(
                "ts_code",
                "report_type",
                "asof_date",
                "action",
                "risk_level",
                "signal_score",
                "target_price",
                "target_return_pct",
                "raw_result",
                "batch_key",
            )
            .order_by("report_type")
        )
        if not rows:
            continue
        chosen = _pick_latest_report_row(rows)
        if chosen is None:
            continue

        action = str(chosen.action or "").upper()
        risk = str(chosen.risk_level or "").upper()
        score = float(chosen.signal_score) if chosen.signal_score is not None else None

        is_buy = (
            action in BUY_ACTIONS
            and score is not None
            and score >= float(args.min_score)
            and _risk_ok(risk, args.max_risk)
        )

        raw = chosen.raw_result if isinstance(chosen.raw_result, dict) else {}
        picked.append(
            {
                "ts_code": chosen.ts_code,
                "asof_date": chosen.asof_date.isoformat() if chosen.asof_date else None,
                "picked_report_type": chosen.report_type,
                "financial_ann_date": str(raw.get("financial_ann_date") or ""),
                "action": action,
                "risk_level": risk,
                "signal_score": score,
                "target_price": float(chosen.target_price) if chosen.target_price is not None else None,
                "target_return_pct": float(chosen.target_return_pct) if chosen.target_return_pct is not None else None,
                "is_buy_candidate": is_buy,
            }
        )

    picked.sort(key=lambda x: (x.get("is_buy_candidate") is True, x.get("signal_score") or -1), reverse=True)
    buy_list = [x for x in picked if x["is_buy_candidate"]]

    summary = {
        "batch_key": args.batch_key,
        "pool_size": len(latest_map),
        "evaluated": len(picked),
        "buy_candidates": len(buy_list),
        "min_score": float(args.min_score),
        "max_risk": args.max_risk,
        "candidates": buy_list,
    }

    print(json.dumps(summary, ensure_ascii=True, indent=2))

    if args.output_json:
        out = Path(args.output_json)
        if not out.is_absolute():
            out = BASE_DIR / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
        print(f"saved: {out}")


if __name__ == "__main__":
    main()
