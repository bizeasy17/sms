# Requirement: Earnings Refresh Scope 60 后异常修复（2026-06-13）

## 背景
在 `CANDIDATE_POLICY=all` 的全量刷新模式下，`scope=60` 运行后出现：
- `'log' is not recognized`
- `'pe' is not recognized`
- 后续 `Select-String` 读取 candidates 文件报不存在。

## 目标
1. 避免 `REFRESH_REASON` 中特殊字符（如 `|`）导致批处理命令被错误拆分。
2. 避免在 candidates 文件不存在时触发 `Select-String` 路径错误。
3. 保持原有刷新流程和参数语义不变（最小改动）。

## 方案
1. 引入 `REFRESH_REASON_SAFE`，仅保留 `[0-9A-Za-z._-]`，其余字符替换为 `_`。
2. `REFRESH_RUN_ID` 基于 `REFRESH_REASON_SAFE` 生成。
3. `COMMON_ARGS` 中 `--refresh-policy` 与 `--refresh-run-id` 使用引号包裹。
4. 启动日志中输出 `refresh_reason_safe`，不直接输出可能含管道符的原始 reason。
5. `:maybe_run_scope` 先检查 `%CANDIDATE_FILE%` 是否存在，不存在则记录 skip 日志并返回。

## 验收标准
1. 全量模式执行不再出现 `'log'/'pe' is not recognized`。
2. 不再出现 candidates 文件不存在导致的 `Select-String` 报错。
3. scope 流程按既定策略继续执行，并保留已有日志结构。
