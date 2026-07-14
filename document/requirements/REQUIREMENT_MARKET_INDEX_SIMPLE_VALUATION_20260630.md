# Requirement: 大盘指数简化版传统估值（组合/保守）(2026-06-30)

## 1. 背景
- 目标是在现有“大盘分位”基础上，新增一个简化版的指数估值能力。
- 口径要求接近传统估值展示：输出组合估值与保守估值。

## 2. 目标
- 新增后端接口，输入指数代码，输出：
  - 简化方法估值（PE/PE_TTM/PB）
  - 组合估值（composite）
  - 保守估值（conservative）
  - 对当前指数点位的高估/低估状态与偏离度

## 3. 服务归属与接口影响
- 归属服务：smartinvestor_be/api
- DB影响：无
- 迁移影响：无
- API新增：
  - GET /api/market-index/valuation-simple/

## 4. 请求参数
- index_code: 指数代码，默认 000001.SH
- freq: 频率，默认 D
- start_date: 历史起始日期，默认 20040101
- band_pct: 估值带宽，默认 0.1

## 5. 计算口径（简化版）
- 基础输入：latest close、latest PE/PE_TTM/PB、对应历史分位基准（默认 P50）
- 三方法估值点位：
  - fair_by_pe = close * pe_p50 / pe_current
  - fair_by_pe_ttm = close * pe_ttm_p50 / pe_ttm_current
  - fair_by_pb = close * pb_p50 / pb_current
- 组装 method_map 后复用 summarize_buy_candidate 产出：
  - composite_valuation_price
  - conservative_valuation_price
  - undervalue_score / buy_candidate / under_methods

## 6. 响应字段（核心）
- index_code, asof_trade_date, current_index_price
- methods: pe/pe_ttm/pb 的 current/p50/implied/status/gap
- summary: summarize_buy_candidate 输出 + composite/conservative status/gap

## 7. 验收标准
- 对主流指数（如 000001.SH）返回非空结果。
- methods 至少有 1 个有效估值方法时，summary 需有可解释输出。
- 无数据时返回明确 error，不影响现有接口行为。

## 8. 前端接入（已确认）
- 接入位置：`smartinvestor_fe/src/components/StockChartFilter.vue` 现有“大盘分位/上证分位”弹窗摘要区。
- 接入方式：
  - 当弹窗切换 `market/shanghai` 时，请求 `/api/market-index/valuation-simple/`。
  - `market` 使用代表指数 `399300.SZ`（沪深300）作为简化估值输入。
  - `shanghai` 使用 `000001.SH`。
- 展示字段：
  - 组合估值价 + 状态 + 偏离度
  - 保守估值价 + 状态 + 偏离度
- 不替换原有分位曲线与分位统计，仅追加估值摘要信息。
