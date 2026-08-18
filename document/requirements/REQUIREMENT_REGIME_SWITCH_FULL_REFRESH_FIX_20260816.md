# 市场风格切换全量刷新修复

## 问题

`daily_financial_periodic_refresh.bat` 在括号块中使用百分号变量展开。
批处理会在块执行前展开变量，导致检测到的市场风格无法写入状态文件，
状态文件被错误写成 `ECHO is off.`，从而无法触发风格切换全量刷新。

## 行为约束

- 有效风格仅为 `BULL`、`BEAR`、`BALANCE`。
- 只有当前和前一状态均有效且不同，才触发全市场预测信号刷新。
- 当前状态首次有效运行只初始化状态文件，不触发刷新。
- 无效或空检测结果不覆盖已有状态文件。
- 风格切换刷新命令保持：
  `refresh_signal_snapshot --scope 60,00,30,68 --full-refresh --report-types LATEST,FUSION`。

## 个股风格切换补充

- 个股风格状态持久化到 PostgreSQL 表 `earnings_stock_regime_state`。
- 状态为 `GROWTH`、`BALANCE`、`DEFENSIVE`、`RISK_OFF`，基于 MA20/MA60、
  20 日波动率与 60 日回撤。
- 新状态连续两日确认后，输出股票代码文件并仅刷新该股票的
  `LATEST,FUSION` 信号快照。
- 手工检查命令可加 `--write` 建立或更新状态；首次运行只建立基线，不触发刷新。

## Dashboard 已刷新预测卡片

- 左侧最新预测卡只读取 `EarningsSignalSnapshot`，禁止加载时触发实时预测。
- 没有已刷新快照时显示为空。
- 快照记录并展示 `MARKET_REGIME_SWITCH`、`STOCK_REGIME_SWITCH`、
  `FINANCIAL_DISCLOSURE`、`MONTHLY_FULL_REFRESH` 或 `MANUAL_REFRESH` 原因。

## 触发刷新历史弹窗

- 新增只读接口 `GET /api/forecast/signal/history/?ts_code=<code>&limit=<n>`。
- 仅返回 `refresh_reason` 非空的 `EarningsSignalSnapshotHistory` 记录，
  按 `triggered_at`、`created_at` 倒序，默认上限 100。
- 返回刷新原因/细节、市场与个股风格、财报输入周期/公告日、信号、分数、
  目标价、预期收益和风险。
- BE 代理接口为 `GET /api/earnings/signal-history/<ts_code>/?limit=<n>`。
- Dashboard 左侧最新预测估值卡片增加历史按钮和只读弹窗；弹窗不触发实时预测。