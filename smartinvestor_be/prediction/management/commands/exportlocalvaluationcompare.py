import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.views import (
    _build_valuation_summary_payload,
    _classify_valuation,
    _enrich_rows_with_share_basis,
    _load_latest_total_share_shares,
    _normalize_report_dates,
    _normalize_valuation_method_name,
)
from datastore.models import StockTradingHistory
from prediction.management.commands.prefillvaluationsnapshot import (
    _build_context_variant,
    _extract_implied_prices,
    _load_business_match_contexts,
    _normalize_valuation_variant,
)
from valuation.models import StockValuationSnapshot
from valuation.services.valuation_engine import get_stock_valuation_snapshot, test_valuation_light


METHOD_ORDER = {
    name: idx
    for idx, name in enumerate(
        [
            "recommended",
            "scarcity_overlay",
            "sw_history",
            "pe",
            "pb",
            "ps",
            "peg",
            "fcff_dcf",
            "ddm",
            "market_cap",
        ]
    )
}

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _variant_sort_key(meta):
    variant = str(meta.get("valuation_variant") or "")
    compare_group = str(meta.get("compare_group") or "")
    score = meta.get("max_match_score")
    if score is None:
        score = -1e9
    if compare_group == "sw_l3_baseline":
        group_rank = 0
    elif compare_group == "business_match":
        group_rank = 1
    elif variant == "default":
        group_rank = 2
    else:
        group_rank = 3
    return (group_rank, -float(score), variant)


def _variant_label(meta):
    variant = meta.get("valuation_variant")
    if variant == "default":
        return "默认估值"
    if meta.get("industry_name"):
        return str(meta.get("industry_name"))
    if meta.get("industry_code"):
        return str(meta.get("industry_code"))
    return str(variant)


def _nearest_price_distance(row, target_price):
    return abs(_to_float(row.get("valuation_price")) - target_price)


def _build_market_context(ts_code, freq, max_trade_date=None):
    trading_qs = StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
    if max_trade_date is not None:
        trading_qs = trading_qs.filter(trade_date__lte=max_trade_date)

    trading_row = (
        trading_qs
        .order_by("-trade_date")
        .values("trade_date", "close_qfq", "close")
        .first()
    )
    current_price = None
    current_trade_date = None
    if trading_row:
        current_trade_date = trading_row.get("trade_date")
        current_price = trading_row.get("close_qfq") or trading_row.get("close")

    current_total_share_shares, current_total_share_trade_date = _load_latest_total_share_shares(
        ts_code,
        freq=freq,
        max_trade_date=max_trade_date or current_trade_date,
    )
    if current_trade_date is None and current_total_share_trade_date is not None:
        current_trade_date = current_total_share_trade_date

    return current_price, current_trade_date, current_total_share_shares


