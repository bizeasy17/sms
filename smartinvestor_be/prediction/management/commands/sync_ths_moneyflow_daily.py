from django.core.management.base import BaseCommand, CommandError

from api.views import _sync_ths_moneyflow_daily


class Command(BaseCommand):
    help = "同步 THS 行业资金流日数据（moneyflow_cnt_ths）到本地快照。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=7,
            help="向前回看天数（默认7）。",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="strict 模式下若未拉到任何数据则返回非零退出码。",
        )

    def handle(self, *args, **options):
        lookback_days = int(options.get("lookback_days") or 7)
        strict = bool(options.get("strict", False))

        try:
            result = _sync_ths_moneyflow_daily(lookback_days=lookback_days)
        except Exception as exc:
            raise CommandError(f"sync ths moneyflow daily failed: {exc}") from exc

        fetched_rows = int(result.get("fetched_rows") or 0)
        if strict and fetched_rows <= 0:
            raise CommandError("ths moneyflow daily sync fetched no rows in strict mode")

        self.stdout.write(
            self.style.SUCCESS(
                "[ths-moneyflow] sync done: "
                f"checked_days={result.get('checked_days')} "
                f"fetched_dates={len(result.get('fetched_dates') or [])} "
                f"fetched_rows={fetched_rows} "
                f"upsert_count={result.get('upsert_count')} "
                f"total_rows={result.get('total_rows')}"
            )
        )
