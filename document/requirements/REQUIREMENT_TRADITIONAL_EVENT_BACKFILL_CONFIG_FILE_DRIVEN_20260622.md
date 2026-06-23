# REQUIREMENT_TRADITIONAL_EVENT_BACKFILL_CONFIG_FILE_DRIVEN_20260622

## 1. 背景

当前 `backfill_traditional_history_event_driven.bat` 已支持通过参数/环境变量强制 `report type + fiscal year`。
但批量回填多个年份和多个报告期时，命令较长且易出错（循环嵌套、参数拼接、run_tag 管理复杂）。

## 2. 目标

将传统估值历史回填改为“配置文件驱动”，bat 读取配置并逐条执行回填任务。

要求支持：

1. 简写：`2023|ALL`、`2024|ALL`、`2025|ALL`
2. 明确类型：`2024|Q1|H1|Q3`（可多类型）
3. 保持现有位置参数能力（start/end/scope/methods/cadence/topn）
4. 保持向后兼容：未提供配置文件时，仍按当前单任务逻辑运行

## 3. 范围

### 3.1 修改范围

- 文件：`backfill_traditional_history_event_driven.bat`
- 新增配置文件读取与任务展开逻辑
- 新增日志分段（每个 year+report_type 任务单独标记）

### 3.2 非目标

- 不修改 `smartinvestor_be/manage.py prefillvaluationsnapshot` 命令实现
- 不改回测服务逻辑
- 不自动修复历史中已有 NULL 记录（仅影响后续回填）

## 4. 配置文件格式

建议文件：`configs/traditional_backfill_plan.txt`（纯文本 UTF-8）

规则：

1. 每行一个 fiscal_year 配置
2. 支持注释：`#` 开头
3. 支持空行
4. 行格式：
   - `YYYY|ALL`
   - `YYYY|RT1|RT2|RT3...`
5. 报告期取值：`Q1`、`H1`、`Q3`、`FY`、`ANNUAL`
6. `FY` 在执行层统一映射为传入 `FY`（由下游规范化）

示例：

```txt
# 年份 + 全部报告期
2023|ALL
2024|ALL

# 仅跑指定报告期
2025|Q1|H1|Q3
```

## 5. bat 参数设计

新增可选参数：

- 第4位：`PLAN_FILE`（当值是存在的文件路径时启用配置模式）

其余参数与当前保持一致：

- `START_DATE`、`END_DATE`、`SCOPE`
- `METHODS`、`CADENCE_DAYS`、`BUSINESS_MATCH_TOPN`

兼容策略：

1. 第4位如果是文件路径：进入配置模式
2. 第4位如果不是文件路径：按当前逻辑视作旧参数（methods/report_type）

## 6. 执行逻辑（配置模式）

1. 读取配置文件，解析为任务列表：`(fiscal_year, report_type)`
2. 若某行是 `ALL`，展开为：`Q1,H1,Q3,FY`
3. 按顺序逐任务执行：
   - 设置 `TARGET_REPORT_TYPE`
   - 设置 `TARGET_FISCAL_YEAR`
   - 调用现有事件驱动流程（保留 checkpoint/no-event/no-rows 语义）
4. 日志中记录任务上下文：
   - `plan_year`
   - `plan_report_type`
   - `plan_task_index/total`

## 7. 验收标准

1. 配置文件 `2023|ALL, 2024|ALL, 2025|ALL` 可被正确展开并逐项执行
2. 配置文件 `2024|Q1|H1|Q3` 仅执行对应报告期
3. 每个任务写入日志并可追溯
4. 配置模式不影响原有非配置模式执行

## 8. 风险与约束

1. 事件驱动本质仍是“事件日期+命中股票”，不是逐交易日全量补齐
2. 单次计划任务较多时耗时增加明显
3. checkpoint 语义需明确是“按任务维度”还是“全局维度”（建议按任务维度，避免任务间互相跳过）

## 9. 影响文件

- `backfill_traditional_history_event_driven.bat`（待改）
- 可新增示例配置文件（可选）：`configs/traditional_backfill_plan.txt`
