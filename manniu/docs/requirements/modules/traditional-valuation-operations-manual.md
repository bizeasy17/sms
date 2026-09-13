# 传统估值运营手册

## 1. 文档目的

本文档面向 `manniu_backend` 传统估值模块的开发、测试和运维人员，说明如何执行配置校验、历史估值回填、事件检测、事件消费、增量刷新和结果核对。

本文档以当前 Django management command 的实际行为为准。设计文档中尚未落地的锁、断点续跑、水位线、完整调度器和公共只读 API，不应视为当前批处理已经提供的能力。

## 2. 处理边界

传统估值模块负责 SW 行业参数解析、估值计算、风险结果、估值快照、事件状态和运行审计。它不负责：

- 同步 Tushare、原始财务数据、行情数据或披露数据；
- 分类市场风格、个股风格或生成财报披露事件；
- 修改 `market_data` 的证券、行业映射和 regime 状态；
- 执行交易或生成交易指令。

推荐数据链路如下：

```text
market_data / financials 原始数据
            |
            v
已提交的行业、行情、财务和披露数据
            |
            +--> detect-events --> TraditionalValuationEventState
            |                            |
            |                            v
            |                    consume-events / refresh
            |
                 +--> historical backfill --> FINANCIAL_DISCLOSED events
                         |
                         v
                       consume-events path
                         |
                         v
                 TraditionalValuationSnapshot / Current / Risk
```

## 3. 执行环境

### 3.1 项目目录与 Django 配置

以下示例假定后端目录为：

```text
C:\Users\HANJ29\Development\web\UAT\manniu\manniu_backend
```

PowerShell 中执行：

```powershell
Set-Location 'C:\Users\HANJ29\Development\web\UAT\manniu\manniu_backend'
$env:DJANGO_SETTINGS_MODULE = 'config.settings'
```

不要在 PowerShell 中使用 `cd /d`；那是 `cmd.exe` 语法。

### 3.2 Python 与数据库

使用已经安装项目依赖的目标虚拟环境。传统估值状态必须写入项目配置的 PostgreSQL，不要用临时 SQLite 连接验证结果。执行前确认：

1. Django settings 指向目标 UAT PostgreSQL；
2. `market_data.Security`、行业映射、行情和财务表已完成必要同步；
3. `static/valuation_config` 下的活动模板文件存在且可读；
4. 传统估值相关表已经迁移；
5. 目标报告期和估值日期的点时数据覆盖完整。

## 4. 回填与事件刷新的边界

历史回填和增量事件刷新使用不同的事件范围，但共享事件消费和估值持久化路径：

- `backfill` 按 `actual_date` 扫描指定范围内已提交的财报披露，创建幂等的 `FINANCIAL_DISCLOSED` 事件，再消费本次导入的事件生成估值；不按交易日逐日遍历；
- `detect-events` 从 `financials` 和 `market_data` 已提交事件源导入本地待处理事件；
- `consume-events` 消费本地待处理事件，并按事件作用域重新计算传统估值；
- `refresh` 等价于先检测事件、再消费事件，不等价于历史回填；
- `refresh-business-matches` 只刷新业务文本到 SW 行业的匹配结果，不是事件扫描，也不替代估值回填。

推荐日常顺序是：市场/财务数据同步，必要的业务匹配或模板刷新，历史回填或增量事件检测，事件消费。历史回填阶段只处理财报 disclosure 事件，不回放历史市场风格和个股风格切换。

## 5. 命令总览

管理命令入口：

```powershell
python manage.py traditional_valuation <subcommand> [options]
```

当前支持：

| 子命令 | 用途 | 是否写库 |
| --- | --- | --- |
| `validate` | 校验模板和传统估值表 | 否 |
| `backfill` | 按财报 `actual_date` 导入 disclosure 事件并消费生成历史估值 | 是，除非 dry-run |
| `refresh-business-matches` | 刷新证券的 L2 业务行业匹配 | 是，除非 dry-run |
| `detect-events` | 导入财报披露、市场风格和个股风格事件 | 是，除非 dry-run |
| `consume-events` | 消费待处理事件并刷新受影响估值 | 是，除非 dry-run |
| `refresh` | 依次执行事件检测和事件消费 | 是，除非 dry-run |
| `status` | 输出快照、事件和运行计数 | 否 |

