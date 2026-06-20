# REQUIREMENT_FIX_DAILY_VALUATION_RISK_UNICODE_20260611

## 背景
- `daily.bat` 在执行 `manage.py prefillvaluationrisk --market CN` 时出现：
  - `UnicodeEncodeError: 'charmap' codec can't encode characters ...`
- 该异常导致步骤返回非 0，触发 daily fail-fast 中断，后续步骤不执行。

## 目标
- 修复 `prefillvaluationrisk` 命令在 Windows 控制台编码场景下的日志输出兼容性，避免因不可编码字符中断任务。

## 服务归属
- 所属服务：`smartinvestor_be`
- 修改文件：`valuation_risk/management/commands/prefillvaluationrisk.py`

## 最小修复方案
1. 在命令内新增统一安全输出方法：
   - 优先按当前输出流编码写入。
   - 遇到 `UnicodeEncodeError` 时使用 `errors=replace` 进行降级输出。
2. 将命令中的关键 `self.stdout.write(...)` 调用切换到安全输出方法。
3. 不调整业务计算逻辑，不修改数据库写入逻辑。

## 验收标准
- `manage.py prefillvaluationrisk --market CN` 不再因字符编码报错退出。
- 命令可正常完成并返回 0。
- daily 链路中该步骤不会再因编码问题中断。

## 风险与回退
- 风险：低，仅影响控制台日志输出字符串。
- 回退：恢复原 `self.stdout.write` 调用。
