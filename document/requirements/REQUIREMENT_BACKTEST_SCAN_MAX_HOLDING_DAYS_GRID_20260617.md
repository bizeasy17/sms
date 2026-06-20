# 需求说明：网格搜索新增持仓天数条件

## 1. 背景
- 当前回测页面已支持单次参数 max_holding_days（最大持有天数，交易日口径）。
- 当前网格搜索参数区未提供 max_holding_days 网格输入，无法在扫描任务中对该参数做组合遍历。

## 2. 目标
1. 在回测页面网格搜索参数区增加“持仓天数网格”输入。
2. 扫描任务提交时将 max_holding_days 作为 scan_grid 组合项下发。
3. 后端扫描任务按组合覆盖 max_holding_days，参与每组回测执行。
4. 历史结果中的 params 可回显该参数。

## 3. 服务归属
- 前端实现归属：smartinvestor_fe
  - 文件：smartinvestor_fe/src/views/BacktestExecuteView.vue
  - 工作：新增输入控件、scanGrid 状态字段、buildScanGridPayload 传参。
- 后端实现归属：smartinvestor_be
  - 文件：backtest/views.py
  - 工作：沿用现有 _parse_scan_grid 组合机制，无需新增接口；确认 max_holding_days 能进入 override 合并并生效。

## 4. 参数契约
- 请求路径：/api/backtest/traditional/scan/submit/
- 请求体 scan_grid 新增键：max_holding_days
- 类型：number 数组（整数，>=0）
- 示例：
  - max_holding_days: [0, 5, 10, 20]
- 语义：
  - 0 表示不限制最大持有天数
  - 正整数按交易日计数触发 max_holding_days_hit

## 5. 交互与文案
- 网格搜索区新增字段名：持仓天数网格
- 输入示例文案：例如: 0,5,10,20
- 与其他网格字段一致，使用逗号分隔。

## 6. 验收标准
1. 扫描提交请求中包含 max_holding_days 网格数组。
2. 后端任务 result.runs 中不同组合的 params.max_holding_days 按网格变化。
3. 至少一组运行触发 max_holding_days_hit 时，交易明细 exit_reason 可见。
4. 不配置该网格时，行为与当前版本一致。

## 7. 风险与回滚
- 风险：网格组合数膨胀导致任务耗时增加。
- 缓解：用户侧建议控制组合规模；后端保持现有串行扫描与可取消机制。
- 回滚：仅回退前端新增网格字段与 payload 键。
