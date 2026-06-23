# REQUIREMENT_TRADITIONAL_EVENT_BACKFILL_FORCE_REPORT_TYPE_YEAR_20260622

## 1. 背景

当前 `backfill_traditional_history_event_driven.bat` 调用 `prefillvaluationsnapshot` 时默认走 `AUTO` 报告期选择。
这会导致历史回填结果中报告期类型（Q1/H1/Q3/FY）按“当日可见最新期”混合分布，无法保证按指定年份与指定报告期完整补齐。

## 2. 目标

为传统估值事件驱动回填脚本增加“强制报告期与财年”能力，支持在执行时明确指定：

- `target_report_type`: `Q1|H1|Q3|ANNUAL|FY`
- `target_fiscal_year`: 例如 `2023/2024/2025`

并透传到 `smartinvestor_be/manage.py prefillvaluationsnapshot`：

- `--target-report-type <...>`
- `--target-fiscal-year <...>`

## 3. 范围

### 3.1 本次改动范围

- 文件：`backfill_traditional_history_event_driven.bat`
- 增加参数/环境变量解析与日志打印。
- 在 full_refresh 和 partial_refresh 两个调用分支都透传强制报告期参数。

### 3.2 非目标

- 不修改 `prefillvaluationsnapshot` Python 命令逻辑。
- 不修改数据库模型与回测逻辑。
- 不保证事件驱动模式下“所有股票都一定有有效估值结果”。

## 4. 设计方案

采用“兼容优先”的增量方案：

1. 默认行为保持不变（未指定时仍为 AUTO）。
2. 新增两项可选输入（推荐环境变量，避免破坏现有位置参数解析）：
   - `BACKFILL_TARGET_REPORT_TYPE`
   - `BACKFILL_TARGET_FISCAL_YEAR`
3. 同时支持可选命令行位置参数覆盖环境变量：
  - 第4位可传 `target_report_type`
  - 第5位可传 `target_fiscal_year`
  - 若第4位不是合法报告期值，则按旧逻辑视为 methods 参数，不影响历史调用
4. 若仅提供其一则报错退出，避免误跑。
5. 在日志中输出最终解析值，便于审计：
   - `forced_target_report_type`
   - `forced_target_fiscal_year`

## 5. 使用示例（目标态）

```powershell
$env:BACKFILL_TARGET_REPORT_TYPE = "Q1"
$env:BACKFILL_TARGET_FISCAL_YEAR = "2024"
.\backfill_traditional_history_event_driven.bat 2023-01-01 2025-12-31 60
```

或循环执行：

```powershell
$scopes  = @("00","30","60","68")
$reports = @("Q1","H1","Q3","FY")
$years   = @(2023,2024,2025)

foreach ($y in $years) {
  foreach ($rt in $reports) {
    $env:BACKFILL_TARGET_REPORT_TYPE = $rt
    $env:BACKFILL_TARGET_FISCAL_YEAR = "$y"
    foreach ($sc in $scopes) {
      $env:BACKFILL_RUN_TAG = "s${sc}_${y}_$rt"
      .\backfill_traditional_history_event_driven.bat 2023-01-01 2025-12-31 $sc
    }
  }
}
```

## 6. 验收标准

1. 未设置强制参数时，脚本行为与当前一致。
2. 设置 `BACKFILL_TARGET_REPORT_TYPE + BACKFILL_TARGET_FISCAL_YEAR` 后：
   - 日志可见强制参数；
   - `prefillvaluationsnapshot` 命令行包含对应参数；
   - 新写入历史数据的 `target_report_type` 与输入一致。
3. 错误输入（仅 report type 或仅 fiscal year）会快速失败并给出可读报错。

## 7. 风险与注意事项

1. 事件驱动仅处理“事件日期 + 命中股票”，即使强制报告期也可能因 no rows 或无事件而无新增。
2. 强制模式会提高运行轮数与耗时（按 scope x report x year 扩增）。
3. 若要彻底补齐历史，需结合周期与范围策略（必要时增设非事件驱动补偿跑批）。

## 8. 影响文件

- `backfill_traditional_history_event_driven.bat`（待改）
