# apps/valuation/management/commands/get_params.py
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from prediction.services.validation_loader import ValuationConfig

class Command(BaseCommand):
    help = "根据细分行业名称，输出映射的大类与估值默认参数（JSON 可选）"

    def add_arguments(self, parser):
        parser.add_argument("industry", type=str, help="细分行业名称，如：白酒、半导体、公路")
        parser.add_argument(
            "--no-fuzzy",
            action="store_true",
            default=False,
            help="关闭模糊匹配（默认开启）"
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="以 JSON 格式输出结果"
        )
        parser.add_argument(
            "--market",
            type=str,
            default="CN",
            help="市场类型，默认为 CN"
        )
        parser.add_argument(
            "--pretty",
            action="store_true",
            default=False,
            help="JSON 美化（仅在 --json 时生效）"
        )

    def handle(self, *args, **options):
        industry: str = options["industry"]
        fuzzy = not options["no_fuzzy"]
        as_json = options["json"]
        market = options["market"]
        pretty = options["pretty"]

        base_dir = Path(settings.BASE_DIR) / "static"
        cfg = ValuationConfig(base_dir, market=market)

        try:
            big, bucket, params = cfg.get_params_by_narrow_industry(industry, fuzzy=fuzzy)
        except Exception as e:
            raise CommandError(str(e))

        result = {
            "input_industry": industry,
            "big_category": big,
            "valuation_bucket": bucket,
            "params": params
        }

        if as_json:
            if pretty:
                self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                self.stdout.write(json.dumps(result, ensure_ascii=False))
        else:
            # 友好的人类可读输出
            self.stdout.write(self.style.SUCCESS(f"[输入行业] {industry}"))
            self.stdout.write(f"[映射大类] {big}")
            self.stdout.write(f"[参数桶]   {bucket}")
            self.stdout.write("[默认参数]")
            for k, v in params.items():
                self.stdout.write(f"  - {k}: {v}")