公共参数包括：

| 参数 | 说明 |
| --- | --- |
| `--ts-codes 000001.SZ,600519.SH` | 逗号分隔的标准股票代码 |
| `--scope all\|ts-code\|60\|00\|30\|68` | 全部、精确代码或按股票代码前缀筛选；`ts-code` 必须同时提供 `--ts-codes` |
| `--asof-date YYYY-MM-DD` | 估值或事件读取的点时日期；缺省为当天 |
| `--start-date YYYY-MM-DD` | 历史 disclosure `actual_date` 扫描开始日期；与 `--history-years` 互斥 |
| `--end-date YYYY-MM-DD` | 历史 disclosure `actual_date` 扫描结束日期；缺省为当天 |
| `--history-years N` | 未指定开始日期时的 disclosure 历史扫描年数，缺省 `5` |
| `--report-type Q1\|H1\|Q3\|FY` | 回填或事件消费的报告类型，缺省 `FY` |
| `--report-types Q1,H1,Q3,FY` | 回填时一次处理多个报告类型 |
| `--profit-bucket formal\|blended\|both` | 正式财报、混合口径或两者 |
| `--business-match-topn N` | L2 业务匹配候选数，缺省为 3 |
| `--limit N` | 历史 disclosure 导入、事件检测、事件消费或市场事件扇出的批量上限；backfill 为 `0` 时不限制导入范围并自动分批消费 |
| `--retry-failed` | 消费时同时重试失败事件 |
| `--dry-run` | 只校验范围，不写估值、事件或运行状态 |

## 6. 配置校验

每次模板变更、数据库迁移或大范围回填前执行：

```powershell
python manage.py traditional_valuation validate
```

成功时应输出模板根目录、模板版本、源文件 hash 和行业映射版本。以下任一情况应停止后续回填：

- 活动模板不存在或没有可用默认参数；
- `traditional_valuation_snapshot`、latest、risk、event state 或 run 表缺失；
- 活动模板的 mapping version 与 `market_data` 不一致；
- 目标证券没有有效 SW 行业映射且没有允许的全局回退；
- 财务、行情或披露数据未覆盖目标点时日期。

## 7. 历史估值回填

### 7.1 预览范围

单证券、H1、正式利润口径的 dry-run。dry-run 只验证证券范围，不扫描或写入 disclosure 事件：

```powershell
python manage.py traditional_valuation backfill `
  --ts-codes 600000.SH `
  --start-date 2026-01-01 `
  --end-date 2026-09-08 `
  --report-type H1 `
  --profit-bucket formal `
  --dry-run
```

`--dry-run` 只检查证券是否存在并输出数量，不创建 run 或快照。

### 7.2 执行回填

```powershell
python manage.py traditional_valuation backfill `
  --ts-codes 600000.SH `
  --start-date 2021-01-01 `
  --end-date 2026-09-08 `
  --report-type H1 `
  --profit-bucket both `
  --business-match-topn 3
```

当前命令先从 `FinancialDisclosureRecord` 中筛选 `actual_date` 落在范围内、报告类型和证券范围匹配的已提交 disclosure，按上游 disclosure 身份幂等创建 `FINANCIAL_DISCLOSED` 事件，然后复用事件消费路径生成估值。消费时使用事件 payload 中的 `financial_end_date` 和 `actual_date`，不会重新按每天选择财报。`both` 会分别生成 `formal` 和 `blended`，两者是独立且可审计的快照身份。回填失败会累计失败数，完成后将 run 标记为失败，运维应结合 run 记录、事件状态和数据库抽样定位。

历史回填不会导入 `MARKET_STYLE_CHANGED` 或 `SECURITY_STYLE_CHANGED` 历史事件；本阶段使用配置的基准/默认风格完成 disclosure 触发的估值。新增财报或当前风格切换的日常处理，仍通过独立的 `detect-events`、`consume-events` 或 `refresh` 执行。

### 7.3 财报选择与点时核对

一次传统估值计算有两个不同的日期概念：

