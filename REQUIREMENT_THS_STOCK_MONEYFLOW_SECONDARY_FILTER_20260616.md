# 需求说明：估值选股集成 THS 个股资金流（二次条件）

## 1. 背景
- 现有“估值选股”已支持估值与财务条件，但缺少个股资金流维度。
- TuShare 提供 `moneyflow_ths` 接口，可获取 THS 个股资金流向日数据。
- 目标是将资金流作为“可选二次筛选条件”，默认不影响当前选股行为。

## 2. 目标
1. 将最近 1 年 THS 个股资金流数据入库，并支持日常增量更新。
2. 在估值选股中新增“资金流入条件开关”，仅开关开启时执行资金流二次过滤。
3. 在估值选股页面将资金流条件区块集成到“财务选个股条件”之下，并以横线分割。
4. 新增“净流入天数窗口”选项：`5/10/15/30/60` 日。
5. 保持默认行为兼容：不开启资金流条件时，结果与当前逻辑一致。

## 3. 服务归属（已确认）
- 归属：
  - 数据同步与筛选逻辑：`smartinvestor_be`
  - 页面交互与参数透传：`smartinvestor_fe`

## 4. 范围
- 后端：
  - 新增 `moneyflow_ths` 个股日数据入库模型/表与同步命令。
  - 在估值选股实时接口增加“资金流条件”参数解析与二阶段过滤。
- 前端：
  - 估值选股筛选面板新增“资金流入条件”区块（位于财务条件下方，横线分割）。
  - 新增开关与净流入天数选项控件，并按开关状态决定是否传参。

## 5. 非目标
- 不改历史 CSV 结果回放链路。
- 不在本期引入分钟级资金流。
- 不改变现有估值打分公式。

## 6. 数据设计（草案）

### 6.1 数据源
- TuShare：`moneyflow_ths`
- 建议主键：`trade_date + ts_code`

### 6.2 入库策略
- 初始化：回补最近 1 年（按交易日分片拉取，避免单次过大）。
- 日增量：每日任务仅同步最近交易日数据。
- 幂等：按唯一键 `upsert`。
- 限流：支持请求间隔与失败重试（可配置）。

### 6.3 建议表结构（草案）
- 表名建议：`StockMoneyflowThsDaily`
- 字段建议：
  - `trade_date` (date, index)
  - `ts_code` (varchar, index)
  - `net_mf_amount` (numeric, nullable)
  - `buy_lg_amount`/`sell_lg_amount` (numeric, nullable)
  - `raw_payload` (json, nullable)
  - `updated_at` (datetime)
- 约束建议：`unique(trade_date, ts_code)`

## 7. 业务规则（草案）

### 7.1 过滤开关
- 请求参数：`apply_moneyflow_filters`
- 默认：`false`
- 行为：
  - `false`：跳过资金流过滤。
  - `true`：执行资金流二阶段过滤。

### 7.2 净流入天数窗口
- 请求参数：`moneyflow_net_inflow_days_window`
- 可选值：`5 | 10 | 15 | 30 | 60`
- 默认值建议：`10`

### 7.3 过滤判定（已确认）
- 采用口径 B：最近 N 日累计净流入 `sum(net_mf_amount) > 0` 即通过。
- 本期不引入 `min_positive_days` 阈值参数。

## 8. API 契约变更（草案）
- 接口：`GET /stock-pick-valuation/{trade_date}/{scope}/`
- 新增 query 参数：
  - `apply_moneyflow_filters`：`1/true/on/yes` 开启，其他为关闭。
  - `moneyflow_net_inflow_days_window`：`5|10|15|30|60`
- 响应回显：
  - `valuation_filter.effective_moneyflow_filters`
  - 示例：
    - `apply_moneyflow_filters`
    - `moneyflow_net_inflow_days_window`
    - `matched_count_before/after`

## 9. 前端交互（草案）
- 页面：估值选股页。
- 布局：在“财务选个股条件”区块正下方新增“资金流入条件”区块，中间加横线分割。
- 控件：
  - 开关：`应用资金流入条件`
  - 下拉：`净流入天数窗口`（5/10/15/30/60）
- 联动：
  - 开关关闭：不传资金流参数。
  - 开关开启：传资金流参数并显示后端回显条件。

## 10. 调度与命令（草案）
- 新增命令（建议名）：`sync_moneyflow_ths_stock_daily`
  - 支持 `--start-date --end-date`（初始化回补）
  - 支持 `--latest`（日增量）
- 调度：
  - `daily.bat` 增加日增量步骤。
  - 首次回补建议单独执行，不放入日常调度。

## 11. 验收标准
1. 最近 1 年 `moneyflow_ths` 个股数据可成功入库，且可重复执行无重复。
2. 开关关闭时，估值选股结果与现网当前行为一致。
3. 开关开启时，资金流条件可生效并在响应中可回显。
4. 前端区块位置正确：位于财务条件下方，且有横线分割。
5. 净流入天数窗口仅允许 5/10/15/30/60。

## 12. 风险与回退
- 风险：TuShare 限流、字段波动、停牌个股导致窗口数据不足。
- 回退：关闭 `apply_moneyflow_filters`，同步任务可独立停用，不影响估值主链路。

## 13. 已确认决策（2026-06-16）
1. 服务归属：`smartinvestor_be` + `smartinvestor_fe`。
2. 净流入口径：采用口径 B（最近 N 日累计净流入为正）。
3. 默认窗口：`10` 日。
4. 本期范围：仅实时接口，不改历史 RESULT 回放链路。
