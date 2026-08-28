# Dashboard 技术趋势 Tab 市场情绪图方案

**状态：待确认，未实施。**

## 目标

在 Dashboard 中栏的个股技术趋势图中，于 K 线和成交量子图下增加“市场情绪指数”折线子图。该图展示全市场 `MARKET/ALL_A` 情绪，不将个股情绪与市场情绪混淆；它用于给当前个股走势提供市场环境参照。

## 现有承载位置

页面链路为 `DashboardView.vue -> StockChartFilter.vue -> StockChart.vue`。`StockChart.vue` 的 `chartTrendOption` 已把 K 线和成交量放在同一个 ECharts 实例的两个 `grid` 中，且共用 `dataZoom`。

实施时在该实例新增第三个 `grid`、第三个 `xAxis/yAxis` 和一条 `line` series，不增加卡片、不创建第二个 ECharts 实例。三个子图统一使用交易日分类轴和同一个缩放区间，横向像素边界一致。

## 后端契约

数据只从已落库的 BE 接口读取：

```text
GET /api/market-sentiment/history/?market=CN&scope=MARKET&scope_code=ALL_A&limit={period}
```

每个 `data` 元素至少使用：

```ts
type MarketSentimentPoint = {
  trade_date: string
  score: number | null
  level: 'PANIC' | 'CAUTIOUS' | 'NEUTRAL' | 'POSITIVE' | 'EUPHORIC' | 'WARMING_UP' | 'INSUFFICIENT_DATA'
  status: string
  momentum_score: number | null
  activity_score: number | null
  fear_score: number | null
}
```

已确认接口返回顶层 `{ data: MarketSentimentPoint[] }`，其中历史序列按交易日升序。前端不调用计算命令，也不从个股 K 线推导或补算情绪。

## 图表行为

- K 线请求完成后，以其 `tradeDates` 为主轴；将市场情绪按 `trade_date` 映射到该数组。缺失、`WARMING_UP` 和 `INSUFFICIENT_DATA` 使用 `null`，形成真实断点而非补值。
- `yAxis` 固定 `min: 0`、`max: 100`，名称为“市场情绪”。增加 30、50、70 的静态 `markLine`，分别表达恐慌/中性/亢奋分界。
- 折线颜色按值分段：低于 30 使用红色，30-45 使用橙色，45-55 使用中性色，55-70 使用绿色，高于 70 使用强调色。线本身保持 2px、无点标记，避免在长周期图中拥挤。
- Tooltip 沿用 K 线的 `axis` 联动：显示交易日、情绪分数、等级，以及动量/热度/恐慌三维分数。无数据日显示“情绪数据未发布”。
- 默认显示。网络请求失败时不阻塞 K 线和成交量，静默显示空子图并在图内保留简短的无数据状态。
- 使用现有的请求缓存与 in-flight 去重模式，缓存键包含 `period` 和情绪 `engine_version`；个股切换不会重复请求同一份全市场序列。

## 尺寸与响应式

将现有 K 线/成交量总高度从 400px 增至约 500px。建议比例：K 线 52%、成交量 18%、情绪 18%，余量用于标题与轴标签。三个 grid 的 `left/right` 完全一致，移动端同样保持纵向三段结构，通过固定高度和 `dataZoom` 保证标签不重叠。

## 实施文件与验收

只修改 `src/components/StockChart.vue`；若当前请求层无法复用，则新增一个局部 API helper，不改变 Dashboard 布局、路由或全局状态。

验收条件：

1. K 线、成交量、情绪折线的交易日横轴及缩放位置一致。
2. 切换 30/60/200/400/1000 日周期时，情绪请求量受缓存控制且不存在竞态覆盖。
3. `score=null`、预热与接口失败不会影响现有 K 线/成交量渲染。
4. 桌面和移动视口截图中三张子图均有稳定尺寸、无轴标签或 tooltip 覆盖。

## 待确认

请确认以“全市场情绪”作为默认叠加数据、固定 0-100 纵轴、三段同实例 ECharts 布局，以及上述只读接口字段后再实施前端。
