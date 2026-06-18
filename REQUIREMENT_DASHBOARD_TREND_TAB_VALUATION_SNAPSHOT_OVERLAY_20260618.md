# Requirement: Dashboard 技术趋势Tab叠加估值快照K线 (2026-06-18)

## 用户目标

- 目标位置: UAT Dashboard 中栏 技术趋势 tab。
- 在现有个股 K 线中，叠加显示估值快照价格点。
- 叠加内容: 组合估值价 + 保守估值价。
- 叠加范围: 前台选择周期内（例如 1Y）所有快照生成日期。
- 前台可切换估值模式: 传统估值 / 预测估值。
- 一致性要求（新增）: 当模式为传统估值时，技术趋势K线叠加应优先跟随估值一览当前 `active_valuation_variant`，避免两侧组合/保守估值口径不一致。

## 已确认代码位置

- 页面入口: `smartinvestor_fe/src/views/DashboardView.vue`
- 中栏容器: `smartinvestor_fe/src/components/StockChartFilter.vue`
- 技术趋势图组件: `smartinvestor_fe/src/components/StockChart.vue`
- 估值状态来源组件: `smartinvestor_fe/src/components/StockValuationQuickView.vue`

## 现状核对

- 技术趋势 tab 已有 K 线图和周期切换（30/60/1y/2y/5y/10y）。
- 传统估值接口 `GET /api/stocks/{ts_code}/valuation/methods/` 当前返回的是按方法聚合后的最新估值结果，不是周期内全快照点序列。
- 预测侧现有接口 `GET /api/earnings/signal/{ts_code}/` 与 `GET /api/earnings/signal-compare/{ts_code}/` 主要返回 latest/report-anchor 视图，不是完整历史快照序列。

## 服务归属建议

- `smartinvestor_fe`:
  - 管理模式切换（traditional/predictive）与周期切换。
  - K线叠加点渲染（稀疏点，不做连续填充）。
- `smartinvestor_be/api`:
  - 新增/扩展接口提供周期内快照点序列（按 trade_date）。
  - 统一返回结构，供 K 线组件直接消费。

## 接口变更方案（待确认）

### A. 新增统一接口（推荐）

- `GET /api/stocks/{ts_code}/valuation/snapshot-history/`

Query:
- `mode=traditional|predictive`
- `freq=D|W|M`（先按 D 实现，W/M 可后续扩展）
- `period=30|60|200|400|1000|2000`（与前台现有周期一致）

Response:
- `data`: 数组
  - `trade_date`
  - `composite_price`
  - `conservative_price`
  - `source_mode`（traditional/predictive）
  - 可选: `report_type`, `report_end_date`, `anchor_mode`

### B. 前端展示行为

- 在 `StockChart.vue` K线主图叠加两个 series:
  - 组合估值价（散点 + 常驻标签）
  - 保守估值价（散点 + 常驻标签）
- 只在快照日期显示，不做 forward-fill。
- 保持与回测弹窗一致的视觉风格与防遮挡间距。
- 传统模式下，叠加接口请求应携带 `valuation_variant=active_valuation_variant`（来自估值一览），确保同一只股票同一口径下数值一致。

## 验证计划

- 同一股票切换周期时，叠加点数量与周期窗口一致。
- 切换 traditional/predictive 时，叠加点按 mode 改变。
- 非快照日期无估值点。
- 不影响现有 K 线、MA、顶部/底部图表联动。

## 风险

- predictive 历史快照若当前库中缺失，预测模式可能点位稀疏或为空。
- W/M 频率与 D 快照日期对齐规则需明确（首版建议先以 D 完成）。
