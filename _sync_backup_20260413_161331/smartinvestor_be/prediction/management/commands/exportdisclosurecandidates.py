from pathlib import Path
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prediction.management.commands.prefillvaluationsnapshot import (
    _normalize_method_name,
    _parse_date_like,
    _resolve_latest_disclosure_signal,
)
from valuation.models import StockValuationSnapshot
from prediction.utils.valuation_util import get_stock_valuation_snapshot
from datastore.models import StockTradingHistory
from users.models import UserWatchlist


class Command(BaseCommand):
    help = "导出披露增量刷新候选股票列表，供 earnings refresh 按候选集运行。"

    def _prepare_output_encoding(self):
        for stream in [self.stdout, self.stderr]:
            raw_stream = getattr(stream, "_out", None)
            if raw_stream is not None and hasattr(raw_stream, "reconfigure"):
                raw_stream.reconfigure(encoding="utf-8")

    def add_arguments(self, parser):
        parser.add_argument("--trade-date", type=str, help="交易日，格式 YYYY-MM-DD")
        parser.add_argument("--freq", type=str, default="D", help="频率，默认 D")
        parser.add_argument("--scope", type=str, default="ALL", help="候选范围：ALL 或 ts_code 前缀")
        parser.add_argument("--market", type=str, default="CN", help="市场代码，默认 CN")
        parser.add_argument(
            "--methods",
            type=str,
            default="sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay",
            help="逗号分隔估值法列表，用于判断快照是否完整",
        )
        parser.add_argument("--offset", type=int, default=0, help="起始偏移")
        parser.add_argument("--limit", type=int, help="最多检查数量")
        parser.add_argument(
            "--output-file",
            type=str,
            required=True,
            help="输出候选文件路径，每行一个 ts_code",
        )
        parser.add_argument(
            "--no-strict-express-match",
            action="store_true",
            default=False,
            help="关闭 express_vip 严格匹配规则",
        )
        parser.add_argument(
            "--express-max-age-days",
            type=int,
            default=180,
            help="严格匹配下，快报公告距估值日最大允许天数",
        )
        parser.add_argument(
            "--candidate-policy",
            type=str,
            default="all",
            choices=["all", "disclosure-only"],
            help="候选策略：all=缺失/回填/披露增量都纳入；disclosure-only=仅披露增量",
        )

    def _resolve_trade_date(self, trade_date, freq):
        if trade_date:
            return trade_date
        latest = (
            StockTradingHistory.objects.filter(freq=freq)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
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

        return [code for code in qs if any(str(code).startswith(prefix) for prefix in prefixes)]

    def handle(self, *_args, **options):
        self._prepare_output_encoding()

        freq = str(options.get("freq", "D")).strip().upper()
        market = str(options.get("market", "CN")).strip().upper()
        strict_express_match = not bool(options.get("no_strict_express_match", False))
        express_max_age_days = int(options.get("express_max_age_days", 180) or 180)
        candidate_policy = str(options.get("candidate_policy", "all") or "all").strip().lower()
        offset = max(0, int(options.get("offset", 0) or 0))
        limit = options.get("limit")

        methods = [
            _normalize_method_name(item)
            for item in str(options.get("methods", "")).split(",")
            if item.strip()
        ]
        methods = [m for m in methods if m]
        if not methods:
            raise CommandError("至少需要一个估值方法 --methods")

        trade_date = self._resolve_trade_date(options.get("trade_date"), freq)
        all_codes = self._collect_codes(trade_date=trade_date, freq=freq, scope=options.get("scope"))
        sliced_codes = all_codes[offset: offset + limit if limit else None]
        trade_date_dt = _parse_date_like(trade_date)

        output_path = Path(options.get("output_file"))
        if not output_path.is_absolute():
            output_path = Path(settings.BASE_DIR) / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        candidates = []
        reason_counts = {
            "missing_method": 0,
            "market_cap_backfill": 0,
            "new_disclosure": 0,
            "already_updated_today": 0,
            "remote_probe_total": 0,
            "remote_probe_no_signal": 0,
        }

        snapshot_rows = StockValuationSnapshot.objects.filter(
            ts_code__in=sliced_codes,
            trade_date=trade_date,
            market=market,
            valuation_method__in=methods,
        ).values("ts_code", "valuation_method", "valuation_market_cap", "updated_at")

        existing_methods_by_code = defaultdict(set)
        market_cap_null_by_code = defaultdict(set)
        latest_update_by_code = {}
        for row in snapshot_rows:
            ts_code = str(row.get("ts_code"))
            method = str(row.get("valuation_method"))
            existing_methods_by_code[ts_code].add(method)
            if row.get("valuation_market_cap") is None:
                market_cap_null_by_code[ts_code].add(method)
            updated_at = row.get("updated_at")
            prev_updated = latest_update_by_code.get(ts_code)
            if prev_updated is None or (updated_at is not None and updated_at > prev_updated):
                latest_update_by_code[ts_code] = updated_at

        self.stdout.write(
            f"开始导出披露增量候选 trade_date={trade_date} freq={freq} scope={options.get('scope')} market={market}"
        )
        self.stdout.write(f"methods: {','.join(methods)}")
        self.stdout.write(f"candidate_policy: {candidate_policy}")

        for idx, ts_code in enumerate(sliced_codes, start=1):
            ts_code_str = str(ts_code)
            existing = existing_methods_by_code.get(ts_code_str, set())
            market_cap_null_methods = market_cap_null_by_code.get(ts_code_str, set())
            missing_methods = [m for m in methods if m not in existing]

            if missing_methods:
                if candidate_policy == "all":
                    candidates.append(ts_code_str)
                    reason_counts["missing_method"] += 1
                    continue

            if market_cap_null_methods:
                if candidate_policy == "all":
                    candidates.append(ts_code_str)
                    reason_counts["market_cap_backfill"] += 1
                    continue

            if len(existing) != len(methods):
                continue

            latest_snapshot_update = latest_update_by_code.get(ts_code_str)
            latest_snapshot_date = _parse_date_like(latest_snapshot_update)
            if latest_snapshot_date is not None and trade_date_dt is not None and latest_snapshot_date >= trade_date_dt:
                reason_counts["already_updated_today"] += 1
                continue

            valuation_snapshot = get_stock_valuation_snapshot(
                ts_code=ts_code,
                trade_date=trade_date,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
            )
            reason_counts["remote_probe_total"] += 1
            latest_disclosure_date, _disclosure_reason = _resolve_latest_disclosure_signal(
                valuation_snapshot,
                trade_date=trade_date,
            )
            if latest_disclosure_date is not None and (
                latest_snapshot_date is None or latest_disclosure_date > latest_snapshot_date
            ):
                candidates.append(ts_code_str)
                reason_counts["new_disclosure"] += 1
            else:
                reason_counts["remote_probe_no_signal"] += 1

            if idx % 200 == 0:
                self.stdout.write(f"checked: {idx}/{len(sliced_codes)} candidates={len(candidates)}")

        output_path.write_text("\n".join(candidates), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"候选导出完成: {output_path}"))
        self.stdout.write(f"checked: {len(sliced_codes)}")
        self.stdout.write(f"candidates: {len(candidates)}")
        for key in [
            "missing_method",
            "market_cap_backfill",
            "new_disclosure",
            "already_updated_today",
            "remote_probe_total",
            "remote_probe_no_signal",
        ]:
            self.stdout.write(f"{key}: {reason_counts[key]}")
