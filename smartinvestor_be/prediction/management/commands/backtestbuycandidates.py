import math
from datetime import datetime
from decimal import Decimal

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from api.views import _build_snapshot_method_map, _summarize_buy_candidate
from datastore.models import StockTradingHistory
from valuation.models import BacktestValuationSnapshot, StockValuationSnapshot
from prediction.utils.prediction_util import get_tushare_pro
from valuation.services.valuation_engine import test_valuation


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


def _safe_price(value):
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    return numeric


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


def _load_backtest_snapshot_method_map(ts_codes, trade_date, batch_key, market="CN"):
    if not ts_codes:
        return {}

    rows = (
        BacktestValuationSnapshot.objects.filter(
            ts_code__in=ts_codes,
            trade_date=trade_date,
            market=market,
            batch_key=batch_key,
        )
        .order_by("ts_code", "valuation_method", "-updated_at")
        .values("ts_code", "valuation_method", "valuation_price", "valuation_market_cap", "source")
    )

    snapshot_map = {}
    for row in rows:
        ts_code = row["ts_code"]
        method = str(row["valuation_method"] or "").strip().lower()
        if not method:
            continue
        method_map = snapshot_map.setdefault(ts_code, {})
        if method in method_map:
            continue
        valuation_price = row.get("valuation_price")
        valuation_market_cap = row.get("valuation_market_cap")
        method_map[method] = {
            "valuation_price": float(valuation_price) if valuation_price is not None else None,
            "valuation_market_cap": float(valuation_market_cap) if valuation_market_cap is not None else None,
            "source": row.get("source"),
        }
    return snapshot_map


def _save_backtest_snapshot_method_map(ts_code, trade_date, method_map, batch_key, market="CN"):
    upserts = []
    if not method_map:
        method_map = {
            "__empty__": {
                "valuation_price": None,
                "valuation_market_cap": None,
                "source": "live_backtest_empty",
            }
        }

    for method, payload in method_map.items():
        upserts.append(
            BacktestValuationSnapshot(
                ts_code=ts_code,
                trade_date=trade_date,
                market=market,
                batch_key=batch_key,
                valuation_method=method,
                valuation_price=_to_decimal_or_none(payload.get("valuation_price"), 6),
                valuation_market_cap=_to_decimal_or_none(payload.get("valuation_market_cap"), 2),
                source=payload.get("source") or "live_backtest",
            )
        )

    if not upserts:
        return

    BacktestValuationSnapshot.objects.bulk_create(
        upserts,
        update_conflicts=True,
        unique_fields=["ts_code", "trade_date", "market", "valuation_method", "batch_key"],
        update_fields=["valuation_price", "valuation_market_cap", "source", "updated_at"],
    )


def _save_backtest_snapshot_error(ts_code, trade_date, batch_key, market="CN", source="live_backtest_error"):
    _save_backtest_snapshot_method_map(
        ts_code=ts_code,
        trade_date=trade_date,
        batch_key=batch_key,
        market=market,
        method_map={
            "__error__": {
                "valuation_price": None,
                "valuation_market_cap": None,
                "source": source,
            }
        },
    )


def _extract_live_method_map(ts_code, trade_date, pro, strict_express_match, express_max_age_days):
    valuation_result = test_valuation(
        ts_code=ts_code,
        trade_date=trade_date,
        pro=pro,
        strict_express_match=strict_express_match,
        express_max_age_days=express_max_age_days,
    )
    valuation_df = valuation_result.get("valuations")
    method_map = {}
    if valuation_df is None or valuation_df.empty:
        return method_map

    for _, row in valuation_df.iterrows():
        method = str(row.get("method") or "").strip().lower()
        if not method:
            continue
        valuation_price = _safe_price(row.get("implied_price"))
        valuation_market_cap = row.get("equity_value")
        method_map[method] = {
            "valuation_price": valuation_price,
            "valuation_market_cap": float(valuation_market_cap) if valuation_market_cap not in (None, "") else None,
            "source": "live_backtest",
        }
    return method_map


