# REQUIREMENT_DAILY_SW_ROTATION_EVAL_RELIABILITY_20260611

## 背景
- 当前 `daily.bat` 在 `BE valuation risk prefill daily` 失败时会直接 `exit /b`。
- 结果：后续 `BE sw rotation run daily evaluation` 不执行，导致 TopN daily summary 当天无新增记录。

## 目标
- 保证 SW 轮动 run 的 daily evaluation 每天都能执行并落盘（在有 run 的情况下）。

## 服务归属
- 实现服务：UAT 编排脚本 `daily.bat`。
- 不修改后端 API 契约，不修改前端协议。

## 最小方案（推荐）
1. 将步骤 `BE sw rotation run daily evaluation` 前置到 `BE valuation risk prefill daily` 之前。
2. 保持其余步骤失败即中止的策略不变。

## 预期效果
- 即使 `valuation risk prefill` 当天失败，SW rotation daily evaluation 已先执行，前台可看到当天 daily_series 新点。

## 验证
1. 人工执行 `daily.bat`（或模拟逐步执行）并确认日志出现：
   - `BE sw rotation run daily evaluation`
   - `[sw-rotation] refreshed daily evaluation done`
2. 调用 run detail API 确认 `evaluation.daily_series` 增量。

## 风险与回退
- 风险：无 API 行为变化，仅步骤顺序调整。
- 回退：恢复 `daily.bat` 原步骤顺序。
