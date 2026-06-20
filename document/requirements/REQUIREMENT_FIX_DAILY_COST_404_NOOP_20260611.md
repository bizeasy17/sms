# REQUIREMENT_FIX_DAILY_COST_404_NOOP_20260611

## 背景
- daily 日志中出现：
  - `Failed to batch fetch cost data: 404 ... /stocks/cost/D/all-not-pulled/`
- ETL 侧接口在“无待拉取记录”时返回 404（当前实现属于业务语义：no data）。
- BE 侧命令 `manage.py pulldata --batch=True --dtype=cost` 将该 404 统一按错误输出，造成误报。

## 目标
- 当 `all-not-pulled` 返回 404 且语义为“无待拉取数据”时，按 no-op 处理，不再记为错误。

## 服务归属
- 所属服务：`smartinvestor_be`
- 修改位置：`datastore/management/commands/pulldata.py`

## 最小修复方案
1. 在 batch 拉取逻辑中，对 `requests` 异常做细分：
   - 若请求 URL 包含 `all-not-pulled` 且状态码是 404：
     - 记录 info/warning（例如 `no unpulled cost data, skip`）
     - 继续执行，不输出 failed 错误。
   - 其它异常仍保持错误处理。
2. 不改 ETL API 契约，不改 HTTP 返回码，不影响现有调用方兼容性。

## 验收标准
- 日志不再出现 `Failed to batch fetch cost data: 404` 的误报。
- 在确实无待拉取 cost 数据时，命令正常完成并继续后续步骤。
- 真正网络/服务异常仍会被报错。

## 风险与回退
- 风险：低，仅调整日志与异常分支。
- 回退：恢复原异常处理逻辑即可。
