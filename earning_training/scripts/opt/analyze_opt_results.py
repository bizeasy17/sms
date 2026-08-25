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

    auc_delta = row["delta_cls_auc"]
    mae_delta = row["delta_reg_mae"]
    return_delta = row["delta_avg_return"]
    hit_delta = row["delta_hit_rate"]
    drawdown_delta = row["delta_max_drawdown"]

    if all(value is not None for value in [auc_delta, mae_delta, return_delta, hit_delta, drawdown_delta]):
        if auc_delta > 0 and mae_delta <= 0 and return_delta > 0 and hit_delta >= 0 and drawdown_delta >= 0:
            return "优先候选：分类、回归和业务回放同步改善。"
        if auc_delta > 0 and return_delta > 0 and drawdown_delta >= 0:
            return "可进入复核：AUC、收益和回撤改善，检查年度切片后再定版。"
        if auc_delta > 0 and (return_delta < 0 or hit_delta < 0):
            return "仅离线改善：缩小参数步长，或调整选股 top_pct/概率校准后复测。"
        if return_delta > 0 and auc_delta <= 0:
            return "业务改善但分类退化：确认目标优先级，并检查是否过拟合回放窗口。"
        if drawdown_delta < 0:
            return "风险退化：不要替换基线，尝试更温和参数或更小 top_pct。"
    return "未形成稳定改善：保留基线并换下一个单变量方向。"


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

    rows = []
    for name, item in variants.items():
        policy = item["policy"]
        row = {
            "variant": name,
            "model_version": item.get("model_version"),
            "cls_acc": number(item.get("cls_acc")),
            "cls_auc": number(item.get("cls_auc")),
            "reg_mae": number(item.get("reg_mae")),
            "avg_return": number(policy.get("avg_return")),
            "hit_rate": number(policy.get("hit_rate")),
            "max_drawdown": number(policy.get("max_drawdown")),
            "annual_std": number(policy.get("annual_std")),
            "picked_rows": int(policy.get("picked_rows") or 0),
            "daily_points": int(policy.get("daily_points") or 0),
        }
        row["sample_sufficient"] = row["picked_rows"] >= 500 and row["daily_points"] >= 50
        row.update(
            {
                "delta_cls_acc": delta(row["cls_acc"], number(baseline.get("cls_acc"))),
                "delta_cls_auc": delta(row["cls_auc"], number(baseline.get("cls_auc"))),
                "delta_reg_mae": delta(row["reg_mae"], number(baseline.get("reg_mae"))),
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
        row for row in rows if row["variant"] != baseline_name and row["sample_sufficient"]
    ]
    candidates.sort(
        key=lambda row: (
            rank_value(row["delta_avg_return"]),
            rank_value(row["delta_cls_auc"]),
            rank_value(row["delta_max_drawdown"]),
        ),
        reverse=True,
    )

    lines = [
        f"# {report['report_type']} 优化结果建议",
        "",
        f"- 扫描参数：`{args.parameter}`",
        f"- 基线：`{baseline_name}`",
        f"- 固定选股比例：`{report['policy']['top_pct']}`",
        "",
        "## 指标汇总",
        "",
        "| variant | cls_acc | cls_auc | reg_mae | avg_return | hit_rate | max_drawdown | 样本/天数 | 建议 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {fmt(row['cls_acc'])} | {fmt(row['cls_auc'])} | "
            f"{fmt(row['reg_mae'])} | {fmt(row['avg_return'])} | {fmt(row['hit_rate'])} | "
            f"{fmt(row['max_drawdown'])} | {row['picked_rows']}/{row['daily_points']} | "
            f"{row['recommendation']} |"
        )

    lines.extend(["", "## 下一步", ""])
    if candidates:
        best = candidates[0]
        lines.append(f"当前综合排序第一：`{best['variant']}`。{best['recommendation']}")
    else:
        lines.append("没有达到最小回放样本要求的候选；先扩展数据覆盖，不输出参数优先级。")
    lines.extend(
        [
            "",
            "判断原则：`reg_mae` 越低越好；`cls_acc/cls_auc/avg_return/hit_rate/max_drawdown` 越高越好。",
            "最大回撤是负数，例如 `-0.40` 优于 `-0.60`。不要只按单一指标替换基线。",
        ]
    )
    (output_dir / "recommendation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written: {csv_path}")
    print(f"written: {output_dir / 'recommendation.md'}")


if __name__ == "__main__":
    main()
