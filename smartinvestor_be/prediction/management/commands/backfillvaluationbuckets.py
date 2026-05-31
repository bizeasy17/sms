from django.core.management.base import BaseCommand, CommandError

from api.views import _save_valuation_snapshot
from prediction.management.commands.prefillvaluationsnapshot import (
    _build_context_variant,
    _extract_implied_prices,
    _load_business_match_contexts,
    _normalize_valuation_variant,
    _parse_snapshot_date,
    _resolve_forced_report_end_date,
)
from prediction.services.scarcity_auto_engine import ScarcityAutoEngine
from valuation.models import StockValuationSnapshot, StockValuationSnapshotLatest
from valuation.services.valuation_engine import (
    get_stock_valuation_snapshot,
    test_valuation_light,
)


class Command(BaseCommand):
    help = "按指定报告期回填正式与 blended 估值快照桶"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, required=True, help="股票代码，如 688002.SH")
        parser.add_argument("--trade-date", type=str, required=True, help="估值交易日，YYYY-MM-DD")
        parser.add_argument(
            "--target-report-type",
            type=str,
            default="FY",
            help="目标报告类型，支持 Q1/H1/Q3/FY/ANNUAL",
        )
        parser.add_argument(
            "--target-fiscal-year",
            type=int,
            required=True,
            help="目标财年，如 2025",
        )
        parser.add_argument(
            "--methods",
            type=str,
            default="sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay",
            help="逗号分隔的方法列表",
        )
        parser.add_argument("--market", type=str, default="CN", help="市场代码，默认 CN")
        parser.add_argument(
            "--business-match-topn",
            type=int,
            default=3,
            help="业务匹配行业 TopN，默认 3",
        )
        parser.add_argument(
            "--no-strict-express-match",
            action="store_true",
            default=False,
            help="关闭 express 严格匹配",
        )
        parser.add_argument(
            "--express-max-age-days",
            type=int,
            default=180,
            help="严格模式下 express 最大时效天数",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="只计算不写库",
        )

    @staticmethod
    def _parse_methods(raw_methods):
        methods = [str(item).strip() for item in str(raw_methods or "").split(",") if str(item).strip()]
        if not methods:
            raise CommandError("--methods 不能为空")
        return methods

    @staticmethod
    def _build_contexts(ts_code, market, business_match_topn):
        contexts = _load_business_match_contexts(
            ts_code=ts_code,
            market=market,
            top_n=max(0, int(business_match_topn or 0)),
        )
        if contexts:
            return contexts
        return [
            {
                "compare_group": None,
                "industry_level": None,
                "industry_code": None,
                "industry_name": None,
                "match_score": None,
                "params": {},
                "valuation_variant": "default",
            }
        ]

    def _collect_rows(self, ts_code, trade_date, market, snapshot, contexts, methods, strict_express_match, express_max_age_days):
        outputs = {method: [] for method in methods}

        for context in contexts:
            valuation_params = dict(context.get("params") or {})
            valuation_params, _ = ScarcityAutoEngine._apply_scarcity_profile(
                valuation_params=valuation_params,
                scarcity_profile="auto",
                market=market,
                tscode=ts_code,
                trade_date=trade_date,
            )
            valuation_result = test_valuation_light(
                ts_code=ts_code,
                trade_date=trade_date,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
                snapshot=snapshot,
                **valuation_params,
            )
            valuation_df = valuation_result.get("valuations")
            context_outputs = _extract_implied_prices(valuation_df, methods)
            for method in methods:
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

        deduped_rows = []
        seen_keys = set()
        for method in methods:
            for row in outputs.get(method) or []:
                normalized_variant = _normalize_valuation_variant(
                    row.get("valuation_variant"),
                    fallback="default",
                )[:128]
                pair_key = (str(row.get("method") or method).strip().lower(), normalized_variant)
                if pair_key in seen_keys:
                    continue
                seen_keys.add(pair_key)
                row["valuation_variant"] = normalized_variant
                deduped_rows.append(row)
        return deduped_rows

    def _emit_bucket_summary(self, ts_code, trade_date, market, forced_report_end_date):
        report_end_date = _parse_snapshot_date(forced_report_end_date)
        snapshot_rows = list(
            StockValuationSnapshot.objects.filter(
                ts_code=ts_code,
                trade_date=trade_date,
                market=market,
                profit_report_end_date=report_end_date,
            )
            .order_by("valuation_method", "valuation_variant", "profit_data_source")
            .values_list("valuation_method", "valuation_variant", "profit_report_type", "profit_data_source")
        )
        latest_rows = list(
            StockValuationSnapshotLatest.objects.filter(
                ts_code=ts_code,
                market=market,
                profit_report_end_date=report_end_date,
            )
            .order_by("valuation_method", "valuation_variant", "profit_data_source")
            .values_list("valuation_method", "valuation_variant", "profit_report_type", "profit_data_source")
        )
        self.stdout.write(f"snapshot_row_count={len(snapshot_rows)}")
        self.stdout.write(f"latest_row_count={len(latest_rows)}")
        for row in snapshot_rows:
            self.stdout.write(f"snapshot={row}")
        for row in latest_rows:
            self.stdout.write(f"latest={row}")

    def handle(self, *args, **options):
        ts_code = str(options.get("tscode") or "").strip().upper()
        trade_date = str(options.get("trade_date") or "").strip()
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        methods = self._parse_methods(options.get("methods"))
        strict_express_match = not bool(options.get("no_strict_express_match"))
        express_max_age_days = int(options.get("express_max_age_days") or 180)
        forced_report_end_date = _resolve_forced_report_end_date(
            options.get("target_report_type"),
            options.get("target_fiscal_year"),
        )
        dry_run = bool(options.get("dry_run"))

        contexts = self._build_contexts(
            ts_code=ts_code,
            market=market,
            business_match_topn=options.get("business_match_topn"),
        )

        formal_snapshot = get_stock_valuation_snapshot(
            ts_code=ts_code,
            trade_date=trade_date,
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
            forced_report_end_date=forced_report_end_date,
            allow_express_adjustment=False,
        )
        blended_snapshot = get_stock_valuation_snapshot(
            ts_code=ts_code,
            trade_date=trade_date,
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
            forced_report_end_date=forced_report_end_date,
            allow_express_adjustment=True,
        )

        bucket_snapshots = [
            ("formal", formal_snapshot),
            ("blended", blended_snapshot),
        ]

        total_rows = 0
        self.stdout.write(f"ts_code={ts_code}")
        self.stdout.write(f"trade_date={trade_date}")
        self.stdout.write(f"forced_report_end_date={forced_report_end_date}")
        self.stdout.write(f"methods={','.join(methods)}")

        for bucket_name, bucket_snapshot in bucket_snapshots:
            bucket_rows = self._collect_rows(
                ts_code=ts_code,
                trade_date=trade_date,
                market=market,
                snapshot=bucket_snapshot,
                contexts=contexts,
                methods=methods,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
            )
            total_rows += len(bucket_rows)
            self.stdout.write(
                f"bucket={bucket_name} profit_source={bucket_snapshot.get('profit_data_source')} rows={len(bucket_rows)}"
            )

            if dry_run:
                continue

            for row in bucket_rows:
                _save_valuation_snapshot(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    market=market,
                    method=row.get("method"),
                    valuation_price=row.get("implied_price"),
                    valuation_market_cap=row.get("equity_value"),
                    source="bucket_backfill",
                    corporation=None,
                    valuation_snapshot=bucket_snapshot,
                    valuation_variant=row.get("valuation_variant"),
                    industry_level=row.get("industry_level"),
                    industry_code=row.get("industry_code"),
                    industry_name=row.get("industry_name"),
                    compare_group=row.get("compare_group"),
                    match_score=row.get("match_score"),
                )

        self.stdout.write(f"total_rows={total_rows}")
        if not dry_run:
            self._emit_bucket_summary(
                ts_code=ts_code,
                trade_date=trade_date,
                market=market,
                forced_report_end_date=forced_report_end_date,
            )