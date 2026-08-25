# Q1/H1 P1 下一轮分类精度优化需求（2026-08-23）

## 1. 目标
- 在保留现有 Q1 F3 主候选可回滚的前提下，继续提升 Q1/H1 `target_fy_up` 分类精度。
- Q1 验证灰区阈值 `abs_min=0.07/0.09` 是否优于当前 `0.08` 主候选和已验证不推荐的 `0.06`。
- H1 迁移 Q1 F3 的“标签灰区 + 分类阈值校准”方法，补齐 H1 同口径实验。

## 2. 固定口径
- 数据库：UAT PostgreSQL。
- 分类目标：`target_fy_up`。
- 回归目标：`target_fy_value_yoy`。
- 不提升 serving，不替换生产指针。
- 训练后仍需用固定回放口径验证，不只看 `cls_acc/cls_auc`。

## 3. 新增实验配置
- Q1 scan07：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan07.yaml`
- Q1 scan09：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan09.yaml`
- H1 F3：`configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2_uat_ocf_fix_f3_grayzone_threshold.yaml`
- Q1 scan07/scan09 复用已存在的 `15y_20260719_q1_p1_f3_grayzone_threshold` 数据集版本，只新增模型产物。
- H1 F3 复用已存在的 `15y_20260402_uat_r1` 数据集版本，只新增模型产物。

## 4. 验收指标
- Q1：优先选择 `cls_acc/cls_auc` 改善且回放 `hit_rate/max_drawdown` 不劣于当前 F3 主候选的版本。
- H1：先比较 H1 OCF Fix 与 H1 F3 的 `cls_acc/cls_auc/reg_mae`，再做业务回放。
- 若离线分类提升但回放风险显著恶化，不作为替换候选。

## 5. 回滚点
- Q1 当前主候选：`uat_20260719_q1_p1_f3_grayzone_threshold`
- Q1 scan06 不推荐版本：`uat_20260723_q1_p1_f3_grayzone_threshold_scan06`
- H1 当前 OCF Fix：`uat_20260718_h1_ocf_fix`