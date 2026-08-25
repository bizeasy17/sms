# Q1/H1 P1 下一轮分类精度优化结果（2026-08-23）

## 1. 实验范围
- Q1：在当前 F3 主候选基础上补充 `abs_min=0.07/0.09` 灰区阈值扫描，并与 `0.06/0.08` 对比。
- H1：迁移 Q1 F3 的“标签灰区 + 分类阈值校准”方案，和 H1 OCF Fix/旧 H1 基线对比。
- 本轮不提升 serving，不替换生产指针。

## 2. 新增产物
- Q1 scan07：`outputs/model_versions/uat_20260823_q1_p1_f3_grayzone_threshold_scan07/`
- Q1 scan09：`outputs/model_versions/uat_20260823_q1_p1_f3_grayzone_threshold_scan09/`
- H1 F3：`outputs/model_versions/uat_20260823_h1_p1_f3_grayzone_threshold/`
- Q1 回放：`outputs/local_valuation_checks/q1_p1_f3_scan07_scan09_vs_f3_20260823.json`
- H1 回放：`outputs/local_valuation_checks/h1_p1_f3_vs_baselines_20260823.json`

## 3. Q1 训练指标
| variant | abs_min | threshold | cls_acc | cls_auc | reg_mae |
|---|---:|---:|---:|---:|---:|
| F3 | 0.08 | 0.53 | 0.693283 | 0.734014 | 1.292484 |
| scan06 | 0.06 | 0.58 | 0.704827 | 0.737066 | 1.294566 |
| scan07 | 0.07 | 0.63 | 0.698351 | 0.739414 | 1.292484 |
| scan09 | 0.09 | 0.59 | 0.701874 | 0.736837 | 1.292484 |

## 4. Q1 固定 Top 8% 回放指标
| variant | avg_return | hit_rate | max_drawdown | annual_std |
|---|---:|---:|---:|---:|
| F3 | 0.028055 | 0.554964 | -0.473363 | 0.030982 |
| scan06 | 0.028067 | 0.549234 | -0.601847 | 0.033976 |
| scan07 | 0.033291 | 0.561621 | -0.434444 | 0.028781 |
| scan09 | 0.028353 | 0.554276 | -0.421796 | 0.027756 |

Q1 结论：
- `scan07` 是本轮最佳候选，`cls_auc`、回放收益、命中率、最大回撤均优于当前 F3 主候选。
- `scan09` 的 `cls_acc` 更高、回撤更低，但收益和命中率改善弱于 `scan07`。
- `scan06` 虽然 `cls_acc` 最高，但回撤明显恶化，继续不建议替换。

## 5. H1 训练指标
| variant | abs_min | threshold | cls_acc | cls_auc | reg_mae |
|---|---:|---:|---:|---:|---:|
| old_base | - | - | 0.758405 | 0.816138 | 1.078519 |
| ocf_fix | - | - | 0.705005 | 0.747268 | 1.320003 |
| h1_f3 | 0.08 | 0.52 | 0.748221 | 0.818933 | 1.183705 |

## 6. H1 Top 10% 回放指标
| variant | avg_return | hit_rate | max_drawdown | annual_std |
|---|---:|---:|---:|---:|
| old_base | 0.062253 | 0.602689 | -0.976922 | 0.059142 |
| ocf_fix | 0.010159 | 0.464811 | -0.999296 | 0.030344 |
| h1_f3 | 0.003480 | 0.425135 | -0.999531 | 0.028548 |

H1 结论：
- 相对 `ocf_fix`，`h1_f3` 明显修复离线分类：`cls_acc +0.043216`、`cls_auc +0.071665`、`reg_mae -0.136298`。
- 但 `h1_f3` 的 Top10 回放收益和命中率低于 `ocf_fix`，因此不建议直接替换 H1 serving。
- 旧基线加载时存在 sklearn 1.7.1/1.8.0 版本告警，旧基线回放仅作方向参考；`ocf_fix` 与 `h1_f3` 为同环境新产物，可直接比较。

## 7. 建议
1. Q1 将 `scan07` 作为新的优先候选，进入更宽窗口/年度切片复核。
2. Q1 若偏风险优先，可保留 `scan09` 作为备选；若偏收益与命中率，优先 `scan07`。
3. H1 不直接发布 `h1_f3`，下一步应扫描 `abs_min=0.04/0.06/0.10`，寻找分类改善与回放收益之间的折中。
4. H1 还需要排查 OCF Fix 后样本规模与业务回放弱化原因，避免只靠灰区过滤修离线指标。

## 8. 已执行命令
```powershell
c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe manage.py check
c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe manage.py train_report_type_models --config configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan07.yaml --report-types Q1 --no-rebuild-dataset --keep-separated-artifacts
c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe manage.py train_report_type_models --config configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan09.yaml --report-types Q1 --no-rebuild-dataset --keep-separated-artifacts
c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe manage.py train_report_type_models --config configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2_uat_ocf_fix_f3_grayzone_threshold.yaml --report-types H1 --no-rebuild-dataset --keep-separated-artifacts
c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe scripts/q1h1_variant_replay_eval.py --report-type Q1 --top-pct 0.08 --out outputs/local_valuation_checks/q1_p1_f3_scan07_scan09_vs_f3_20260823.json --variant f3=uat_20260719_q1_p1_f3_grayzone_threshold=configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold.yaml --variant scan06=uat_20260723_q1_p1_f3_grayzone_threshold_scan06=configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan06.yaml --variant scan07=uat_20260823_q1_p1_f3_grayzone_threshold_scan07=configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan07.yaml --variant scan09=uat_20260823_q1_p1_f3_grayzone_threshold_scan09=configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan09.yaml
c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe scripts/q1h1_variant_replay_eval.py --report-type H1 --top-pct 0.10 --out outputs/local_valuation_checks/h1_p1_f3_vs_baselines_20260823.json --variant old_base=dev_20260503_h1_oos2024_cut20231231_fy2=configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2.yaml --variant ocf_fix=uat_20260718_h1_ocf_fix=configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2_uat_ocf_fix.yaml --variant h1_f3=uat_20260823_h1_p1_f3_grayzone_threshold=configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2_uat_ocf_fix_f3_grayzone_threshold.yaml
```
