import math
import hashlib
import json
from datetime import datetime
from decimal import Decimal

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max
from django.db import transaction

from datastore.models import Corporation, StockFundamentalHistory, StockTradingHistory
from valuation.models import AnnualOutlookSnapshot


def _parse_date_text(value):
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _normalize_scope(scope):
    return str(scope or "ALL").strip().upper()


def _split_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _resolve_scope_filter(qs, scope):
    normalized_scope = _normalize_scope(scope)
    if normalized_scope == "ALL":
        return qs

    prefixes = _split_csv(normalized_scope)
    if not prefixes:
        return qs

    matched_codes = []
    for code in qs.values_list("ts_code", flat=True).distinct():
        if any(str(code).startswith(prefix) for prefix in prefixes):
            matched_codes.append(code)
    return qs.filter(ts_code__in=matched_codes)


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _safe_positive(value):
    numeric = _safe_float(value)
    if numeric is None or numeric <= 0:
        return None
    return numeric


def _resolve_trade_date(trade_date_text, freq):
    if trade_date_text:
        return _parse_date_text(trade_date_text)
    latest = (
        StockTradingHistory.objects.filter(freq=freq)
        .aggregate(latest_date=Max("trade_date"))
        .get("latest_date")
    )
    if latest is None:
        raise CommandError("No trading data found for selected freq.")
    return latest


def _median_or_none(values):
    valid = [v for v in values if v is not None and math.isfinite(v) and v > 0]
    if not valid:
        return None
    return float(pd.Series(valid, dtype="float64").median())


def _calc_price_from_equity(equity_value, total_share):
    if equity_value is None or total_share in (None, 0):
        return None
    if total_share <= 0:
        return None
    return equity_value / total_share


def _to_decimal_or_none(value, digits):
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return Decimal(str(round(numeric, digits)))


def _build_assumptions_signature(payload):
    body = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _build_scenario_result(
    scenario,
    current_price,
    total_share,
    base_netprofit,
    base_revenue,
    base_equity,
    pe_base,
    ps_base,
    pb_base,
    profit_growth_pct,
    revenue_growth_pct,
    multiple_shift_pct,
):
    profit_factor = 1.0 + profit_growth_pct / 100.0
    revenue_factor = 1.0 + revenue_growth_pct / 100.0

    netprofit = base_netprofit * profit_factor if base_netprofit is not None else None
    revenue = base_revenue * revenue_factor if base_revenue is not None else None

    equity_growth_factor = 1.0 + max(revenue_growth_pct, profit_growth_pct) / 100.0 * 0.5
    equity_book = base_equity * equity_growth_factor if base_equity is not None else None

    pe_target = pe_base * (1.0 + multiple_shift_pct / 100.0) if pe_base is not None else None
    ps_target = ps_base * (1.0 + multiple_shift_pct / 100.0) if ps_base is not None else None
    pb_target = pb_base * (1.0 + multiple_shift_pct / 100.0) if pb_base is not None else None

    pe_equity = netprofit * pe_target if netprofit is not None and pe_target is not None else None
    ps_equity = revenue * ps_target if revenue is not None and ps_target is not None else None
    pb_equity = equity_book * pb_target if equity_book is not None and pb_target is not None else None

    pe_price = _calc_price_from_equity(pe_equity, total_share)
    ps_price = _calc_price_from_equity(ps_equity, total_share)
    pb_price = _calc_price_from_equity(pb_equity, total_share)

    composite_price = _median_or_none([pe_price, ps_price, pb_price])
    upside_pct = None
    if composite_price is not None and current_price not in (None, 0):
        upside_pct = (composite_price - current_price) / current_price * 100.0

    return {
        "scenario": scenario,
        "forecast_netprofit": netprofit,
        "forecast_revenue": revenue,
        "forecast_equity_book": equity_book,
        "target_pe": pe_target,
        "target_ps": ps_target,
        "target_pb": pb_target,
        "implied_price_pe": pe_price,
        "implied_price_ps": ps_price,
        "implied_price_pb": pb_price,
        "composite_price": composite_price,
        "upside_pct": upside_pct,
    }


