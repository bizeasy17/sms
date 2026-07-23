# Q1 P1-F4 需求说明（历史 A 方案 UAT 复刻）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：将历史表现较好的 `dev_20260429_q1_exp_r3_cls_a` 方案迁移到当前 UAT 数据口径下，验证其是否仍能实现 `reg_mae < 1`，并与当前 F3 候选进行对比。

## 2. 变更范围
- 配置变更：新增 UAT 复刻配置文件。
- 训练验证：使用当前 UAT 数据链路重训 Q1。
- 不改线上 API，不改数据库 schema。

## 3. DB/API 合同确认
- 数据库字段：无新增/无修改。
- API 请求字段：无新增/无修改。
- API 响应字段：无新增/无修改。

## 4. 接口变更计划
- 无外部接口变更。
- 仅复刻训练配置：
  - 采用旧 A 的训练策略参数
  - 切到当前 UAT 数据源与当前训练管道

## 5. 实现要点
1. 以历史 A 的关键参数为主：
  - `fy_test_years=1`（按历史 A 口径保留），且分类目标固定优先使用 `target_fy_up`，不因测试集评估不足自动回退为 `target_valuation_up`
   - 不启用 `cls_gray_zone`
   - 不启用 `cls_threshold_tuning`
   - `industry_eval_min_samples=200`
   - `industry_train_min_rows=400`
   - `time_decay.half_life_years=2.5`
   - `time_decay.min_weight=0.70`
2. 保持当前 UAT 数据表、目录结构与训练代码。
3. 训练完成后，与当前 F3 和 baseline 对比。

## 6. 验证计划
1. 训练 `uat_20260720_q1_p1_f4_legacy_a_replica`。
2. 输出训练指标：`reg_mae`, `cls_acc`, `cls_auc`。
3. 必要时再做固定策略回放对比。

## 7. 回滚点
- 当前优先候选仍为 F3。
- 若 F4 无法复现旧 A 优势，则仅保留为对照实验。
