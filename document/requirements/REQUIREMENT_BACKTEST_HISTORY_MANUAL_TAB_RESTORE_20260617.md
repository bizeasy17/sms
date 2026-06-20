# 需求说明：手动执行回测结果回归手动回测 Tab

## 1. 背景
- 当前“执行回测”按钮走异步 scan 提交流程（`/backtest/traditional/scan/submit/`，`scan_grid={}`）。
- 生成的 run_key 形如 `traditional_scan_..._run_001`，会被手动历史过滤规则识别为 scan-like。
- 导致用户从“执行回测”触发的单次回测结果进入“网格搜索”Tab，而不在“手动回测”Tab 展示。

## 2. 问题定义
1. 手动执行（单次）与网格扫描（多组合）在历史弹窗中的归类与用户认知不一致。
2. 用户期望“执行回测”产生的结果归于“手动回测”。

## 3. 目标
1. 将“执行回测”产生的单次异步结果归入手动历史。
2. 网格搜索 Tab 仅展示真正的扫描结果（多组合任务）。
3. 保持现有 run 详情、参数回填、双击跳转行为不变。

## 4. 服务归属确认
- 实现归属：`smartinvestor_be` 的回测历史聚合接口（`backtest/views.py`）。
- 前端 `smartinvestor_fe` 仅消费接口，不新增分流判定逻辑。

## 5. 方案
### 5.1 手动历史新增“单次 scan 结果”并入
- 在 `list_traditional_backtest_runs(kind=manual)` 的数据源中，额外并入来自 `TraditionalBacktestScanTask` 的“单次任务”结果。
- 单次任务判定：`task.total_jobs <= 1` 且 run 列表仅包含单一组合结果（`index/combo_index` 缺省或为 1）。

### 5.2 扫描历史排除“单次任务结果”
- 在 `list_traditional_backtest_runs(kind=scan)` 的聚合中，默认排除上述“单次任务”结果，仅保留真正网格扫描记录。

### 5.3 字段契约
- 返回字段继续沿用：`run_id/run_key/summary/params/task_id/task_key/combo_index/created_at/updated_at`。
- 不改变现有 API 路径与分页参数。

## 6. 验收标准
1. 手动执行新产出的 run 在“手动回测”Tab 可见。
2. 同一 run 不应同时出现在“手动回测”和“网格搜索”Tab。
3. 网格搜索 Tab 仍能展示多组合任务结果。
4. 双击历史行加载详情与参数回填正常。

## 7. 风险与回滚
- 风险：历史旧数据中存在边界任务（`total_jobs=1` 但业务上视为扫描）。
- 缓解：判定条件使用 `total_jobs + run index` 双约束；必要时补充显式 source 标记。
- 回滚：仅回退 `backtest/views.py` 的历史聚合逻辑，不影响回测执行主链路。

## 8. 验证计划
1. 执行一次“执行回测”，检查历史弹窗分组。
2. 提交一次带多个组合的网格扫描，检查仍在 scan Tab。
3. 校验 run 详情接口和参数回填接口响应不变。
