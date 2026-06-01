import math
from datetime import datetime
from decimal import Decimal

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from datastore.models import StockTradingHistory
from valuation.models import BacktestValuationSnapshot, StockValuationSnapshot
from prediction.utils.prediction_util import get_tushare_pro
from prediction.utils.valuation_util import test_valuation


BUY_CANDIDATE_CORE_METHODS = ("pe", "pb", "ps")
BUY_CANDIDATE_SUPPORT_METHODS = ("fcff_dcf", "ddm")
BUY_CANDIDATE_OPTIONAL_METHODS = ("peg",)
BUY_CANDIDATE_RULE_VERSION = "baseline_v20260319"

BUY_CANDIDATE_MIN_CORE_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_CORE_UNDER_COUNT = 1
BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT = 2
BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT = -0.02
BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT = -0.12


def _normalize_valuation_method_name(method_name):
    if method_name is None:
        return ""
    return (
        str(method_name)
        .strip()
        .lower()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "")
    )


VALUATION_METHOD_ALIAS_MAP = {
    "pe": {"pe"},
    "ps": {"ps"},
    "pb": {"pb"},
    "peg": {"peg"},
    "fcff_dcf": {"fcff_dcf", "fcff"},
    "ddm": {"ddm"},
    "ev_ebitda": {"ev_ebitda"},
    "market_cap": {"market_cap"},
}


def _resolve_method_candidates(selected_method):
    normalized_selected = _normalize_valuation_method_name(selected_method)
    return normalized_selected, VALUATION_METHOD_ALIAS_MAP.get(
        normalized_selected,
        {normalized_selected},
    )


def _build_snapshot_method_map(ts_codes, trade_date, market="CN"):
    if not ts_codes:
        return {}

    snapshots = (
        StockValuationSnapshot.objects.filter(
            ts_code__in=ts_codes,
            trade_date=trade_date,
            market=market,
        )
        .order_by("ts_code", "valuation_method", "-updated_at")
        .values(
            "ts_code",
            "valuation_method",
            "valuation_price",
            "valuation_market_cap",
            "source",
        )
    )

    snapshot_map = {}
    for row in snapshots:
        ts_code = row["ts_code"]
        method = _normalize_valuation_method_name(row["valuation_method"])
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


