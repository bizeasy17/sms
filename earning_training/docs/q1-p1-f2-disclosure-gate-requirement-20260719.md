# Q1 P1-F2 需求说明（披露时效门控）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：在 P1-F1 基础上，为披露时效特征增加“近30天门控”，减少陈旧披露信息对模型打分的噪声影响。

## 2. 变更范围
- 代码变更：`earnings_forecast/services/pipeline.py`
- 配置变更：新增 F2 实验配置文件。
- 仅离线训练/回放流程，线上接口不改动。

## 3. DB/API 合同确认
- 数据库字段：无新增/无修改。
- API 请求字段：无新增/无修改。
- API 响应字段：无新增/无修改。

## 4. 接口变更计划
- 无外部 API 合同变更。
- 新增内部训练配置项（feature 层）：
  - `disclosure_timeliness_gate_days`（默认 0，0 表示关闭门控）

## 5. 实现要点
1. 在 `_build_features` 中读取门控阈值。
2. 当阈值 > 0 时，仅在 `ann_date_lag_days <= 阈值` 的样本上保留时效特征信号；其余样本置零。
3. 维持 F1 特征列名不变，避免破坏下游依赖。

## 6. 验证计划
1. 使用独立配置重建数据并训练 Q1：
   - baseline: `uat_20260718_q1_ocf_fix_fy2`
   - new: `uat_20260719_q1_p1_f2_disclosure_gate30`
2. 固定回放策略：`top_pct=0.08,min_score=none,max_per_industry=none`
3. 对比指标：
   - 训练：`cls_auc`, `cls_acc`, `reg_mae`
   - 回放：`avg_return`, `hit_rate`, `max_drawdown`, `annual_std`

## 7. 回滚点
- 保留主候选 `uat_20260718_q1_ocf_fix_fy2`。
- 若 F2 不优于主候选，保留 F2 作为对照实验，不切换主候选。
