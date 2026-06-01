import argparse
import csv
import datetime
import json
import os
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tushare_earnings_service.settings")
django.setup()

from earnings_forecast.models import (  # noqa: E402
    FinancialFeaturePanel,
    LocalFundamentalHistory,
    LocalTradingHistory,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build required feature snapshots JSON for pred-missing rows."
    )
    parser.add_argument(
        "--pred-missing-csv",
        required=True,
        help="Pred missing report csv path.",
    )
    parser.add_argument(
        "--output-json",
        default="tmp_required_feature_snapshots.json",
        help="Output JSON file path.",
    )
    parser.add_argument(
        "--freq",
        default="D",
        help="Frequency for local market snapshots. Default D.",
    )
    return parser.parse_args()


def normalize_end_date_token(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = text[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def to_date(value):
    token = normalize_end_date_token(value)
    if not token:
        return None
    try:
        return datetime.date.fromisoformat(token)
    except Exception:
        return None


def end_date_candidates(value):
    normalized = normalize_end_date_token(value)
    if not normalized:
        return []
    compact = normalized.replace("-", "")
    return [normalized, compact]


def to_float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def pick_feature_panel(ts_code, report_type, financial_end_date):
    candidates = end_date_candidates(financial_end_date)
    qs = FinancialFeaturePanel.objects.filter(
        ts_code=str(ts_code or "").strip().upper(),
        report_type=str(report_type or "").strip().upper(),
    )
    if candidates:
        qs = qs.filter(end_date__in=candidates)

    payload = (
        qs.order_by("-ann_date", "-end_date")
        .values()
        .first()
    )
    return payload


def pick_market_snapshot(ts_code, anchor_trade, freq="D"):
    anchor_dt = to_date(anchor_trade)
    if anchor_dt is None:
        return None

    trade_row = (
        LocalTradingHistory.objects.filter(
            ts_code=str(ts_code or "").strip().upper(),
            freq=str(freq or "D").strip().upper(),
            trade_date__gte=anchor_dt,
        )
        .order_by("trade_date")
        .values("trade_date", "close", "pct_change", "vol")
        .first()
    )
    if trade_row is None:
        trade_row = (
            LocalTradingHistory.objects.filter(
                ts_code=str(ts_code or "").strip().upper(),
                freq=str(freq or "D").strip().upper(),
                trade_date__lte=anchor_dt,
            )
            .order_by("-trade_date")
            .values("trade_date", "close", "pct_change", "vol")
            .first()
        )
    if trade_row is None:
        return None

    trade_date = trade_row.get("trade_date")
    funda_row = (
        LocalFundamentalHistory.objects.filter(
            ts_code=str(ts_code or "").strip().upper(),
            freq=str(freq or "D").strip().upper(),
            trade_date=trade_date,
        )
        .values("pe", "pb", "ps", "total_mv", "circ_mv", "turnover_rate")
        .first()
    )
    return {
        "trade_date": trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date or ""),
        "close": to_float_or_none(trade_row.get("close")),
        "pct_change": to_float_or_none(trade_row.get("pct_change")),
        "vol": to_float_or_none(trade_row.get("vol")),
        "pe": to_float_or_none((funda_row or {}).get("pe")),
        "pb": to_float_or_none((funda_row or {}).get("pb")),
        "ps": to_float_or_none((funda_row or {}).get("ps")),
        "total_mv": to_float_or_none((funda_row or {}).get("total_mv")),
        "circ_mv": to_float_or_none((funda_row or {}).get("circ_mv")),
        "turnover_rate": to_float_or_none((funda_row or {}).get("turnover_rate")),
    }


def main():
    args = parse_args()
    pred_missing_csv = Path(args.pred_missing_csv)
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    seen = set()
    with pred_missing_csv.open("r", encoding="utf-8") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            report_type = str(row.get("report_type") or "").strip().upper()
            financial_end_date = normalize_end_date_token(row.get("report_end"))
            key = (ts_code, report_type, financial_end_date)
            if not ts_code or not report_type or not financial_end_date or key in seen:
                continue
            seen.add(key)

            panel_row = pick_feature_panel(ts_code, report_type, financial_end_date)
            market_row = pick_market_snapshot(
                ts_code=ts_code,
                anchor_trade=row.get("anchor_trade"),
                freq=args.freq,
            )

            if panel_row is not None:
                # Keep JSON compact and predictable by dropping internal ids/timestamps.
                panel_row = {
                    k: panel_row[k]
                    for k in panel_row.keys()
                    if k not in {"id", "created_at", "updated_at", "source_updated_at"}
                }

            rows.append(
                {
                    "ts_code": ts_code,
                    "stock_name": row.get("stock_name"),
                    "report_type": report_type,
                    "financial_end_date": financial_end_date,
                    "anchor_trade": row.get("anchor_trade"),
                    "note": row.get("note"),
                    "feature_snapshot": panel_row,
                    "market_snapshot": market_row,
                    "ready_for_predict": bool(panel_row),
                }
            )

    ready_count = sum(1 for item in rows if item.get("ready_for_predict"))
    rows = sorted(rows, key=lambda item: (item.get("ts_code") or "", item.get("financial_end_date") or "", item.get("report_type") or ""))
    output_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"pred_missing_csv={pred_missing_csv}")
    print(f"output_json={output_json}")
    print(f"rows={len(rows)}")
    print(f"ready_for_predict_rows={ready_count}")


if __name__ == "__main__":
    main()