- `asof_date`：估值可见性边界。财务记录必须满足 `ann_date <= asof_date`，行情和日基本面必须满足 `trade_date <= asof_date`；
- `financial_end_date`：财报所属财务期末，例如 03-31、06-30、09-30 或 12-31。它表示使用哪个报告期，不能替代公告日期过滤。

当前输入解析过程是：

```text
security + FINANCIAL_DISCLOSED event
  -> 使用事件 actual_date 作为 asof_date
  -> 使用事件 financial_end_date 锁定财报期
  -> 校验财务记录的有效公告日期 <= actual_date
  -> 用该财报的 end_date 查询 indicator、balance、cashflow
  -> 查询 asof_date 之前最近行情和基本面
  -> 计算估值并持久化
```

例如，`financial_end_date=2025-06-30`、`ann_date=2025-08-28` 的中报，在 `asof_date=2025-08-20` 的历史估值中不能使用；从 `2025-08-28` 起才具备可见性。运维抽样时应同时核对 `asof_date`、`financial_end_date`、财报 `ann_date` 和 `source_trade_date`，不能只检查报告期末日期。

因此，`--start-date` 和 `--end-date` 限制的是 disclosure 的有效发布日 `actual_date`，不表示财报的 `financial_end_date` 必须落在这个日期区间内。每个 disclosure 事件携带自己的财报期末和实际发布日，系统按该事件重放点时输入。例如某条 `H1` disclosure 的 `financial_end_date=2025-06-30`、`actual_date=2025-08-28`，它只会在包含 `2025-08-28` 的回填范围中触发估值；早于该日期的回填不会使用它。

| 报告类型 | `asof_date=2025-09-01` 时使用的财务期末 | 公告日 | 选择原因 |
| --- | --- | --- | --- |
| `Q1` | `2025-03-31` | 已公告 | 2025 Q1 已满足 `ann_date <= asof_date` |
| `H1` | `2025-06-30` | 已公告 | 2025 H1 已满足 `ann_date <= asof_date` |
| `Q3` | `2024-09-30` | 2024-10-28 | 2025 Q3 要到 2025-10-31 才公告 |
| `FY` | `2024-12-31` | 已公告 | 2024 年报是当时最新可见年报 |

因此，看到回填结果中的财报期末日期早于 `actual_date`，不应直接判定为日期参数错位；应检查 disclosure 事件的 `actual_date`、快照的 `asof_date`、`financial_end_date` 和 `financial_ann_date`。财报期末早于发布日是正常的报告时序，不应把 `financial_end_date` 当成 disclosure 扫描日期。

当前命令按 disclosure 的 `actual_date` 范围回填，不再按交易日展开历史区间，也不接受 `backfill --asof-date`。`--report-types` 可以一次筛选 Q1、H1、Q3、FY；未指定 `--start-date` 时，使用 `--history-years` 从当天向前生成 disclosure 扫描起点。

### 7.4 Windows batch 回填

传统估值 batch 位于：

```text
manniu_backend\scripts\traditional_valuation.bat
```

调用格式：

```cmd
traditional_valuation.bat backfill [START_DATE] [END_DATE] [SCOPE] [TS_CODES] [LIMIT] [REPORT_TYPES] [HISTORY_YEARS]
traditional_valuation.bat refresh
```

位置参数说明：

| 位置 | 参数 | 缺省值 | 说明 |
| --- | --- | --- | --- |
| 1 | `MODE` | `backfill` | `backfill`、`history`、`refresh`；`history` 会转换为 `backfill` |
| 2 | `START_DATE` | 空 | 回填开始日期 |
| 3 | `END_DATE` | 空 | 回填结束日期 |
| 4 | `SCOPE` | `all` | `all`、`ts-code`、`60`、`00`、`30`、`68` |
| 5 | `TS_CODES` | 空 | `ts-code` 范围下的逗号分隔代码列表 |
| 6 | `LIMIT` | 回填 `0`，刷新 `500` | 回填证券或事件数量上限；回填 `0` 表示不限制 |
| 7 | `REPORT_TYPES` | `Q1,H1,Q3,FY` | 逗号分隔的报告类型 |
| 8 | `HISTORY_YEARS` | `5` | 未指定开始日期时的默认回填年份 |

示例：

