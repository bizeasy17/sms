# Q1 P1-F3 需求说明（标签灰区 + 阈值校准）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：提升 Q1 分类指标上限，尝试把 `cls_acc` 向 70% 逼近、`cls_auc` 向 0.70 逼近。

## 2. 变更范围
- 代码变更：`earnings_forecast/services/pipeline.py` 训练流程。
- 配置变更：新增 F3 实验配置文件。
- 仅训练/评估链路，不改线上 API。

## 3. DB/API 合同确认
- 数据库字段：无新增/无修改。
- API 请求字段：无新增/无修改。
- API 响应字段：无新增/无修改。

## 4. 接口变更计划
- 无外部接口变化。
- 新增内部训练配置项：
  - `label.cls_gray_zone.enabled`
  - `label.cls_gray_zone.abs_min`
  - `label.cls_gray_zone.metric_col`（可选）
  - `train.cls_decision_threshold`
  - `train.cls_threshold_tuning.enabled/min/max/step`

## 5. 实现要点
1. 分类灰区：对接近决策边界的低幅度标签样本从分类训练/评估中剔除。
2. 阈值校准：在配置区间内扫描概率阈值，选择准确率最高阈值用于 `cls_acc`。
3. 默认关闭，保持向后兼容。

## 6. 验证计划
1. 使用独立 F3 配置重建数据并训练 Q1。
2. 固定策略回放对比 baseline：`top_pct=0.08,min_score=none,max_per_industry=none`。
3. 对比：`cls_auc`, `cls_acc`, `reg_mae`, `avg_return`, `hit_rate`, `max_drawdown`, `annual_std`。

## 7. 回滚点
- 保留主候选 `uat_20260718_q1_ocf_fix_fy2`。
- 若 F3 未形成交易层优势，仅保留为候选实验。
