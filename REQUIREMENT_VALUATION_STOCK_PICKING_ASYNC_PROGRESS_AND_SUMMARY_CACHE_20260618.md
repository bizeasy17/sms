# REQUIREMENT_VALUATION_STOCK_PICKING_ASYNC_PROGRESS_AND_SUMMARY_CACHE_20260618

## 目标
- 估值选股增加明确 loading / 进度反馈。
- 选股结果支持后端分批产出、前端轮询增量展示。
- strict 批量选股优先复用 persisted summary，避免逐票慢路径。
- 实施顺序：先 UAT，再同步 DEV。

## 归属
- smartinvestor_be：异步任务、进度状态、批量 strict summary 优化。
- smartinvestor_fe：loading、轮询、增量展示。

## 已确认方案
- 新增异步任务接口：
  - POST /api/stock-pick-valuation/jobs/
  - GET /api/stock-pick-valuation/jobs/{job_id}/
- 前端默认改为提交任务 + 轮询展示。
- strict 批量选股优先复用 persisted summary，禁止逐票走单票慢路径。
