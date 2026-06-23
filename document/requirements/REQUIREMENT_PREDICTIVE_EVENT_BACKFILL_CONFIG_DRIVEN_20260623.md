# 需求文档：预测估值回填脚本同构改造（对齐传统版）

- 日期：2026-06-23
- 环境：UAT
- 目标：将预测估值回填脚本改造为与传统估值回填一致的可用性与可维护性模式（命名、参数、配置驱动、验收方式）。

## 1. 背景与问题

当前预测回填脚本仍采用年份后缀命名与旧参数模式，存在以下问题：

1. 文件名与日志名含 2024_2025 后缀，和传统脚本当前命名规范不一致。
2. 事件驱动脚本缺少配置文件驱动的批量任务模式（类似传统版 plan 模式）。
3. 并行脚本硬编码调用旧文件名，后续维护成本高。
4. 运维层面难以统一“单次命令 + 配置文件”执行体验。

## 2. 改造目标

1. 去年份后缀命名，与传统脚本保持一致。
2. 支持配置文件驱动批量执行（plan mode）。
3. 保留原有命令行兼容能力，不破坏既有调用。
4. 提供最小冒烟验收配置与命令。

## 3. 拟改造文件

1. backfill_predictive_history_2024_2025.bat
2. backfill_predictive_history_event_driven_2024_2025.bat
3. backfill_predictive_history_event_driven_2024_2025_parallel_scopes.bat

## 4. 目标命名（拟）

1. backfill_predictive_history.bat
2. backfill_predictive_history_event_driven.bat
3. backfill_predictive_history_event_driven_parallel_scopes.bat

并同步内部日志/检查点/事件文件命名去后缀：

1. logs/backfill_predictive_history.log
2. logs/backfill_predictive_history_event_driven*.log
3. logs/event_dates_predictive*.txt
4. logs/event_codes_predictive/*

## 5. 配置驱动模式（拟）

在事件驱动脚本中新增 plan mode（与传统版对齐）：

- 触发方式：第 4 个参数为存在的配置文件路径。
- 行格式（初版建议）：
  - YEAR|REPORT_TYPES
  - 示例：
    - 2023|LATEST
    - 2024|LATEST,FUSION
    - 2025|LATEST
- 展开规则（初版建议）：
  - 每行展开为一个子任务：
    - start_date=YEAR-01-01
    - end_date=YEAR-12-31
    - report_types=REPORT_TYPES
  - 其余参数（scope/store_mode/enable_regime_switch）沿用父命令。

说明：预测回填命令本身没有 target_fiscal_year 参数，因此这里的 YEAR 用于日期窗口切分，而非强制财报年度参数。

## 6. 并行脚本同步

并行脚本改为调用新文件名，并更新提示日志中的示例日志路径。

## 7. 兼容性要求

1. 保持原有非 plan 模式参数行为不变。
2. 保留 report_types 自动拼接与 PowerShell 参数拆分兼容逻辑。
3. 保持 run tag 机制与按 scope 隔离日志的能力。

## 8. 验收标准

1. 新脚本名可用，旧后缀脚本不再作为主入口。
2. plan 模式可读取配置并展开子任务。
3. 单日、单 scope、单 report_types 冒烟可完成。
4. 日志中可见：plan 启动、task start、task ok、plan done。

## 9. 冒烟验收建议

- 建议 smoke 配置：
  - 2025|LATEST
- 建议命令：
  - backfill_predictive_history_event_driven.bat 2025-03-03 2025-03-03 600009.SH .\configs\predictive_backfill_plan_smoke.txt history 0

## 10. 风险与回滚

1. 风险：批处理参数解析（逗号/竖线/空格）在不同终端有差异。
2. 风险：日志文件被并发进程占用导致追加失败。
3. 回滚：保留提交粒度可回滚至改造前版本；并行脚本可临时回指旧入口。

## 11. 待确认项（需用户确认）

1. 服务归属：本次改造是否由 UAT 脚本层（调用 tushare_earnings_service 命令）负责实现？
2. plan 格式是否确认采用 YEAR|REPORT_TYPES（YEAR 仅用于日期窗口）？
3. 是否同步改造非事件驱动预测脚本为同名去后缀版本（建议是）？
4. 是否需要新增正式配置文件：configs/predictive_backfill_plan.txt（例如 2023-2025）？
