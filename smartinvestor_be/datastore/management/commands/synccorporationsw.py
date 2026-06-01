import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datastore.models import Corporation


class Command(BaseCommand):
    help = "将 SW 三级行业映射回填到 Corporation.sw_l3_code / sw_l3_name"

    def add_arguments(self, parser):
        parser.add_argument(
            "--market",
            type=str,
            default="CN",
            help="市场代码，默认 CN",
        )
        parser.add_argument(
            "--tscode",
            type=str,
            help="仅同步单只股票，如 000001.SZ",
        )
        parser.add_argument(
            "--clear-missing",
            action="store_true",
            default=False,
            help="当 SW 映射不存在时清空 sw_l3_code/sw_l3_name",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="只统计不落库",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="bulk_update 批量大小，默认 1000",
        )

    def handle(self, *_args, **options):
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        ts_code = options.get("tscode")
        clear_missing = bool(options.get("clear_missing"))
        dry_run = bool(options.get("dry_run"))
        batch_size = max(1, int(options.get("batch_size") or 1000))

        mapping_path = (
            Path(settings.BASE_DIR)
            / "static"
            / "valuation_config"
            / f"sw_industry_mapping_{market}.json"
        )

        if not mapping_path.exists():
            raise CommandError(f"SW 映射文件不存在: {mapping_path}")

        with mapping_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        ts_map = payload.get("ts_code_to_levels", {}) or {}

        queryset = Corporation.objects.all().order_by("ts_code")
        if ts_code:
            queryset = queryset.filter(ts_code=ts_code)

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("没有可同步的公司记录。"))
            return

        to_update = []
        matched = 0
        changed = 0
        missing = 0

        for corp in queryset.iterator(chunk_size=batch_size):
            entry = ts_map.get(corp.ts_code)
            old_code = corp.sw_l3_code or ""
            old_name = corp.sw_l3_name or ""

            if entry:
                new_code = (entry.get("l3_code") or "").strip()
                new_name = (entry.get("l3_name") or "").strip()
                matched += 1
            else:
                missing += 1
                if clear_missing:
                    new_code = ""
                    new_name = ""
                else:
                    new_code = old_code
                    new_name = old_name

            if new_code != old_code or new_name != old_name:
                corp.sw_l3_code = new_code or None
                corp.sw_l3_name = new_name or None
                to_update.append(corp)
                changed += 1

        self.stdout.write(
            f"total={total}, matched={matched}, missing={missing}, changed={changed}, dry_run={dry_run}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run 模式，未写入数据库。"))
            return

        if to_update:
            Corporation.objects.bulk_update(
                to_update,
                fields=["sw_l3_code", "sw_l3_name"],
                batch_size=batch_size,
            )
            self.stdout.write(self.style.SUCCESS(f"已更新 {len(to_update)} 条公司记录。"))
        else:
            self.stdout.write(self.style.SUCCESS("无需更新，数据已是最新。"))