def _build_local_variant_payload(
    ts_code,
    trade_date,
    report_end_date=None,
    business_topn=3,
    band_pct=0.1,
    freq="D",
    asof_trade_date=None,
):
    stock_snapshot = get_stock_valuation_snapshot(
        ts_code=ts_code,
        trade_date=trade_date,
        strict_express_match=True,
        express_max_age_days=180,
        forced_report_end_date=report_end_date,
    )
    contexts = [
        {
            "valuation_variant": "default",
            "compare_group": None,
            "industry_level": None,
            "industry_code": None,
            "industry_name": None,
            "match_score": None,
            "params": {},
        }
    ]
    contexts.extend(_load_business_match_contexts(ts_code, market="CN", top_n=max(0, int(business_topn or 0))))
    methods = ["market_cap", "sw_history", "pe", "pb", "ps", "peg", "fcff_dcf", "ddm"]
    outputs = {method: [] for method in methods}

    for context in contexts:
        valuation_result = test_valuation_light(
            ts_code=ts_code,
            trade_date=trade_date,
            strict_express_match=True,
            express_max_age_days=180,
            snapshot=stock_snapshot,
            **dict(context.get("params") or {}),
        )
        valuation_df = valuation_result.get("valuations")
        context_outputs = _extract_implied_prices(valuation_df, methods)
        for method in methods:
            for row in context_outputs.get(method) or []:
                row["valuation_variant"] = context.get("valuation_variant") or _build_context_variant(
                    compare_group=context.get("compare_group"),
                    industry_level=context.get("industry_level"),
                    industry_code=context.get("industry_code"),
                    industry_name=context.get("industry_name"),
                )
                row["industry_level"] = context.get("industry_level")
                row["industry_code"] = context.get("industry_code")
                row["industry_name"] = context.get("industry_name")
                row["compare_group"] = context.get("compare_group")
                row["match_score"] = context.get("match_score")
                outputs[method].append(row)

    for method in methods:
        deduped = []
        seen_variants = set()
        for row in outputs.get(method) or []:
            variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
            if variant in seen_variants:
                continue
            seen_variants.add(variant)
            deduped.append(row)
        outputs[method] = deduped

    current_price, current_trade_date, current_total_share_shares = _build_market_context(
        ts_code,
        freq,
        max_trade_date=asof_trade_date or trade_date,
    )
    data_by_variant = {}
    variant_meta = {}

    for method in methods:
        for row in outputs.get(method) or []:
            variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
            implied_price = _to_float(row.get("implied_price"))
            status, gap_pct = _classify_valuation(current_price, implied_price, band_pct)
            payload = {
                "valuation_method": _normalize_valuation_method_name(row.get("method") or method),
                "valuation_variant": variant,
                "valuation_price": round(implied_price, 4) if implied_price is not None else None,
                "valuation_market_cap": _to_float(row.get("equity_value")),
                "valuation_status": status,
                "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
                "source": "local_test_valuation_light",
                "latest_trade_date": trade_date,
                "profit_data_source": stock_snapshot.get("profit_data_source"),
                "profit_report_end_date": report_end_date,
                "profit_report_ann_date": stock_snapshot.get("ann_date"),
                "profit_report_type": stock_snapshot.get("profit_report_type"),
                "industry_level": row.get("industry_level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
                "compare_group": row.get("compare_group"),
                "match_score": _to_float(row.get("match_score")),
            }
            data_by_variant.setdefault(variant, []).append(payload)

            meta = variant_meta.setdefault(
                variant,
                {
                    "valuation_variant": variant,
                    "industry_level": row.get("industry_level"),
                    "industry_code": row.get("industry_code"),
                    "industry_name": row.get("industry_name"),
                    "compare_group": row.get("compare_group"),
                    "max_match_score": None,
                },
            )
            score = _to_float(row.get("match_score"))
            if score is not None and (meta.get("max_match_score") is None or score > meta.get("max_match_score")):
                meta["max_match_score"] = score

    for variant, rows in data_by_variant.items():
        rows.sort(key=lambda item: METHOD_ORDER.get(item.get("valuation_method"), 999))
        data_by_variant[variant] = _enrich_rows_with_share_basis(
            ts_code=ts_code,
            current_trade_date=current_trade_date,
            current_total_share_shares=current_total_share_shares,
            current_price=current_price,
            band_pct=band_pct,
            rows=rows,
        )

    valuation_variants = []
    for meta in sorted(variant_meta.values(), key=_variant_sort_key):
        variant = meta.get("valuation_variant")
        valuation_variants.append(
            {
                "valuation_variant": variant,
                "label": _variant_label(meta),
                "industry_level": meta.get("industry_level"),
                "industry_code": meta.get("industry_code"),
                "industry_name": meta.get("industry_name"),
                "compare_group": meta.get("compare_group"),
                "match_score": round(float(meta.get("max_match_score")), 4)
                if meta.get("max_match_score") is not None
                else None,
                "method_count": len(data_by_variant.get(variant) or []),
            }
        )

    summary_by_variant = {}
    summary_by_variant_normalized = {}
    for variant, rows in data_by_variant.items():
        summary_by_variant[variant] = _build_valuation_summary_payload(current_price, rows, band_pct)
        summary_by_variant_normalized[variant] = _build_valuation_summary_payload(
            current_price,
            rows,
            band_pct,
            price_key="valuation_price_normalized_to_latest_share",
        )

    return {
        "snapshot": stock_snapshot,
        "contexts": contexts,
        "current_price": current_price,
        "current_trade_date": current_trade_date,
        "data_by_variant": data_by_variant,
        "valuation_variants": valuation_variants,
        "summary_by_variant": summary_by_variant,
        "summary_by_variant_normalized_to_latest_share": summary_by_variant_normalized,
    }


def _build_existing_snapshot_payload(ts_code, trade_date, report_end_date=None, band_pct=0.1, freq="D"):
    qs = StockValuationSnapshot.objects.filter(ts_code=ts_code, trade_date=trade_date, market="CN")
    if report_end_date:
        qs = qs.filter(profit_report_end_date=report_end_date)

    snapshot_rows = list(
        qs.order_by("valuation_variant", "valuation_method", "-updated_at").values(
            "trade_date",
            "valuation_method",
            "valuation_variant",
            "valuation_price",
            "valuation_market_cap",
            "profit_report_end_date",
            "profit_report_ann_date",
            "profit_report_type",
            "profit_data_source",
            "express_ann_date",
            "compare_group",
            "industry_level",
            "industry_code",
            "industry_name",
            "match_score",
            "source",
            "updated_at",
        )
    )

    current_price, current_trade_date, current_total_share_shares = _build_market_context(ts_code, freq)
    data_by_variant = {}
    variant_meta = {}

    for row in snapshot_rows:
        method = _normalize_valuation_method_name(row.get("valuation_method"))
        if not method:
            continue
        variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
        normalized_report_end_date, normalized_report_ann_date = _normalize_report_dates(
            row.get("profit_report_end_date"),
            row.get("profit_report_ann_date"),
        )
        valuation_price = _to_float(row.get("valuation_price"))
        status, gap_pct = _classify_valuation(current_price, valuation_price, band_pct)
        payload = {
            "valuation_method": method,
            "valuation_variant": variant,
            "valuation_price": round(valuation_price, 4) if valuation_price is not None else None,
            "valuation_market_cap": _to_float(row.get("valuation_market_cap")),
            "valuation_status": status,
            "valuation_gap_pct": round(gap_pct * 100, 2) if gap_pct is not None else None,
            "source": row.get("source"),
            "latest_trade_date": row.get("trade_date"),
            "profit_data_source": row.get("profit_data_source"),
            "profit_report_end_date": normalized_report_end_date,
            "profit_report_ann_date": normalized_report_ann_date,
            "profit_report_type": row.get("profit_report_type"),
            "industry_level": row.get("industry_level"),
            "industry_code": row.get("industry_code"),
            "industry_name": row.get("industry_name"),
            "compare_group": row.get("compare_group"),
            "match_score": _to_float(row.get("match_score")),
            "updated_at": row.get("updated_at"),
        }
        data_by_variant.setdefault(variant, []).append(payload)

        meta = variant_meta.setdefault(
            variant,
            {
                "valuation_variant": variant,
                "industry_level": row.get("industry_level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
                "compare_group": row.get("compare_group"),
                "max_match_score": None,
            },
        )
        score = _to_float(row.get("match_score"))
        if score is not None and (meta.get("max_match_score") is None or score > meta.get("max_match_score")):
            meta["max_match_score"] = score

    for variant, rows in data_by_variant.items():
        rows.sort(key=lambda item: METHOD_ORDER.get(item.get("valuation_method"), 999))
        data_by_variant[variant] = _enrich_rows_with_share_basis(
            ts_code=ts_code,
            current_trade_date=current_trade_date,
            current_total_share_shares=current_total_share_shares,
            current_price=current_price,
            band_pct=band_pct,
            rows=rows,
        )

    valuation_variants = []
    for meta in sorted(variant_meta.values(), key=_variant_sort_key):
        variant = meta.get("valuation_variant")
        valuation_variants.append(
            {
                "valuation_variant": variant,
                "label": _variant_label(meta),
                "industry_level": meta.get("industry_level"),
                "industry_code": meta.get("industry_code"),
                "industry_name": meta.get("industry_name"),
                "compare_group": meta.get("compare_group"),
                "match_score": round(float(meta.get("max_match_score")), 4)
                if meta.get("max_match_score") is not None
                else None,
                "method_count": len(data_by_variant.get(variant) or []),
            }
        )

    summary_by_variant = {}
    summary_by_variant_normalized = {}
    for variant, rows in data_by_variant.items():
        summary_by_variant[variant] = _build_valuation_summary_payload(current_price, rows, band_pct)
        summary_by_variant_normalized[variant] = _build_valuation_summary_payload(
            current_price,
            rows,
            band_pct,
            price_key="valuation_price_normalized_to_latest_share",
        )

    return {
        "rows": snapshot_rows,
        "current_price": current_price,
        "current_trade_date": current_trade_date,
        "data_by_variant": data_by_variant,
        "valuation_variants": valuation_variants,
        "summary_by_variant": summary_by_variant,
        "summary_by_variant_normalized_to_latest_share": summary_by_variant_normalized,
    }


def _build_method_comparison(local_payload, existing_payload):
    comparison_rows = []
    existing_rows = list(existing_payload.get("rows") or [])

    for variant, local_rows in (local_payload.get("data_by_variant") or {}).items():
        for local_row in local_rows or []:
            method = local_row.get("valuation_method")
            local_price = _to_float(local_row.get("valuation_price"))

            existing_same_variant = None
            for row in existing_rows:
                if _normalize_valuation_method_name(row.get("valuation_method")) != method:
                    continue
                if _normalize_valuation_variant(row.get("valuation_variant"), fallback="default") == variant:
                    existing_same_variant = row
                    break

            existing_default = None
            for row in existing_rows:
                if _normalize_valuation_method_name(row.get("valuation_method")) != method:
                    continue
                row_variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
                if row_variant == "default":
                    existing_default = row
                    break

            nearest_row = None
            if local_price is not None:
                candidate_rows = [
                    row
                    for row in existing_rows
                    if _normalize_valuation_method_name(row.get("valuation_method")) == method
                    and _to_float(row.get("valuation_price")) is not None
                ]
                if candidate_rows:
                    target_price = local_price
                    nearest_row = min(candidate_rows, key=lambda row: _nearest_price_distance(row, target_price))

            same_variant_price = _to_float((existing_same_variant or {}).get("valuation_price"))
            default_price = _to_float((existing_default or {}).get("valuation_price"))
            nearest_price = _to_float((nearest_row or {}).get("valuation_price"))
            comparison_rows.append(
                {
                    "valuation_variant": variant,
                    "valuation_method": method,
                    "local_price": local_price,
                    "local_status": local_row.get("valuation_status"),
                    "same_variant_existing_price": same_variant_price,
                    "same_variant_existing_variant": (existing_same_variant or {}).get("valuation_variant"),
                    "default_existing_price": default_price,
                    "nearest_existing_price": nearest_price,
                    "nearest_existing_variant": (nearest_row or {}).get("valuation_variant"),
                    "diff_vs_same_variant": round(local_price - same_variant_price, 4)
                    if local_price is not None and same_variant_price is not None
                    else None,
                    "diff_vs_default": round(local_price - default_price, 4)
                    if local_price is not None and default_price is not None
                    else None,
                    "diff_vs_nearest": round(local_price - nearest_price, 4)
                    if local_price is not None and nearest_price is not None
                    else None,
                }
            )

    return comparison_rows


def _build_summary_comparison(local_payload, existing_payload):
    rows = []
    local_summaries = local_payload.get("summary_by_variant") or {}
    existing_summaries = existing_payload.get("summary_by_variant") or {}
    all_variants = sorted(set(local_summaries.keys()) | set(existing_summaries.keys()))

    for variant in all_variants:
        local_summary = local_summaries.get(variant) or {}
        existing_summary = existing_summaries.get(variant) or {}
        local_composite = _to_float(local_summary.get("composite_valuation_price"))
        existing_composite = _to_float(existing_summary.get("composite_valuation_price"))
        local_conservative = _to_float(local_summary.get("conservative_valuation_price"))
        existing_conservative = _to_float(existing_summary.get("conservative_valuation_price"))

        rows.append(
            {
                "valuation_variant": variant,
                "local_composite_valuation_price": local_composite,
                "existing_composite_valuation_price": existing_composite,
                "composite_diff": round(local_composite - existing_composite, 4)
                if local_composite is not None and existing_composite is not None
                else None,
                "local_conservative_valuation_price": local_conservative,
                "existing_conservative_valuation_price": existing_conservative,
                "conservative_diff": round(local_conservative - existing_conservative, 4)
                if local_conservative is not None and existing_conservative is not None
                else None,
            }
        )

    return rows


class Command(BaseCommand):
    help = "Export non-persistent local valuation comparison artifact with multi-variant outputs and frontend summary metrics."

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, required=True, help="TS code, for example 688599.SH")
        parser.add_argument("--trade-date", type=str, required=True, help="Trade date in YYYY-MM-DD")
        parser.add_argument("--report-end-date", type=str, default=None, help="Report end date in YYYY-MM-DD")
        parser.add_argument("--ann-date", type=str, default=None, help="Announcement date in YYYY-MM-DD, stored as metadata only")
        parser.add_argument("--business-topn", type=int, default=3, help="Top N business match variants to simulate")
        parser.add_argument("--freq", type=str, default="D", help="Trading frequency, default D")
        parser.add_argument("--valuation-band-pct", type=float, default=0.1, help="Band percent used for fair/under/over classification")
        parser.add_argument("--output", type=str, default=None, help="Optional output file path")

    def handle(self, *args, **options):
        ts_code = str(options.get("tscode") or "").strip().upper()
        trade_date = str(options.get("trade_date") or "").strip()
        report_end_date = str(options.get("report_end_date") or "").strip() or None
        ann_date = str(options.get("ann_date") or "").strip() or None
        business_topn = int(options.get("business_topn") or 0)
        freq = str(options.get("freq") or "D").strip().upper() or "D"
        band_pct = float(options.get("valuation_band_pct") or 0.1)

        if not ts_code:
            raise CommandError("--tscode is required")
        if not trade_date:
            raise CommandError("--trade-date is required")

        output_path = options.get("output")
        if output_path:
            output_file = Path(output_path)
        else:
            output_dir = PROJECT_ROOT / "output" / "local_valuation_checks"
            output_dir.mkdir(parents=True, exist_ok=True)
            suffix = trade_date.replace("-", "")
            output_file = output_dir / f"{ts_code.replace('.', '_')}_{suffix}_multi_variant_compare.json"

        local_payload = _build_local_variant_payload(
            ts_code=ts_code,
            trade_date=trade_date,
            report_end_date=report_end_date,
            business_topn=business_topn,
            band_pct=band_pct,
            freq=freq,
        )
        existing_payload = _build_existing_snapshot_payload(
            ts_code=ts_code,
            trade_date=trade_date,
            report_end_date=report_end_date,
            band_pct=band_pct,
            freq=freq,
        )

        payload = {
            "meta": {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "report_end_date": report_end_date,
                "announcement_date": ann_date,
                "business_topn": business_topn,
                "valuation_band_pct": band_pct,
                "freq": freq,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "generation_mode": "dev_local_file_only_no_persist_multi_variant",
                "note": "Local comparison artifact only. No valuation snapshot rows are written by this command.",
            },
            "local_multi_variant": local_payload,
            "existing_snapshot": existing_payload,
            "comparison": {
                "method_level": _build_method_comparison(local_payload, existing_payload),
                "summary_level": _build_summary_comparison(local_payload, existing_payload),
            },
        }

        output_file.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(str(output_file))