```cmd
rem 60 开头股票，回填最近五年全部报告类型
scripts\traditional_valuation.bat backfill "" "" 60 "" 0 "Q1,H1,Q3,FY" 5

rem 指定日期区间和 00 开头股票
scripts\traditional_valuation.bat backfill 2021-01-01 2026-09-12 00 "" 0 "Q1,H1,Q3,FY" 5

rem 指定证券和单个报告类型
scripts\traditional_valuation.bat backfill 2021-01-01 2026-09-12 ts-code "600000.SH,000001.SZ" 0 FY 5

rem 事件检测和消费刷新
scripts\traditional_valuation.bat refresh
```

batch 会先执行 `validate`。`backfill` 随后按 `FinancialDisclosureRecord.actual_date` 扫描日期范围、证券范围和报告类型，导入 `FINANCIAL_DISCLOSED` 事件，再自动分批消费这些事件生成估值；它不再按交易日逐日调用估值引擎。`refresh` 只执行日常事件检测与事件消费。指定 `START_DATE` 时不要再依赖 `HISTORY_YEARS`，脚本会避免同时传递这两个互斥参数。代码列表必须作为一个带引号的位置参数传递，不能拆分成多个参数。

历史 batch 回填命令等价于以下两阶段操作：

```text
traditional_valuation backfill
  -> historical disclosure scan by actual_date
  -> idempotent FINANCIAL_DISCLOSED import
  -> bounded event consumption
  -> formal/blended valuation snapshots
```

日期范围内没有 disclosure 时，命令不会因为没有交易日而生成空的每日工作项；应在日志和 run 摘要中核对 `scanned`、`created`、`existing`、`completed` 和 `failed`。重复执行同一范围不会重复创建相同 source event。

PowerShell 调用时，即使传入 `""`，空的 `TS_CODES` 位置参数也可能被省略，导致后续的 `LIMIT`、`REPORT_TYPES` 和 `HISTORY_YEARS` 左移。当前 batch 已兼容这种调用：当 `SCOPE` 不是 `ts-code` 且检测到报告类型落入错误位置时，会恢复为文档定义的参数顺序；也兼容未加引号而拆成 `Q1 H1 Q3 FY` 的完整报告类型列表。推荐仍显式保留空参数，并始终将报告类型列表作为一个整体参数：

```powershell
& '.\scripts\traditional_valuation.bat' backfill `
  '' '' 60 '' 0 'Q1,H1,Q3,FY' 5

& '.\scripts\traditional_valuation.bat' backfill `
  2021-01-01 2026-09-12 ts-code '600000.SH,000001.SZ' 0 FY 5
```

不要依赖报告类型或股票代码中的空格分隔；空的 `TS_CODES` 兼容恢复只适用于非 `ts-code` 范围。脚本完成参数恢复后，仍按 `manage.py traditional_valuation backfill` 的校验规则执行，参数无效时会在回填前失败并写入带时间戳的日志。

传统估值回填默认开启多行业变体估值。batch 未显式传递 `--business-match-topn` 时，Django 命令使用默认值 `3`：每个证券先生成一个 SW 基准行业变体，再尝试生成最多 3 个业务匹配行业变体。业务匹配结果与基准行业重复时会去重，因此实际持久化的变体数量可能少于 3 个；没有可用业务匹配时，基准行业变体仍可正常回填。

如需关闭业务匹配、只回填基准行业，应直接调用 Django 命令并设置 `--business-match-topn 0`。当前 batch 参数中没有对应的关闭选项：

```powershell
python manage.py traditional_valuation backfill `
  --scope 60 `
  --business-match-topn 0
```

`business_match_topn` 只控制回填生成的行业变体数量，不改变报告类型、日期范围、证券范围或利润桶的选择。

## 8. 事件驱动刷新

### 8.1 检测事件

预览：

```powershell
python manage.py traditional_valuation detect-events `
  --asof-date 2026-09-12 `
  --limit 100 `
  --dry-run
```

正式导入：

```powershell
python manage.py traditional_valuation detect-events `
  --asof-date 2026-09-12 `
  --limit 100
