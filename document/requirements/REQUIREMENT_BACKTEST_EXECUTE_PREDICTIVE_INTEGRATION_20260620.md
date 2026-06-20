# REQUIREMENT_BACKTEST_EXECUTE_PREDICTIVE_INTEGRATION_20260620

## 1. 背景

当前回测执行页仅接入传统估值回测链路：
- 前端页面使用 traditional 接口路径。
- 后端 backtest app 仅暴露 traditional 路由。

预测估值回测能力已存在于 tushare_earnings_service，但执行页未接入。

## 2. 目标

在不破坏传统回测现有行为的前提下，使回测执行页可一键切换并执行：
- 传统估值回测
- 预测估值回测

并在同一页面查看对应执行结果。

## 3. 服务归属与边界

- 执行页入口与统一后端入口归属：smartinvestor_fe + smartinvestor_be
- 预测回测核心计算归属：tushare_earnings_service（保持现有 /api/forecast/backtest/* 合同不变）

## 4. 接口改造方案（待确认）

### 4.1 smartinvestor_be 新增预测回测代理接口

在 backtest 路由下新增 predictive 分组：
- POST /api/backtest/predictive/run/
  - 转发至 earnings service: POST /api/forecast/backtest/run/
- GET /api/backtest/predictive/runs/
  - 转发至 earnings service: GET /api/forecast/backtest/runs/
- GET /api/backtest/predictive/runs/{run_id}/
  - 转发至 earnings service: GET /api/forecast/backtest/runs/{run_id}/

说明：
- 统一使用 smartinvestor_be 的 EARNINGS_SERVICE_BASE_URL 与超时配置。
- 透传 query/body（仅做必要字段校验与错误码标准化）。
- 返回结构尽量与上游保持一致，外层保持现有 API 风格（ok/data/error）。

### 4.2 smartinvestor_fe 回测执行页接入预测模式

文件：smartinvestor_fe/src/views/BacktestExecuteView.vue

新增/调整：
- 新增回测来源切换字段：traditional | predictive（默认 traditional，保持兼容）
- 当来源为 traditional：沿用现有表单与接口
- 当来源为 predictive：
  - 调用 /api/backtest/predictive/run/
  - 读取 /api/backtest/predictive/runs/ 与 /api/backtest/predictive/runs/{id}/
  - 表单仅展示业务筛选与风控参数，不展示以下字段：
    - batch_key
    - ts_codes
    - report_type
    - persist
  - 预测回测提交参数约束：
    - batch_key：不允许手工输入，永远由后端自动生成（命名风格与传统回测保持一致）
    - ts_codes：前端不提交；股票池定义为“全市场内符合回测条件的股票”
    - report_type：固定默认值（ALL）
    - persist：固定默认值（true）
- 结果区按来源渲染：
  - traditional 继续显示现有 stocks/buy-candidates/detail
  - predictive 先显示 summary + metrics + sample_trades（不复用 traditional 单股详情接口）

### 4.3 兼容性要求

- 不修改现有 traditional 参数含义与默认值。
- 不影响回测查询页现有 predictive/traditional 双源逻辑。
- 前端刷新后默认保持 traditional，避免影响现网使用习惯。

## 5. 验收标准

- 传统模式回归通过：
  - 可执行、可查历史、可看单股详情。
- 预测模式新增通过：
  - 可提交 run，成功返回 run_id。
  - 可查询 runs 列表与 run 详情。
  - 页面可展示 summary、按年 metrics、sample_trades。
- 错误场景：
  - earnings service 不可达时，页面收到明确错误信息，不影响 traditional 模式。

## 6. 风险与回滚

风险：
- 上游预测服务超时或返回结构变化。

缓解：
- 后端代理增加超时与错误透传；前端按来源分离渲染。

回滚：
- 前端移除 predictive 来源开关与调用。
- 后端删除新增 predictive 路由与视图，不影响 traditional 路由。

## 7. 本轮增补（2026-06-20）

### 7.1 验证要求增补

- 在 run_id=852 同条件映射到预测回测后，若无交易，需放宽条件再验证是否可产生交易历史。

### 7.2 展示分流要求增补

- 回测执行页结果展示必须区分传统/预测，不允许混在同一个结果区。
- 回测历史弹窗必须支持按来源切换并分流查询，不允许传统与预测混合展示。

### 7.3 验收补充

- 放宽条件后可得到非零交易样本（用于验证链路可执行）。
- 历史弹窗来源切换为预测时，不显示传统网格扫描页签。

## 8. 本轮新增约束（2026-06-20 第二次确认）

- 预测回测股票池定义：全市场中满足回测条件的股票，不使用手工给定 ts_codes。
- batch_key 规则：永远自动生成，不允许页面手填或透传外部固定值。

## 9. 本轮新增约束（2026-06-20 停止语义修复）

- 用户在执行页点击停止后，后端任务必须在运行中可中断，不允许继续跑到自然结束。
- 任务状态从 running 进入 cancel_requested 后，前端停止按钮应禁用，不允许重复点击。
- 单次执行按钮 loading 必须在 cancel_requested 或 canceled 状态下及时释放。
- 扫描任务事件流需要记录取消轨迹（cancel requested / run canceled / task finished）。

## 10. 预测扫描任务最小改动接口合同（2026-06-20）

目标：仅为 predictive 新增独立扫描编排接口，不修改 traditional 已有接口和执行逻辑。

### 10.1 新增接口（smartinvestor_be）

- `POST /api/backtest/predictive/scan/tasks/`
  - 用途：创建并异步启动预测扫描任务。
  - 请求体：沿用执行页 predictive 现有参数（不接受外部 `batch_key/ts_codes/report_type/persist`）。
  - 返回：`{ ok, data: { task_id, task_key, status } }`

- `GET /api/backtest/predictive/scan/tasks/`
  - 用途：查询预测扫描任务列表。
  - 返回：`{ ok, data: { rows: [{ id, task_key, status, total_jobs, completed_jobs, failed_jobs, created_at, updated_at }] } }`

- `GET /api/backtest/predictive/scan/tasks/{task_id}/`
  - 用途：查询任务详情与阶段事件。
  - 返回：`{ ok, data: { id, task_key, status, error_message, result: { runs, failures, events } } }`

- `POST /api/backtest/predictive/scan/tasks/{task_id}/cancel/`
  - 用途：请求停止任务。
  - 返回：`{ ok, task_id, status }`

### 10.2 状态合同

- 状态枚举：`pending | running | cancel_requested | canceled | success | partial_success | failed`
- 前端按钮语义：仅 `pending/running` 可点击停止；`cancel_requested/canceled` 均视为执行态结束。

### 10.3 执行与中断语义

- 扫描编排在 smartinvestor_be 内执行；每个组合调用预测服务 `POST /api/forecast/backtest/run/`。
- 每次提交新组合前必须检查任务状态；命中 `cancel_requested/canceled` 立即短路。
- 若上游预测服务未来提供 cancel 接口，可在本合同上增加“在途子任务取消”增强能力；当前最小版本不要求强制硬中断在途 HTTP 调用。

### 10.4 兼容性保护

- 不修改 `traditional/scan/*` 的任何 URL、请求体、响应体和状态流转逻辑。
- 不修改 traditional 前端分支逻辑；仅在 predictive 分支新增调用路径。
- 预测任务模型与传统任务模型物理隔离，避免相互污染。
