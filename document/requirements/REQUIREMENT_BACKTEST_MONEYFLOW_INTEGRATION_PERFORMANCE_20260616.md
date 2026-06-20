# 需求说明：回测接入个股资金净流入（性能不降级）

## 1. 背景
- 当前估值选股已接入 THS 个股资金流二次过滤（实时接口侧）。
- 新诉求是将资金净流入条件引入回测链路，用于策略筛选与效果评估。
- 约束前提是不能明显拉长回测耗时，避免在回测循环中做高成本窗口聚合。

## 2. 目标
1. 在不影响现有回测效率的前提下，支持按窗口资金净流入条件过滤候选标的。
2. 保持默认兼容：不开启资金流过滤时，回测结果与现有版本一致。
3. 提供可解释输出：在回测结果中可追踪资金流过滤是否生效及关键值。

## 3. 服务归属（待你确认）
- 方案建议：
  - 回测执行与过滤逻辑归属 `smartinvestor_be`。
  - 数据同步与预计算可由 `smartinvestor_be` 内管理命令完成。
- 待确认项 A：是否由 `smartinvestor_be` 独立承担实现与调度，不改 `smartinvestor_etl`。

## 4. 范围
- 后端（本期）
  - 新增回测可用的资金流预计算数据层（按 `ts_code + trade_date`）。
  - 在回测入口新增资金流参数并接入过滤流程。
  - 在回测输出增加资金流过滤回显字段。
- 前端（可选，本期可不做）
  - 若已有回测参数面板，则新增开关与窗口选择控件；否则仅支持后端参数调用。

## 5. 非目标
- 不改现有资金流原始入库口径。
- 不在回测过程中按标的逐条在线计算 rolling sum。
- 不在本期引入分钟级资金流或盘口级特征。

## 6. 关键设计（性能优先）

### 6.1 预计算特征表（核心）
- 表建议：`StockMoneyflowFeatureDaily`（名称可按现有命名规范微调）。
- 主键建议：`trade_date + ts_code`。
- 字段建议：
  - `mf_sum_5`, `mf_sum_10`, `mf_sum_15`, `mf_sum_30`, `mf_sum_60`（numeric）
  - `observed_days_5`, `observed_days_10`, `observed_days_15`, `observed_days_30`, `observed_days_60`（int，可选）
  - `updated_at`（datetime）
- 约束与索引：
  - `unique(trade_date, ts_code)`
  - 索引 `(trade_date)`、`(ts_code, trade_date)`

### 6.2 计算与更新策略
- 初始化回补：对历史区间批量生成窗口特征。
- 日增量：每个交易日仅计算当日特征并 upsert。
- 避免重复：基于唯一键幂等更新。
- 失败策略：支持 `--strict`，失败非零退出。

### 6.3 回测接入策略
- 回测新增参数：
  - `apply_moneyflow_filters`（bool，默认 false）
  - `moneyflow_net_inflow_days_window`（5/10/15/30/60，默认 10）
  - `moneyflow_mode`（本期固定 `sum_positive`，预留扩展）
- 过滤规则（本期）：
  - `mf_sum_{window} > 0` 才允许进入买入候选。
- 执行位置：
  - 在候选池生成后、交易决策前一次性过滤。
  - 严禁在逐笔撮合环节做在线窗口聚合。

## 7. API/命令契约（草案）

### 7.1 管理命令
- 建议新增：`build_stock_moneyflow_features`
- 参数建议：
  - `--start-date --end-date`（历史回补）
  - `--latest`（日增量）
  - `--windows 5,10,15,30,60`（默认全量）
  - `--strict`

### 7.2 回测接口/任务参数
- 若回测通过 API 触发：新增 query/body 参数同第 6.3。
- 若回测通过命令触发：新增 CLI 参数同第 6.3。

### 7.3 返回回显
- 在回测结果 metadata 回显：
  - `effective_moneyflow_filters.apply_moneyflow_filters`
  - `effective_moneyflow_filters.moneyflow_net_inflow_days_window`
  - `effective_moneyflow_filters.filtered_before`
  - `effective_moneyflow_filters.filtered_after`

## 8. 验收标准
1. 默认关闭资金流过滤时，回测结果与基线版本一致（交易数、收益序列、关键统计一致）。
2. 开启资金流过滤后，回测能正确过滤并输出回显字段。
3. 在同一数据区间、同一参数集下，开启资金流过滤后的耗时增幅满足阈值：
   - 目标阈值：总耗时增幅不高于 10%。
4. 预计算与日增量命令可重复执行且幂等。

## 9. 性能与风险
- 性能风险：
  - 风险点是实时滚动计算导致 N x window 聚合放大。
  - 规避方式是预计算表 + 回测日批量加载到内存 map。
- 数据风险：
  - 某些交易日窗口样本不足。
  - 处理方式：缺失值视为不通过过滤，并在回显中统计缺失数量（可选）。

## 10. 验证计划（DEV/UAT）
1. 离线验证：随机抽样股票核对 `mf_sum_10` 与原始 `moneyflow_ths` 累加一致。
2. 回测 A/B：同参数跑两组（过滤 off/on），记录耗时与交易数变化。
3. 兼容验证：过滤 off 时，结果与当前基线完全一致。
4. 冒烟验证：最近 1 个自然月、1 个季度、1 年窗口各跑一次。

## 11. 实施分期
- Phase 1：数据层
  - 建表与命令（回补 + 增量）
- Phase 2：回测参数与过滤
  - 引擎接入、metadata 回显
- Phase 3：性能优化与基线固化
  - 缓存、批量加载、A/B 性能报告

## 12. 待确认项
1. 服务归属：是否确认由 `smartinvestor_be` 独立实现（不改 `smartinvestor_etl`）。
2. 性能阈值：是否确认“开启过滤后总耗时增幅 <= 10%”。
3. 默认窗口：是否确认 `10` 日。
4. 前端范围：本期是否仅后端参数接入，前端改动延后。
5. 缺失处理：窗口数据不足时是否统一按“不通过过滤”处理。

## 13. 备注
- 本文档为功能实现前的需求确认稿；待你确认第 12 节后，再进入代码改造阶段。
