# REQUIREMENT_BACKTEST_PREDICTIVE_MULTI_BATCH_MAPPING_20260624

## 1. 背景与问题
当前预测估值回测仅支持单一 batch_key。
这会导致以下问题：
- 无法覆盖“Q1/H1 由模型A生成，Q3/FY 由模型B生成”的真实生产口径。
- 跨年度/跨财报周期回测时，策略评估口径与实际生产运行存在偏差。

## 2. 目标
在保持 batch 隔离与可追溯性的前提下，支持“按 report_type 选择不同 batch_key”的组合回测。

## 3. 范围
- 服务：tushare_earnings_service
- 入口：预测回测接口（run_backtest）及其参数归一化、回测数据读取逻辑
- 不修改模型推理逻辑，仅调整回测读取历史快照的方式
- 前台接入：smartinvestor_fe 回测执行页支持按 report_type 选择 batch_key
- 网关接入：smartinvestor_be 提供 batch 候选列表代理接口

## 4. 接口变更（草案）
新增可选参数：
- batch_key_map: object
  - 示例：
    - Q1: backfill_pred_q1h1_xxx
    - H1: backfill_pred_q1h1_xxx
    - Q3: backfill_pred_q3fy_xxx
    - FY: backfill_pred_q3fy_xxx
    - FUSION: backfill_pred_fusion_xxx（可选）

兼容策略：
- 若提供 batch_key_map：优先使用 batch_key_map。
- 若未提供 batch_key_map：沿用现有单一 batch_key 行为。
- 若 batch_key_map 缺少某个 report_type：
  - 直接跳过该 report_type（不回退默认 batch_key）。

新增候选查询接口（效率优先）：
- GET /api/forecast/backtest/batch-candidates/
- query: start_year, end_year, report_type(可选), limit_per_report_type(可选)
- 返回结构：按 report_type 分组对象，避免前端二次分组开销
  - report_type -> [{ batch_key, record_count, first_asof_date, last_asof_date, latest_created_at }]
  - 组内按 record_count DESC，再按 latest_created_at DESC

## 5. 数据选择规则
按 asof_date + ts_code 聚合后，候选行来源如下：
- Q1 候选仅来自 batch_key_map.Q1
- H1 候选仅来自 batch_key_map.H1
- Q3 候选仅来自 batch_key_map.Q3
- FY 候选仅来自 batch_key_map.FY
- FUSION 候选仅来自 batch_key_map.FUSION（若配置）

同日同股若存在多条同 report_type 记录，沿用现有“最新财报公告日/报告优先级/分数”择优逻辑。

## 6. 风险与约束
- 必须保留 batch 级可追溯能力，回测结果中需回显各 report_type 使用的 batch_key。
- 禁止无约束全表扫描，避免混入不同模型版本造成口径污染。
- 防止未来信息泄漏：仅使用 asof_date 落在回测窗口内的记录。

## 7. 输出增强
回测响应新增：
- effective_batch_key_map: 实际生效的 report_type -> batch_key 映射
- coverage_by_report_type: 各 report_type 在回测窗口内的候选覆盖统计（可选）

候选接口返回新增：
- buckets: 按 report_type 分组的候选列表
- options: 扁平候选列表（用于兼容旧前端，如需）

## 8. 验收标准
1. 提供 Q1/H1 与 Q3/FY 不同 batch_key 时，回测可成功运行。
2. 未提供 batch_key_map 时，旧请求行为与结果保持兼容。
3. 回测结果可清晰审计每个 report_type 的 batch 来源。
4. 回测窗口跨 Q1->FY 周期时，候选覆盖显著优于单 batch_key。
5. 前端可按 Q1/H1/Q3/FY/FUSION 分别选择 batch，且下拉按记录数倒序展示。
6. 仅选择部分 report_type 时，未选择部分按“缺项跳过”生效。

## 10. 增补需求（2026-06-24）
### 10.1 预测任务提交后立即进入任务列表
- 场景：用户在“预测估值回测”点击执行后，任务应立即出现在“预测任务执行过程”表中。
- 目标：无需额外点击“刷新”按钮即可看到运行中的 task。
- 实现约束：
  - 在前端提交预测 scan task 成功后，立即主动拉取一次预测任务列表。
  - 保持现有轮询与状态判断逻辑不变。

### 10.2 回测候选池排除北交所股票
- 场景：预测回测候选不应包含北交所（BJ）代码。
- 目标：网关组装 ts_codes 时，过滤掉以 `.BJ` 结尾的代码。
- 实现约束：
  - 仅影响预测回测候选池构建逻辑，不影响其他市场数据接口。
  - 过滤规则采用代码后缀判断，统一大写后执行。

### 10.3 预测执行股票结果需展示股票名与最大跌幅
- 场景：预测估值回测“执行股票结果”列表中，股票名称为空，最大跌幅长期显示为 0。
- 目标：
  - 列表展示可读股票名称。
  - 返回并展示每只股票的最大跌幅（非固定 0）。
- 实现约束：
  - 预测服务在 `sample_trades` 交易明细中输出每笔交易 `max_drawdown_pct`。
  - 网关在预测 run 详情响应中按 `ts_code` 回填 `stock_name`。
  - 前端按 `ts_code` 聚合时使用交易明细中的 `stock_name` 和 `max_drawdown_pct` 计算展示值。

### 10.4 预测跨年回测 run 超时处理
- 场景：预测估值跨年任务（特别是候选池较大时）在网关调用预测服务 run 接口阶段出现 `timed out`。
- 目标：避免 run 调用被短超时（默认 12s）误判失败。
- 实现约束：
  - 仅对预测回测 `POST /api/forecast/backtest/run/` 使用更长超时。
  - 其他查询型接口（runs、detail、batch candidates）保持现有短超时策略。
  - 新增可配置项：`EARNINGS_SERVICE_BACKTEST_TIMEOUT_SECONDS`（默认 180s）。

### 10.5 预测回测接入账户模式
- 场景：用户在预测估值回测页面选择“账户模式”后，期望仓位/资金约束生效，而非信号模式下的高频多笔交易。
- 目标：预测回测支持 `mode=account`，并应用账户侧参数：
  - `starting_capital`
  - `max_position_pct`
  - `first_entry_pct`
  - `max_buy_per_day`
- 实现约束：
  - 保留 `mode=signal` 兼容行为；未显式传 mode 时默认沿用 signal。
  - 账户模式按日计算组合净值收益，年度年化指标基于账户净值曲线计算。
  - 账户模式下同一股票同一时点仅允许一笔持仓，买入受现金与仓位上限双重约束。
- 验收标准：
  - 同一组参数下，`mode=account` 交易数应显著低于 `mode=signal`（在非极端参数下）。
  - run 详情返回 `mode` 与账户参数，便于审计。

## 9. 示例请求（草案）
{
  "batch_key": "backfill_pred_fallback_2025",
  "batch_key_map": {
    "Q1": "backfill_pred_q1h1_2025",
    "H1": "backfill_pred_q1h1_2025",
    "Q3": "backfill_pred_q3fy_2025",
    "FY": "backfill_pred_q3fy_2025"
  },
  "start_year": 2024,
  "end_year": 2025,
  "min_score": 90,
  "max_risk": "LOW",
  "report_type": "ALL"
}
