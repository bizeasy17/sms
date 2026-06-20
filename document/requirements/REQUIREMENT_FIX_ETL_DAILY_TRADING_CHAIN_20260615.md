# REQUIREMENT_FIX_ETL_DAILY_TRADING_CHAIN_20260615

## 背景
- 2026-06-15 的 UAT daily 链路中，ETL `trading` 当日下载失败，导致后续 BE `pulldata --batch=True --dtype=trading` 看起来只有 `all-not-pulled 404 / no unpulled`。
- 同日日志显示：
  - ETL daily trading download 报错：`Error fetching or saving data for trade_date 20260615: 'ts_code'`
  - 但命令随后仍输出：`Successfully processed trading data for None in frequency D`
  - 后续 BE batch pull 输出：`No unpulled trading data from ETL, skip batch pull.`
- 同时验证到 ETL 最新日频数据：
  - `trading latest_D=2026-06-12`
  - `fundamental latest_D=2026-06-15`
  - `cost latest_D=2026-06-15`
- 说明故障集中在 ETL trading 当日下载/入库链路，而不是 BE pull 主流程。

## 目标
- 修复 UAT 中 ETL 日频 `trading` 当日下载失败问题，使 2026-06-15 之后的 daily 链路能正常把当日交易数据写入 ETL，并继续被 BE 批量拉取。
- 修复后，若 `daily + adj_factor` 任一上游返回异常或列缺失，日志必须明确暴露原因，且命令不能再误报成功。

## 服务归属
- 主服务：`smartinvestor_etl`
- 主修改位置：`smartinvestor_etl/utils/data_utils.py`
- 相关调用位置：`smartinvestor_etl/stockdata/management/commands/download.py`
- 调度验证位置：`daily.bat`

## 根因判断
- 当前 ETL trading 日频逻辑已改为基于 `daily + adj_factor` 合并后计算 qfq/hfq。
- 在 `trade_date` 全市场下载分支中，代码直接假定 `adj_factor` 返回结果一定包含 `ts_code/trade_date/adj_factor` 三列。
- 当上游返回非标准结果或异常结果集时，切列/合并阶段抛出 `KeyError('ts_code')`，导致整日 trading 入库跳过。
- 现有异常被函数内部吞掉，只打印错误，不向上抛出；`download` 命令仍继续打印 success，造成 daily 调度误判成功。

## 最小修复方案
1. 在 ETL 的 `daily + adj_factor` 合并前，显式校验必需列：
   - `daily` 侧至少校验：`ts_code`, `trade_date`
   - `adj_factor` 侧至少校验：`ts_code`, `trade_date`, `adj_factor`
2. 当 `adj_factor` 缺列或返回非标准结果时：
   - 记录实际返回列和当前请求参数
   - 对当日全市场分支采用安全降级：允许仅以 `daily` 原始行情入库，并将 `adj_factor` 相关字段置空，避免整日 trading 缺失
3. 当出现真正不可继续的异常时：
   - `fetch_and_store_daily_trading_history` 需要把失败状态传递给 `download` 命令
   - `download --dtype=TRADING` 需要非 0 退出，避免 daily.bat 把失败误判为成功
4. 不修改 BE/FE 接口契约，不改 ETL `all-not-pulled` 404 语义；本次修复仅针对 ETL trading 数据生成与失败传播。

## 验收标准
- 重新执行 UAT ETL trading 当日下载后，ETL `StockTradingHistory` 的 `latest_D` 至少推进到 `2026-06-15`。
- 随后执行 BE `pulldata --freq=D --dtype=trading --batch=True` 时，不再出现“上游其实失败但这里只显示 no unpulled”的误导结果。
- 若上游再次返回异常 payload，日志中能看到缺失列信息，且命令退出码为失败，不再打印 success。
- `fundamental` 与 `cost` 现有日链路行为不受影响。

## 非目标
- 本次不调整 ETL API `all-not-pulled` 的 404 语义。
- 本次不重构全量复权重建命令 `rebuildadjfactor`。
- 本次不处理日志中的 `fromisoformat` 与 `charmap` 旁路问题，除非验证显示它们直接阻塞 trading 修复。

## 风险与回退
- 风险：若简单降级为 daily-only，部分 qfq/hfq 字段在上游 `adj_factor` 异常当天可能为空。
- 风险控制：优先保证当日原始交易数据不断链，复权字段后续可补跑修正。
- 回退：恢复 `data_utils.py` 与 `download.py` 的本次改动即可。

## 验证计划
1. 在 UAT 执行单次 `manage.py download --freq=D --dtype=TRADING --trade_date=20260615`。
2. 检查 ETL `StockTradingHistory` 最新日期是否推进。
3. 在 UAT BE 执行 `manage.py pulldata --freq=D --dtype=trading --batch=True`。
4. 复查 ETL/BE 日志，确认失败传播与成功路径都符合预期。