```

事件来源包括：

- `FINANCIAL_DISCLOSED`：已提交的财务披露事件；
- `MARKET_STYLE_CHANGED`：已提交的市场风格变化；
- `SECURITY_STYLE_CHANGED`：已确认的个股风格变化。

本模块只读取 `market_data.list_regime_events(...)` 和
`financials` 的披露事件接口，不自行分类风格。普通 `detect-events` 读取已提交的上游事件；历史 `backfill` 允许在明确日期范围内只读扫描已提交的 `FinancialDisclosureRecord.actual_date`，将其转换为本地 `FINANCIAL_DISCLOSED` 事件。重复导入使用上游 source event identity 幂等，不应制造重复本地事件。

### 8.2 消费事件

先预览待处理数量：

```powershell
python manage.py traditional_valuation consume-events `
  --limit 100 `
  --dry-run
```

正式消费：

```powershell
python manage.py traditional_valuation consume-events `
  --limit 100
```

重试失败事件：

```powershell
python manage.py traditional_valuation consume-events `
  --limit 50 `
  --retry-failed
```

消费行为按事件作用域执行：财报事件刷新受影响证券和报告期，个股风格事件只刷新该证券，市场风格事件在有界证券范围内扇出。成功时事件在估值持久化完成后标记成功；异常时保留失败状态、错误信息和重试计数。

### 8.3 刷新快捷命令

```powershell
python manage.py traditional_valuation refresh `
  --asof-date 2026-09-12 `
  --limit 100
```

该命令只做“检测事件 + 消费事件”，不做五年历史回填。`--limit` 同时影响检测数量和部分事件消费的有界范围，生产环境应显式设置。

## 9. 业务行业匹配刷新

预览指定证券：

```powershell
python manage.py traditional_valuation refresh-business-matches `
  --ts-codes 600000.SH `
  --asof-date 2026-09-12 `
  --business-match-topn 3 `
  --dry-run
```

正式执行：

```powershell
python manage.py traditional_valuation refresh-business-matches `
  --ts-codes 600000.SH `
  --asof-date 2026-09-12 `
  --business-match-topn 3
```

该命令读取市场数据侧的公司主营业务和匹配服务，维护匹配结果或其相关来源状态。它不直接执行估值快照回填；若匹配结果或模板版本发生变化，应按要求再执行目标范围的 `backfill` 或事件刷新。`--business-match-topn 0` 保留基线行业，不添加业务匹配候选。

## 10. 推荐运行流程

### 10.1 首次初始化或大范围回填

1. 完成 `market_data` 和 `financials` 原始数据同步。
2. 确认证券、SW 映射、行情、财务和 disclosure 数据覆盖目标 `actual_date` 范围。
3. 执行 `traditional_valuation validate`。
4. 对单证券和小日期范围执行 `backfill --dry-run`。
5. 小范围执行 disclosure-driven `backfill`，核对事件导入、formal/blended 和 variant 结果。
6. 扩大证券、`actual_date` 日期范围和报告类型，完成历史基线。
7. 完成基线核对后，再启用日常 `detect-events` 和 `consume-events`。

### 10.2 日常增量刷新

1. 等待市场和财务同步成功。
2. 按需刷新业务匹配或活动估值模板。
3. 使用有界 `detect-events` 导入已提交事件。
4. 使用有界 `consume-events` 消费事件。
5. 对当前快照、事件状态和失败计数做抽样核对。

不要把 `refresh` 当作历史回填替代品，也不要在同一证券范围内并行执行历史回填和独立的事件消费；backfill 自身已经包含本次 disclosure 事件的消费阶段。

## 11. 状态与数据库核对

查看总量：

```powershell
python manage.py traditional_valuation status
```

至少核对：

- 快照总数是否与本次证券、报告期和利润桶范围一致；
- `formal` 与 `blended` 是否保持独立；
- 默认 SW 基线和业务匹配 variant 是否有清晰身份；
- 事件的 pending、claimed、succeeded、failed 数量是否符合检测和消费日志；
- run 的 completed/failed 数量是否与命令输出一致。

数据库抽样时应按证券、报告类型、利润桶、as-of 日期和 variant 查询，不要只按 snapshot id 推断业务匹配摘要。重点检查模板版本、mapping version、财务结束日期、来源交易日期、市场风格状态和风险结果是否可追溯。

## 12. 常见故障处理

### 12.1 模板或表校验失败

先确认 `settings.BASE_DIR`、模板目录和 PostgreSQL 连接，再重新执行 `validate`。不要绕过校验直接回填，也不要用其他行业模板静默替代缺失的 SW 参数。

### 12.2 Unknown stock ts_codes

使用 `market_data.Security.ts_code` 中的标准交易所后缀格式，例如 `000001.SZ` 或 `600000.SH`。先执行带 `--dry-run` 的单证券命令确认范围。

### 12.3 回填部分失败

保留命令输出、run 记录和事件状态，按 `actual_date`、证券、报告期、利润桶逐项重跑小范围命令。检查对应 disclosure 的 `actual_date`、`financial_end_date`、财务字段、市场日期、SW 参数、业务匹配和方法 skip reason。不要直接删除历史快照或事件记录来“清理”失败。

### 12.4 事件检测无新增

历史 backfill 中 `scanned` 有值但 `created=0` 通常表示 disclosure 已被幂等导入；先检查 `status` 中是否已有 pending/failed/succeeded 事件。若范围内没有满足 `actual_date` 的已提交 disclosure，backfill 不会按交易日或当前财报状态临时制造估值事件。

### 12.5 事件消费失败

查看事件的失败状态、重试计数和错误消息，先修复输入或配置，再使用受控批次重试：

```powershell
python manage.py traditional_valuation consume-events `
  --limit 50 `
  --retry-failed
