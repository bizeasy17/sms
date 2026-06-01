import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "将高置信度的中信建议映射自动并入 business keyword rules 配置"

    def add_arguments(self, parser):
        parser.add_argument("--market", type=str, default="CN", help="市场代码，默认 CN")
        parser.add_argument(
            "--min-similarity",
            type=float,
            default=0.95,
            help="fuzzy 建议被自动并入的最小相似度，默认 0.95",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="仅预览，不写回配置文件",
        )

    def handle(self, *_args, **options):
        market = options["market"]
        min_similarity = float(options["min_similarity"])
        dry_run = options["dry_run"]

        base_dir = Path(settings.BASE_DIR) / "static" / "valuation_config"
        rules_path = base_dir / f"business_keyword_rules_{market}.json"
        suggestions_path = base_dir / f"citic_name_suggestions_{market}.json"
        if not rules_path.exists():
            raise CommandError(f"未找到规则文件: {rules_path}")
        if not suggestions_path.exists():
            raise CommandError(f"未找到建议文件: {suggestions_path}")

        rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
        suggestions_data = json.loads(suggestions_path.read_text(encoding="utf-8"))
        explicit_targets = rules_data.setdefault("citic_name_targets", {})

        inserted = {}
        for item in suggestions_data.get("suggestions", []):
            citic_name = item.get("citic_name")
            if not citic_name or citic_name in explicit_targets:
                continue
            suggestions = item.get("suggestions") or []
            accepted = []
            for suggestion in suggestions:
                match_type = suggestion.get("match_type")
                similarity = float(suggestion.get("similarity") or 0.0)
                if match_type == "keyword_rule":
                    accepted.append(
                        {
                            "level": suggestion.get("target_level"),
                            "name": suggestion.get("target_name"),
                        }
                    )
                elif match_type == "fuzzy" and similarity >= min_similarity:
                    accepted.append(
                        {
                            "level": suggestion.get("target_level"),
                            "name": suggestion.get("target_name"),
                        }
                    )

            unique_targets = []
            for target in accepted:
                if not target.get("level") or not target.get("name"):
                    continue
                if target not in unique_targets:
                    unique_targets.append(target)

            if unique_targets:
                explicit_targets[citic_name] = unique_targets
                inserted[citic_name] = unique_targets

        if not dry_run and inserted:
            rules_path.write_text(json.dumps(rules_data, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS("中信建议并入完成"))
        self.stdout.write(f"dry_run: {dry_run}")
        self.stdout.write(f"inserted_count: {len(inserted)}")
        preview = list(inserted.items())[:20]
        self.stdout.write(json.dumps(preview, ensure_ascii=False, indent=2))