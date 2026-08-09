# Q1 P1-F3 灰区阈值扫描需求说明（2026-07-23）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：在当前 F3 优先候选基础上，仅对分类灰区阈值做窄幅扫描，验证是否可以在不破坏回放改善的前提下进一步提升 Q1 预测表现。

## 2. 变更范围
- 仅新增一个训练配置分支，不修改代码逻辑。
- 不改数据库 schema。
- 不改线上 API 请求/响应字段。
- 不改服务契约。

## 3. 接口变更计划
- 无外部接口变更。
- 仅增加一个实验配置：
  - `configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold_scan06.yaml`

## 4. 变更要点
- 以当前 F3 配置为基线。
- 仅调整：
  - `label.cls_gray_zone.abs_min: 0.08 -> 0.06`
- 其余训练参数保持不变，尤其保留：
  - `train.cls_threshold_tuning.enabled=true`
  - `label.cls_gray_zone.enabled=true`
  - `label.cls_gray_zone.metric_col=target_fy_value_yoy`

## 5. 验证计划
1. 训练 Q1 单报告类型模型。
2. 对比当前 F3 基线与新扫描版本的：
   - `cls_auc`
   - `cls_acc`
   - `reg_mae`
3. 继续用固定 P0.1 推荐策略回放对比：
   - `top_pct=0.08, min_score=none, max_per_industry=none`
4. 若新版本提升回放与分类指标，则考虑替换 UAT 候选；否则保留 F3 0.08 作为主候选。

## 6. 回滚点
- 当前主候选仍保留为 `uat_20260719_q1_p1_f3_grayzone_threshold`。
- 若 0.06 扫描不优于现有 F3，则不进入服务指针替换。