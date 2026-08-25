# Q1 优化步骤台账（截至 2026-07-19）

## 1. 总览
- 目的：按步骤追踪 Q1 优化过程，确保每一步都有“需求->执行->结果->产物”记录。
- 当前状态：P0 与 P0.1 已记录完成，可进入 P1。

## 2. 步骤记录

### Step A: OCF 特征修复与同口径重训
- 需求文档：docs/q1-ocf-fix-fyup-fy2-retrain-requirement-20260718.md
- 关键配置：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2.yaml
- 训练结果：outputs/model_versions/uat_20260718_q1_ocf_fix_fy2/metrics_Q1.json
- 对比报告：docs/q1-h1-ocf-fix-business-replay-comparison-20260719.md
- 结论：Q1 在 target_fy_up 同口径下可训练可比；收益/命中率改善但回撤更深。

### Step B: P0.1 回撤收敛（策略后处理）
- 需求文档：docs/q1-p01-risk-convergence-requirement-20260719.md
- 扫描脚本：scripts/q1_p01_risk_tuning.py
- 原始产物：outputs/local_valuation_checks/q1_p01_risk_tuning_20260719/
- 结果报告：docs/q1-p01-risk-tuning-results-20260719.md
- 结论：top_pct 从 10% 调整到 8% 可在维持收益附近的同时收敛回撤。

### Step C: P1-R1 模型本体优化（时间衰减增强）
- 需求文档：docs/q1-p1-r1-time-decay-requirement-20260719.md
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2_p1_r1_decay20.yaml
- 结果报告：docs/q1-p1-r1-time-decay-results-20260719.md
- 模型产物：outputs/model_versions/uat_20260719_q1_p1_r1_decay20/
- 结论：训练与收益提升，但回撤与波动恶化，不作为主候选。

### Step D: P1-R2 模型本体优化（温和时间衰减）
- 需求文档：docs/q1-p1-r2-time-decay-requirement-20260719.md
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2_p1_r2_decay25.yaml
- 结果报告：docs/q1-p1-r2-time-decay-results-20260719.md
- 模型产物：outputs/model_versions/uat_20260719_q1_p1_r2_decay25/
- 结论：训练指标小幅改善，但回放收益和风险均劣于 baseline，不作为主候选。

### Step E: P1-R3 模型本体优化（行业门槛收紧）
- 需求文档：docs/q1-p1-r3-industry-threshold-requirement-20260719.md
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2_p1_r3_indthr.yaml
- 结果报告：docs/q1-p1-r3-industry-threshold-results-20260719.md
- 模型产物：outputs/model_versions/uat_20260719_q1_p1_r3_indthr/
- 结论：训练与回放指标与 baseline 完全一致（delta 全为 0），不进入主候选。

### Step F: P1-R4 模型本体优化（训练窗口收缩）
- 需求文档：docs/q1-p1-r4-train-window-requirement-20260719.md
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2_p1_r4_start2017.yaml
- 结果报告：docs/q1-p1-r4-train-window-results-20260719.md
- 模型产物：outputs/model_versions/uat_20260719_q1_p1_r4_start2017/
- 结论：训练面部分改善，但回放收益、命中率和回撤均未优于 baseline，不作为主候选。

### Step G: P1-F1 特征优化（披露时效特征）
- 需求文档：docs/q1-p1-f1-disclosure-timeliness-requirement-20260719.md
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f1_disclosure.yaml
- 代码变更：earnings_forecast/services/pipeline.py（新增披露时效特征）
- 模型产物：outputs/model_versions/uat_20260719_q1_p1_f1_disclosure/
- 对比产物：output/local_valuation_checks/q1_p1_f1_vs_baseline_20260719.json
- 结果报告：docs/q1-p1-f1-disclosure-timeliness-results-20260719.md
- 结论：训练指标有局部改善，但固定策略回放收益/命中率/回撤均劣于 baseline，不作为主候选。

### Step H: P1-F2 特征优化（披露时效门控 30 天）
- 需求文档：docs/q1-p1-f2-disclosure-gate-requirement-20260719.md
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f2_disclosure_gate30.yaml
- 代码变更：earnings_forecast/services/pipeline.py（新增 `disclosure_timeliness_gate_days` 配置门控）
- 模型产物：outputs/model_versions/uat_20260719_q1_p1_f2_disclosure_gate30/
- 对比产物：output/local_valuation_checks/q1_p1_f2_vs_baseline_20260719.json
- 结果报告：docs/q1-p1-f2-disclosure-gate-results-20260719.md
- 结论：回放收益、命中率、回撤仍未优于 baseline，不作为主候选。

### Step I: P1-F3 训练策略优化（标签灰区 + 阈值校准）
- 需求文档：docs/q1-p1-f3-grayzone-threshold-requirement-20260719.md
- 配置文件：configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold.yaml
- 代码变更：earnings_forecast/services/pipeline.py（新增分类灰区过滤与阈值扫描）
- 模型产物：outputs/model_versions/uat_20260719_q1_p1_f3_grayzone_threshold/
- 对比产物：output/local_valuation_checks/q1_p1_f3_vs_baseline_20260719.json
- 结果报告：docs/q1-p1-f3-grayzone-threshold-results-20260719.md
- 结论：`cls_auc` 提升至 0.734、`cls_acc` 提升至 69.33%，且固定策略回放收益/命中率/回撤同步改善，进入优先候选。

### Step J: P1-F3 窄幅扫描（abs_min=0.07/0.09）
- 需求文档：docs/q1-h1-p1-next-round-optimization-requirement-20260823.md
- 配置文件：
  - configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan07.yaml
  - configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan09.yaml
- 模型产物：
  - outputs/model_versions/uat_20260823_q1_p1_f3_grayzone_threshold_scan07/
  - outputs/model_versions/uat_20260823_q1_p1_f3_grayzone_threshold_scan09/
- 对比产物：outputs/local_valuation_checks/q1_p1_f3_scan07_scan09_vs_f3_20260823.json
- 结果报告：docs/q1-h1-p1-next-round-optimization-results-20260823.md
- 结论：`scan07` 在 `cls_auc`、Top8 收益、命中率、回撤上同时优于 F3，成为新的 Q1 优先候选；`scan09` 可作为风险优先备选。

### Step K: H1-F3 训练策略迁移（标签灰区 + 阈值校准）
- 需求文档：docs/q1-h1-p1-next-round-optimization-requirement-20260823.md
- 配置文件：configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2_uat_ocf_fix_f3_grayzone_threshold.yaml
- 模型产物：outputs/model_versions/uat_20260823_h1_p1_f3_grayzone_threshold/
- 对比产物：outputs/local_valuation_checks/h1_p1_f3_vs_baselines_20260823.json
- 结果报告：docs/q1-h1-p1-next-round-optimization-results-20260823.md
- 结论：离线分类相对 H1 OCF Fix 明显改善，但 Top10 回放收益与命中率下降，不作为直接替换候选。

## 3. 记录完整性检查
- 需求记录：已覆盖
- 配置/脚本记录：已覆盖
- 指标结果记录：已覆盖
- 结论与下一步建议：已覆盖

## 4. P1 记录规范（执行时遵循）
- 每个 P1 子实验新增一页：
  - docs/q1-p1-<topic>-requirement-YYYYMMDD.md
  - docs/q1-p1-<topic>-results-YYYYMMDD.md
- 每页至少包含：
  - 目标
  - 变更点
  - 训练/回放命令
  - 关键指标与对比
  - 结论与回滚点
