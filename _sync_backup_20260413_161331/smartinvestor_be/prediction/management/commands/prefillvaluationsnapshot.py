import time
import math
from functools import lru_cache
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models import Max
from django.utils import timezone
from django.conf import settings

from datastore.models import Corporation, StockTradingHistory
from valuation.models import (
    StockValuationSnapshot,
    StockValuationSnapshotHistory,
    StockValuationSnapshotLatest,
)
from prediction.services.scarcity_auto_engine import ScarcityAutoEngine
from prediction.utils.valuation_util import get_stock_valuation_snapshot, test_valuation_light
from prediction.services.business_industry_matcher import BusinessIndustryMatcher
from prediction.services.validation_loader import ValuationConfig
from users.models import UserWatchlist


METHOD_ALIAS_MAP = {
    "pe": {"pe"},
    "ps": {"ps"},
    "pb": {"pb"},
    "sw_history": {"sw_history", "sw_hist", "industry_history"},
    "peg": {"peg"},
    "fcff_dcf": {"fcff_dcf", "fcff"},
    "ddm": {"ddm"},
    "ev_ebitda": {"ev_ebitda"},
    "market_cap": {"market_cap"},
}


REPORT_TYPE_END_SUFFIX = {
    "Q1": "0331",
    "H1": "0630",
    "Q3": "0930",
    "ANNUAL": "1231",
}


def _normalize_method_name(method_name):
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


def _resolve_method_candidates(method_name):
    normalized = _normalize_method_name(method_name)
    return normalized, METHOD_ALIAS_MAP.get(normalized, {normalized})


def _normalize_valuation_variant(value, fallback="default"):
    if value is None:
        return fallback
    try:
        if math.isnan(float(value)):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return fallback
    return text


def _extract_implied_prices(valuation_df, methods):
    outputs = {m: [] for m in methods}
    if valuation_df is None or valuation_df.empty:
        return outputs

    def _build_valuation_variant(row):
        explicit_variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="")
        if explicit_variant:
            return explicit_variant[:128]

        compare_group = str(row.get("compare_group") or "").strip()
        industry_level = str(row.get("industry_level") or row.get("level") or "").strip()
        industry_code = str(row.get("industry_code") or "").strip()
        industry_name = str(row.get("industry_name") or "").strip()

        parts = [part for part in [compare_group, industry_level, industry_code, industry_name] if part]
        if not parts:
            return "default"
        return "|".join(parts)[:128]

    normalized_rows = []
    for _, row in valuation_df.iterrows():
        row_method = _normalize_method_name(row.get("method"))
        implied_price = row.get("implied_price")
        equity_value = row.get("equity_value")
        match_score = row.get("match_score")
        if match_score is not None and isinstance(match_score, float) and math.isnan(match_score):
            match_score = None

        normalized_rows.append(
            {
                "row_method": row_method,
                "method": row.get("method"),
                "implied_price": implied_price,
                "equity_value": equity_value,
                "valuation_variant": _build_valuation_variant(row),
                "industry_level": row.get("industry_level") or row.get("level"),
                "industry_code": row.get("industry_code"),
                "industry_name": row.get("industry_name"),
                "compare_group": row.get("compare_group"),
                "match_score": match_score,
            }
        )

    for target_method in methods:
        _normalized, candidates = _resolve_method_candidates(target_method)
        method_rows = []
        for row in normalized_rows:
            if row["row_method"] not in candidates:
                continue
            implied_price = row.get("implied_price")
            if implied_price is None:
                continue
            try:
                implied_price_float = float(implied_price)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(implied_price_float):
                continue

            equity_value_float = None
            equity_value = row.get("equity_value")
            if equity_value is not None:
                try:
                    candidate_equity_value = float(equity_value)
                    if math.isfinite(candidate_equity_value):
                        equity_value_float = candidate_equity_value
                except (TypeError, ValueError):
                    equity_value_float = None

            method_rows.append(
                {
                    "method": row.get("method"),
                    "implied_price": implied_price_float,
                    "equity_value": equity_value_float,
                    "valuation_variant": row.get("valuation_variant"),
                    "industry_level": row.get("industry_level"),
                    "industry_code": row.get("industry_code"),
                    "industry_name": row.get("industry_name"),
                    "compare_group": row.get("compare_group"),
                    "match_score": row.get("match_score"),
                }
            )

        outputs[target_method] = method_rows

    return outputs


def _build_context_variant(compare_group=None, industry_level=None, industry_code=None, industry_name=None):
    parts = [
        str(compare_group or "").strip(),
        str(industry_level or "").strip(),
        str(industry_code or "").strip(),
        str(industry_name or "").strip(),
    ]
    parts = [part for part in parts if part]
    if not parts:
        return "default"
    return "|".join(parts)[:128]


@lru_cache(maxsize=8)
def _get_business_match_resources(market="CN"):
    base_dir = Path(settings.BASE_DIR) / "static"
    cfg = ValuationConfig(base_dir, market=market)
    matcher = BusinessIndustryMatcher(base_dir, market=market)
    return cfg, matcher


