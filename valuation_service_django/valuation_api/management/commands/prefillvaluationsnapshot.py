import math
import time
from functools import lru_cache
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from valuation_api.business_industry_matcher import BusinessIndustryMatcher
from valuation_api.live_valuation import get_local_valuation_snapshot, test_valuation_local_light
from valuation_api.models import StockExpressVip, StockTradingHistory, ValuationSnapshot, ValuationSnapshotLatest
from valuation_api.valuation_config import StandaloneValuationConfig


METHOD_ALIAS_MAP = {
    "sw_history": {"sw_history", "sw_hist", "industry_history"},
    "pe": {"pe"},
    "ps": {"ps"},
    "pb": {"pb"},
    "peg": {"peg"},
    "fcff_dcf": {"fcff_dcf", "fcff"},
    "ddm": {"ddm"},
    "ev_ebitda": {"ev_ebitda"},
    "market_cap": {"market_cap"},
    "weighted": {"weighted"},
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


def _parse_date_like(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _extract_method_rows(result, methods, persist_context):
    outputs = {method: [] for method in methods}
    valuations_df = result.get("valuations")
    if valuations_df is None or valuations_df.empty:
        return outputs

    rows = []
    for _, row in valuations_df.iterrows():
        method_name = _normalize_method_name(row.get("method"))
        implied_price = row.get("implied_price")
        if implied_price is None:
            continue
        try:
            implied_price_float = float(implied_price)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(implied_price_float):
            continue
        equity_value = row.get("equity_value")
        try:
            equity_value_float = float(equity_value) if equity_value is not None else None
        except (TypeError, ValueError):
            equity_value_float = None
        rows.append(
            {
                "method": method_name,
                "implied_price": implied_price_float,
                "equity_value": equity_value_float,
                "valuation_variant": _normalize_valuation_variant(
                    row.get("valuation_variant"),
                    fallback=(persist_context.get("valuation_variant") or "default"),
                ),
                "industry_level": persist_context.get("industry_level"),
                "industry_code": persist_context.get("industry_code"),
                "industry_name": persist_context.get("industry_name"),
                "compare_group": persist_context.get("compare_group"),
                "match_score": persist_context.get("match_score"),
            }
        )

    for target_method in methods:
        _, candidates = _resolve_method_candidates(target_method)
        outputs[target_method] = [row for row in rows if row["method"] in candidates]
    return outputs


def _infer_report_type(report_end_date):
    if not isinstance(report_end_date, date):
        return None
    if report_end_date.month == 3:
        return "Q1"
    if report_end_date.month == 6:
        return "H1"
    if report_end_date.month == 9:
        return "Q3"
    if report_end_date.month == 12:
        return "ANNUAL"
    return "OTHER"


def _build_profit_trace_fields(snapshot):
    report_end_date = _parse_date_like(snapshot.get("report_date"))
    return {
        "profit_data_source": snapshot.get("profit_data_source"),
        "profit_report_end_date": report_end_date,
        "profit_report_type": _infer_report_type(report_end_date),
        "express_end_date": _parse_date_like(snapshot.get("express_end_date")),
        "express_ann_date": _parse_date_like(snapshot.get("express_ann_date")),
        "express_apply_reason": snapshot.get("express_apply_reason"),
        "express_block_reason": snapshot.get("express_block_reason"),
        "strict_express_match": snapshot.get("strict_express_match"),
        "express_max_age_days": snapshot.get("express_max_age_days"),
    }


def _bulk_upsert_valuation_rows(snapshot_rows, latest_rows):
    if not snapshot_rows and not latest_rows:
        return
    with transaction.atomic():
        if snapshot_rows:
            ValuationSnapshot.objects.bulk_create(
                snapshot_rows,
                update_conflicts=True,
                update_fields=[
                    "updated_at",
                    "valuation_price",
                    "valuation_market_cap",
                    "source",
                    "industry_level",
                    "industry_code",
                    "industry_name",
                    "compare_group",
                    "match_score",
                    "profit_data_source",
                    "profit_report_end_date",
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
            ValuationSnapshotLatest.objects.bulk_create(
                latest_rows,
                update_conflicts=True,
                update_fields=[
                    "updated_at",
                    "latest_trade_date",
                    "valuation_price",
                    "valuation_market_cap",
                    "source",
                    "industry_level",
                    "industry_code",
                    "industry_name",
                    "compare_group",
                    "match_score",
                    "profit_data_source",
                    "profit_report_end_date",
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


def _load_business_match_contexts(ts_code, market="CN", top_n=0):
    if top_n <= 0:
        return []

    cfg, matcher = _get_business_match_resources(market=market)

    contexts = []


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
    except (ValueError, KeyError, TypeError, RuntimeError):
        pass

    try:
        matched_payload = matcher.match_by_tscode(ts_code=ts_code, top_n=top_n, level="L2")
        matches = (matched_payload or {}).get("matches", [])
        citic_mappings = (matched_payload or {}).get("citic_mappings", [])
        fallback_settings = matcher.get_fallback_settings_for_profile((matched_payload or {}).get("citic_profile"))
        should_fallback, _fallback_reason = matcher.should_fallback(matches, citic_mappings, fallback_settings)

        if (not matches) or should_fallback:
            fallback_match = matcher.choose_citic_fallback_match(matches, citic_mappings)
            if fallback_match is not None:
                sw_info = cfg.get_sw_params_by_industry(
                    industry=fallback_match.get("industry_code") or fallback_match.get("industry_name"),
                    level=fallback_match.get("level"),
                    fuzzy=False,
                )
                contexts.append(
                    {
                        "compare_group": "business_fallback",
                        "industry_level": fallback_match.get("level") or sw_info.get("level"),
                        "industry_code": fallback_match.get("industry_code") or sw_info.get("industry_code"),
                        "industry_name": fallback_match.get("industry_name") or sw_info.get("industry_name"),
                        "match_score": None,
                        "params": sw_info.get("params", {}),
                    }
                )
        else:
            for match in matches:
                try:
                    sw_info = cfg.get_sw_params_by_industry(
                        industry=match.get("industry_code"),
                        level=match.get("level"),
                        fuzzy=False,
                    )
                except (ValueError, KeyError, TypeError, RuntimeError):
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
    except (ValueError, KeyError, TypeError, RuntimeError):
        pass

    deduped = []
    seen = set()
    for context in contexts:
        variant = _build_context_variant(
            compare_group=context.get("compare_group"),
            industry_level=context.get("industry_level"),
            industry_code=context.get("industry_code"),
            industry_name=context.get("industry_name"),
        )
        if variant in seen:
            continue
        seen.add(variant)
        context["valuation_variant"] = variant
        deduped.append(context)
    return deduped


@lru_cache(maxsize=8)
def _get_business_match_resources(market="CN"):
    base_dir = Path(settings.BASE_DIR)
    cfg = StandaloneValuationConfig(base_dir=base_dir, market=market)
    matcher = BusinessIndustryMatcher(base_dir=base_dir, market=market)
    return cfg, matcher


class Command(BaseCommand):
    help = "预热估值快照：批量计算并写入 valuation_snapshot / valuation_snapshot_latest"

    def _prepare_output_encoding(self):
        for stream in [self.stdout, self.stderr]:
            raw_stream = getattr(stream, "_out", None)
            if raw_stream is not None and hasattr(raw_stream, "reconfigure"):
                raw_stream.reconfigure(encoding="utf-8")

    def add_arguments(self, parser):
        parser.add_argument("--trade-date", type=str, help="交易日，格式 YYYY-MM-DD")
        parser.add_argument("--freq", type=str, default="D", help="频率，默认 D")
        parser.add_argument("--scope", type=str, default="ALL", help="范围：ALL 或代码前缀列表，如 60,68,00,30,8")
        parser.add_argument("--methods", type=str, default="sw_history,pe,pb,ps,peg,fcff_dcf,ddm", help="逗号分隔估值法列表")
        parser.add_argument("--offset", type=int, default=0, help="起始偏移")
        parser.add_argument("--limit", type=int, help="最多处理数量")
        parser.add_argument("--market", type=str, default="CN", help="市场代码")
        parser.add_argument("--request-interval", type=float, default=0.0, help="每只股票之间的间隔秒数")
        parser.add_argument("--refresh", action="store_true", default=False, help="强制全部重算")
        parser.add_argument(
            "--refresh-policy",
            type=str,
            default="missing",
            choices=["missing", "all", "disclosure"],
            help="刷新策略：missing / all / disclosure",
        )
        parser.add_argument("--dry-run", action="store_true", default=False, help="仅统计，不写库")
        parser.add_argument("--no-strict-express-match", action="store_true", default=False)
        parser.add_argument("--express-max-age-days", type=int, default=180)
        parser.add_argument("--business-match-topn", type=int, default=0)
        parser.add_argument(
            "--progress-every",
            type=int,
            default=50,
            help="每处理 N 只股票输出一次阶段耗时统计（<=0 关闭）",
        )

    def _resolve_trade_date(self, trade_date, freq):
        if trade_date:
            return trade_date
        latest = StockTradingHistory.objects.filter(freq=freq).aggregate(latest_date=Max("trade_date")).get("latest_date")
        if latest is None:
            raise CommandError("未找到交易数据，无法推断 trade-date")
        return latest.strftime("%Y-%m-%d")

    def _collect_codes(self, trade_date, freq, scope):
        scope = str(scope or "ALL").strip().upper()
        qs = StockTradingHistory.objects.filter(trade_date=trade_date, freq=freq).values_list("ts_code", flat=True).distinct().order_by("ts_code")
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

    def _latest_disclosure_marker(self, ts_code, trade_date):
        target_date = _parse_date_like(trade_date)
        express_qs = StockExpressVip.objects.filter(ts_code=ts_code)
        if target_date is not None:
            express_qs = express_qs.filter(ann_date__lte=target_date)
        express_row = express_qs.order_by("-ann_date", "-end_date").only("ann_date").first()
        if express_row and express_row.ann_date:
            return express_row.ann_date, "express_vip_ann_date"

        funda_row = (
            StockTradingHistory.objects.filter(ts_code=ts_code, trade_date__lte=target_date, freq="D")
            .order_by("-trade_date")
            .only("trade_date")
            .first()
        )
        if funda_row and funda_row.trade_date:
            return funda_row.trade_date, "trading_trade_date"
        return None, None

    def handle(self, *_args, **options):
        self._prepare_output_encoding()

        freq = str(options.get("freq") or "D").strip().upper() or "D"
        trade_date = self._resolve_trade_date(options.get("trade_date"), freq)
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        dry_run = bool(options.get("dry_run"))
        refresh = bool(options.get("refresh"))
        refresh_policy = str(options.get("refresh_policy") or "missing").strip().lower()
        if refresh:
            if refresh_policy not in ("missing", "all"):
                raise CommandError("--refresh 与 --refresh-policy=disclosure 不能同时使用")
            refresh_policy = "all"
        offset = max(0, int(options.get("offset") or 0))
        limit = options.get("limit")
        interval = max(0.0, float(options.get("request_interval") or 0.0))
        strict_express_match = not bool(options.get("no_strict_express_match"))
        express_max_age_days = int(options.get("express_max_age_days") or 180)
        business_match_topn = max(0, int(options.get("business_match_topn") or 0))
        progress_every = int(options.get("progress_every", 50) or 0)

        methods = [_normalize_method_name(item) for item in str(options.get("methods") or "").split(",") if item.strip()]
        methods = [item for item in methods if item]
        if not methods:
            raise CommandError("至少需要一个估值方法 --methods")

        all_codes = self._collect_codes(trade_date=trade_date, freq=freq, scope=options.get("scope"))
        sliced_codes = all_codes[offset: offset + limit if limit else None]
        if not sliced_codes:
            raise CommandError("筛选后没有待处理股票")

        counters = {
            "selected": len(sliced_codes),
            "processed": 0,
            "evaluated": 0,
            "written": 0,
            "would_write": 0,
            "skipped_existing": 0,
            "skipped_unchanged": 0,
            "disclosure_refreshed": 0,
            "skipped_no_price": 0,
            "errors": 0,
        }
        disclosure_reason_counts = {}
        timing = {
            "wall_start": time.perf_counter(),
            "context_sec": 0.0,
            "valuation_sec": 0.0,
            "write_sec": 0.0,
            "stock_sec": 0.0,
        }

        self.stdout.write("开始预热估值快照")
        self.stdout.write(f"trade_date: {trade_date} | freq: {freq} | scope: {options.get('scope')} | dry_run: {dry_run}")
        self.stdout.write(f"methods: {','.join(methods)}")
        self.stdout.write(f"refresh_policy: {refresh_policy}")
        self.stdout.write(f"strict_express_match: {strict_express_match} | express_max_age_days: {express_max_age_days}")
        self.stdout.write(f"business_match_topn: {business_match_topn}")

        for idx, ts_code in enumerate(sliced_codes, start=1):
            stock_t0 = time.perf_counter()
            counters["processed"] += 1
            self.stdout.write(f"[{idx}/{len(sliced_codes)}] {ts_code} 开始处理")
            try:
                existing_qs = ValuationSnapshot.objects.filter(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    market=market,
                    valuation_method__in=methods,
                )
                existing_methods = set(existing_qs.values_list("valuation_method", flat=True))
                methods_to_compute = list(methods)

                if refresh_policy == "missing":
                    methods_to_compute = [method for method in methods if method not in existing_methods]
                    if not methods_to_compute:
                        counters["skipped_existing"] += 1
                        continue
                elif refresh_policy == "disclosure":
                    existing_updated_at = existing_qs.aggregate(last_updated=Max("updated_at")).get("last_updated")
                    latest_marker, disclosure_reason = self._latest_disclosure_marker(ts_code, trade_date)
                    if existing_updated_at is not None and latest_marker is not None and existing_updated_at.date() >= latest_marker:
                        counters["skipped_unchanged"] += 1
                        continue
                    if disclosure_reason:
                        counters["disclosure_refreshed"] += 1
                        disclosure_reason_counts[disclosure_reason] = disclosure_reason_counts.get(disclosure_reason, 0) + 1

                context_t0 = time.perf_counter()
                contexts = _load_business_match_contexts(ts_code=ts_code, market=market, top_n=business_match_topn)
                timing["context_sec"] += (time.perf_counter() - context_t0)
                if not contexts:
                    contexts = [{
                        "compare_group": None,
                        "industry_level": None,
                        "industry_code": None,
                        "industry_name": None,
                        "match_score": None,
                        "valuation_variant": "default",
                        "params": {},
                    }]

                outputs = {method: [] for method in methods_to_compute}
                trace_fields = {}
                stock_snapshot = get_local_valuation_snapshot(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    freq=freq,
                    strict_express_match=strict_express_match,
                    express_max_age_days=express_max_age_days,
                )
                for context in contexts:
                    valuation_t0 = time.perf_counter()
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
                    context_outputs = _extract_method_rows(valuation_result, methods_to_compute, context)
                    for method in methods_to_compute:
                        outputs[method].extend(context_outputs.get(method, []))
                    timing["valuation_sec"] += (time.perf_counter() - valuation_t0)

                counters["evaluated"] += 1
                if dry_run:
                    for method in methods_to_compute:
                        counters["would_write"] += len(outputs.get(method) or [])
                    continue

                timestamp = timezone.now()
                snapshot_rows = []
                latest_rows = []
                write_count = 0
                for method in methods_to_compute:
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
                    continue
                write_t0 = time.perf_counter()
                _bulk_upsert_valuation_rows(snapshot_rows, latest_rows)
                timing["write_sec"] += (time.perf_counter() - write_t0)
                counters["written"] += write_count
            except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                counters["errors"] += 1
                self.stderr.write(f"[{idx}/{len(sliced_codes)}] {ts_code} 失败: {exc}")
            finally:
                timing["stock_sec"] += (time.perf_counter() - stock_t0)

            if progress_every > 0 and idx % progress_every == 0:
                evaluated = max(counters["evaluated"], 1)
                self.stdout.write(
                    "progress: "
                    f"processed={idx}/{len(sliced_codes)} "
                    f"avg_stock_sec={timing['stock_sec']/idx:.3f} "
                    f"avg_context_sec={timing['context_sec']/evaluated:.3f} "
                    f"avg_valuation_sec={timing['valuation_sec']/evaluated:.3f} "
                    f"avg_write_sec={timing['write_sec']/evaluated:.3f}"
                )

            if interval > 0:
                time.sleep(interval)

        self.stdout.write("预热完成")
        for key, value in counters.items():
            self.stdout.write(f"{key}: {value}")
        if disclosure_reason_counts:
            summary = ", ".join(f"{key}={value}" for key, value in sorted(disclosure_reason_counts.items()))
            self.stdout.write(f"disclosure_refresh_reasons: {summary}")

        wall_elapsed = time.perf_counter() - timing["wall_start"]
        evaluated = max(counters["evaluated"], 1)
        processed = max(counters["processed"], 1)
        self.stdout.write("timing_summary:")
        self.stdout.write(f"- wall_sec: {wall_elapsed:.3f}")
        self.stdout.write(f"- avg_stock_sec: {timing['stock_sec']/processed:.3f}")
        self.stdout.write(f"- avg_context_sec_per_evaluated: {timing['context_sec']/evaluated:.3f}")
        self.stdout.write(f"- avg_valuation_sec_per_evaluated: {timing['valuation_sec']/evaluated:.3f}")
        self.stdout.write(f"- avg_write_sec_per_evaluated: {timing['write_sec']/evaluated:.3f}")
        if counters["errors"]:
            raise CommandError(f"预热完成，但有 {counters['errors']} 个失败")