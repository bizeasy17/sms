# Q1 P1-F2 结果报告（披露时效门控，2026-07-19）

## 1. 实验目标
- 在 P1-F1 披露时效特征基础上，新增“近30天门控”以压制陈旧披露信号，验证是否改善 Q1 回放表现。

## 2. 实验配置
- baseline model: `uat_20260718_q1_ocf_fix_fy2`
- new model: `uat_20260719_q1_p1_f2_disclosure_gate30`
- 配置文件：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f2_disclosure_gate30.yaml`
- 关键配置：`feature.disclosure_timeliness_gate_days=30`
- new run_id: `20260719_135529_hgb_hgb_0717efd7`

## 3. 训练指标对比

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| cls_auc | 0.680059 | 0.681725 | +0.001666 |
| cls_acc | 0.667396 | 0.665572 | -0.001824 |
| reg_mae | 1.451747 | 1.292484 | -0.159263 |

## 4. 回放指标对比（固定 P0.1 策略）
- 策略口径：`top_pct=0.08, min_score=none, max_per_industry=none`
- 对比产物：`output/local_valuation_checks/q1_p1_f2_vs_baseline_20260719.json`

| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| avg_return | -0.026660 | -0.029118 | -0.002458 |
| hit_rate | 0.317093 | 0.306915 | -0.010178 |
| max_drawdown | -0.632716 | -0.663490 | -0.030773 |
| annual_std | 0.000000 | 0.000000 | 0.000000 |

## 5. 结论
- 训练面：`cls_auc` 与 `reg_mae` 有改善，但 `cls_acc` 小幅下降。
- 回放面：收益、命中率、回撤仍劣于 baseline。
- 判定：P1-F2 不建议替代主候选 `uat_20260718_q1_ocf_fix_fy2`。

## 6. 备注
- F2 表现与此前 R4 结果数值一致，说明“30天门控”在当前实现下未带来新的组合层增益。
- 后续若继续推进时效方向，建议把门控改为“按 report_type 分层阈值”或“仅门控部分时效特征列”，避免整体信息过度压缩。
