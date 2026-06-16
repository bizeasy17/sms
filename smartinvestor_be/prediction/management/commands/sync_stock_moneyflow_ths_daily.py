from django.core.management.base import BaseCommand, CommandError

from api.views import _sync_stock_moneyflow_ths_daily


class Command(BaseCommand):
    help = "同步 THS 个股资金流日数据（moneyflow_ths）到本地数据库。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="开始日期，支持 YYYY-MM-DD 或 YYYYMMDD。",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="",
            help="结束日期，支持 YYYY-MM-DD 或 YYYYMMDD。",
        )
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=365,
            help="当未指定开始日期时，从结束日向前回补天数（默认365）。",
        )
        parser.add_argument(
            "--latest",
            action="store_true",
            default=False,
            help="仅同步最近交易日（以今日请求，接口无数据时自动跳过）。",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="strict 模式下若未拉到任何数据则返回非零退出码。",
        )

    def handle(self, *args, **options):
        start_date = str(options.get("start_date") or "").strip()
        end_date = str(options.get("end_date") or "").strip()
        lookback_days = int(options.get("lookback_days") or 365)
        latest = bool(options.get("latest", False))
        strict = bool(options.get("strict", False))

        try:
            result = _sync_stock_moneyflow_ths_daily(
                start_date=start_date or None,
                end_date=end_date or None,
                latest=latest,
                lookback_days=lookback_days,
            )
        except Exception as exc:
            raise CommandError(f"sync stock moneyflow_ths failed: {exc}") from exc

        fetched_rows = int(result.get("fetched_rows") or 0)
        if strict and fetched_rows <= 0:
            raise CommandError("stock moneyflow_ths sync fetched no rows in strict mode")

        self.stdout.write(
            self.style.SUCCESS(
                "[stock-moneyflow-ths] sync done: "
                f"start_date={result.get('start_date')} "
                f"end_date={result.get('end_date')} "
                f"checked_days={result.get('checked_days')} "
                f"fetched_dates={len(result.get('fetched_dates') or [])} "
                f"fetched_rows={fetched_rows} "
                f"upsert_count={result.get('upsert_count')} "
                f"total_rows={result.get('total_rows')}"
            )
        )
