# Q1 P1-R1 需求说明（时间衰减增强）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：在 P0.1 后，开始模型本体优化第 1 步，验证更强时间衰减是否能改善 Q1 泛化与回放稳定性。

## 2. 变更范围
- 仅修改训练配置参数，不改代码逻辑。
- 基于 `default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2.yaml` 新建实验配置。
- 仅调 `train.sample_weight.time_decay`：
  - `half_life_years`: 3.0 -> 2.0
  - `min_weight`: 0.60 -> 0.40
  - `max_weight`: 1.00 (保持)

## 3. DB/API 合同确认
- 数据库字段：无新增/无修改。
- API 请求字段：无新增/无修改。
- API 响应字段：无新增/无修改。
- 仅影响离线训练产物与离线回放结果。

## 4. 接口变更计划
- 无线上接口变更。
- 仅新增模型版本目录与实验报告。

## 5. 验证计划
1. 训练 Q1 单报告类型模型并记录 `metrics_Q1.json`。
2. 用同一数据集做业务回放对比：
   - 基线模型：`uat_20260718_q1_ocf_fix_fy2`
   - 新模型：`uat_20260719_q1_p1_r1_decay20`
3. 统一对比口径：
   - 训练分类指标：`cls_auc`, `cls_acc`
   - 回放指标：`avg_return`, `hit_rate`, `max_drawdown`, `annual_std`
   - 策略口径：P0.1 推荐（top_pct=0.08，无额外阈值、无行业上限）

## 6. 回滚点
- 继续保留 `uat_20260718_q1_ocf_fix_fy2` 为当前候选版本。
- 若 P1-R1 不优，直接回退到上一版配置与模型版本。