def _load_business_match_contexts(ts_code, market="CN", top_n=0):
    cfg, matcher = _get_business_match_resources(market=market)

    contexts = []
    touched_tushare_endpoints = set()

    try:
        sw_info = cfg.get_sw_params_by_tscode(ts_code)
        hierarchy = sw_info.get("hierarchy", {})
        contexts.append(
            {
                "compare_group": "sw_l3_baseline",
                "industry_level": sw_info.get("level"),
                "industry_code": sw_info.get("industry_code") or hierarchy.get("l3_code"),
                "industry_name": sw_info.get("industry_name") or hierarchy.get("l3_name"),
                "match_score": None,
                "params": sw_info.get("params", {}),
            }
        )
    except Exception:
        pass

    if top_n > 0:
        try:
            matched_payload = matcher.match_by_tscode(ts_code, top_n=top_n, level="L2")
            profile_source = str(((matched_payload or {}).get("profile") or {}).get("source") or "").strip().lower()
            citic_source = str(((matched_payload or {}).get("citic_profile") or {}).get("source") or "").strip().lower()
            if citic_source == "tushare_ci_index_member":
                touched_tushare_endpoints.add("ci_index_member")
            if profile_source == "tushare_stock_company":
                touched_tushare_endpoints.add("stock_company")

            for match in (matched_payload or {}).get("matches", []):
                try:
                    sw_info = cfg.get_sw_params_by_industry(
                        industry=match.get("industry_code"),
                        level=match.get("level"),
                        fuzzy=False,
                    )
                except Exception:
                    continue

                contexts.append(
                    {
                        "compare_group": "business_match",
                        "industry_level": match.get("level") or sw_info.get("level"),
                        "industry_code": match.get("industry_code") or sw_info.get("industry_code"),
                        "industry_name": match.get("industry_name") or sw_info.get("industry_name"),
                        "match_score": match.get("score"),
                        "params": sw_info.get("params", {}),
                    }
                )
        except Exception:
            pass

    deduped = []
    seen_variants = set()
    for context in contexts:
        variant = _build_context_variant(
            compare_group=context.get("compare_group"),
            industry_level=context.get("industry_level"),
            industry_code=context.get("industry_code"),
            industry_name=context.get("industry_name"),
        )
        if variant in seen_variants:
            continue
        seen_variants.add(variant)
        context["valuation_variant"] = variant
        deduped.append(context)

    if deduped and touched_tushare_endpoints:
        deduped[0]["__business_match_tushare_endpoints__"] = sorted(touched_tushare_endpoints)

    return deduped


def _to_decimal_or_none(value, digits):
    if value is None:
        return None
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value_float):
        return None
    return Decimal(str(round(value_float, digits)))


