# REQUIREMENT_VALUATION_PICKING_PREDICTIVE_FISCAL_YEAR_SEASON_FILTER_20260812

## 1. 问题描述
- 页面: /picking-valuation
- 场景: 预测估值模式，筛选条件包含财报季(H1) + 财报所属年份(如 2026) + 沪市 + 分数阈值 + 低估 + BUY。
- 现象: 返回结果中存在 2025H1 财报日期记录，不符合“2026 + H1”筛选预期。

## 2. 归属服务确认
- 前端归属: UAT/smartinvestor_fe
  - 参数构建: src/components/ValuationStockPickingResult.vue
  - 参数状态: src/components/ValuationStockPickingFilter.vue, src/stores/valuationStockPickingStore.ts
- 后端归属: UAT/smartinvestor_be
  - 选股接口: api/views.py -> pick_stocks_by_valuation -> _pick_stocks_by_valuation_fast

## 3. 现状核对
- FE 已传 valuation_fiscal_year 与 earnings_report_type。
- BE 已解析 valuation_fiscal_year，并据此推导 valuation_report_end_date。
- 但在 predictive 模式结果合并阶段，未对最终输出执行“年份+财报季”强约束，导致部分记录回落到历史财报口径。

## 4. 目标行为
- 当用户指定 valuation_fiscal_year=YYYY 且 earnings_report_type in {Q1,H1,Q3,FY} 时：
  - 最终返回结果必须满足该年+该季（报告期末日期一致）。
  - 不满足条件的股票应从结果中过滤掉。

## 5. 接口与数据影响
- API 路径不变。
- 请求参数不变（继续使用 valuation_fiscal_year + earnings_report_type）。
- 响应字段不新增；仅返回集合变严格。
- 数据库表结构不变；使用现有字段：
  - valuation_profit_report_end_date
  - valuation_profit_report_type
  - earnings_report_type
  - financial_fiscal_year

## 6. 实施计划
1. 在 predictive 合并后、排序前增加严格过滤函数：
   - 以 valuation_report_end_date 为主锚点，辅以 report_type 校验。
2. 仅在用户显式传入有效年份且 report_type 为季节口径时启用。
3. 保持未传年份时的历史兼容行为。
4. 缓存键保持现状（已包含 valuation_fiscal_year 和 valuation_report_end_date）。

## 7. 验证计划
- 用例A: 2026 + H1 -> 返回行的 report_end_date 必须是 2026-06-30。
- 用例B: 2025 + H1 -> 返回行切换为 2025-06-30 口径。
- 用例C: 未传 fiscal year -> 行为与当前一致。
- 用例D: predictive + BUY + 分数阈值 + 沪市 -> 上述约束仍生效。

## 8. 风险与回退
- 风险: 结果数量可能下降（严格过滤后属预期）。
- 回退: 仅需回退过滤段代码，无 DB 迁移影响。