def _summarize_buy_candidate(current_price, method_map, band_pct):
    summary = {
        "composite_valuation_price": None,
        "conservative_valuation_price": None,
        "undervalue_score": None,
        "buy_candidate": False,
        "buy_candidate_reason": "no_valid_valuation_methods",
        "buy_candidate_rule_version": BUY_CANDIDATE_RULE_VERSION,
        "valuation_valid_methods": [],
        "valuation_under_methods": [],
        "valuation_core_methods": [],
    }

    if current_price in (None, 0) or not method_map:
        return summary

    current_price = float(current_price)
    valid_methods = {}
    for method, payload in (method_map or {}).items():
        valuation_price = payload.get("valuation_price")
        if valuation_price is None:
            continue
        valuation_price = float(valuation_price)
        if valuation_price <= 0:
            continue
        valid_methods[method] = valuation_price

    if not valid_methods:
        return summary

    core_prices = [valid_methods[m] for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods]
    support_prices = [valid_methods[m] for m in BUY_CANDIDATE_SUPPORT_METHODS if m in valid_methods]
    optional_prices = []
    for method in BUY_CANDIDATE_OPTIONAL_METHODS:
        price = valid_methods.get(method)
        if price is None:
            continue
        if 0.5 * current_price <= price <= 2.5 * current_price:
            optional_prices.append(price)

    candidate_prices = core_prices + support_prices + optional_prices
    if not candidate_prices:
        return summary

    composite_price = float(pd.Series(candidate_prices, dtype="float64").median())
    conservative_pool = core_prices or candidate_prices
    conservative_price = min(conservative_pool)

    under_methods = [
        method for method, valuation_price in valid_methods.items()
        if current_price <= valuation_price * (1 - band_pct)
    ]
    core_under_methods = [
        method for method in BUY_CANDIDATE_CORE_METHODS
        if method in valid_methods and current_price <= valid_methods[method] * (1 - band_pct)
    ]

    composite_gap_pct = (composite_price - current_price) / current_price
    conservative_gap_pct = (conservative_price - current_price) / current_price

    score = 0
    valid_method_count = len(valid_methods)
    core_method_count = len(core_prices)
    core_under_count = len(core_under_methods)

    if valid_method_count >= 4:
        score += 20
    elif valid_method_count >= 3:
        score += 15
    elif valid_method_count >= 2:
        score += 8

    if core_method_count >= 3:
        score += 25
    elif core_method_count >= 2:
        score += 18
    elif core_method_count == 1:
        score += 8

    if core_under_count >= 3:
        score += 30
    elif core_under_count >= 2:
        score += 24
    elif core_under_count == 1:
        score += 16

    under_method_count = len(under_methods)
    if under_method_count >= 4:
        score += 10
    elif under_method_count >= 3:
        score += 7
    elif under_method_count >= 2:
        score += 4

    if composite_gap_pct >= 0.3:
        score += 15
    elif composite_gap_pct >= 0.15:
        score += 10
    elif composite_gap_pct >= band_pct:
        score += 5

    if conservative_gap_pct >= 0.15:
        score += 10
    elif conservative_gap_pct >= 0.08:
        score += 6
    elif conservative_gap_pct >= 0.03:
        score += 3

    buy_candidate = (
        core_method_count >= BUY_CANDIDATE_MIN_CORE_METHOD_COUNT
        and core_under_count >= BUY_CANDIDATE_MIN_CORE_UNDER_COUNT
        and under_method_count >= BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT
        and composite_gap_pct >= BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT
        and conservative_gap_pct >= BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT
    )

    reasons = [
        f"valid_methods={valid_method_count}",
        f"core_methods={core_method_count}",
        f"core_under={core_under_count}",
        f"under_methods={under_method_count}",
        f"composite_gap_pct={round(composite_gap_pct * 100, 2)}",
        f"conservative_gap_pct={round(conservative_gap_pct * 100, 2)}",
    ]

    summary.update(
        {
            "composite_valuation_price": round(composite_price, 4),
            "conservative_valuation_price": round(conservative_price, 4),
            "undervalue_score": min(score, 100),
            "buy_candidate": buy_candidate,
            "buy_candidate_reason": "; ".join(reasons),
            "valuation_valid_methods": sorted(valid_methods.keys()),
            "valuation_under_methods": sorted(under_methods),
            "valuation_core_methods": [m for m in BUY_CANDIDATE_CORE_METHODS if m in valid_methods],
        }
    )
    return summary


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

    trailing_vol_pct = None
    if returns:
        trailing_vol_pct = float(pd.Series(returns, dtype="float64").std(ddof=0) * 100.0)

    peak_price = max(window_prices)
    entry_price = window_prices[-1]
    trailing_drawdown_pct = None
    if peak_price > 0 and entry_price > 0:
        trailing_drawdown_pct = float((1.0 - entry_price / peak_price) * 100.0)

    return trailing_vol_pct, trailing_drawdown_pct


def _build_price_history(ts_codes, trade_date, lookback_days, freq="D"):
    start_date = trade_date - pd.Timedelta(days=max(lookback_days * 2, 40))
    qs = (
        StockTradingHistory.objects.filter(
            ts_code__in=ts_codes,
            freq=freq,
            trade_date__gte=start_date,
            trade_date__lte=trade_date,
        )
        .values("ts_code", "trade_date", "close_qfq", "close")
        .order_by("ts_code", "trade_date")
    )

    history = {}
    for row in qs:
        price = _safe_price(row.get("close_qfq")) or _safe_price(row.get("close"))
        if price is None:
            continue
        history.setdefault(row["ts_code"], []).append((row["trade_date"], price))
    return history


def _load_backtest_cache_map(ts_codes, trade_date, batch_key, market="CN"):
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
        method_map[method] = {
            "valuation_price": float(row["valuation_price"]) if row.get("valuation_price") is not None else None,
            "valuation_market_cap": float(row["valuation_market_cap"]) if row.get("valuation_market_cap") is not None else None,
            "source": row.get("source"),
        }
    return snapshot_map