def _build_price_history(scope, start_date, end_date, freq="D"):
    trading_qs = StockTradingHistory.objects.filter(
        freq=freq,
        trade_date__gte=start_date,
        trade_date__lte=end_date,
    )
    trading_qs = _resolve_scope_filter(trading_qs, scope)
    rows = trading_qs.values("ts_code", "trade_date", "close_qfq", "close")

    price_history = {}
    for row in rows:
        ts_code = row["ts_code"]
        price = _safe_price(row.get("close_qfq")) or _safe_price(row.get("close"))
        if price is None:
            continue
        price_history.setdefault(ts_code, []).append((row["trade_date"], price))

    for ts_code in price_history:
        price_history[ts_code].sort(key=lambda item: item[0])
    return price_history


def _resolve_entry_dates(scope, start_date, end_date, snapshot_only, rebalance_step):
    if snapshot_only:
        snapshot_qs = StockValuationSnapshot.objects.all()
        if start_date:
            snapshot_qs = snapshot_qs.filter(trade_date__gte=start_date)
        if end_date:
            snapshot_qs = snapshot_qs.filter(trade_date__lte=end_date)
        snapshot_qs = _resolve_scope_filter(snapshot_qs, scope)
        return list(snapshot_qs.values_list("trade_date", flat=True).distinct().order_by("trade_date"))

    trading_qs = StockTradingHistory.objects.filter(freq="D")
    if start_date:
        trading_qs = trading_qs.filter(trade_date__gte=start_date)
    if end_date:
        trading_qs = trading_qs.filter(trade_date__lte=end_date)
    trading_qs = _resolve_scope_filter(trading_qs, scope)
    dates = list(trading_qs.values_list("trade_date", flat=True).distinct().order_by("trade_date"))
    step = max(1, int(rebalance_step or 1))
    return dates[::step]


def _calc_forward_return(price_series, entry_date, holding_period):
    if not price_series:
        return None, None, None

    for index, (trade_date, entry_price) in enumerate(price_series):
        if trade_date != entry_date:
            continue
        target_index = index + holding_period
        if target_index >= len(price_series):
            return entry_price, None, None
        exit_date, exit_price = price_series[target_index]
        return entry_price, exit_date, round((exit_price / entry_price - 1.0) * 100.0, 4)
    return None, None, None


def _find_entry_index(price_series, entry_date):
    for index, (trade_date, _entry_price) in enumerate(price_series):
        if trade_date == entry_date:
            return index
    return None


def _calc_trailing_risk_metrics(price_series, entry_date, lookback_days):
    if not price_series:
        return None, None

    entry_index = _find_entry_index(price_series, entry_date)
    if entry_index is None:
        return None, None

    start_index = max(0, entry_index - max(1, int(lookback_days)) + 1)
    window_prices = [price for _d, price in price_series[start_index : entry_index + 1] if price and price > 0]
    if len(window_prices) < 2:
        return None, None

    returns = []
    for prev_price, cur_price in zip(window_prices[:-1], window_prices[1:]):
        if prev_price <= 0:
            continue
        returns.append(cur_price / prev_price - 1.0)
    if not returns:
        trailing_vol_pct = None
    else:
        trailing_vol_pct = float(pd.Series(returns, dtype="float64").std(ddof=0) * 100.0)

    peak_price = max(window_prices)
    entry_price = window_prices[-1]
    trailing_drawdown_pct = None
    if peak_price > 0 and entry_price > 0:
        trailing_drawdown_pct = float((1.0 - entry_price / peak_price) * 100.0)

    return trailing_vol_pct, trailing_drawdown_pct