def _parse_date_like(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).replace("-", "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_snapshot_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _emit_fetch_trace(command, ts_code, snapshot):
    trace = (snapshot or {}).get("data_fetch_trace") or {}
    if not trace:
        return

    local_error = trace.get("local_fetch_error")
    endpoints = ",".join(trace.get("tushare_endpoints") or [])

    if local_error:
        command.stdout.write(
            command.style.WARNING(
                f"[{ts_code}] 本地财报读取异常: {local_error}"
            )
        )

    if trace.get("used_tushare_fallback"):
        command.stdout.write(
            command.style.WARNING(
                f"[{ts_code}] 已回退远程TuShare接口: {endpoints or 'unknown'}"
            )
        )


def _resolve_report_type(report_end_date):
    if report_end_date is None:
        return None
    md = report_end_date.strftime("%m%d")
    if md == "0331":
        return "Q1"
    if md == "0630":
        return "H1"
    if md == "0930":
        return "Q3"
    if md == "1231":
        return "ANNUAL"
    return "OTHER"


def _build_profit_trace_fields(snapshot):
    source = snapshot.get("profit_data_source")
    express_end_dt = _parse_snapshot_date(snapshot.get("express_end_date"))
    express_ann_dt = _parse_snapshot_date(snapshot.get("express_ann_date"))
    base_end_dt = _parse_snapshot_date(snapshot.get("end_date"))
    frames = (snapshot or {}).get("raw_frames") or {}
    base_ann_candidates = []
    for frame_name in ["income", "fina_indicator", "balancesheet", "cashflow", "dividend"]:
        frame = frames.get(frame_name)
        ann = _max_frame_date(frame, ["ann_date"])
        if ann is not None:
            base_ann_candidates.append(ann)
    base_ann_dt = max(base_ann_candidates) if base_ann_candidates else None

    effective_end_dt = base_end_dt
    if source and str(source).startswith("express_vip") and express_end_dt is not None:
        effective_end_dt = express_end_dt

    effective_ann_dt = base_ann_dt
    if source and str(source).startswith("express_vip") and express_ann_dt is not None:
        effective_ann_dt = express_ann_dt

    return {
        "profit_data_source": source,
        "profit_report_end_date": effective_end_dt,
        "profit_report_ann_date": effective_ann_dt,
        "profit_report_type": _resolve_report_type(effective_end_dt),
        "express_end_date": express_end_dt,
        "express_ann_date": express_ann_dt,
        "express_apply_reason": snapshot.get("express_apply_reason"),
        "express_block_reason": snapshot.get("express_block_reason"),
        "strict_express_match": snapshot.get("strict_express_match"),
        "express_max_age_days": snapshot.get("express_max_age_days"),
    }


def _normalize_optional_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_forced_report_end_date(target_report_type, target_fiscal_year):
    report_type = (target_report_type or "AUTO").strip().upper()
    if report_type == "FY":
        report_type = "ANNUAL"
    if report_type == "AUTO":
        return None
    if report_type not in REPORT_TYPE_END_SUFFIX:
        raise CommandError(f"不支持的 --target-report-type: {target_report_type}")
    if target_fiscal_year is None:
        raise CommandError("指定 --target-report-type 时必须同时提供 --target-fiscal-year")
    year = int(target_fiscal_year)
    if year < 2000 or year > 2100:
        raise CommandError("--target-fiscal-year 必须在 2000-2100 范围内")
    return f"{year:04d}{REPORT_TYPE_END_SUFFIX[report_type]}"


def _build_snapshot_defaults(method_output, source_label, corporation, trace_fields):
    return {
        "valuation_price": _to_decimal_or_none(method_output.get("implied_price"), 6),
        "valuation_market_cap": _to_decimal_or_none(method_output.get("equity_value"), 2),
        "source": source_label,
        "corporation": corporation,
        "industry_level": _normalize_optional_text(method_output.get("industry_level")),
        "industry_code": _normalize_optional_text(method_output.get("industry_code")),
        "industry_name": _normalize_optional_text(method_output.get("industry_name")),
        "compare_group": _normalize_optional_text(method_output.get("compare_group")),
        "match_score": _to_decimal_or_none(method_output.get("match_score"), 4),
        **trace_fields,
    }


def _bulk_upsert_valuation_rows(snapshot_rows, latest_rows):
    if not snapshot_rows and not latest_rows:
        return

    with transaction.atomic():
        if snapshot_rows:
            key_set = {
                (
                    row.ts_code,
                    row.trade_date,
                    row.market,
                    row.valuation_method,
                    row.valuation_variant,
                )
                for row in snapshot_rows
            }

            if key_set:
                exact_q = Q()
                for ts_code, trade_date, market, method, variant in key_set:
                    exact_q |= Q(
                        ts_code=ts_code,
                        trade_date=trade_date,
                        market=market,
                        valuation_method=method,
                        valuation_variant=variant,
                    )

                existing_qs = StockValuationSnapshot.objects.filter(exact_q)

                history_rows = []
                for old in existing_qs:
                    history_rows.append(
                        StockValuationSnapshotHistory(
                            archive_reason="upsert_replace",
                            source_snapshot_id=old.id,
                            snapshot_created_at=old.created_at,
                            snapshot_updated_at=old.updated_at,
                            corporation=old.corporation,
                            ts_code=old.ts_code,
                            trade_date=old.trade_date,
                            market=old.market,
                            valuation_method=old.valuation_method,
                            valuation_variant=old.valuation_variant,
                            valuation_price=old.valuation_price,
                            valuation_market_cap=old.valuation_market_cap,
                            source=old.source,
                            industry_level=old.industry_level,
                            industry_code=old.industry_code,
                            industry_name=old.industry_name,
                            compare_group=old.compare_group,
                            match_score=old.match_score,
                            profit_data_source=old.profit_data_source,
                            profit_report_end_date=old.profit_report_end_date,
                            profit_report_ann_date=old.profit_report_ann_date,
                            profit_report_type=old.profit_report_type,
                            express_end_date=old.express_end_date,
                            express_ann_date=old.express_ann_date,
                            express_apply_reason=old.express_apply_reason,
                            express_block_reason=old.express_block_reason,
                            strict_express_match=old.strict_express_match,
                            express_max_age_days=old.express_max_age_days,
                        )
                    )

                if history_rows:
                    StockValuationSnapshotHistory.objects.bulk_create(history_rows, batch_size=1000)

            StockValuationSnapshot.objects.bulk_create(
                snapshot_rows,
                update_conflicts=True,
                update_fields=[
                    "updated_at",
                    "valuation_price",
                    "valuation_market_cap",
                    "source",
                    "corporation",
                    "industry_level",
                    "industry_code",
                    "industry_name",
                    "compare_group",
                    "match_score",
                    "profit_data_source",
                    "profit_report_end_date",
                    "profit_report_ann_date",
                    "profit_report_type",
                    "express_end_date",
                    "express_ann_date",
                    "express_apply_reason",
                    "express_block_reason",
                    "strict_express_match",
                    "express_max_age_days",
                ],
                unique_fields=["ts_code", "trade_date", "market", "valuation_method", "valuation_variant"],
            )

        if latest_rows:
            StockValuationSnapshotLatest.objects.bulk_create(
                latest_rows,
                update_conflicts=True,
                update_fields=[
                    "updated_at",
                    "latest_trade_date",
                    "valuation_price",
                    "valuation_market_cap",
                    "source",
                    "corporation",
                    "industry_level",
                    "industry_code",
                    "industry_name",
                    "compare_group",
                    "match_score",
                    "profit_data_source",
                    "profit_report_end_date",
                    "profit_report_ann_date",
                    "profit_report_type",
                    "express_end_date",
                    "express_ann_date",
                    "express_apply_reason",
                    "express_block_reason",
                    "strict_express_match",
                    "express_max_age_days",
                ],
                unique_fields=["ts_code", "market", "valuation_method", "valuation_variant"],
            )


def _max_frame_date(frame, candidate_columns, upper_bound=None):
    if frame is None or getattr(frame, "empty", True):
        return None

    dates = []
    for column in candidate_columns:
        if column not in frame.columns:
            continue
        for value in frame[column].tolist():
            parsed = _parse_date_like(value)
            if parsed is None:
                continue
            if upper_bound is not None and parsed > upper_bound:
                continue
            dates.append(parsed)

    return max(dates) if dates else None


def _resolve_first_trade_on_or_after(ts_code, freq, start_date, upper_bound=None):
    if start_date is None:
        return None

    qs = StockTradingHistory.objects.filter(
        ts_code=ts_code,
        freq=freq,
        trade_date__gte=start_date,
    )
    if upper_bound is not None:
        qs = qs.filter(trade_date__lte=upper_bound)

    row = qs.order_by("trade_date").values("trade_date").first()
    if row:
        return row.get("trade_date")

    if upper_bound is None:
        return None

    fallback = (
        StockTradingHistory.objects.filter(
            ts_code=ts_code,
            freq=freq,
            trade_date__lte=upper_bound,
        )
        .order_by("-trade_date")
        .values("trade_date")
        .first()
    )
    if fallback:
        return fallback.get("trade_date")
    return None


def _resolve_latest_disclosure_signal(snapshot, trade_date=None):
    frames = (snapshot or {}).get("raw_frames") or {}
    cutoff = _parse_date_like((snapshot or {}).get("trade_date") or trade_date)

    candidates = []
    for frame_name in ["fina_indicator", "income", "balancesheet", "cashflow", "dividend", "express_vip"]:
        frame = frames.get(frame_name)
        latest_ann = _max_frame_date(frame, ["ann_date"], upper_bound=cutoff)
        latest_end = _max_frame_date(frame, ["end_date"], upper_bound=cutoff)
        if latest_ann is not None:
            candidates.append((latest_ann, f"{frame_name}_ann_date"))
        elif latest_end is not None:
            candidates.append((latest_end, f"{frame_name}_end_date"))

    snapshot_end = _parse_date_like((snapshot or {}).get("end_date"))
    snapshot_express_ann = _parse_date_like((snapshot or {}).get("express_ann_date"))
    if snapshot_end is not None:
        candidates.append((snapshot_end, "snapshot_end_date"))
    if snapshot_express_ann is not None:
        candidates.append((snapshot_express_ann, "snapshot_express_ann_date"))

    if not candidates:
        return None, "no_disclosure_signal"

    latest_date = max(item[0] for item in candidates)
    tied_reasons = [item[1] for item in candidates if item[0] == latest_date]
    priority = [
        "snapshot_express_ann_date",
        "express_vip_ann_date",
        "income_ann_date",
        "fina_indicator_ann_date",
        "balancesheet_ann_date",
        "cashflow_ann_date",
        "dividend_ann_date",
        "snapshot_end_date",
        "income_end_date",
        "fina_indicator_end_date",
        "balancesheet_end_date",
        "cashflow_end_date",
        "dividend_end_date",
        "express_vip_end_date",
    ]
    for reason in priority:
        if reason in tied_reasons:
            return latest_date, reason

    return latest_date, tied_reasons[0]


class Command(BaseCommand):
    help = "预热股票估值快照：批量计算并写入 StockValuationSnapshot"

    def _prepare_output_encoding(self):
        for stream in [self.stdout, self.stderr]:
            raw_stream = getattr(stream, "_out", None)
            if raw_stream is not None and hasattr(raw_stream, "reconfigure"):
                raw_stream.reconfigure(encoding="utf-8")

    def add_arguments(self, parser):
        parser.add_argument("--trade-date", type=str, help="交易日，格式 YYYY-MM-DD")
        parser.add_argument("--freq", type=str, default="D", help="频率，用于选取样本，默认 D")
        parser.add_argument(
            "--codes-file",
            type=str,
            help="候选股票代码文件，每行一个 ts_code；若提供则与 scope 结果取交集",
        )
        parser.add_argument(
            "--scope",
            type=str,
            default="ALL",
            help="范围：ALL / WATCHLIST / 前缀(如 60 或 60,0,3,688)",
        )
        parser.add_argument(
            "--methods",
            type=str,
            default="sw_history,pe,pb,ps,peg,fcff_dcf,ddm",
            help="逗号分隔估值法列表",
        )
        parser.add_argument("--offset", type=int, default=0, help="起始偏移")
        parser.add_argument("--limit", type=int, help="最多处理数量")
        parser.add_argument("--market", type=str, default="CN", help="市场代码，默认 CN")
        parser.add_argument(
            "--request-interval",
            type=float,
            default=0.0,
            help="每只股票请求间隔秒数，用于限速",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            default=False,
            help="强制刷新，忽略已存在快照",
        )
        parser.add_argument(
            "--refresh-policy",
            type=str,
            default="missing",
            choices=["missing", "all", "disclosure"],
            help="刷新策略：missing=仅补缺失；all=全部重算；disclosure=仅重算披露日期晚于现有快照更新时间的股票",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="仅计算统计，不写入数据库",
        )
        parser.add_argument(
            "--no-strict-express-match",
            action="store_true",
            default=False,
            help="关闭 express_vip 严格匹配规则（公告可见性/报告期一致性/时效窗口）",
        )
        parser.add_argument(
            "--express-max-age-days",
            type=int,
            default=180,
            help="严格匹配下，快报公告距估值日最大允许天数",
        )
        parser.add_argument(
            "--business-match-topn",
            type=int,
            default=int(getattr(settings, "LIVE_VALUATION_BUSINESS_MATCH_TOPN", 3) or 3),
            help="按业务匹配追加估值行业候选数量（0 表示关闭）",
        )
        parser.add_argument(
            "--target-report-type",
            type=str,
            default="AUTO",
            choices=["AUTO", "Q1", "H1", "Q3", "ANNUAL", "FY"],
            help="指定估值利润口径报告类型，默认 AUTO（按最新可见财报）",
        )
        parser.add_argument(
            "--target-fiscal-year",
            type=int,
            help="指定估值利润口径财年（如 2024）；与 --target-report-type 搭配使用",
        )

    def _resolve_trade_date(self, trade_date, freq):
        if trade_date:
            return trade_date
        latest = (
            StockTradingHistory.objects.filter(freq=freq)
            .aggregate(latest_date=Max("trade_date"))
            .get("latest_date")
        )
        if latest is None:
            raise CommandError("未找到交易数据，无法推断 trade-date")
        return latest.strftime("%Y-%m-%d")

    def _collect_codes(self, trade_date, freq, scope):
        scope = (scope or "ALL").strip().upper()
        if scope == "WATCHLIST":
            return list(
                UserWatchlist.objects.filter(is_enabled=True)
                .values_list("ts_code", flat=True)
                .order_by("ts_code")
            )

        qs = StockTradingHistory.objects.filter(
            trade_date=trade_date,
            freq=freq,
        ).values_list("ts_code", flat=True).distinct().order_by("ts_code")

        if scope == "ALL":
            return list(qs)

        prefixes = [item.strip() for item in scope.split(",") if item.strip()]
        if not prefixes:
            return list(qs)

        selected = []
        for code in qs:
            if any(str(code).startswith(prefix) for prefix in prefixes):
                selected.append(code)
        return selected

    def _collect_codes_from_candidates(self, trade_date, freq, scope, candidate_codes):
        valid_codes = list(
            StockTradingHistory.objects.filter(
                trade_date=trade_date,
                freq=freq,
                ts_code__in=list(candidate_codes),
            )
            .values_list("ts_code", flat=True)
            .distinct()
            .order_by("ts_code")
        )

        scope = (scope or "ALL").strip().upper()
        if scope == "ALL":
            return valid_codes

        if scope == "WATCHLIST":
            watch_codes = set(
                UserWatchlist.objects.filter(is_enabled=True).values_list("ts_code", flat=True)
            )
            return [code for code in valid_codes if code in watch_codes]

        prefixes = [item.strip() for item in scope.split(",") if item.strip()]
        if not prefixes:
            return valid_codes

        return [code for code in valid_codes if any(str(code).startswith(prefix) for prefix in prefixes)]

    def handle(self, *_args, **options):
        self._prepare_output_encoding()

        freq = str(options.get("freq", "D")).strip().upper()
        trade_date = self._resolve_trade_date(options.get("trade_date"), freq)
        market = str(options.get("market", "CN")).strip().upper()
        dry_run = bool(options.get("dry_run", False))
        refresh = bool(options.get("refresh", False))
        refresh_policy = str(options.get("refresh_policy", "missing") or "missing").strip().lower()
        if refresh:
            if refresh_policy not in ("missing", "all"):
                raise CommandError("--refresh 与 --refresh-policy=disclosure 不能同时使用")
            refresh_policy = "all"
        offset = max(0, int(options.get("offset", 0) or 0))
        limit = options.get("limit")
        interval = max(0.0, float(options.get("request_interval", 0.0) or 0.0))
        strict_express_match = not bool(options.get("no_strict_express_match", False))
        express_max_age_days = int(options.get("express_max_age_days", 180) or 180)
        business_match_topn = max(0, int(options.get("business_match_topn", 0) or 0))
        forced_report_end_date = _resolve_forced_report_end_date(
            options.get("target_report_type"),
            options.get("target_fiscal_year"),
        )

        methods = [
            _normalize_method_name(item)
            for item in str(options.get("methods", "")).split(",")
            if item.strip()
        ]
        methods = [m for m in methods if m]
        if not methods:
            raise CommandError("至少需要一个估值方法 --methods")

        needs_tushare_throttle = ("sw_history" in methods) or business_match_topn > 0
        prefill_min_interval = max(
            0.0,
            float(getattr(settings, "PREFILL_TUSHARE_MIN_INTERVAL_SECONDS", 0.35) or 0.35),
        )
        context_interval = max(
            0.0,
            float(getattr(settings, "PREFILL_TUSHARE_CONTEXT_INTERVAL_SECONDS", 0.12) or 0.12),
        )
        if needs_tushare_throttle and interval < prefill_min_interval:
            interval = prefill_min_interval

        codes_file = options.get("codes_file")
        if codes_file:
            codes_path = Path(codes_file)
            if not codes_path.is_absolute():
                codes_path = Path(settings.BASE_DIR) / codes_path
            if not codes_path.exists():
                raise CommandError(f"候选代码文件不存在: {codes_path}")
            allowed_codes = {
                line.strip()
                for line in codes_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            all_codes = self._collect_codes_from_candidates(
                trade_date=trade_date,
                freq=freq,
                scope=options.get("scope"),
                candidate_codes=allowed_codes,
            )
        else:
            all_codes = self._collect_codes(trade_date=trade_date, freq=freq, scope=options.get("scope"))
        sliced_codes = all_codes[offset: offset + limit if limit else None]
        if not sliced_codes:
            self.stdout.write(
                self.style.WARNING(
                    f"没有待处理股票，跳过本次预热 trade_date={trade_date} freq={freq} scope={options.get('scope')}"
                )
            )
            return

        corp_map = {
            corp.ts_code: corp
            for corp in Corporation.objects.filter(ts_code__in=sliced_codes).only("id", "ts_code")
        }

        counters = {
            "selected": len(sliced_codes),
            "processed": 0,
            "evaluated": 0,
            "written": 0,
            "would_write": 0,
            "skipped_existing": 0,
            "market_cap_backfill_targets": 0,
            "skipped_unchanged": 0,
            "disclosure_refreshed": 0,
            "skipped_no_price": 0,
            "errors": 0,
            "aligned_trade_date": 0,
        }
        disclosure_reason_counts = {}

        self.stdout.write(self.style.SUCCESS("开始预热估值快照"))
        self.stdout.write(f"trade_date: {trade_date} | freq: {freq} | scope: {options.get('scope')} | dry_run: {dry_run}")
        self.stdout.write(f"methods: {','.join(methods)}")
        self.stdout.write(f"refresh_policy: {refresh_policy}")
        self.stdout.write(
            f"strict_express_match: {strict_express_match} | express_max_age_days: {express_max_age_days}"
        )
        self.stdout.write(f"business_match_topn: {business_match_topn}")
        self.stdout.write(f"forced_report_end_date: {forced_report_end_date or 'AUTO'}")
        if needs_tushare_throttle:
            self.stdout.write(
                self.style.WARNING(
                    f"检测到TuShare密集接口（sw_history/business_match），已启用节流: request_interval={interval:.2f}s context_interval={context_interval:.2f}s"
                )
            )
        if "sw_history" in methods:
            sw_cache_file = Path(settings.BASE_DIR) / "static" / "valuation_cache" / f"sw_history_anchor_{market}.json"
            sw_local_cache_enabled = str(
                getattr(settings, "SW_HISTORY_USE_LOCAL_CACHE", "1")
            ).lower() in {"1", "true", "yes", "on"}
            sw_remote_fallback_enabled = str(
                getattr(settings, "SW_HISTORY_USE_REMOTE_FALLBACK", "1")
            ).lower() in {"1", "true", "yes", "on"}
            self.stdout.write(
                self.style.WARNING(
                    "methods包含sw_history：默认本地缓存优先（sw_history_anchor_*.json），仅缺失时才回退TuShare sw_daily"
                )
            )
            self.stdout.write(
                f"sw_history cache_status: enabled={sw_local_cache_enabled} exists={sw_cache_file.exists()} remote_fallback={sw_remote_fallback_enabled} file={sw_cache_file}"
            )
        if business_match_topn > 0:
            self.stdout.write(
                self.style.WARNING(
                    "business_match_topn>0：会调用TuShare接口 ci_index_member/stock_company 进行业务匹配扩展"
                )
            )

        for idx, ts_code in enumerate(sliced_codes, start=1):
            counters["processed"] += 1
            status = "pending"
            before_evaluated = counters["evaluated"]
            before_written = counters["written"]
            before_would_write = counters["would_write"]
            before_skipped_no_price = counters["skipped_no_price"]
            self.stdout.write(f"[{idx}/{len(sliced_codes)}] {ts_code} 开始处理")
            try:
                anchor_trade_date = trade_date
                anchor_trade_date_dt = _parse_date_like(anchor_trade_date)
                probe_snapshot = get_stock_valuation_snapshot(
                    ts_code=ts_code,
                    trade_date=anchor_trade_date,
                    strict_express_match=strict_express_match,
                    express_max_age_days=express_max_age_days,
                    forced_report_end_date=forced_report_end_date,
                )
                _emit_fetch_trace(self, ts_code, probe_snapshot)
                probe_trace_fields = _build_profit_trace_fields(probe_snapshot)
                aligned_trade_date_dt = _resolve_first_trade_on_or_after(
                    ts_code=ts_code,
                    freq=freq,
                    start_date=probe_trace_fields.get("profit_report_ann_date") or probe_trace_fields.get("express_ann_date"),
                    upper_bound=anchor_trade_date_dt,
                )
                aligned_trade_date = (
                    aligned_trade_date_dt.strftime("%Y-%m-%d")
                    if aligned_trade_date_dt is not None
                    else anchor_trade_date
                )
                if aligned_trade_date != anchor_trade_date:
                    counters["aligned_trade_date"] += 1

                existing_qs = StockValuationSnapshot.objects.filter(
                    ts_code=ts_code,
                    trade_date=aligned_trade_date,
                    market=market,
                    valuation_method__in=methods,
                )
                existing = set(existing_qs.values_list("valuation_method", flat=True))
                market_cap_null_methods = set(
                    existing_qs.filter(valuation_market_cap__isnull=True).values_list("valuation_method", flat=True)
                )
                missing_methods = [m for m in methods if m not in existing]
                methods_to_compute = [m for m in methods if (m in missing_methods or m in market_cap_null_methods)]
                source_label = "prefill_command"

                if refresh_policy == "all":
                    methods_to_compute = list(methods)
                    source_label = "prefill_refresh"
                elif forced_report_end_date:
                    # 强制报告期场景需要覆盖已有同键快照，不能因为 existing 而跳过
                    methods_to_compute = list(methods)
                    source_label = "prefill_forced_report"
                else:
                    counters["skipped_existing"] += len(methods) - len(methods_to_compute)
                    counters["market_cap_backfill_targets"] += len(market_cap_null_methods)
                    if market_cap_null_methods and not missing_methods:
                        source_label = "prefill_market_cap_backfill"

                if (
                    refresh_policy == "disclosure"
                    and not methods_to_compute
                    and not missing_methods
                    and len(existing) == len(methods)
                ):
                    latest_snapshot_update = existing_qs.aggregate(latest=Max("updated_at")).get("latest")
                    valuation_snapshot = get_stock_valuation_snapshot(
                        ts_code=ts_code,
                        trade_date=aligned_trade_date,
                        strict_express_match=strict_express_match,
                        express_max_age_days=express_max_age_days,
                    )
                    latest_disclosure_date, disclosure_reason = _resolve_latest_disclosure_signal(
                        valuation_snapshot,
                        trade_date=aligned_trade_date,
                    )
                    latest_snapshot_date = _parse_date_like(latest_snapshot_update)
                    should_refresh_disclosure = False
                    if latest_disclosure_date is not None:
                        if latest_snapshot_date is None:
                            should_refresh_disclosure = True
                        elif latest_disclosure_date > latest_snapshot_date:
                            should_refresh_disclosure = True

                    if should_refresh_disclosure:
                        methods_to_compute = list(methods)
                        source_label = "prefill_disclosure_refresh"
                        counters["disclosure_refreshed"] += 1
                        disclosure_reason_counts[disclosure_reason] = (
                            disclosure_reason_counts.get(disclosure_reason, 0) + 1
                        )
                    else:
                        counters["skipped_unchanged"] += 1
                        status = "skip_unchanged"
                        continue

                if not methods_to_compute:
                    status = "skip_no_work"
                    continue

                if "sw_history" in methods_to_compute:
                    self.stdout.write(f"[{ts_code}] sw_history估值: 本地缓存优先，缺失时回退TuShare sw_daily")

                if aligned_trade_date == anchor_trade_date:
                    stock_snapshot = probe_snapshot
                else:
                    stock_snapshot = get_stock_valuation_snapshot(
                        ts_code=ts_code,
                        trade_date=aligned_trade_date,
                        strict_express_match=strict_express_match,
                        express_max_age_days=express_max_age_days,
                        forced_report_end_date=forced_report_end_date,
                    )

                outputs = {m: [] for m in methods_to_compute}
                trace_fields = None

                contexts = _load_business_match_contexts(
                    ts_code=ts_code,
                    market=market,
                    top_n=business_match_topn,
                )
                touched_business_match_endpoints = []
                for _context_item in contexts:
                    for _endpoint in _context_item.get("__business_match_tushare_endpoints__", []) or []:
                        if _endpoint not in touched_business_match_endpoints:
                            touched_business_match_endpoints.append(_endpoint)
                    _context_item.pop("__business_match_tushare_endpoints__", None)

                if touched_business_match_endpoints:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[{ts_code}] business_match已访问TuShare接口: {','.join(touched_business_match_endpoints)}"
                        )
                    )

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

                for context_idx, context in enumerate(contexts):
                    if context_idx > 0 and needs_tushare_throttle and context_interval > 0:
                        time.sleep(context_interval)
                    valuation_params = dict(context.get("params") or {})
                    valuation_params, _scarcity_meta = ScarcityAutoEngine._apply_scarcity_profile(
                        valuation_params=valuation_params,
                        scarcity_profile="auto",
                        market=market,
                        tscode=ts_code,
                        trade_date=aligned_trade_date,
                    )
                    valuation_result = test_valuation_light(
                        ts_code=ts_code,
                        trade_date=aligned_trade_date,
                        strict_express_match=strict_express_match,
                        express_max_age_days=express_max_age_days,
                        snapshot=stock_snapshot,
                        **valuation_params,
                    )
                    valuation_df = valuation_result.get("valuations")
                    if trace_fields is None:
                        valuation_snapshot = valuation_result.get("snapshot") or {}
                        trace_fields = _build_profit_trace_fields(valuation_snapshot)

                    context_outputs = _extract_implied_prices(valuation_df, methods_to_compute)
                    for method in methods_to_compute:
                        for row in context_outputs.get(method, []):
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

                counters["evaluated"] += 1

                for method in methods_to_compute:
                    deduped_rows = []
                    seen_variants = set()
                    for row in outputs.get(method, []):
                        variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
                        if variant in seen_variants:
                            continue
                        seen_variants.add(variant)
                        deduped_rows.append(row)
                    outputs[method] = deduped_rows

                trace_fields = trace_fields or {}

                snapshot_rows = []
                latest_rows = []
                row_write_count = 0

                for method in methods_to_compute:
                    method_outputs = outputs.get(method) or []
                    if not method_outputs:
                        counters["skipped_no_price"] += 1
                        continue

                    for method_output in method_outputs:
                        if dry_run:
                            counters["would_write"] += 1
                            continue

                        normalized_variant = _normalize_valuation_variant(
                            method_output.get("valuation_variant"),
                            fallback="default",
                        )[:128]
                        snapshot_defaults = _build_snapshot_defaults(
                            method_output=method_output,
                            source_label=source_label,
                            corporation=corp_map.get(ts_code),
                            trace_fields=trace_fields,
                        )
                        timestamp = timezone.now()

                        snapshot_rows.append(
                            StockValuationSnapshot(
                                ts_code=ts_code,
                                trade_date=aligned_trade_date,
                                market=market,
                                valuation_method=method,
                                valuation_variant=normalized_variant,
                                created_at=timestamp,
                                updated_at=timestamp,
                                **snapshot_defaults,
                            )
                        )
                        latest_rows.append(
                            StockValuationSnapshotLatest(
                                ts_code=ts_code,
                                market=market,
                                valuation_method=method,
                                valuation_variant=normalized_variant,
                                latest_trade_date=aligned_trade_date,
                                created_at=timestamp,
                                updated_at=timestamp,
                                **snapshot_defaults,
                            )
                        )
                        row_write_count += 1

                if not dry_run:
                    _bulk_upsert_valuation_rows(snapshot_rows, latest_rows)
                    counters["written"] += row_write_count

                if interval > 0:
                    time.sleep(interval)
                status = "ok"

            except Exception as exc:
                counters["errors"] += 1
                status = f"error:{exc}"
                self.stderr.write(f"[{idx}/{len(sliced_codes)}] {ts_code} 处理失败: {exc}")
            finally:
                eval_delta = counters["evaluated"] - before_evaluated
                write_delta = counters["written"] - before_written
                dry_delta = counters["would_write"] - before_would_write
                no_price_delta = counters["skipped_no_price"] - before_skipped_no_price
                self.stdout.write(
                    f"[{idx}/{len(sliced_codes)}] {ts_code} 完成 status={status} evaluated+={eval_delta} written+={write_delta} dry+={dry_delta} no_price+={no_price_delta}"
                )

        self.stdout.write(self.style.SUCCESS("估值快照预热完成"))
        for key in [
            "selected",
            "processed",
            "evaluated",
            "written",
            "would_write",
            "skipped_existing",
            "market_cap_backfill_targets",
            "skipped_unchanged",
            "disclosure_refreshed",
            "skipped_no_price",
            "errors",
            "aligned_trade_date",
        ]:
            self.stdout.write(f"{key}: {counters[key]}")

        if refresh_policy == "disclosure":
            self.stdout.write("disclosure_refresh_reasons:")
            if not disclosure_reason_counts:
                self.stdout.write("- none")
            else:
                for reason, count in sorted(disclosure_reason_counts.items(), key=lambda item: (-item[1], item[0])):
                    self.stdout.write(f"- {reason}: {count}")
