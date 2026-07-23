# Q1 P1-R2 结果报告（温和时间衰减，2026-07-19）

## 1. 实验目标
- 在 P1-R1 基础上使用更温和时间衰减，评估是否能同时保持模型质量并改善回撤表现。

## 2. 实验配置
- baseline model: `uat_20260718_q1_ocf_fix_fy2`
- new model: `uat_20260719_q1_p1_r2_decay25`
- 配置文件：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2_p1_r2_decay25.yaml`
- 参数变化：
  - `half_life_years`: 3.0 -> 2.5
  - `min_weight`: 0.60 -> 0.50

## 3. 训练指标对比
- baseline run_id: `20260718_232234_hgb_hgb_9b7121e6`
- new run_id: `20260719_095742_hgb_hgb_bcf6eb7d`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| cls_auc | 0.680059 | 0.684514 | +0.004454 |
| cls_acc | 0.667396 | 0.667717 | +0.000321 |
| reg_mae | 1.451747 | 1.444121 | -0.007626 |

## 4. 回放指标对比（固定 P0.1 策略）
- 策略口径：`top_pct=0.08, min_score=none, max_per_industry=none`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| avg_return | 0.022676 | 0.021750 | -0.000926 |
| hit_rate | 0.533174 | 0.523676 | -0.009497 |
| max_drawdown | -0.600832 | -0.663856 | -0.063024 |
| annual_std | 0.033570 | 0.036291 | +0.002721 |

## 5. 结论
- 训练面：分类 AUC、回归 MAE 有小幅改善。
- 回放面：收益、命中率、回撤、波动均劣于 baseline。
- 判定：P1-R2 不满足当前目标，不建议进入主候选链路。

## 6. 与 P1-R1 对照判断
- P1-R1：收益改善但回撤恶化。
- P1-R2：收益未改善且回撤仍恶化。
- 说明仅通过时间衰减强化，当前方向难以兼顾收益与风险，P1 下一步建议切到其他维度（如训练窗口或行业门槛）。
