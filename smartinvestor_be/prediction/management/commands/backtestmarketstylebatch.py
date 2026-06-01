import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datastore.models import Corporation, StockTradingHistory
from valuation.models import StockValuationSnapshot


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANAGE_PY = PROJECT_ROOT / "manage.py"


INDUSTRY_KEYWORDS = {
    "银行": ["银行", "国有大型银行", "城商行", "农商行"],
    "半导体": ["半导体", "芯片", "集成电路", "封测"],
    "小金属": ["小金属", "稀土", "稀有金属", "钨", "锗", "钽"],
    "煤炭": ["煤炭", "煤炭开采", "焦煤", "动力煤"],
    "有色": ["有色", "铜", "铝", "锌", "黄金", "贵金属"],
    "白酒": ["白酒", "啤酒", "饮料制造"],
    "医药": ["医药", "创新药", "中药", "生物制品", "医疗器械"],
    "消费电子": ["消费电子", "电子元件", "光学光电子", "声学", "面板"],
    "军工": ["军工", "航空装备", "航天装备", "地面兵装", "军工电子"],
    "光伏": ["光伏", "逆变器", "硅料", "硅片", "组件", "电池片"],
}

INDUSTRY_STYLE_GROUP = {
    "银行": "defensive",
    "白酒": "defensive",
    "医药": "defensive",
    "半导体": "growth_semis_design",
    "消费电子": "growth",
    "军工": "growth",
    "光伏": "cyclical",
    "有色": "cyclical",
    "小金属": "cyclical",
    "煤炭": "cyclical",
}

MILITARY_SUBGROUP_RULES = {
    "growth_military_aerospace": ["航空装备", "航天装备"],
    "growth_military_electronics": ["军工电子"],
}

SEMICONDUCTOR_SUBGROUP_RULES = {
    "growth_semis_software": ["垂直应用软件", "EDA", "设计软件"],
    "growth_semis_design": ["数字芯片设计", "模拟芯片设计", "芯片设计", "SOC", "MCU"],
    "growth_semis_equipment": ["半导体设备", "设备", "装备", "晶圆制造设备"],
    "growth_semis_materials": ["半导体材料", "电子化学品", "光刻胶", "硅片材料", "靶材"],
    "growth_semis_manufacturing": ["封测", "分立器件", "制造", "代工", "功率器件", "IDM", "LED"],
}


def _matches_keywords(text, keywords):
    return any(keyword in text for keyword in keywords)


def _resolve_industry_group(industry_name, sw_l3_name):
    industry_text = str(industry_name or "")
    sw_name = str(sw_l3_name or "")
    combined_text = f"{industry_text} {sw_name}"

    semis_keywords = INDUSTRY_KEYWORDS.get("半导体") or []
    if any(token in combined_text for token in semis_keywords):
        for subgroup, tokens in SEMICONDUCTOR_SUBGROUP_RULES.items():
            if any(token in sw_name for token in tokens):
                return subgroup
        return "growth_semis_design"

    military_keywords = INDUSTRY_KEYWORDS.get("军工") or []
    if any(token in combined_text for token in military_keywords):
        for subgroup, tokens in MILITARY_SUBGROUP_RULES.items():
            if any(token in sw_name for token in tokens):
                return subgroup
        if "航空" in industry_text:
            return "growth_military_aerospace"
        return "growth_military_electronics"

    for industry_key, keywords in INDUSTRY_KEYWORDS.items():
        if industry_key in {"半导体", "军工"}:
            continue
        if any(token in combined_text for token in keywords):
            return INDUSTRY_STYLE_GROUP.get(industry_key, "balanced")

    return INDUSTRY_STYLE_GROUP.get(industry_text, "balanced")


def _pick_stocks_for_industry(
    industry_name,
    keywords,
    per_industry,
    year,
    min_trade_days,
    valuation_source="auto",
    allow_st=False,
):
    candidates = []
    corp_rows = Corporation.objects.all().values("ts_code", "name", "industry__name", "sw_l3_name")

    for row in corp_rows:
        ts_code = row.get("ts_code")
        if not ts_code:
            continue
        name = str(row.get("name") or "")
        upper_name = name.upper()
        if (not allow_st) and ("ST" in upper_name or "退" in name):
            continue
        text = " ".join([str(row.get("industry__name") or ""), str(row.get("sw_l3_name") or "")])
        if not _matches_keywords(text, keywords):
            continue

        trade_cnt = (
            StockTradingHistory.objects.filter(
                ts_code=ts_code,
                freq="D",
                trade_date__gte=f"{year}-01-01",
                trade_date__lte=f"{year}-12-31",
            )
            .exclude(close_qfq__isnull=True, close__isnull=True)
            .count()
        )
        if trade_cnt < min_trade_days:
            continue

        snap_cnt = StockValuationSnapshot.objects.filter(
            ts_code=ts_code,
            market="CN",
            trade_date__gte=f"{year}-01-01",
            trade_date__lte=f"{year}-12-31",
        ).count()
        if valuation_source == "snapshot" and snap_cnt <= 0:
            continue

        candidates.append(
            {
                "industry": industry_name,
                "ts_code": ts_code,
                "name": row.get("name"),
                "industry_name": row.get("industry__name"),
                "sw_l3_name": row.get("sw_l3_name"),
                "trade_cnt": trade_cnt,
                "snap_cnt": snap_cnt,
            }
        )

    candidates.sort(key=lambda item: (-item["trade_cnt"], -item["snap_cnt"], item["ts_code"]))
    return candidates[:per_industry]


