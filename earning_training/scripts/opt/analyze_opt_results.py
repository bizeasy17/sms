from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def rank_value(value: float | None) -> float:
    return -999.0 if value is None else value


def recommendation(row: dict[str, Any]) -> str:
    if not row["sample_sufficient"]:
        return "样本不足：先扩展回放窗口或检查收益标签覆盖，不据此调参。"
    if not row["drawdown_pass"]:
        return "回撤超限：不进入候选，优先降低仓位或提高置信度阈值。"
    if row["positive_fold_ratio"] < 0.5:
        return "滚动窗口不稳定：多数时间窗未盈利，不进入候选。"

    return_delta = row["delta_avg_return"]
    drawdown_delta = row["delta_max_drawdown"]

    if return_delta is not None and drawdown_delta is not None:
        if return_delta > 0 and drawdown_delta >= 0:
            return "优先候选：净收益提升、回撤未恶化且滚动窗口通过。"
        if return_delta > 0:
            return "收益改善但回撤变深：仅进入风险参数复核，不直接替换基线。"
    return "交易收益未改善：保留基线，不因分类指标提升而替换。"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize replay JSON and generate parameter-adjustment advice.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--parameter", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = json.loads(input_path.read_text(encoding="utf-8"))
    variants = report["variants"]
    baseline_name = report["baseline_variant"]
    baseline = variants[baseline_name]
    baseline_policy = baseline["policy"]
    backtest_window = baseline.get("backtest_window") or {}
    drawdown_limit = number((report.get("policy") or {}).get("max_allowed_drawdown")) or -0.30

    rows = []
    for name, item in variants.items():
        policy = item["policy"]
        walk_forward = policy.get("walk_forward") or {}
        row = {
            "variant": name,
            "model_version": item.get("model_version"),
            "cls_acc": number(item.get("cls_acc")),
            "cls_auc": number(item.get("cls_auc")),
            "reg_mae": number(item.get("reg_mae")),
            "total_return": number(policy.get("total_return")),
            "avg_return": number(policy.get("avg_return")),
            "hit_rate": number(policy.get("hit_rate")),
            "max_drawdown": number(policy.get("max_drawdown")),
            "annual_std": number(policy.get("annual_std")),
            "avg_turnover": number(policy.get("avg_turnover")),
            "total_cost": number(policy.get("total_cost")),
            "avg_exposure": number(policy.get("avg_exposure")),
            "positive_fold_ratio": number(walk_forward.get("positive_fold_ratio")) or 0.0,
            "worst_fold_return": number(walk_forward.get("worst_fold_return")),
            "picked_rows": int(policy.get("picked_rows") or 0),
            "daily_points": int(policy.get("daily_points") or 0),
        }
        row["sample_sufficient"] = row["picked_rows"] >= 500 and row["daily_points"] >= 50
        row["drawdown_pass"] = row["max_drawdown"] is not None and row["max_drawdown"] >= drawdown_limit
        row.update(
            {
                "delta_cls_acc": delta(row["cls_acc"], number(baseline.get("cls_acc"))),
                "delta_cls_auc": delta(row["cls_auc"], number(baseline.get("cls_auc"))),
                "delta_reg_mae": delta(row["reg_mae"], number(baseline.get("reg_mae"))),
                "delta_total_return": delta(row["total_return"], number(baseline_policy.get("total_return"))),
                "delta_avg_return": delta(row["avg_return"], number(baseline_policy.get("avg_return"))),
                "delta_hit_rate": delta(row["hit_rate"], number(baseline_policy.get("hit_rate"))),
                "delta_max_drawdown": delta(row["max_drawdown"], number(baseline_policy.get("max_drawdown"))),
            }
        )
        row["recommendation"] = "基线" if name == baseline_name else recommendation(row)
        rows.append(row)

    csv_path = output_dir / "summary.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    candidates = [
        row
        for row in rows
        if row["variant"] != baseline_name
        and row["sample_sufficient"]
        and row["drawdown_pass"]
        and row["positive_fold_ratio"] >= 0.5
    ]
    candidates.sort(
        key=lambda row: (
            rank_value(row["avg_return"]),
            rank_value(row["positive_fold_ratio"]),
            rank_value(row["worst_fold_return"]),
            rank_value(row["delta_max_drawdown"]),
            rank_value(row["delta_cls_auc"]),
        ),
        reverse=True,
    )

    lines = [
        f"# {report['report_type']} 优化结果建议",
        "",
        f"- 扫描参数：`{args.parameter}`",
        f"- 基线：`{baseline_name}`",
        f"- 年度回测窗口：`{report.get('backtest_start_month', backtest_window.get('start_month', 1))}` 月至次年 `{report.get('backtest_end_month', backtest_window.get('end_month', 12))}` 月" if report.get('backtest_start_month', backtest_window.get('start_month', 1)) > report.get('backtest_end_month', backtest_window.get('end_month', 12)) else f"- 年度回测窗口：每年 `{report.get('backtest_start_month', backtest_window.get('start_month', 1))}` 月至 `{report.get('backtest_end_month', backtest_window.get('end_month', 12))}` 月",
        f"- 实际日期覆盖：`{backtest_window.get('start_date', '-')}` 至 `{backtest_window.get('end_date', '-')}`（过滤前/后交易日：{backtest_window.get('unfiltered_dates', '-')}/{backtest_window.get('filtered_dates', '-')}）",
        f"- 固定选股比例：`{report['policy']['top_pct']}`",
        f"- 最低概率：`{report['policy'].get('min_score', '-')}`",
        f"- 最大回撤门槛：`{drawdown_limit}`",
        f"- 成本假设：commission=`{report['policy'].get('commission', '-')}`，slippage=`{report['policy'].get('slippage', '-')}`",
        "",
        "## 指标汇总",
        "",
        "| variant | avg_net_return | compounded_return | max_drawdown | WF正收益率 | 最差WF | avg_exposure | turnover | cost | cls_auc | 样本/天数 | 建议 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {fmt(row['avg_return'])} | {fmt(row['total_return'])} | {fmt(row['max_drawdown'])} | "
            f"{fmt(row['positive_fold_ratio'])} | {fmt(row['worst_fold_return'])} | "
            f"{fmt(row['avg_exposure'])} | {fmt(row['avg_turnover'])} | {fmt(row['total_cost'])} | "
            f"{fmt(row['cls_auc'])} | {row['picked_rows']}/{row['daily_points']} | "
            f"{row['recommendation']} |"
        )

    lines.extend(["", "## 下一步", ""])
    if candidates:
        best = candidates[0]
        lines.append(f"当前综合排序第一：`{best['variant']}`。{best['recommendation']}")
    else:
        lines.append("没有同时满足样本量、最大回撤和 walk-forward 稳定性门槛的候选。")
    lines.extend(
        [
            "",
            "判断原则：先满足最大回撤与 walk-forward 稳定性门槛，再按扣除成本后的平均组合收益排序。",
            "复利收益仅用于观察资金路径；标签持有期可能重叠，不作为参数优化主目标。",
            "`cls_acc/cls_auc/reg_mae` 仅作模型诊断，不再覆盖交易收益结论。",
            "回撤控制会降低后续仓位，但无法防止单期跳空直接穿越硬门槛。",
        ]
    )
    (output_dir / "recommendation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written: {csv_path}")
    print(f"written: {output_dir / 'recommendation.md'}")


if __name__ == "__main__":
    main()
