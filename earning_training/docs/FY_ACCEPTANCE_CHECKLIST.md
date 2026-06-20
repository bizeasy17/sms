# FY 监督标签验收清单（DEV/UAT 实测）

## 目标

验证 FY 监督任务是否真正落地并可上线，覆盖：

1. 标签定义正确性
2. 训练目标配置生效
3. 数据切片与样本有效性
4. 评估结果可解释
5. DEV/UAT 一致性

## 验收标准

- A1: 分类目标列必须为 `target_fy_up`。
- A2: 回归目标列必须为 `target_fy_value_yoy`。
- A3: Q1/H1/Q3 训练数据中 FY 行比例应为 0（当 `exclude_fy_rows_for_training=true`）。
- A4: `target_fy_up` 与 `target_fy_value_yoy>0` 一致率应接近 1.0。
- A5: DEV/UAT 在同版本数据上关键样本统计一致。

## 实测范围

- DEV: `code/sms/tushare_earnings_service/outputs`
- UAT: `web/UAT/tushare_earnings_service/outputs`
- DEV 最新数据集版本: `15y_20260402_r1`
- UAT 当前 serving 数据集版本: `15y_20260331_r3`
- 分报告期分片: Q1/H1/Q3

## 实测结果

### 1) 训练目标列与最新 DEV 实测（来自 metrics_*.json）

| 环境 | 报告期 | cls_target_col | reg_target_col | cls_acc | cls_auc | reg_mae | 结论 |
|---|---|---|---|---:|---:|---:|---|
| DEV | Q1 | target_fy_up | target_fy_value_yoy | 0.7076 | 0.7777 | 1.1085 | A1/A2 通过 |
| DEV | H1 | target_fy_up | target_fy_value_yoy | 0.7550 | 0.8447 | 1.0401 | A1/A2 通过 |
| DEV | Q3 | target_fy_up | target_fy_value_yoy | 0.7824 | 0.8683 | 0.9783 | A1/A2 通过 |
| UAT | Q3 serving | target_valuation_up | target_fy_value_yoy | - | - | - | 仍为旧 serving 版本 |

结论：DEV 分类任务已切换到 `target_fy_up`，FY 分类监督生效。UAT 当前 serving 尚未切换到新版本。

### 2) 数据集 FY 标签覆盖（DEV 最新版本）

旧版本 `15y_20260331_r3` 的主要问题不是 FY 标签定义错误，而是 FY 标签构建依赖 dataset 中显式出现 FY 行，导致大量被次年 Q1 披露覆盖的 FY 年报无法回填到 Q1/H1/Q3。

本轮修复后：

- FY 标签改为直接从 financial feature panel 构建 `ts_code + fiscal_year` 映射，再回填到 dataset。
- Q1/H1/Q3 的理论 FY 标签缺失率从约 `43.93%` 降到约 `8.39%`。
- FY 行自身缺失率保持为 `0%`。

结论：A3/A4 通过，且 FY 标签覆盖已显著改善。

### 3) DEV/UAT 一致性

- DEV 已完成 FY 标签构建修复并重新训练。
- UAT 当前作为对外 service 环境，不做训练；其 `serving.yaml` 已修正到 UAT 本地路径，但 serving 版本仍是旧模型旧数据集。
- 因此当前 A5 只能判定为“环境隔离通过，serving 版本尚未同步”。

## 总结判定

- DEV 通过项：A1, A2, A3, A4
- UAT 通过项：环境隔离、refresh 可用
- UAT 待完成项：切 serving 到新 FY 监督版本
- 当前总判定：**DEV 通过，UAT 待发布新 serving 版本**

## 建议后续动作

1. 将 DEV 当前新版本模型发布到 UAT serving。
2. 在 UAT 执行一次 `refresh_signal_snapshot --serving-slot production` 验证线上读路。
3. 如需保留旧版本回滚能力，在 UAT `serving.yaml` 中保留 candidate/production 双槽。
4. 后续继续关注 Q3 的 `cls_acc` 与阈值校准，但当前 `cls_auc` 已优于旧版。

## 本次实测命令（留档）

在 `code/sms/tushare_earnings_service` 下执行：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe -c "..."
```

该脚本读取 DEV/UAT 的 `metrics_*.json` 与 `datasets_by_report_type/dataset_{Q1,H1,Q3}.parquet`，统计目标列、覆盖率、一致性与 FY 行比例。
