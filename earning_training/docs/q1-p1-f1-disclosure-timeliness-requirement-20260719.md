# Q1 P1-F1 需求说明（披露时效特征）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：在不改标签与模型结构的前提下，新增披露时效类特征，增强 Q1 对“信息新鲜度”的表达能力。

## 2. 变更范围
- 代码变更：`earnings_forecast/services/pipeline.py` 的 `_build_features`。
- 新增特征：
  - `ann_date_missing`
  - `ann_date_lag_clipped_180d`
  - `ann_freshness_score`
  - `ann_is_recent_7d`
  - `ann_is_recent_30d`
  - `report_end_lag_days`
  - `report_end_lag_clipped_365d`
- 现有 `ann_date_lag_days` 保留。

## 3. DB/API 合同确认
- 数据库字段：无新增/无修改（仅训练数据特征列变化）。
- API 请求字段：无新增/无修改。
- API 响应字段：无新增/无修改。

## 4. 接口变更计划
- 无线上接口改动。
- 仅新增训练产物与离线评估文档。

## 5. 验证计划
1. 用独立实验配置重建数据集并训练 Q1。
2. 固定 P0.1 策略进行回放对比：
   - baseline: `uat_20260718_q1_ocf_fix_fy2`
   - new: `uat_20260719_q1_p1_f1_disclosure`
   - policy: `top_pct=0.08,min_score=none,max_per_industry=none`
3. 对比指标：
   - 训练：`cls_auc`, `cls_acc`, `reg_mae`
   - 回放：`avg_return`, `hit_rate`, `max_drawdown`, `annual_std`

## 6. 回滚点
- 保留 `uat_20260718_q1_ocf_fix_fy2` 为主候选。
- 若 F1 不优于主候选，回滚到该版本并保留 F1 作为对照实验。
