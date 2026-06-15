from django.core.management.base import BaseCommand, CommandError

from api.views import _load_ths_index_rows
from prediction.utils.prediction_util import get_tushare_pro


class Command(BaseCommand):
    help = "刷新 THS 行业本地快照（包含 member_count 与 member_stocks）。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefer-local",
            action="store_true",
            default=False,
            help="优先使用本地快照；默认 false 表示强制走远端刷新并回写本地。",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="strict 模式下若刷新结果为空则返回非零退出码。",
        )

    def handle(self, *args, **options):
        prefer_local = bool(options.get("prefer_local", False))
        strict = bool(options.get("strict", False))

        try:
            pro = get_tushare_pro()
        except Exception as exc:
            if strict:
                raise CommandError(f"init tushare pro failed: {exc}") from exc
            self.stdout.write(self.style.WARNING(f"[ths-snapshot] init tushare pro failed, fallback local: {exc}"))
            pro = None

        try:
            rows = _load_ths_index_rows(pro=pro, prefer_local=prefer_local)
        except Exception as exc:
            raise CommandError(f"refresh ths snapshot failed: {exc}") from exc

        total = len(rows) if isinstance(rows, list) else 0
        with_count = 0
        with_members = 0
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    if int(row.get("member_count", 0)) > 0:
                        with_count += 1
                except (TypeError, ValueError):
                    continue
                if isinstance(row.get("member_stocks"), list) and len(row.get("member_stocks")) > 0:
                    with_members += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"[ths-snapshot] refreshed total={total} with_member_count={with_count} with_member_stocks={with_members} prefer_local={prefer_local}"
            )
        )

        if strict and total <= 0:
            raise CommandError("ths snapshot is empty in strict mode")
