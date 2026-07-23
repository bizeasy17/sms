# Q1 P1-F1 结果报告（披露时效特征，2026-07-19）

## 1. 实验目标
- 在不改标签、模型结构与策略口径的前提下，验证“披露时效特征”是否能改善 Q1 的训练与回放表现。

## 2. 实验配置
- baseline model: `uat_20260718_q1_ocf_fix_fy2`
- new model: `uat_20260719_q1_p1_f1_disclosure`
- 配置文件：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f1_disclosure.yaml`
- 代码变更：`earnings_forecast/services/pipeline.py`
  - 新增：`ann_date_missing`
  - 新增：`ann_date_lag_clipped_180d`
  - 新增：`ann_freshness_score`
  - 新增：`ann_is_recent_7d`
  - 新增：`ann_is_recent_30d`
  - 新增：`report_end_lag_days`
  - 新增：`report_end_lag_clipped_365d`

## 3. 训练执行与修复记录
- 首轮失败原因：`dataset_file` 包含子目录，写 parquet 前未确保父目录存在。
- 修复：在 `prepare_dataset` 中补充目录创建。
- 最终训练状态：成功。
- new run_id: `20260719_114656_hgb_hgb_6cc28f23`

## 4. 训练指标对比

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| cls_auc | 0.680059 | 0.678905 | -0.001154 |
| cls_acc | 0.667396 | 0.668677 | +0.001282 |
| reg_mae | 1.451747 | 1.292484 | -0.159263 |

## 5. 回放指标对比（固定 P0.1 策略）
- 策略口径：`top_pct=0.08, min_score=none, max_per_industry=none`
- 对比产物：`output/local_valuation_checks/q1_p1_f1_vs_baseline_20260719.json`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| avg_return | -0.026660 | -0.031349 | -0.004689 |
| hit_rate | 0.317093 | 0.295091 | -0.022003 |
| max_drawdown | -0.632716 | -0.690918 | -0.058202 |
| annual_std | 0.000000 | 0.000000 | 0.000000 |

## 6. 结论
- 训练面：`cls_acc` 与 `reg_mae` 有改善，但 `cls_auc` 小幅回落。
- 回放面：收益、命中率、回撤均劣于 baseline，且负收益加深。
- 判定：P1-F1 不建议替代当前主候选 `uat_20260718_q1_ocf_fix_fy2`。

## 7. 备注
- 这一步验证了“时效特征有效提升部分离线拟合指标”不必然转化为组合层收益改善。
- 下一步优先考虑：
  - 对时效特征做更强约束（例如仅在特定 report_type 或滞后窗口内启用）。
  - 与更明确的风险过滤联动，而不是直接全量入模。
