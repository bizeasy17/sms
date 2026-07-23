# Q1 P1-R1 结果报告（时间衰减增强，2026-07-19）

## 1. 实验目标
- 在不改特征、不改标签前提下，验证更强时间衰减是否改善 Q1 模型质量与业务表现。

## 2. 实验配置
- baseline model: `uat_20260718_q1_ocf_fix_fy2`
- new model: `uat_20260719_q1_p1_r1_decay20`
- 配置文件：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2_p1_r1_decay20.yaml`
- 参数变化：
  - `half_life_years`: 3.0 -> 2.0
  - `min_weight`: 0.60 -> 0.40
- 其他项保持不变。

## 3. 训练指标对比
- baseline run_id: `20260718_232234_hgb_hgb_9b7121e6`
- new run_id: `20260719_093520_hgb_hgb_70247c4d`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| cls_auc | 0.680059 | 0.684979 | +0.004920 |
| cls_acc | 0.667396 | 0.671073 | +0.003678 |
| reg_mae | 1.451747 | 1.444124 | -0.007623 |

## 4. 回放指标对比（固定 P0.1 策略）
- 策略口径：`top_pct=0.08, min_score=none, max_per_industry=none`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| avg_return | 0.022676 | 0.024326 | +0.001651 |
| hit_rate | 0.533174 | 0.537212 | +0.004039 |
| max_drawdown | -0.600832 | -0.659870 | -0.059038 |
| annual_std | 0.033570 | 0.036729 | +0.003159 |

## 5. 结论
- 正向：训练指标与回放收益、命中率均有提升。
- 负向：回撤与年度波动变差。
- 判定：P1-R1 为“收益增强型”方案，不满足当前“回撤优先”目标，不建议直接替换为主候选。

## 6. 建议下一步（P1-R2）
- 延续同一框架，尝试较温和衰减：
  - `half_life_years=2.5`
  - `min_weight=0.50`
- 目标：在保留部分收益提升的同时回收回撤劣化。