def _avg(rows, key):
    values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 6)


class Command(BaseCommand):
    help = "Batch backtest market-style adjustment across multiple industries and aggregate results."

    def add_arguments(self, parser):
        parser.add_argument(
            "--industries",
            type=str,
            default="银行,半导体,小金属,煤炭,有色,白酒,医药,消费电子,军工,光伏",
            help="Comma-separated industry groups",
        )
        parser.add_argument("--per-industry", type=int, default=5, help="Stocks per industry")
        parser.add_argument("--year", type=int, default=2025, help="Backtest year")
        parser.add_argument("--sample-size", type=int, default=40, help="Sample size per stock")
        parser.add_argument("--seed", type=int, default=2025, help="Random seed")
        parser.add_argument("--horizon", type=int, default=20, help="Future horizon in trading days")
        parser.add_argument("--min-trade-days", type=int, default=160, help="Minimum trading days in selected year")
        parser.add_argument("--freq", type=str, default="D", help="Trading frequency")
        parser.add_argument("--market", type=str, default="CN", help="Market code")
        parser.add_argument("--valuation-band-pct", type=float, default=0.1, help="Band pct")
        parser.add_argument(
            "--style-profile",
            type=str,
            default="adaptive",
            help="Style profile passed to single-stock backtest: unified or industry or adaptive",
        )
        parser.add_argument(
            "--valuation-source",
            type=str,
            default="auto",
            help="Valuation source passed to single-stock backtest: auto, snapshot, or recompute",
        )
        parser.add_argument(
            "--allow-st",
            action="store_true",
            help="Allow ST/delisting-risk names in sample selection (use only for sparse-history diagnostics)",
        )
        parser.add_argument("--output", type=str, default=None, help="Optional output summary path")

    def handle(self, *args, **options):
        industry_names = [item.strip() for item in str(options.get("industries") or "").split(",") if item.strip()]
        per_industry = int(options.get("per_industry") or 5)
        year = int(options.get("year") or 2025)
        sample_size = int(options.get("sample_size") or 40)
        seed = int(options.get("seed") or 2025)
        horizon = int(options.get("horizon") or 20)
        min_trade_days = int(options.get("min_trade_days") or 160)
        freq = str(options.get("freq") or "D").strip().upper() or "D"
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        band_pct = float(options.get("valuation_band_pct") or 0.1)
        style_profile = str(options.get("style_profile") or "adaptive").strip().lower()
        valuation_source = str(options.get("valuation_source") or "auto").strip().lower()
        allow_st = bool(options.get("allow_st"))

        if per_industry <= 0:
            raise CommandError("--per-industry must be > 0")

        selected = {}
        stock_list = []
        for industry_name in industry_names:
            keywords = INDUSTRY_KEYWORDS.get(industry_name)
            if not keywords:
                keywords = [industry_name]
            picks = _pick_stocks_for_industry(
                industry_name=industry_name,
                keywords=keywords,
                per_industry=per_industry,
                year=year,
                min_trade_days=min_trade_days,
                valuation_source=valuation_source,
                allow_st=allow_st,
            )
            selected[industry_name] = picks
            stock_list.extend(picks)

        if not stock_list:
            raise CommandError("No stocks selected. Please adjust industries or constraints.")

        output_dir = PROJECT_ROOT / "output" / "local_valuation_checks"
        output_dir.mkdir(parents=True, exist_ok=True)

        detail_rows = []
        python_bin = str(Path(sys.executable))
        for stock in stock_list:
            ts_code = stock["ts_code"]
            industry_group = _resolve_industry_group(stock.get("industry"), stock.get("sw_l3_name"))
            stock_output = output_dir / f"{ts_code.replace('.', '_')}_{year}_market_style_backtest.json"
            cmd = [
                python_bin,
                str(MANAGE_PY),
                "backtestmarketstyleadjustment",
                "--tscode",
                ts_code,
                "--year",
                str(year),
                "--sample-size",
                str(sample_size),
                "--seed",
                str(seed),
                "--horizon",
                str(horizon),
                "--freq",
                freq,
                "--market",
                market,
                "--valuation-band-pct",
                str(band_pct),
                "--style-profile",
                style_profile,
                "--valuation-source",
                valuation_source,
                "--industry-group",
                industry_group,
                "--output",
                str(stock_output),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            row = {
                "industry": stock["industry"],
                "ts_code": ts_code,
                "name": stock.get("name"),
                "industry_name": stock.get("industry_name"),
                "sw_l3_name": stock.get("sw_l3_name"),
                "trade_cnt": stock.get("trade_cnt"),
                "snap_cnt": stock.get("snap_cnt"),
                "style_profile": style_profile,
                "valuation_source": valuation_source,
                "allow_st": allow_st,
                "industry_group": industry_group,
                "ok": proc.returncode == 0 and stock_output.exists(),
                "returncode": proc.returncode,
            }

            if row["ok"]:
                payload = json.loads(stock_output.read_text(encoding="utf-8"))
                metrics = payload.get("metrics") or {}
                meta = payload.get("meta") or {}
                row.update(
                    {
                        "sample_size_used": meta.get("sample_size_used"),
                        "mae_baseline": metrics.get("mae_baseline"),
                        "mae_adjusted": metrics.get("mae_adjusted"),
                        "mae_delta": metrics.get("mae_delta"),
                        "mae_delta_abs": metrics.get("mae_delta_abs"),
                        "mae_improvement_ratio": metrics.get("mae_improvement_ratio"),
                        "mae_improvement_pct": metrics.get("mae_improvement_pct"),
                        "mape_baseline": metrics.get("mape_baseline"),
                        "mape_adjusted": metrics.get("mape_adjusted"),
                        "mape_delta": metrics.get("mape_delta"),
                        "mape_delta_abs": metrics.get("mape_delta_abs"),
                        "mape_delta_pct_point": metrics.get("mape_delta_pct_point"),
                        "mape_improvement_ratio": metrics.get("mape_improvement_ratio"),
                        "mape_improvement_pct": metrics.get("mape_improvement_pct"),
                        "adjusted_better_rate": metrics.get("adjusted_better_rate"),
                    }
                )
            else:
                row.update(
                    {
                        "stderr_tail": (proc.stderr or "")[-1000:],
                        "stdout_tail": (proc.stdout or "")[-1000:],
                    }
                )
            detail_rows.append(row)

        summary_by_industry = {}
        for industry_name in industry_names:
            rows = [row for row in detail_rows if row["industry"] == industry_name and row.get("ok")]
            failed_rows = [row for row in detail_rows if row["industry"] == industry_name and not row.get("ok")]
            summary_by_industry[industry_name] = {
                "selected_count": len(selected.get(industry_name) or []),
                "success_count": len(rows),
                "failed_count": len(failed_rows),
                "avg_sample_size_used": _avg(rows, "sample_size_used"),
                "avg_mae_baseline": _avg(rows, "mae_baseline"),
                "avg_mae_adjusted": _avg(rows, "mae_adjusted"),
                "avg_mae_delta": _avg(rows, "mae_delta"),
                "avg_mae_delta_abs": _avg(rows, "mae_delta_abs"),
                "avg_mae_improvement_ratio": _avg(rows, "mae_improvement_ratio"),
                "avg_mae_improvement_pct": _avg(rows, "mae_improvement_pct"),
                "avg_mape_baseline": _avg(rows, "mape_baseline"),
                "avg_mape_adjusted": _avg(rows, "mape_adjusted"),
                "avg_mape_delta": _avg(rows, "mape_delta"),
                "avg_mape_delta_abs": _avg(rows, "mape_delta_abs"),
                "avg_mape_delta_pct_point": _avg(rows, "mape_delta_pct_point"),
                "avg_mape_improvement_ratio": _avg(rows, "mape_improvement_ratio"),
                "avg_mape_improvement_pct": _avg(rows, "mape_improvement_pct"),
                "avg_adjusted_better_rate": _avg(rows, "adjusted_better_rate"),
            }

        summary_payload = {
            "meta": {
                "industries": industry_names,
                "per_industry": per_industry,
                "year": year,
                "sample_size": sample_size,
                "seed": seed,
                "horizon": horizon,
                "min_trade_days": min_trade_days,
                "freq": freq,
                "market": market,
                "valuation_band_pct": band_pct,
                "style_profile": style_profile,
                "valuation_source": valuation_source,
                "allow_st": allow_st,
                "metrics_schema_version": "v2_abs_rel_pp",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "generation_mode": "dev_local_file_only_market_style_batch_backtest",
            },
            "selected_stocks": selected,
            "summary_by_industry": summary_by_industry,
            "details": detail_rows,
        }

        output_path = options.get("output")
        if output_path:
            output_file = Path(output_path)
        else:
            output_file = output_dir / f"market_style_batch_backtest_{year}.json"

        output_file.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(str(output_file))