# REQUIREMENT_VALUATION_STOCK_PICKING_ASYNC_PROGRESS_AND_SUMMARY_CACHE_20260618

## 1. 背景

当前估值选股存在两个明显问题：

1. 前端体验差
- 用户设置完条件后，页面没有明确 loading / 进度反馈。
- 后端长时间计算时，前端看起来像“完全没反应”。
- 即使后台已经算出部分结果，前端也只能等整次请求结束后一次性展示。

2. 默认统一口径后性能显著下降
- 最近将估值选股默认切到 `single_variant_strict` 后，选股耗时明显上升。
- 现象上可看到后台持续打印 `Fetching INDICATOR` / `Fetching BALANCESHEET`。
- 根因判断：当前批量选股路径中，对每只股票都调用了单票估值一览内部接口以生成 strict summary，导致逐票触发指标/资产负债表读取与额外估值组装，批量请求退化为 N 次单票重算。

## 2. 目标

1. 选股提交后，前端立即显示明确 loading / 进度状态。
2. 后端一边计算，前端一边按批次轮询并增量展示结果。
3. 默认 strict 口径下，批量选股不再逐票重走单票重算逻辑。
4. 优先复用已生成的 summary / risk / netprofit 等持久化或批量可加载结果，避免逐票慢路径。

## 3. 非目标

1. 不修改估值一览单票接口的核心估值算法。
2. 不引入 WebSocket；先采用轮询方案。
3. 不改变用户现有筛选项语义。

## 4. 服务归属（待确认）

建议按以下归属实施：
- `smartinvestor_be`：负责异步任务、进度状态、分页/增量结果接口、strict summary 批量优化。
- `smartinvestor_fe`：负责 loading、轮询、进度展示、增量刷新表格。

## 5. 现状问题定位

### 5.1 前端当前行为

当前组件：`smartinvestor_fe/src/components/ValuationStockPickingResult.vue`
- `fetchPickingResult()` 直接发起一次长 GET 请求。
- 请求返回前，没有显式 loading 状态，也没有进度提示。
- 结果必须等后端完整返回后，`pickingResult.value = res.data.data || []` 才一次性渲染。

### 5.2 后端当前行为

当前入口：`smartinvestor_be/api/views.py` 中 `_pick_stocks_by_valuation_fast`
- 默认 strict 口径时，逐票调用 `_load_internal_stock_valuation_methods_payload(...)`。
- 该内部函数进一步走 `get_stock_valuation_methods(...)` 单票路径。
- 单票路径会触发额外的指标/报表加载与 summary/risk 补全，因此在批量场景性能急剧下降。

## 6. 推荐方案（待确认）

### 6.1 接口方案

#### A. 启动异步选股任务
- 接口：`POST /api/stock-pick-valuation/jobs/`
- 请求体：沿用现有选股筛选参数
- 返回：
  - `job_id`
  - `status`: `queued | running`
  - `poll_interval_seconds`: 默认 2 或 3
  - `result_page_size`: 后端建议前端每次取回的批次大小

#### B. 轮询任务状态与增量结果
- 接口：`GET /api/stock-pick-valuation/jobs/{job_id}/`
- 返回字段：
  - `job_id`
  - `status`: `queued | running | done | failed`
  - `progress_pct`
  - `processed_count`
  - `matched_count`
  - `total_candidates`
  - `message`
  - `data`: 当前已产出的结果列表（已排序后的前 N 条或当前累计结果）
  - `has_more`
  - `updated_at`

#### C. 保留现有同步接口
- 现有 `GET /stock-pick-valuation/{trade_date}/{scope}/` 先保留，作为兼容路径。
- 前端默认切到异步任务模式。

### 6.2 前端展示方案

在 `ValuationStockPickingResult.vue` 增加：
- 提交后立即进入 loading 状态。
- 顶部显示：
  - 当前状态（排队/计算中/完成/失败）
  - 已处理数量 / 总候选数量
  - 当前命中数量
- 每隔 2-3 秒轮询一次任务状态。
- 一旦后端返回部分结果，立刻覆盖或追加表格内容，不等待整批完成。
- 完成后自动停止轮询。
- 失败时展示错误态与重试入口。

### 6.3 后端性能优化方案

strict 模式批量选股时，不再逐票调用单票估值一览内部接口；改为批量路径：

1. 先批量加载：
- `valuation_snapshot_map`
- `latest_risk_snapshot_map`
- `latest_income_netprofit_map`
- 如可用，再批量加载 persisted variant summary latest

2. strict summary 生成逻辑改为：
- 从当前股票 `method_map` 中确定 active variant
- 在当前 `method_map` 内按 `variant + report_end_date` 严格筛选
- 优先直接读取已持久化的 variant summary
- 若 persisted summary 缺失，再用当前批量已加载的方法集做轻量 summary 汇总
- 批量选股路径禁止逐票触发 `Fetching INDICATOR/BALANCESHEET` 这类慢调用

3. 任务执行过程按批写入缓存
- 建议使用 Django cache 或 DB job table 保存任务状态和已产出结果
- 每处理完一批（例如 20/50 支），更新一次任务进度与增量结果

## 7. 兼容性与风险

1. 新增异步任务接口，前端需要配套切换。
2. strict summary 的实现从“单票内部接口复用”改为“批量等价实现”，需要做结果一致性校验。
3. 若 persisted summary 缺失，需定义 fallback 规则，避免任务卡住。

## 8. 验证计划

### 8.1 性能验证
- 同一选股条件下，对比改造前后：
  - 首屏有感响应时间
  - 5 分钟内结果产出数量
  - 后端日志中 `Fetching INDICATOR/BALANCESHEET` 次数

### 8.2 结果一致性验证
- 样本：`603260.SH`, `Q1`
- 要求：批量 strict summary 与单票估值一览 summary 一致

### 8.3 前端交互验证
- 提交即显示 loading
- 轮询期间进度数字持续更新
- 部分结果可先展示
- 完成后停止轮询
- 失败时展示错误信息

## 9. 待确认事项

1. 是否确认由 `smartinvestor_be + smartinvestor_fe` 分别承接后后端/前端改造？
2. 是否确认新增异步任务接口：
   - `POST /api/stock-pick-valuation/jobs/`
   - `GET /api/stock-pick-valuation/jobs/{job_id}/`
3. 是否确认前端默认改为“提交任务 + 轮询展示”，而不是继续等待同步接口一次返回？
4. 是否确认 strict 批量选股优先复用 persisted summary，禁止逐票走单票慢路径？
5. 确认后我将先在 UAT 实现并验证，再同步同改到 DEV。
