# Q1 P1-R4 需求说明（训练窗口优化）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：在不改特征、不改标签、不改数据集的前提下，收缩训练历史窗口，验证是否能改善 Q1 泛化与回放风险表现。

## 2. 变更范围
- 仅修改训练配置参数，不改代码逻辑。
- 基于 `default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2.yaml` 新建实验配置。
- 调整 `data.start_date`：
  - `2015-01-01` -> `2017-01-01`
- 其他参数保持不变。

## 3. DB/API 合同确认
- 数据库字段：无新增/无修改。
- API 请求字段：无新增/无修改。
- API 响应字段：无新增/无修改。

## 4. 接口变更计划
- 无线上接口改动。
- 仅新增模型版本产物和离线评估文档。

## 5. 验证计划
1. 训练 Q1 单报告类型模型并输出 `metrics_Q1.json`。
2. 固定 P0.1 推荐策略进行回放对比：
   - baseline：`uat_20260718_q1_ocf_fix_fy2`
   - new：`uat_20260719_q1_p1_r4_start2017`
   - 策略：`top_pct=0.08,min_score=none,max_per_industry=none`
3. 对比指标：
   - 训练：`cls_auc`, `cls_acc`, `reg_mae`
   - 回放：`avg_return`, `hit_rate`, `max_drawdown`, `annual_std`

## 6. 回滚点
- 保留 `uat_20260718_q1_ocf_fix_fy2` 为主候选。
- 若 R4 不优于主候选，直接放弃该分支。