def _save_backtest_cache_map(ts_code, trade_date, method_map, batch_key, market="CN"):
    if not method_map:
        method_map = {
            "__empty__": {
                "valuation_price": None,
                "valuation_market_cap": None,
                "source": "live_pick_empty",
            }
        }

    rows = []
    for method, payload in method_map.items():
        rows.append(
            BacktestValuationSnapshot(
                ts_code=ts_code,
                trade_date=trade_date,
                market=market,
                batch_key=batch_key,
                valuation_method=method,
                valuation_price=_to_decimal_or_none(payload.get("valuation_price"), 6),
                valuation_market_cap=_to_decimal_or_none(payload.get("valuation_market_cap"), 2),
                source=payload.get("source") or "live_pick",
            )
        )

    BacktestValuationSnapshot.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["ts_code", "trade_date", "market", "valuation_method", "batch_key"],
        update_fields=["valuation_price", "valuation_market_cap", "source", "updated_at"],
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
        method_map[method] = {
            "valuation_price": _safe_price(row.get("implied_price")),
            "valuation_market_cap": float(row.get("equity_value")) if row.get("equity_value") not in (None, "") else None,
            "source": "live_pick",
        }
    return method_map


def _resolve_trade_date(trade_date_text, freq):
    if trade_date_text:
        return _parse_date_text(trade_date_text)
    latest = (
        StockTradingHistory.objects.filter(freq=freq)
        .aggregate(latest_date=Max("trade_date"))
        .get("latest_date")
    )
    if latest is None:
        raise CommandError("未找到交易数据，无法推断 trade-date")
    return latest


def _resolve_risk_profile(profile_name):
    profile = str(profile_name or "none").strip().lower()
    if profile == "none":
        return {"max_trailing_vol_pct": None, "max_trailing_drawdown_pct": None}
    if profile == "medium":
        return {"max_trailing_vol_pct": 3.5, "max_trailing_drawdown_pct": 12.0}
    if profile == "strict":
        return {"max_trailing_vol_pct": 2.8, "max_trailing_drawdown_pct": 8.0}
    raise CommandError("--risk-profile 仅支持 none/medium/strict")


