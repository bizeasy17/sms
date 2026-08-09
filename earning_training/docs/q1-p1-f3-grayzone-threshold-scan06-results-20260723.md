# Q1 P1-F3 扫描结果报告（abs_min=0.06，2026-07-23）

## 1. 实验目标
- 在 F3 基线（abs_min=0.08）基础上，仅下调灰区阈值到 0.06，验证是否可继续提升 Q1 效果。

## 2. 实验配置
- baseline model: uat_20260719_q1_p1_f3_grayzone_threshold
- new model: uat_20260723_q1_p1_f3_grayzone_threshold_scan06
- new run_id: 20260723_100026_hgb_hgb_ad5ca3a3
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan06.yaml
- 固定回放策略：top_pct=0.08, min_score=none, max_per_industry=none

## 3. 训练指标对比

| 指标 | baseline(0.08) | new(0.06) | delta(new-baseline) |
|---|---:|---:|---:|
| cls_acc | 0.693283 | 0.704827 | +0.011545 |
| cls_auc | 0.734014 | 0.737066 | +0.003052 |
| reg_mae | 1.292484 | 1.294566 | +0.002082 |

说明：reg_mae 为越低越好，本次出现轻微回退。

## 4. 回放指标对比（固定 P0.1）

| 指标 | baseline(0.08) | new(0.06) | delta(new-baseline) |
|---|---:|---:|---:|
| avg_return | 0.028055 | 0.028067 | +0.000012 |
| hit_rate | 0.554964 | 0.549234 | -0.005730 |
| max_drawdown | -0.473363 | -0.601847 | -0.128483 |
| annual_std | 0.030982 | 0.033976 | +0.002994 |

## 5. 结论
- 新版本在分类指标上继续提升，但回放风险明显变差：
  - 最大回撤显著恶化（更负）
  - 命中率下降
  - 年度波动上升
- 综合判定：scan06 不建议替换当前 F3 主候选。

## 6. 建议
1. 继续保留 uat_20260719_q1_p1_f3_grayzone_threshold 作为当前候选。
2. 若继续扫描灰区阈值，优先尝试 0.07 或 0.09 的窄幅对照，并继续使用同一固定回放口径。

## 7. 产物路径
- outputs/local_valuation_checks/q1_p1_f3_scan06_vs_f3_20260723.json