class Command(BaseCommand):
    help = "回测 buy-candidate 规则在历史日期上的未来收益表现"

    def add_arguments(self, parser):
        parser.add_argument("--scope", type=str, default="688", help="范围：ALL 或 ts_code 前缀，如 688 / 60,0,3")
        parser.add_argument("--start-date", type=str, help="起始日期 YYYY-MM-DD")
        parser.add_argument("--end-date", type=str, help="结束日期 YYYY-MM-DD")
        parser.add_argument("--entry-dates", type=str, help="指定入场日期列表，逗号分隔")
        parser.add_argument("--code-offset", type=int, default=0, help="股票采样起始偏移")
        parser.add_argument("--code-limit", type=int, help="每个入场日最多处理多少只股票，用于抽样 live 回测")
        parser.add_argument("--holding-periods", type=str, default="5,10,20", help="持有交易日数，逗号分隔")
        parser.add_argument("--valuation-band-pct", type=float, default=0.1, help="低估偏离带阈值")
        parser.add_argument("--min-score", type=float, help="候选附加过滤：最低低估分")
        parser.add_argument("--min-core-under", type=int, help="候选附加过滤：核心方法低估最少个数")
        parser.add_argument("--min-under-methods", type=int, help="候选附加过滤：低估方法最少个数")
        parser.add_argument("--min-composite-gap-pct", type=float, help="候选附加过滤：组合估值相对现价最小溢价(小数)")
        parser.add_argument("--min-conservative-gap-pct", type=float, help="候选附加过滤：保守估值相对现价最小溢价(小数)")
        parser.add_argument("--risk-lookback-days", type=int, default=20, help="风控统计回看窗口(交易日)")
        parser.add_argument("--max-trailing-vol-pct", type=float, help="风控二筛：入场前波动率上限(%)")
        parser.add_argument("--max-trailing-drawdown-pct", type=float, help="风控二筛：入场前回撤上限(%)")
        parser.add_argument("--rebalance-step", type=int, default=5, help="非 snapshot-only 模式下，每隔多少个交易日取一个入场日")
        parser.add_argument("--snapshot-only", action="store_true", default=False, help="仅使用已有 valuation snapshot 回测")
        parser.add_argument("--use-live-valuation", action="store_true", default=False, help="缺少 snapshot 时实时重算估值")
        parser.add_argument("--strict-express-match", action="store_true", default=False, help="实时估值时启用 express_vip 严格匹配")
        parser.add_argument("--express-max-age-days", type=int, default=180, help="实时估值时 express_vip 最大账龄")
        parser.add_argument("--top", type=int, default=20, help="输出明细前 N 条")
        parser.add_argument("--output-csv", type=str, help="回测明细输出 csv 路径")
        parser.add_argument("--cache-batch-key", type=str, default="default", help="回测临时快照批次标识")
        parser.add_argument("--refresh-cache", action="store_true", default=False, help="忽略已缓存的回测临时快照并强制重算")

    def handle(self, *_args, **options):
        scope = _normalize_scope(options.get("scope"))
        start_date = options.get("start_date")
        end_date = options.get("end_date")
        entry_dates_raw = options.get("entry_dates")
        holding_periods = [int(item) for item in _split_csv(options.get("holding_periods"))]
        if not holding_periods:
            raise CommandError("--holding-periods 至少需要一个正整数")
        if any(period <= 0 for period in holding_periods):
            raise CommandError("--holding-periods 只能包含正整数")

        snapshot_only = bool(options.get("snapshot_only"))
        use_live_valuation = bool(options.get("use_live_valuation"))
        strict_express_match = bool(options.get("strict_express_match"))
        express_max_age_days = int(options.get("express_max_age_days") or 180)
        band_pct = max(0.01, float(options.get("valuation_band_pct") or 0.1))
        rebalance_step = max(1, int(options.get("rebalance_step") or 1))
        top_n = max(1, int(options.get("top") or 20))
        code_offset = max(0, int(options.get("code_offset") or 0))
        code_limit = options.get("code_limit")
        if code_limit is not None:
            code_limit = max(1, int(code_limit))

        min_score = options.get("min_score")
        min_core_under = options.get("min_core_under")
        min_under_methods = options.get("min_under_methods")
        min_composite_gap_pct = options.get("min_composite_gap_pct")
        min_conservative_gap_pct = options.get("min_conservative_gap_pct")
        risk_lookback_days = max(2, int(options.get("risk_lookback_days") or 20))
        max_trailing_vol_pct = options.get("max_trailing_vol_pct")
        max_trailing_drawdown_pct = options.get("max_trailing_drawdown_pct")
        cache_batch_key = str(options.get("cache_batch_key") or "default").strip() or "default"
        refresh_cache = bool(options.get("refresh_cache"))

        if snapshot_only and use_live_valuation:
            raise CommandError("--snapshot-only 与 --use-live-valuation 只能二选一")

        start_date_obj = _parse_date_text(start_date) if start_date else None
        end_date_obj = _parse_date_text(end_date) if end_date else None

        if entry_dates_raw:
            entry_dates = [_parse_date_text(item) for item in _split_csv(entry_dates_raw)]
        else:
            entry_dates = _resolve_entry_dates(
                scope=scope,
                start_date=start_date_obj,
                end_date=end_date_obj,
                snapshot_only=snapshot_only,
                rebalance_step=rebalance_step,
            )

        entry_dates = [item for item in entry_dates if item is not None]
        if not entry_dates:
            raise CommandError("未找到可用于回测的入场日期")

        if start_date_obj is None:
            start_date_obj = min(entry_dates)
        if end_date_obj is None:
            end_date_obj = max(entry_dates)

        trading_end_qs = StockTradingHistory.objects.filter(freq="D", trade_date__gte=end_date_obj)
        trading_end_qs = _resolve_scope_filter(trading_end_qs, scope)
        latest_trading_date = trading_end_qs.order_by("-trade_date").values_list("trade_date", flat=True).first()
        if latest_trading_date is None:
            raise CommandError("未找到交易历史，无法计算未来收益")

        price_history = _build_price_history(scope=scope, start_date=start_date_obj, end_date=latest_trading_date, freq="D")
        if not price_history:
            raise CommandError("指定范围内没有有效价格历史")

        pro = get_tushare_pro() if use_live_valuation else None
        detail_rows = []
        summary_rows = []

        for entry_date in entry_dates:
            date_prices = {
                ts_code: series_entry_price
                for ts_code, series in price_history.items()
                for series_date, series_entry_price in series
                if series_date == entry_date
            }
            ts_codes = sorted(date_prices.keys())
            if code_offset:
                ts_codes = ts_codes[code_offset:]
            if code_limit is not None:
                ts_codes = ts_codes[:code_limit]
            if not ts_codes:
                continue

            if use_live_valuation:
                valuation_method_map = {}
                cached_method_map = {}
                if not refresh_cache:
                    cached_method_map = _load_backtest_snapshot_method_map(
                        ts_codes=ts_codes,
                        trade_date=entry_date,
                        batch_key=cache_batch_key,
                        market="CN",
                    )

                for ts_code in ts_codes:
                    cached_payload = cached_method_map.get(ts_code, {})
                    if cached_payload:
                        valuation_method_map[ts_code] = cached_payload
                        continue
                    try:
                        live_payload = _extract_live_method_map(
                            ts_code=ts_code,
                            trade_date=entry_date,
                            pro=pro,
                            strict_express_match=strict_express_match,
                            express_max_age_days=express_max_age_days,
                        )
                        valuation_method_map[ts_code] = live_payload
                        if live_payload:
                            _save_backtest_snapshot_method_map(
                                ts_code=ts_code,
                                trade_date=entry_date,
                                method_map=live_payload,
                                batch_key=cache_batch_key,
                                market="CN",
                            )
                    except Exception as exc:
                        self.stderr.write(f"[warn] live valuation failed {ts_code} {entry_date}: {exc}")
                        _save_backtest_snapshot_error(
                            ts_code=ts_code,
                            trade_date=entry_date,
                            batch_key=cache_batch_key,
                            market="CN",
                        )
                        valuation_method_map[ts_code] = {}
            else:
                valuation_method_map = _build_snapshot_method_map(ts_codes=ts_codes, trade_date=entry_date, market="CN")

            date_candidate_count = 0
            for ts_code in ts_codes:
                current_price = date_prices.get(ts_code)
                method_map = valuation_method_map.get(ts_code, {})
                candidate_summary = _summarize_buy_candidate(
                    current_price=current_price,
                    method_map=method_map,
                    band_pct=band_pct,
                )
                if not candidate_summary.get("buy_candidate"):
                    continue

                # Optional tightening filters for threshold optimization experiments.
                score = candidate_summary.get("undervalue_score")
                under_methods = candidate_summary.get("valuation_under_methods") or []
                core_methods = candidate_summary.get("valuation_core_methods") or []
                core_under_count = len([m for m in core_methods if m in under_methods])
                under_method_count = len(under_methods)

                composite_price = _safe_price(candidate_summary.get("composite_valuation_price"))
                conservative_price = _safe_price(candidate_summary.get("conservative_valuation_price"))
                composite_gap_pct = (
                    (composite_price - current_price) / current_price
                    if composite_price is not None and current_price is not None
                    else None
                )
                conservative_gap_pct = (
                    (conservative_price - current_price) / current_price
                    if conservative_price is not None and current_price is not None
                    else None
                )

                if min_score is not None and (score is None or float(score) < float(min_score)):
                    continue
                if min_core_under is not None and core_under_count < int(min_core_under):
                    continue
                if min_under_methods is not None and under_method_count < int(min_under_methods):
                    continue
                if min_composite_gap_pct is not None and (
                    composite_gap_pct is None or composite_gap_pct < float(min_composite_gap_pct)
                ):
                    continue
                if min_conservative_gap_pct is not None and (
                    conservative_gap_pct is None or conservative_gap_pct < float(min_conservative_gap_pct)
                ):
                    continue

                series = price_history.get(ts_code, [])
                trailing_vol_pct, trailing_drawdown_pct = _calc_trailing_risk_metrics(
                    price_series=series,
                    entry_date=entry_date,
                    lookback_days=risk_lookback_days,
                )
                if max_trailing_vol_pct is not None and (
                    trailing_vol_pct is None or trailing_vol_pct > float(max_trailing_vol_pct)
                ):
                    continue
                if max_trailing_drawdown_pct is not None and (
                    trailing_drawdown_pct is None or trailing_drawdown_pct > float(max_trailing_drawdown_pct)
                ):
                    continue

                date_candidate_count += 1
                detail = {
                    "entry_date": entry_date,
                    "ts_code": ts_code,
                    "entry_price": round(current_price, 4) if current_price is not None else None,
                    "undervalue_score": candidate_summary.get("undervalue_score"),
                    "composite_valuation_price": candidate_summary.get("composite_valuation_price"),
                    "conservative_valuation_price": candidate_summary.get("conservative_valuation_price"),
                    "valuation_valid_methods": ",".join(candidate_summary.get("valuation_valid_methods") or []),
                    "valuation_under_methods": ",".join(candidate_summary.get("valuation_under_methods") or []),
                    "buy_candidate_reason": candidate_summary.get("buy_candidate_reason"),
                    "core_under_count": core_under_count,
                    "under_method_count": under_method_count,
                    "composite_gap_pct": round(composite_gap_pct * 100.0, 4) if composite_gap_pct is not None else None,
                    "conservative_gap_pct": round(conservative_gap_pct * 100.0, 4) if conservative_gap_pct is not None else None,
                    "trailing_vol_pct": round(trailing_vol_pct, 4) if trailing_vol_pct is not None else None,
                    "trailing_drawdown_pct": round(trailing_drawdown_pct, 4) if trailing_drawdown_pct is not None else None,
                }

                for holding_period in holding_periods:
                    _entry_price, exit_date, forward_return_pct = _calc_forward_return(
                        price_series=series,
                        entry_date=entry_date,
                        holding_period=holding_period,
                    )
                    detail[f"exit_date_{holding_period}d"] = exit_date
                    detail[f"return_{holding_period}d_pct"] = forward_return_pct
                detail_rows.append(detail)

            summary_rows.append({
                "entry_date": entry_date,
                "candidate_count": date_candidate_count,
            })

        detail_df = pd.DataFrame(detail_rows)
        summary_df = pd.DataFrame(summary_rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"backtest complete: dates={len(entry_dates)} candidates={len(detail_df)} scope={scope} mode={'live' if use_live_valuation else 'snapshot'}"
            )
        )
        if use_live_valuation:
            cached_rows = BacktestValuationSnapshot.objects.filter(batch_key=cache_batch_key).count()
            self.stdout.write(f"cache_batch_key={cache_batch_key} cached_rows={cached_rows} refresh_cache={refresh_cache}")

        if summary_df.empty:
            self.stdout.write("No buy candidates found for the requested configuration.")
            return

        date_stats = {
            "avg_candidates_per_date": round(float(summary_df["candidate_count"].mean()), 4),
            "max_candidates_single_date": int(summary_df["candidate_count"].max()),
            "active_dates": int((summary_df["candidate_count"] > 0).sum()),
        }
        self.stdout.write(f"date_stats={date_stats}")

        if not detail_df.empty:
            risk_stats = {
                "avg_trailing_vol_pct": round(float(detail_df["trailing_vol_pct"].dropna().mean()), 4)
                if "trailing_vol_pct" in detail_df and detail_df["trailing_vol_pct"].notna().any()
                else None,
                "avg_trailing_drawdown_pct": round(float(detail_df["trailing_drawdown_pct"].dropna().mean()), 4)
                if "trailing_drawdown_pct" in detail_df and detail_df["trailing_drawdown_pct"].notna().any()
                else None,
            }
            self.stdout.write(f"risk_stats={risk_stats}")

        for holding_period in holding_periods:
            return_col = f"return_{holding_period}d_pct"
            valid_df = detail_df.dropna(subset=[return_col])
            if valid_df.empty:
                self.stdout.write(f"holding_{holding_period}d: no completed trades")
                continue
            avg_return = round(float(valid_df[return_col].mean()), 4)
            median_return = round(float(valid_df[return_col].median()), 4)
            win_rate = round(float((valid_df[return_col] > 0).mean() * 100.0), 2)
            hit_5 = round(float((valid_df[return_col] >= 5.0).mean() * 100.0), 2)
            hit_10 = round(float((valid_df[return_col] >= 10.0).mean() * 100.0), 2)
            self.stdout.write(
                f"holding_{holding_period}d: trades={len(valid_df)} avg={avg_return}% median={median_return}% win_rate={win_rate}% hit_5pct={hit_5}% hit_10pct={hit_10}%"
            )

        preview_cols = [
            "entry_date",
            "ts_code",
            "entry_price",
            "undervalue_score",
            "composite_valuation_price",
            "conservative_valuation_price",
        ]
        for holding_period in holding_periods:
            preview_cols.append(f"return_{holding_period}d_pct")

        preview_df = detail_df.sort_values(
            by=["entry_date", "undervalue_score"],
            ascending=[True, False],
        )[preview_cols].head(top_n)
        if not preview_df.empty:
            self.stdout.write("top_candidates_preview=")
            self.stdout.write(preview_df.to_string(index=False))

        output_csv = options.get("output_csv")
        if output_csv:
            detail_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
            self.stdout.write(self.style.SUCCESS(f"saved details to {output_csv}"))