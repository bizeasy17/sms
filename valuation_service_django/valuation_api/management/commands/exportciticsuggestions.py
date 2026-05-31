import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from valuation_api.business_industry_matcher import BusinessIndustryMatcher


def _get_tushare_pro_client():
    try:
        import tushare as ts
    except ImportError:
        return None

    token = (
        os.getenv("TUSHARE_TOKEN")
        or os.getenv("TUSHARE_PRO_TOKEN")
        or str(getattr(settings, "TUSHARE_TOKEN", "") or "").strip()
    )
    if token:
        ts.set_token(token)

    try:
        return ts.pro_api()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = "导出中信行业名称到申万行业的显式映射建议"

    def add_arguments(self, parser):
        parser.add_argument("--market", type=str, default="CN", help="市场代码，默认 CN")
        parser.add_argument("--level", type=str, choices=["L1", "L2", "L3", "ALL"], default="L2")
        parser.add_argument(
            "--output",
            type=str,
            help="输出文件路径，默认写入 static/valuation_config/citic_name_suggestions_<market>.json",
        )

    def handle(self, *_args, **options):
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        level = str(options.get("level") or "L2").strip().upper() or "L2"
        base_dir = Path(settings.BASE_DIR)
        matcher = BusinessIndustryMatcher(base_dir=base_dir, market=market)
        pro = _get_tushare_pro_client()
        if pro is None:
            raise CommandError("Tushare client unavailable")

        try:
            df = pro.ci_index_member(is_new="Y")
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if df is None or df.empty:
            raise CommandError("ci_index_member 未返回可用数据。")

        config_path = base_dir / "static" / "valuation_config" / f"business_keyword_rules_{market}.json"
        config_data = json.loads(config_path.read_text(encoding="utf-8"))
        explicit_targets = config_data.get("citic_name_targets", {})

        l2_names = set(df["l2_name"].dropna().tolist()) if "l2_name" in df.columns else set()
        l3_names = set(df["l3_name"].dropna().tolist()) if "l3_name" in df.columns else set()
        citic_names = sorted(l2_names.union(l3_names))
        missing_names = [name for name in citic_names if name not in explicit_targets]

        suggestions = []
        for citic_name in missing_names:
            suggestions.append(
                {
                    "citic_name": citic_name,
                    "suggestions": matcher.suggest_citic_targets(citic_name, level=level),
                }
            )

        output_path = (
            Path(options["output"])
            if options.get("output")
            else base_dir / "static" / "valuation_config" / f"citic_name_suggestions_{market}.json"
        )
        payload = {
            "market": market,
            "sw_level": level,
            "total_citic_names": len(citic_names),
            "explicit_mapping_count": len(explicit_targets),
            "remaining_unmapped_count": len(missing_names),
            "suggestions": suggestions,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write("中信映射建议导出完成")
        self.stdout.write(f"output: {output_path}")
        self.stdout.write(f"total_citic_names: {len(citic_names)}")
        self.stdout.write(f"explicit_mapping_count: {len(explicit_targets)}")
        self.stdout.write(f"remaining_unmapped_count: {len(missing_names)}")