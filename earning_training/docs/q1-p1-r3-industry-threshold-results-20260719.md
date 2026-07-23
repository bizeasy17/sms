# Q1 P1-R3 结果报告（行业子模型门槛优化，2026-07-19）

## 1. 实验目标
- 在不改特征/标签/数据的前提下，收紧行业子模型门槛，验证对 Q1 模型与回放稳定性的影响。

## 2. 实验配置
- baseline model: `uat_20260718_q1_ocf_fix_fy2`
- new model: `uat_20260719_q1_p1_r3_indthr`
- 配置文件：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2_p1_r3_indthr.yaml`
- 参数变化：
  - `industry_train_min_rows`: 300 -> 500
  - `industry_reg_min_rows`: 120 -> 200
  - `industry_eval_min_samples`: 150 -> 220

## 3. 训练指标对比
- baseline run_id: `20260718_232234_hgb_hgb_9b7121e6`
- new run_id: `20260719_100930_hgb_hgb_8f610365`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| cls_auc | 0.680059 | 0.680059 | 0.000000 |
| cls_acc | 0.667396 | 0.667396 | 0.000000 |
| reg_mae | 1.451747 | 1.451747 | 0.000000 |

## 4. 回放指标对比（固定 P0.1 策略）
- 策略口径：`top_pct=0.08, min_score=none, max_per_industry=none`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| avg_return | 0.022676 | 0.022676 | 0.000000 |
| hit_rate | 0.533174 | 0.533174 | 0.000000 |
| max_drawdown | -0.600832 | -0.600832 | 0.000000 |
| annual_std | 0.033570 | 0.033570 | 0.000000 |

## 5. 结论
- 本轮参数改动未带来可观测差异，训练与回放结果与 baseline 完全一致。
- 说明这些行业门槛在当前数据分布下未成为有效约束（未触发实际分支变化）。
- 判定：P1-R3 不进入主候选。

## 6. 下一轮建议
- 建议进入 P1-R4：训练窗口优化（例如 start_date 收缩到 2017）
- 或进入 P1-R4：更激进地关闭行业子模型，仅用全局模型做对照（use_industry_models=false）
