# Q1 P0.1 回撤收敛需求说明（2026-07-19）

## 1. 归属与目标
- owning service: earning_training / earnings_forecast
- 目标：在不改特征、不改标签、不改训练主链路的前提下，先通过后处理选股规则做 Q1 回撤收敛。

## 2. 约束
- 不修改数据库表结构。
- 不新增/修改 API 请求或响应字段。
- 仅离线回放与参数筛选，产出可复现配置建议。

## 3. 范围
- 使用现有 Q1 新模型：`uat_20260718_q1_ocf_fix_fy2`。
- 固定同一测试切分口径（target_fy_up）。
- 调整项仅限：
  - 日内入选比例（top_pct）
  - 分数下限（min_score）
  - 单行业当日最大持仓数（max_per_industry）

## 4. 评估指标
- top portfolio avg return
- top portfolio hit rate
- max drawdown
- annual std

## 5. 交付
- 生成 P0.1 参数扫描结果文件（json/csv）。
- 形成推荐参数与下一步执行建议。
