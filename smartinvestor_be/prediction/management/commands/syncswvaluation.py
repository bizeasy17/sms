from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prediction.services.sw_valuation import ShenwanValuationSyncService


class Command(BaseCommand):
    help = "同步申万一二三级行业映射，并基于 tushare 生成动态估值参数"

    def add_arguments(self, parser):
        parser.add_argument("--trade-date", type=str, help="交易日，格式 YYYYMMDD")
        parser.add_argument(
            "--sample-size",
            type=int,
            default=5,
            help="每个三级行业抽样的龙头样本数，用于提取财务指标",
        )
        parser.add_argument(
            "--request-interval",
            type=float,
            default=0.45,
            help="连续请求 tushare 财务指标接口的最小间隔秒数，用于规避频控",
        )
        parser.add_argument(
            "--max-industries",
            type=int,
            help="仅处理前 N 个三级行业，便于调试",
        )
        parser.add_argument(
            "--mapping-only",
            action="store_true",
            default=False,
            help="仅同步申万层级映射，不生成估值参数",
        )
        parser.add_argument(
            "--params-only",
            action="store_true",
            default=False,
            help="仅生成估值参数，使用现有映射文件",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="只计算不落盘",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=0,
            help="参数生成阶段每处理 N 个三级行业打印一次进度；0 表示不打印",
        )
        parser.add_argument(
            "--disable-history-anchors",
            action="store_true",
            default=False,
            help="关闭基于 sw_daily 的 3Y/5Y/10Y 历史分位锚点增强",
        )
        parser.add_argument(
            "--history-years",
            type=str,
            default="3,5,10",
            help="历史窗口（年），逗号分隔，例如 3,5,10",
        )
        parser.add_argument(
            "--history-quantile",
            type=float,
            default=0.5,
            help="历史分位点，默认 0.5（中位数）",
        )
        parser.add_argument(
            "--history-min-samples",
            type=int,
            default=120,
            help="每个历史窗口最小样本点数量，低于阈值则忽略该窗口",
        )

    def handle(self, *_args, **options):
        if options["mapping_only"] and options["params_only"]:
            raise CommandError("--mapping-only 与 --params-only 不能同时使用。")

        history_years = []
        for item in str(options.get("history_years") or "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = int(item)
            except ValueError as exc:
                raise CommandError(f"invalid --history-years value: {item}") from exc
            if value > 0:
                history_years.append(value)
        if not history_years:
            history_years = [3, 5, 10]

        service = ShenwanValuationSyncService(
            Path(settings.BASE_DIR) / "static",
            history_enabled=not bool(options.get("disable_history_anchors", False)),
            history_years=history_years,
            history_quantile=float(options.get("history_quantile") or 0.5),
            history_min_samples=int(options.get("history_min_samples") or 120),
        )
        include_mapping = not options["params_only"]
        include_params = not options["mapping_only"]

        self.stdout.write(
            f"开始执行申万估值同步... include_mapping={include_mapping}, include_params={include_params}, dry_run={options['dry_run']}, "
            f"trade_date={options.get('trade_date') or 'auto'}, sample_size={options['sample_size']}, "
            f"max_industries={options.get('max_industries') or 'all'}, request_interval={options['request_interval']}, "
            f"history_enabled={not bool(options.get('disable_history_anchors', False))}, "
            f"history_years={','.join(str(y) for y in history_years)}, history_quantile={float(options.get('history_quantile') or 0.5)}, "
            f"history_min_samples={int(options.get('history_min_samples') or 120)}"
        )
        if include_params:
            self.stdout.write("提示：参数生成阶段会调用外部接口，期间可能数分钟无输出，属正常现象。")

        progress_every = max(0, int(options.get("progress_every") or 0))

        def _on_progress(payload):
            if payload.get("stage") != "params_l3":
                return
            done = int(payload.get("done") or 0)
            total = int(payload.get("total") or 0)
            last_code = payload.get("last_code") or ""
            if total > 0:
                pct = round(done * 100.0 / total, 1)
                self.stdout.write(
                    f"[progress] params_l3 {done}/{total} ({pct}%) last={last_code}"
                )

        try:
            result = service.sync(
                trade_date=options["trade_date"],
                sample_size=options["sample_size"],
                max_industries=options["max_industries"],
                include_mapping=include_mapping,
                include_params=include_params,
                dry_run=options["dry_run"],
                request_interval=options["request_interval"],
                progress_every=progress_every,
                progress_callback=_on_progress if progress_every > 0 else None,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("申万估值同步完成"))
        self.stdout.write(f"dry_run: {result['dry_run']}")
        if include_mapping:
            self.stdout.write(f"mapping_file: {result['mapping_file']}")
            self.stdout.write(f"mapping_levels: {result['mapping_levels']}")
            self.stdout.write(f"mapped_ts_codes: {result['mapped_ts_codes']}")
        if include_params:
            self.stdout.write(f"params_file: {result['params_file']}")
            self.stdout.write(f"params_levels: {result['params_levels']}")
            self.stdout.write(f"trade_date: {result['trade_date']}")