```

### 12.6 风格刷新范围异常

确认事件 payload 的 scope、证券是否为空以及 `--limit` 是否过小。市场级事件必须有界扇出；个股风格事件不得扩散到其他证券。不要通过手工复制事件行扩大范围。

## 13. 安全与数据安全规则

- 所有状态写入 PostgreSQL；不要使用 SQLite 或临时数据库作为运行结果。
- 批量写入前先执行 dry-run，并保留命令、参数、时间和 run 信息。
- 不在日志中记录数据库连接串、token、供应商凭证或完整原始 payload。
- 不执行清空表、删除全部事件或覆盖历史快照等破坏性操作。
- 模板、行业映射和事件来源必须保留版本与 provenance。
- 传统估值输出不是交易指令，不得由运营命令触发自动交易。

## 14. 最小验收清单

### 历史初始化

- [ ] PostgreSQL 连接正确，传统估值表已迁移。
- [ ] `validate` 通过，活动模板和 mapping version 可用。
- [ ] 单证券、指定 `actual_date` 范围的 `backfill --dry-run` 范围正确。
- [ ] 历史回填日志显示 disclosure 扫描和事件导入统计，且事件按 source identity 幂等。
- [ ] formal/blended 回填结果分别存在且可追溯。
- [ ] SW 基线和业务匹配 variant 身份正确。
- [ ] 历史结果的财务和市场来源日期符合点时约束。
- [ ] 历史回填未生成每日交易日工作项，也未回放历史市场/个股风格切换。
- [ ] 重复回填不会产生违反自然键的重复快照。

### 日常事件刷新

- [ ] 上游市场和财务同步已完成。
- [ ] `detect-events` 使用了有界 `--limit`。
- [ ] `consume-events` 使用了有界 `--limit`。
- [ ] 财报、市场风格和个股风格事件的作用域符合预期。
- [ ] 事件只在估值持久化完成后标记成功。
- [ ] 失败事件保留错误和重试信息，必要时显式 `--retry-failed`。
- [ ] 刷新后当前快照的日期、模板版本、风格状态和来源可追溯。

## 15. 当前实现与目标设计的差异

- 当前 `backfill` 的 `--dry-run` 只验证证券范围，不会扫描或导入 disclosure，也不会完成设计文档设想的全部数据覆盖审计。
- 当前命令没有设计文档中的完整断点续跑、水位线和 run-key 恢复接口。
- 当前 `refresh` 是命令内同步执行的检测和消费组合，不代表调度器已经具备跨任务锁和失败 checkpoint 管理。
- 传统命令的 `--asof-date` 当前按 ISO 日期或斜杠日期解析；本手册示例使用 `YYYY-MM-DD`。
- 历史 `backfill` 与增量事件刷新共用事件消费、估值引擎和持久化服务；backfill 只导入指定 `actual_date` 范围的 `FINANCIAL_DISCLOSED`，不处理历史市场风格和个股风格切换。