class Command(BaseCommand):
    help = "Generate annual outlook (base/bull/bear) using local fundamentals and valuation multiples."

    def add_arguments(self, parser):
        parser.add_argument("--trade-date", type=str, help="Trade date YYYY-MM-DD. Defaults to latest D date.")
        parser.add_argument("--scope", type=str, default="688", help="Universe scope: ALL or code prefixes like 60,0,3,688")
        parser.add_argument("--freq", type=str, default="D", help="Trading frequency, default D")
        parser.add_argument("--code-offset", type=int, default=0, help="Code sampling offset")
        parser.add_argument("--code-limit", type=int, help="Code sampling limit")

        parser.add_argument("--base-profit-growth-pct", type=float, default=12.0, help="Base scenario FY netprofit growth pct")
        parser.add_argument("--bull-profit-growth-pct", type=float, help="Bull scenario FY netprofit growth pct")
        parser.add_argument("--bear-profit-growth-pct", type=float, help="Bear scenario FY netprofit growth pct")

        parser.add_argument("--base-revenue-growth-pct", type=float, help="Base scenario FY revenue growth pct")
        parser.add_argument("--bull-revenue-growth-pct", type=float, help="Bull scenario FY revenue growth pct")
        parser.add_argument("--bear-revenue-growth-pct", type=float, help="Bear scenario FY revenue growth pct")

        parser.add_argument("--bull-multiple-premium-pct", type=float, default=10.0, help="Bull scenario multiple premium pct")
        parser.add_argument("--bear-multiple-discount-pct", type=float, default=10.0, help="Bear scenario multiple discount pct")

        parser.add_argument("--top", type=int, default=30, help="Print top N by base upside")
        parser.add_argument("--output-csv", type=str, help="CSV output path")
        parser.add_argument("--outlook-version", type=str, default="annual_mvp_v20260319", help="Outlook version label")
        parser.add_argument("--persist", action="store_true", default=False, help="Persist scenario rows to AnnualOutlookSnapshot")

    def handle(self, *_args, **options):
        freq = str(options.get("freq") or "D").strip().upper()
        trade_date = _resolve_trade_date(options.get("trade_date"), freq=freq)
        scope = _normalize_scope(options.get("scope"))

        code_offset = max(0, int(options.get("code_offset") or 0))
        code_limit = options.get("code_limit")
        if code_limit is not None:
            code_limit = max(1, int(code_limit))

        base_profit_growth_pct = float(options.get("base_profit_growth_pct") or 12.0)
        bull_profit_growth_pct = options.get("bull_profit_growth_pct")
        bear_profit_growth_pct = options.get("bear_profit_growth_pct")
        if bull_profit_growth_pct is None:
            bull_profit_growth_pct = base_profit_growth_pct + 8.0
        if bear_profit_growth_pct is None:
            bear_profit_growth_pct = base_profit_growth_pct - 8.0

        base_revenue_growth_pct = options.get("base_revenue_growth_pct")
        bull_revenue_growth_pct = options.get("bull_revenue_growth_pct")
        bear_revenue_growth_pct = options.get("bear_revenue_growth_pct")
        if base_revenue_growth_pct is None:
            base_revenue_growth_pct = base_profit_growth_pct
        if bull_revenue_growth_pct is None:
            bull_revenue_growth_pct = bull_profit_growth_pct
        if bear_revenue_growth_pct is None:
            bear_revenue_growth_pct = bear_profit_growth_pct

        bull_multiple_premium_pct = float(options.get("bull_multiple_premium_pct") or 10.0)
        bear_multiple_discount_pct = float(options.get("bear_multiple_discount_pct") or 10.0)
        outlook_version = str(options.get("outlook_version") or "annual_mvp_v20260319").strip() or "annual_mvp_v20260319"
        persist = bool(options.get("persist"))

        assumptions_signature = _build_assumptions_signature(
            {
                "scope": scope,
                "freq": freq,
                "base_profit_growth_pct": float(base_profit_growth_pct),
                "bull_profit_growth_pct": float(bull_profit_growth_pct),
                "bear_profit_growth_pct": float(bear_profit_growth_pct),
                "base_revenue_growth_pct": float(base_revenue_growth_pct),
                "bull_revenue_growth_pct": float(bull_revenue_growth_pct),
                "bear_revenue_growth_pct": float(bear_revenue_growth_pct),
                "bull_multiple_premium_pct": float(bull_multiple_premium_pct),
                "bear_multiple_discount_pct": float(bear_multiple_discount_pct),
            }
        )

        trading_qs = StockTradingHistory.objects.filter(trade_date=trade_date, freq=freq)
        trading_qs = _resolve_scope_filter(trading_qs, scope)
        trading_rows = list(trading_qs.values("ts_code", "close_qfq", "close").order_by("ts_code"))
        if not trading_rows:
            raise CommandError("No stocks found for selected trade date/scope.")

        ts_codes = [row["ts_code"] for row in trading_rows]
        if code_offset:
            ts_codes = ts_codes[code_offset:]
        if code_limit is not None:
            ts_codes = ts_codes[:code_limit]
        if not ts_codes:
            raise CommandError("No stocks remain after code sampling.")

        code_to_price = {
            row["ts_code"]: (_safe_positive(row.get("close_qfq")) or _safe_positive(row.get("close")))
            for row in trading_rows
            if row["ts_code"] in ts_codes
        }

        fundamental_rows = (
            StockFundamentalHistory.objects.filter(ts_code__in=ts_codes, freq=freq, trade_date__lte=trade_date)
            .order_by("ts_code", "-trade_date")
            .values(
                "ts_code",
                "trade_date",
                "total_mv",
                "total_share",
                "pe_ttm",
                "ps_ttm",
                "pb",
            )
        )

        fundamental_map = {}
        for row in fundamental_rows:
            ts_code = row["ts_code"]
            if ts_code in fundamental_map:
                continue
            fundamental_map[ts_code] = row

        corp_rows = list(Corporation.objects.filter(ts_code__in=ts_codes).values("id", "ts_code", "name"))
        corp_name_map = {row["ts_code"]: row.get("name") for row in corp_rows}
        corp_id_map = {row["ts_code"]: row.get("id") for row in corp_rows}

        records = []
        persist_rows = []
        skipped = 0
        for ts_code in ts_codes:
            fundamental = fundamental_map.get(ts_code)
            if not fundamental:
                skipped += 1
                continue

            current_price = code_to_price.get(ts_code)
            total_mv = _safe_positive(fundamental.get("total_mv"))
            total_share = _safe_positive(fundamental.get("total_share"))
            pe_ttm = _safe_positive(fundamental.get("pe_ttm"))
            ps_ttm = _safe_positive(fundamental.get("ps_ttm"))
            pb = _safe_positive(fundamental.get("pb"))

            if total_mv is None or total_share is None:
                skipped += 1
                continue

            base_netprofit = total_mv / pe_ttm if pe_ttm not in (None, 0) else None
            base_revenue = total_mv / ps_ttm if ps_ttm not in (None, 0) else None
            base_equity = total_mv / pb if pb not in (None, 0) else None

            if base_netprofit is None and base_revenue is None and base_equity is None:
                skipped += 1
                continue

            bear_result = _build_scenario_result(
                scenario="bear",
                current_price=current_price,
                total_share=total_share,
                base_netprofit=base_netprofit,
                base_revenue=base_revenue,
                base_equity=base_equity,
                pe_base=pe_ttm,
                ps_base=ps_ttm,
                pb_base=pb,
                profit_growth_pct=float(bear_profit_growth_pct),
                revenue_growth_pct=float(bear_revenue_growth_pct),
                multiple_shift_pct=-abs(bear_multiple_discount_pct),
            )
            base_result = _build_scenario_result(
                scenario="base",
                current_price=current_price,
                total_share=total_share,
                base_netprofit=base_netprofit,
                base_revenue=base_revenue,
                base_equity=base_equity,
                pe_base=pe_ttm,
                ps_base=ps_ttm,
                pb_base=pb,
                profit_growth_pct=float(base_profit_growth_pct),
                revenue_growth_pct=float(base_revenue_growth_pct),
                multiple_shift_pct=0.0,
            )
            bull_result = _build_scenario_result(
                scenario="bull",
                current_price=current_price,
                total_share=total_share,
                base_netprofit=base_netprofit,
                base_revenue=base_revenue,
                base_equity=base_equity,
                pe_base=pe_ttm,
                ps_base=ps_ttm,
                pb_base=pb,
                profit_growth_pct=float(bull_profit_growth_pct),
                revenue_growth_pct=float(bull_revenue_growth_pct),
                multiple_shift_pct=abs(bull_multiple_premium_pct),
            )

            record = {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "name": corp_name_map.get(ts_code),
                "fundamental_trade_date": fundamental.get("trade_date"),
                "outlook_version": outlook_version,
                "assumptions_signature": assumptions_signature,
                "current_price": current_price,
                "base_total_mv": total_mv,
                "base_total_share": total_share,
                "base_pe_ttm": pe_ttm,
                "base_ps_ttm": ps_ttm,
                "base_pb": pb,
                "base_netprofit": base_netprofit,
                "base_revenue": base_revenue,
                "base_equity_book": base_equity,
            }

            for scenario_payload in [bear_result, base_result, bull_result]:
                prefix = scenario_payload["scenario"]
                record[f"{prefix}_profit_growth_pct"] = (
                    bear_profit_growth_pct if prefix == "bear" else
                    base_profit_growth_pct if prefix == "base" else
                    bull_profit_growth_pct
                )
                record[f"{prefix}_revenue_growth_pct"] = (
                    bear_revenue_growth_pct if prefix == "bear" else
                    base_revenue_growth_pct if prefix == "base" else
                    bull_revenue_growth_pct
                )
                record[f"{prefix}_forecast_netprofit"] = scenario_payload.get("forecast_netprofit")
                record[f"{prefix}_forecast_revenue"] = scenario_payload.get("forecast_revenue")
                record[f"{prefix}_target_pe"] = scenario_payload.get("target_pe")
                record[f"{prefix}_target_ps"] = scenario_payload.get("target_ps")
                record[f"{prefix}_target_pb"] = scenario_payload.get("target_pb")
                record[f"{prefix}_implied_price_pe"] = scenario_payload.get("implied_price_pe")
                record[f"{prefix}_implied_price_ps"] = scenario_payload.get("implied_price_ps")
                record[f"{prefix}_implied_price_pb"] = scenario_payload.get("implied_price_pb")
                record[f"{prefix}_composite_price"] = scenario_payload.get("composite_price")
                record[f"{prefix}_upside_pct"] = scenario_payload.get("upside_pct")

                if persist:
                    persist_rows.append(
                        {
                            "ts_code": ts_code,
                            "trade_date": trade_date,
                            "freq": freq,
                            "scope": scope,
                            "outlook_version": outlook_version,
                            "assumptions_signature": assumptions_signature,
                            "scenario": prefix,
                            "corporation_id": corp_id_map.get(ts_code),
                            "fundamental_trade_date": fundamental.get("trade_date"),
                            "current_price": _to_decimal_or_none(current_price, 6),
                            "base_total_mv": _to_decimal_or_none(total_mv, 2),
                            "base_total_share": _to_decimal_or_none(total_share, 2),
                            "profit_growth_pct": _to_decimal_or_none(record[f"{prefix}_profit_growth_pct"], 4),
                            "revenue_growth_pct": _to_decimal_or_none(record[f"{prefix}_revenue_growth_pct"], 4),
                            "forecast_netprofit": _to_decimal_or_none(scenario_payload.get("forecast_netprofit"), 2),
                            "forecast_revenue": _to_decimal_or_none(scenario_payload.get("forecast_revenue"), 2),
                            "target_pe": _to_decimal_or_none(scenario_payload.get("target_pe"), 4),
                            "target_ps": _to_decimal_or_none(scenario_payload.get("target_ps"), 4),
                            "target_pb": _to_decimal_or_none(scenario_payload.get("target_pb"), 4),
                            "implied_price_pe": _to_decimal_or_none(scenario_payload.get("implied_price_pe"), 6),
                            "implied_price_ps": _to_decimal_or_none(scenario_payload.get("implied_price_ps"), 6),
                            "implied_price_pb": _to_decimal_or_none(scenario_payload.get("implied_price_pb"), 6),
                            "composite_price": _to_decimal_or_none(scenario_payload.get("composite_price"), 6),
                            "upside_pct": _to_decimal_or_none(scenario_payload.get("upside_pct"), 4),
                        }
                    )

            records.append(record)

        result_df = pd.DataFrame(records)

        self.stdout.write(
            self.style.SUCCESS(
                f"annual outlook complete: trade_date={trade_date} scope={scope} universe={len(ts_codes)} covered={len(result_df)} skipped={skipped} version={outlook_version}"
            )
        )

        if result_df.empty:
            self.stdout.write("No annual outlook rows generated.")
            return

        result_df = result_df.sort_values(
            by=["base_upside_pct", "bull_upside_pct"],
            ascending=[False, False],
        )

        preview_cols = [
            "ts_code",
            "name",
            "current_price",
            "base_composite_price",
            "base_upside_pct",
            "bull_composite_price",
            "bull_upside_pct",
            "bear_composite_price",
            "bear_upside_pct",
        ]
        top_n = max(1, int(options.get("top") or 30))
        self.stdout.write("top_outlook=")
        self.stdout.write(result_df[preview_cols].head(top_n).to_string(index=False))

        if persist and persist_rows:
            with transaction.atomic():
                for row in persist_rows:
                    lookup = {
                        "ts_code": row["ts_code"],
                        "trade_date": row["trade_date"],
                        "freq": row["freq"],
                        "outlook_version": row["outlook_version"],
                        "assumptions_signature": row["assumptions_signature"],
                        "scenario": row["scenario"],
                    }
                    defaults = {k: v for k, v in row.items() if k not in lookup}
                    AnnualOutlookSnapshot.objects.update_or_create(
                        **lookup,
                        defaults=defaults,
                    )
            self.stdout.write(self.style.SUCCESS(f"persisted scenario rows: {len(persist_rows)}"))

        output_csv = options.get("output_csv")
        if output_csv:
            result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
            self.stdout.write(self.style.SUCCESS(f"saved annual outlook to {output_csv}"))
