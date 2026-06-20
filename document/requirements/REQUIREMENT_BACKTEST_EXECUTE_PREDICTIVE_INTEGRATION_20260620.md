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
