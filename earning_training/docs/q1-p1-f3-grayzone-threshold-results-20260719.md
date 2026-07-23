# Q1 P1-F3 结果报告（标签灰区 + 阈值校准，2026-07-19）

## 1. 实验目标
- 通过分类灰区样本过滤与分类阈值扫描，提升 Q1 分类能力上限（优先 `cls_acc`、`cls_auc`）。

## 2. 实验配置
- baseline model: `uat_20260718_q1_ocf_fix_fy2`
- new model: `uat_20260719_q1_p1_f3_grayzone_threshold`
- 配置文件：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold.yaml`
- 关键参数：
  - `label.cls_gray_zone.enabled=true`
  - `label.cls_gray_zone.abs_min=0.08`
  - `label.cls_gray_zone.metric_col=target_fy_value_yoy`
  - `train.cls_threshold_tuning.enabled=true`
  - `train.cls_threshold_tuning[min,max,step]=[0.35,0.70,0.01]`
- new run_id: `20260719_143741_hgb_hgb_31f265ae`
- 训练选出的分类阈值：`0.53`

## 3. 训练指标对比

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| cls_auc | 0.680059 | 0.734014 | +0.053955 |
| cls_acc | 0.667396 | 0.693283 | +0.025887 |
| reg_mae | 1.451747 | 1.292484 | -0.159263 |

## 4. 回放指标对比（固定 P0.1 策略）
- 策略口径：`top_pct=0.08, min_score=none, max_per_industry=none`
- 对比产物：`output/local_valuation_checks/q1_p1_f3_vs_baseline_20260719.json`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| avg_return | -0.026660 | -0.018769 | +0.007891 |
| hit_rate | 0.317093 | 0.354662 | +0.037569 |
| max_drawdown | -0.632716 | -0.528483 | +0.104233 |
| annual_std | 0.000000 | 0.000000 | 0.000000 |

## 5. 结论
- F3 显著提升了分类能力：`cls_auc` 达到 `0.734`，`cls_acc` 提升至 `69.33%`。
- 固定策略回放同步改善：收益、命中率、最大回撤均优于 baseline。
- 判定：P1-F3 成为新的优先候选版本（建议进入下一轮稳定性复核）。

## 6. 备注
- `cls_acc` 尚未达到 70%，但已经接近目标，且 `cls_auc` 已明显超过 0.70。
- 下一步建议在不破坏回放改善的前提下，做小范围灰区阈值微调（例如 `abs_min` 在 0.06~0.10 扫描）。
