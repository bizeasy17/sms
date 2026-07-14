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

## 待确认补充需求（2026-06-29）

### 背景问题
- 当前筛选条件切换会直接提交新任务，旧任务仍在后台继续执行。
- 结果：同一用户可并发多个估值选股任务，造成重复计算与资源浪费。

### 目标
- 同一用户在估值选股页同一时间只保留一个“活跃任务”（queued/running）。
- 新任务提交时自动抢占旧任务：旧任务尽快停止，前端仅追踪新任务。

### 数据库字段确认
- 本次不新增/变更数据库表字段。
- 任务状态仅使用 Django cache 存储（与现有 job 机制一致）。

### API 合同草案（待最终确认）
- POST /api/stock-pick-valuation/jobs/
  - 行为增强：
    - 若存在同用户活跃任务，则先标记旧任务为 canceled，再创建新任务。
  - 响应新增字段：
    - superseded_job_id: string | null（被抢占的旧任务 ID）
- GET /api/stock-pick-valuation/jobs/{job_id}/
  - status 枚举扩展：queued | running | done | failed | canceled
  - canceled 状态响应字段：
    - message: "任务已取消（被新任务抢占）" 或等价文案

### 前端行为草案（待最终确认）
- 发起新任务前先停止旧轮询计时器。
- 若收到 superseded_job_id，仅继续追踪新 job_id。
- 轮询到 status=canceled 时，静默结束轮询，不报错弹窗。

### 实施顺序
1. smartinvestor_be 增加任务抢占与取消态。
2. smartinvestor_fe 对 canceled/superseded_job_id 做兼容。
3. 运行回归验证：旧流程 done/failed 不受影响。