class Command(BaseCommand):
    help = "后台命令选出买入候选（无前台场景）"

    def add_arguments(self, parser):
        parser.add_argument("--trade-date", type=str, help="交易日 YYYY-MM-DD，默认自动取最新交易日")
        parser.add_argument("--scope", type=str, default="688", help="范围：ALL 或前缀，如 688 / 60,0,3")
        parser.add_argument("--freq", type=str, default="D", help="频率，默认 D")
        parser.add_argument("--valuation-band-pct", type=float, default=0.1, help="低估偏离带")
        parser.add_argument("--code-offset", type=int, default=0, help="股票采样偏移")
        parser.add_argument("--code-limit", type=int, help="股票采样上限")
        parser.add_argument("--top", type=int, default=30, help="打印前 N 条候选")
        parser.add_argument("--output-csv", type=str, help="候选输出 CSV")

        parser.add_argument("--risk-lookback-days", type=int, default=20, help="风控回看窗口（交易日）")
        parser.add_argument("--risk-profile", type=str, default="medium", help="风险档位：none/medium/strict")
        parser.add_argument("--max-trailing-vol-pct", type=float, help="覆盖风险档位：入场前波动率上限(%)")
        parser.add_argument("--max-trailing-drawdown-pct", type=float, help="覆盖风险档位：入场前回撤上限(%)")

        parser.add_argument("--min-score", type=float, help="附加过滤：最低低估分")
        parser.add_argument("--min-core-under", type=int, help="附加过滤：核心低估方法最少个数")
        parser.add_argument("--min-under-methods", type=int, help="附加过滤：低估方法最少个数")
        parser.add_argument("--min-composite-gap-pct", type=float, help="附加过滤：组合估值最小溢价(小数)")
        parser.add_argument("--min-conservative-gap-pct", type=float, help="附加过滤：保守估值最小溢价(小数)")

        parser.add_argument("--use-live-valuation", action="store_true", default=False, help="快照缺失时使用实时估值")
        parser.add_argument("--strict-express-match", action="store_true", default=False, help="实时估值时启用 express 严格匹配")
        parser.add_argument("--express-max-age-days", type=int, default=180, help="实时估值 express 最大账龄")
        parser.add_argument("--cache-batch-key", type=str, default="pick_runtime", help="实时估值缓存批次键")
        parser.add_argument("--refresh-cache", action="store_true", default=False, help="实时估值时强制忽略缓存")

    def handle(self, *_args, **options):
        freq = str(options.get("freq") or "D").strip().upper()
        trade_date = _resolve_trade_date(options.get("trade_date"), freq=freq)
        scope = _normalize_scope(options.get("scope"))
        band_pct = max(0.01, float(options.get("valuation_band_pct") or 0.1))

        code_offset = max(0, int(options.get("code_offset") or 0))
        code_limit = options.get("code_limit")
        if code_limit is not None:
            code_limit = max(1, int(code_limit))

        risk_profile = _resolve_risk_profile(options.get("risk_profile"))
        max_trailing_vol_pct = options.get("max_trailing_vol_pct")
        max_trailing_drawdown_pct = options.get("max_trailing_drawdown_pct")
        if max_trailing_vol_pct is None:
            max_trailing_vol_pct = risk_profile["max_trailing_vol_pct"]
        if max_trailing_drawdown_pct is None:
            max_trailing_drawdown_pct = risk_profile["max_trailing_drawdown_pct"]
        risk_lookback_days = max(2, int(options.get("risk_lookback_days") or 20))

        min_score = options.get("min_score")
        min_core_under = options.get("min_core_under")
        min_under_methods = options.get("min_under_methods")
        min_composite_gap_pct = options.get("min_composite_gap_pct")
        min_conservative_gap_pct = options.get("min_conservative_gap_pct")

        use_live_valuation = bool(options.get("use_live_valuation"))
        strict_express_match = bool(options.get("strict_express_match"))
        express_max_age_days = int(options.get("express_max_age_days") or 180)
        cache_batch_key = str(options.get("cache_batch_key") or "pick_runtime").strip() or "pick_runtime"
        refresh_cache = bool(options.get("refresh_cache"))

        trading_qs = StockTradingHistory.objects.filter(trade_date=trade_date, freq=freq)
        trading_qs = _resolve_scope_filter(trading_qs, scope)
        rows = list(
            trading_qs.values("ts_code", "close_qfq", "close").order_by("ts_code")
        )
        if not rows:
            raise CommandError("指定日期和范围内没有可选股票")

        ts_codes = [row["ts_code"] for row in rows]
        if code_offset:
            ts_codes = ts_codes[code_offset:]
        if code_limit is not None:
            ts_codes = ts_codes[:code_limit]
        if not ts_codes:
            raise CommandError("采样后没有股票可选")

        price_map = {
            row["ts_code"]: (_safe_price(row.get("close_qfq")) or _safe_price(row.get("close")))
            for row in rows
            if row["ts_code"] in ts_codes
        }

        method_map_by_code = _build_snapshot_method_map(ts_codes=ts_codes, trade_date=trade_date, market="CN")
        pro = get_tushare_pro() if use_live_valuation else None

        if use_live_valuation:
            cached_live_map = {}
            if not refresh_cache:
                cached_live_map = _load_backtest_cache_map(
                    ts_codes=ts_codes,
                    trade_date=trade_date,
                    batch_key=cache_batch_key,
                    market="CN",
                )
            for ts_code in ts_codes:
                existing = method_map_by_code.get(ts_code) or {}
                if existing:
                    continue

                cached_payload = cached_live_map.get(ts_code, {})
                if cached_payload:
                    method_map_by_code[ts_code] = cached_payload
                    continue

                try:
                    live_payload = _extract_live_method_map(
                        ts_code=ts_code,
                        trade_date=trade_date,
                        pro=pro,
                        strict_express_match=strict_express_match,
                        express_max_age_days=express_max_age_days,
                    )
                    method_map_by_code[ts_code] = live_payload
                    _save_backtest_cache_map(
                        ts_code=ts_code,
                        trade_date=trade_date,
                        method_map=live_payload,
                        batch_key=cache_batch_key,
                        market="CN",
                    )
                except Exception as exc:
                    self.stderr.write(f"[warn] live valuation failed {ts_code}: {exc}")
                    method_map_by_code[ts_code] = {}
                    _save_backtest_cache_map(
                        ts_code=ts_code,
                        trade_date=trade_date,
                        method_map={},
                        batch_key=cache_batch_key,
                        market="CN",
                    )

        price_history = _build_price_history(ts_codes, trade_date, lookback_days=risk_lookback_days, freq=freq)

        candidates = []
        for ts_code in ts_codes:
            current_price = price_map.get(ts_code)
            if current_price is None:
                continue

            summary = _summarize_buy_candidate(
                current_price=current_price,
                method_map=method_map_by_code.get(ts_code, {}),
                band_pct=band_pct,
            )
            if not summary.get("buy_candidate"):
                continue

            under_methods = summary.get("valuation_under_methods") or []
            core_methods = summary.get("valuation_core_methods") or []
            core_under_count = len([m for m in core_methods if m in under_methods])
            under_method_count = len(under_methods)

            composite_price = _safe_price(summary.get("composite_valuation_price"))
            conservative_price = _safe_price(summary.get("conservative_valuation_price"))
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

            if min_score is not None and (summary.get("undervalue_score") is None or float(summary.get("undervalue_score")) < float(min_score)):
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

            trailing_vol_pct, trailing_drawdown_pct = _calc_trailing_risk_metrics(
                price_series=price_history.get(ts_code, []),
                entry_date=trade_date,
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

            candidates.append(
                {
                    "trade_date": trade_date,
                    "ts_code": ts_code,
                    "current_price": round(current_price, 4),
                    "undervalue_score": summary.get("undervalue_score"),
                    "composite_valuation_price": summary.get("composite_valuation_price"),
                    "conservative_valuation_price": summary.get("conservative_valuation_price"),
                    "composite_gap_pct": round(composite_gap_pct * 100.0, 4) if composite_gap_pct is not None else None,
                    "conservative_gap_pct": round(conservative_gap_pct * 100.0, 4) if conservative_gap_pct is not None else None,
                    "core_under_count": core_under_count,
                    "under_method_count": under_method_count,
                    "trailing_vol_pct": round(trailing_vol_pct, 4) if trailing_vol_pct is not None else None,
                    "trailing_drawdown_pct": round(trailing_drawdown_pct, 4) if trailing_drawdown_pct is not None else None,
                    "valuation_valid_methods": ",".join(summary.get("valuation_valid_methods") or []),
                    "valuation_under_methods": ",".join(summary.get("valuation_under_methods") or []),
                    "buy_candidate_rule_version": summary.get("buy_candidate_rule_version"),
                    "buy_candidate_reason": summary.get("buy_candidate_reason"),
                }
            )

        result_df = pd.DataFrame(candidates)
        self.stdout.write(
            self.style.SUCCESS(
                f"pick complete: trade_date={trade_date} scope={scope} universe={len(ts_codes)} candidates={len(result_df)} risk_profile={options.get('risk_profile')}"
            )
        )

        if result_df.empty:
            self.stdout.write("No buy candidates found.")
            return

        result_df = result_df.sort_values(
            by=["undervalue_score", "composite_gap_pct", "conservative_gap_pct"],
            ascending=[False, False, False],
        )

        top_n = max(1, int(options.get("top") or 30))
        preview_cols = [
            "ts_code",
            "current_price",
            "undervalue_score",
            "composite_valuation_price",
            "conservative_valuation_price",
            "composite_gap_pct",
            "conservative_gap_pct",
            "trailing_vol_pct",
            "trailing_drawdown_pct",
            "buy_candidate_rule_version",
        ]
        self.stdout.write("top_candidates=")
        self.stdout.write(result_df[preview_cols].head(top_n).to_string(index=False))

        output_csv = options.get("output_csv")
        if output_csv:
            result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
            self.stdout.write(self.style.SUCCESS(f"saved candidates to {output_csv}"))
