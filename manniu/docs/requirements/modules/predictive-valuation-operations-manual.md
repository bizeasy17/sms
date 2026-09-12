# 预测估值操作手册

## 1. 文档目的

本文档面向 `manniu_backend` 预测估值模块的开发、测试和运维人员，说明如何安全地执行配置校验、财务特征构建、历史预测估值回填、事件刷新和结果核对。

本文档结合以下材料编写：

- [预测估值后端设计](predictive-valuation-backend-design.md)
- [预测估值 CLI 设计](predictive-valuation-cli-design.md)
- `predictive_valuation` Django 管理命令
- `schedule/setup/predictive_valuation.bat` 调度脚本

本文档描述的是当前代码的可操作行为。设计文档中尚未落地的能力，例如完整的断点续跑、水位线、网关读取接口和三层展示模板，不应被视为当前批处理已经提供的功能。

## 2. 处理边界

预测估值模块只负责模型特征投影、模型推理、预测快照、事件状态和运行审计。它不负责以下工作：

- 不在预测过程中调用 Tushare。
- 不同步 `financials` 原始财务数据。
- 不同步 `market_data` 行情或基本面数据。
- 不复制交易、原始财务或披露表。
- 不创建或执行交易订单。
- 不使用 SQLite；所有状态写入项目配置的 PostgreSQL 数据库。

推荐的数据链路如下：

```text
market_data / financials 原始数据
            |
            v
financial feature builder
            |
            v
PredictiveFinancialFeaturePanel / Latest
            |
            v
artifact registry + feature builder + inference service
            |
            v
PredictiveValuationSnapshot / Current
            |
            v
事件状态、运行审计、下游只读查询
```

`financials` 原始数据同步和 `market_data` 行情覆盖是预测估值的前置条件。原始数据同步成功，不等于预测特征或预测快照已经刷新。

## 3. 执行环境

### 3.1 项目目录

以下示例假定后端目录为：

```text
C:\Users\HANJ29\Development\web\UAT\manniu\manniu_backend
```

PowerShell 中先进入后端目录，并明确设置 Django 配置：

```powershell
Set-Location 'C:\Users\HANJ29\Development\web\UAT\manniu\manniu_backend'
$env:DJANGO_SETTINGS_MODULE = 'config.settings'
```

之后所有 `manage.py` 命令都应从该目录执行，或使用 `manage.py` 的绝对路径。不要使用 `cd /d`，那是 `cmd.exe` 语法，在 PowerShell 中会失败。

### 3.2 Python 解释器

当前调度脚本固定使用：

```text
C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe
```

手工执行时应使用已经安装了项目依赖、Django、PyYAML、pandas、joblib 和模型运行时依赖的 Python。UAT 仓库默认建议的通用 Python 路径是 `C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe`，但本模块最终必须以实际部署环境和模型包兼容的解释器为准。不要在同一轮操作中混用两个虚拟环境。

示例：

```powershell
$py = 'C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe'
& $py manage.py predictive_valuation validate
```

### 3.3 数据库与静态工件

执行前确认：

1. Django 使用目标 UAT PostgreSQL 数据库，而不是本地临时数据库。
2. 数据库连接配置沿用项目既有配置，不新增第二套数据库 URL。
3. `PREDICTIVE_VALUATION_CONFIG` 能解析到有效 YAML。
4. `PREDICTIVE_VALUATION_MODEL_ROOT` 和 `PREDICTIVE_VALUATION_RISK_DATA_ROOT` 存在。
5. serving pointer 存在，且包含 `Q1`、`H1`、`Q3`、`FY` 对应模型映射。
6. 模型包内的 `feature_cols` 存在且顺序有效。
7. 模型工件位于配置的模型根目录内，不从任意路径加载。
8. 财务报告、披露日期和目标日期范围内的市场交易数据已经准备完成。

常用配置项：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `PREDICTIVE_VALUATION_ENABLED` | `false` | 是否允许 CLI/调度推理 |
| `PREDICTIVE_VALUATION_CONFIG` | `predictive_valuation/configs/default.yaml` | 活动 YAML 配置 |
| `PREDICTIVE_VALUATION_MODEL_ROOT` | `predictive_valuation/outputs` | 模型和 serving pointer 根目录 |
| `PREDICTIVE_VALUATION_RISK_DATA_ROOT` | `predictive_valuation/outputs_risk` | 风险数据根目录 |
| `PREDICTIVE_VALUATION_LOOKBACK_YEARS` | `5` | 默认历史回填年数 |
| `PREDICTIVE_VALUATION_STRICT_LIVE_FEATURES` | `true` | 是否拒绝陈旧/缺失实时特征 |
| `PREDICTIVE_VALUATION_SERVING_SLOT` | `production` | 默认模型服务槽位 |
| `PREDICTIVE_VALUATION_ALLOW_DATASET_FALLBACK` | `false` | 是否允许离线数据集回退 |

路径没有明确写成绝对路径时，按 `settings.BASE_DIR` 解析。

## 4. 推荐执行流程

首次初始化或大范围重算必须按以下顺序进行：

1. 完成 `financials` 原始数据和披露数据同步。
2. 确认 `market_data` 历史交易数据覆盖目标日期。
3. 执行 `validate`，确认数据库、表、配置和四个季度模型均可用。
4. 对目标证券执行 `backfill-features --dry-run`。
5. 小范围执行非 dry-run 的 `backfill-features`，核对面板行数和字段来源。
6. 执行 `backfill-valuations --dry-run`，确认模型路由和待处理面板数量。
7. 小范围执行非 dry-run 的 `backfill-valuations`，核对成功/失败数量。
8. 扩大日期和证券范围，完成历史回填。
9. 历史基线稳定后，才启用 `detect-events` 和 `consume-events` 的增量刷新。
10. 通过 `status` 和数据库抽样核对结果，再接入调度任务。

不要在同一证券范围内并行运行特征回填和估值回填。估值回填必须消费已经持久化的预测财务特征面板。

## 5. 命令总览

管理命令入口：

```text
python manage.py predictive_valuation <subcommand> [options]
```

当前支持：

| 子命令 | 用途 | 是否写库 |
| --- | --- | --- |
| `validate` | 校验配置、表、模型根目录、风险目录和生产模型 | 否 |
| `build-features` | 为当前证券构建特征面板/最新行 | 是，除非 dry-run |
| `backfill-features` | 构建历史特征面板 | 是，除非 dry-run |
| `backfill-valuations` | 基于已持久化面板执行历史推理 | 是，除非 dry-run |
| `backfill` | 先特征回填，再估值回填 | 是，除非 dry-run |
| `detect-events` | 检测财务披露和市场/证券状态事件 | 是，除非 dry-run |
| `consume-events` | 消费待处理事件并刷新预测 | 是，除非 dry-run |
| `refresh` | 依次检测事件和消费事件 | 是，除非 dry-run |
| `status` | 输出面板、快照、事件和运行计数 | 否 |

公共参数：

| 参数 | 说明 |
| --- | --- |
| `--ts-codes 000001.SZ,600519.SH` | 逗号分隔的标准证券代码 |
| `--scope all\|ts-code` | 全量或指定证券范围；`ts-code` 必须同时提供 `--ts-codes` |
| `--start-date YYYYMMDD` | 回填开始日期 |
| `--end-date YYYYMMDD` | 回填结束日期；缺省为最新市场交易日 |
| `--history-years N` | 回填年数；缺省为 5，必须为正数 |
| `--report-types Q1,H1,Q3,FY` | 报告类型；缺省读取活动配置；可显式使用 `FUSION` |
| `--horizon 1M` | 预测期限，属于快照身份的一部分 |
| `--limit N` | 限制本次证券、面板或事件数量 |
| `--retry-failed` | 消费事件时同时重试失败事件 |
| `--dry-run` | 只校验参数和范围，不写特征、快照、运行或事件状态 |

`--start-date` 与 `--history-years` 互斥。日期参数应使用 `YYYYMMDD`，例如 `20260901`。

## 6. 配置与模型校验

每次模型包切换、配置修改或批量回填前执行：

```powershell
& $py manage.py predictive_valuation validate
```

成功时应看到配置路径、模型根目录、风险目录、serving pointer 和各报告类型模型版本。`scikit-learn` 版本不一致会输出兼容性警告；警告不会自动阻止预测，但必须记录并在小范围样本上验证。

以下情况应立即停止，不要继续回填：

- 配置文件不存在或 YAML 无法解析。
- `feature_contract_version` 缺失。
- 任一预测估值表不存在。
- 模型根目录或风险目录不存在。
- serving pointer 不存在。
- 某个季度模型缺失、路径越界或模型映射错误。
- 目标季度没有对应模型却试图借用其他季度模型。

## 7. 当前特征构建

### 7.1 单证券当前构建

对一只或多只证券构建当前面板：

```powershell
& $py manage.py predictive_valuation build-features `
  --ts-codes 000001.SZ,600519.SH
```

对全部股票构建：

```powershell
& $py manage.py predictive_valuation build-features --all
```

预览指定证券而不写库：

```powershell
& $py manage.py predictive_valuation build-features `
  --ts-codes 000001.SZ --dry-run
```

`--all` 与 `--ts-codes` 互斥。指定代码必须是 `market_data.Security` 中已存在的股票代码。

### 7.2 历史特征回填

先执行五年范围预览：

```powershell
& $py manage.py predictive_valuation backfill-features `
  --scope ts-code --ts-codes 000001.SZ `
  --history-years 5 --report-types Q1,H1,Q3,FY --dry-run
```

确认范围后执行：

```powershell
& $py manage.py predictive_valuation backfill-features `
  --scope ts-code --ts-codes 000001.SZ `
  --history-years 5 --report-types Q1,H1,Q3,FY
```

指定日期范围：

```powershell
& $py manage.py predictive_valuation backfill-features `
  --scope ts-code --ts-codes 000001.SZ `
  --start-date 20210101 --end-date 20260912
```

历史特征回填：

- 只写 `PredictiveFinancialFeaturePanel`。
- 使用 `financials` 中的类型化收入、资产负债表、现金流、指标和披露记录。
- 根据有效披露日期执行时间点过滤。
- 缺失的直接原始字段保留为空，交由模型插补。
- 不应把 `cash_ratio`、`ocf_to_or` 等字段改为重新计算值或相似字段替代值。
- `update_latest=False`，因此不应因为历史回填而覆盖当前 serving 使用的 Latest 行。
- 重复运行应按面板自然键收敛，而不是无限制造重复业务记录。

## 8. 历史预测估值回填

估值回填只消费已经持久化的预测特征面板，不负责下载原始数据。

先预览：

```powershell
& $py manage.py predictive_valuation backfill-valuations `
  --scope ts-code --ts-codes 000001.SZ `
  --history-years 5 --report-types Q1,H1,Q3,FY `
  --horizon 1M --dry-run
```

再执行小范围回填：

```powershell
& $py manage.py predictive_valuation backfill-valuations `
  --scope ts-code --ts-codes 000001.SZ `
  --history-years 5 --report-types Q1,H1,Q3,FY `
  --horizon 1M
```

执行逻辑包括：

1. 再次执行模型和配置校验。
2. 选择日期范围内、报告类型匹配的 `PredictiveFinancialFeaturePanel`。
3. 按 `Q1`、`H1`、`Q3`、`FY` 精确路由到同季度模型。
4. 依据面板的 `source_as_of_date` 选择可用市场特征，避免历史回填使用未来数据。
5. 按模型 `feature_cols` 重建特征列，再执行层级插补。
6. 调用推理服务并写入预测快照/当前结果。
7. 记录模型版本、特征契约、市场日期、财务日期、数据来源和解释载荷。

当前命令对单个面板预测异常会记录警告并继续处理其他面板。若全部预测失败，运行状态为失败并返回非零；若有部分成功，当前实现会将运行标记为成功，但必须在运行汇总中明确记录 `ok` 与 `fail`，不能把部分失败当作零失败。

### 8.1 FUSION 综合估值回填

显式指定 `FUSION` 时，命令会按证券和财年聚合 Q1、H1、Q3、FY 面板，并对每个季度组件独立执行对应模型预测。缺失或预测失败的季度会记录在 Fusion 审计载荷中；只要至少有一个季度成功，就按配置中的基础权重、数据新鲜度和组件置信度计算归一化权重：

$$
w_q = base\_weight_q \times e^{-age\_days / half\_life\_days}
	imes confidence\_weight
$$

预览单证券 Fusion 回填：

```powershell
& $py manage.py predictive_valuation backfill-valuations `
  --scope ts-code --ts-codes 000001.SZ `
  --history-years 5 --report-types FUSION `
  --horizon 1M --dry-run
```

确认范围后执行：

```powershell
& $py manage.py predictive_valuation backfill-valuations `
  --scope ts-code --ts-codes 000001.SZ `
  --history-years 5 --report-types FUSION `
  --horizon 1M
```

Fusion 会写入独立的 `report_type=FUSION` 快照和当前结果。`raw_result.fusion` 保存成功组件、失败组件、归一化权重、来源日期、模型版本和数据状态。全部季度组件失败时，该 Fusion 工作项失败；批次全部失败时命令返回非零。

## 9. 一键历史初始化

`backfill` 当前实现为两个命令的串行组合：先 `backfill-features`，成功后再 `backfill-valuations`。

建议先对单证券执行：

```powershell
& $py manage.py predictive_valuation backfill `
  --scope ts-code --ts-codes 000001.SZ `
  --history-years 5 --report-types Q1,H1,Q3,FY `
  --horizon 1M --dry-run
```

确认 dry-run 后去掉 `--dry-run`。大范围操作应拆成证券批次和日期批次，保留每次命令输出与 `run_key`，便于定位失败范围。

注意：当前 `backfill-features` 和 `backfill-valuations` 分别创建运行记录；不要只依据外层命令退出信息判断所有面板均成功，应同时检查两次命令的日志和运行汇总。

## 10. 事件驱动刷新

### 10.1 检测事件

预览事件检测：

```powershell
& $py manage.py predictive_valuation detect-events `
  --limit 100 --dry-run
```

正式检测：

```powershell
& $py manage.py predictive_valuation detect-events --limit 100
```

事件来源包括：

- 财务披露事件。
- 证券状态/证券市场状态变化。
- 市场整体状态变化。

`--limit` 用于限制状态变化事件的扇出规模。正式环境不要在没有边界的情况下消费大量事件。

### 10.2 消费事件

先预览待处理数量：

```powershell
& $py manage.py predictive_valuation consume-events `
  --limit 100 --dry-run
```

消费新事件：

```powershell
& $py manage.py predictive_valuation consume-events --limit 100
```

重试失败事件：

```powershell
& $py manage.py predictive_valuation consume-events `
  --limit 100 --retry-failed
```

消费流程会先将事件置为 `RUNNING`，成功后置为 `SUCCEEDED`；异常则置为 `FAILED`、增加重试次数并保存错误信息。当前实现要求 `--limit` 大于 0，否则命令直接失败。

### 10.3 刷新快捷命令

`refresh` 等价于先检测事件、再消费事件：

```powershell
& $py manage.py predictive_valuation refresh --limit 100
```

历史初始化未完成、模型校验未通过或市场/财务输入未覆盖时，不应运行 `refresh` 代替历史回填。

## 11. Windows 批处理脚本

当前脚本位置：

```text
manniu_backend\schedule\setup\predictive_valuation.bat
```

设计目标是：

```cmd
predictive_valuation.bat refresh
predictive_valuation.bat backfill [START_DATE] [END_DATE] [SCOPE] [TS_CODES] [LIMIT]
```

脚本会创建时间戳日志，先执行 `validate`，然后按模式执行刷新或历史回填。日志目录目标为：

```text
manniu_backend\log\predictive_valuation
```

### 11.1 当前脚本使用前的检查

当前脚本中的 `%~dp0` 指向 `schedule\setup`，但 `set "PROJECT_ROOT=%~dp0.."` 只会定位到 `schedule`，而 `manage.py` 位于 `manniu_backend` 根目录。因此直接运行现有脚本前，应先修正为向上两级：

```bat
set "PROJECT_ROOT=%~dp0..\.."
```

此外，脚本当前把 Python 固定为 `ASI_DEV\.venv`。若部署环境使用其他解释器，应通过代码评审后统一修改，不要在同一批任务中混用解释器。脚本参数中的 `TS_CODES` 也应始终加引号传递，避免逗号、空格或特殊字符造成批处理解析歧义。

在上述问题修正并验证前，推荐直接从 `manniu_backend` 目录执行管理命令，并将完整 stdout/stderr 重定向到运维日志。

## 12. 结果核对

### 12.1 命令级核对

每次操作至少记录：

- 子命令和完整参数。
- 开始/结束时间。
- 使用的 Python 路径和 Django settings。
- 配置文件、模型版本和特征契约版本。
- `run_key`。
- 证券范围、日期范围、报告类型和 horizon。
- 成功数量、失败数量和首个失败原因。

不要在日志中输出数据库连接串、密钥、Tushare token 或完整供应商原始 payload。

### 12.2 状态汇总

```powershell
& $py manage.py predictive_valuation status
```

输出包括：

- `feature_panel_rows`
- `feature_latest_rows`
- `snapshot_rows`
- 各事件状态计数
- 各运行状态计数

状态汇总只能作为总量检查，不能替代按证券、报告类型、日期和模型版本的抽样检查。

### 12.3 数据库抽样核对

以 Django shell 检查当前和历史结果：

```powershell
& $py manage.py shell -c "from market_data.models import Security; from predictive_valuation.models import PredictiveValuationCurrent, PredictiveValuationSnapshot; s=Security.objects.get(ts_code='000001.SZ'); print(list(PredictiveValuationCurrent.objects.filter(security=s).values('report_type','asof_date','model_version','snapshot__anchor_mode'))); print(list(PredictiveValuationSnapshot.objects.filter(security=s).order_by('-asof_date').values('report_type','asof_date','model_version','anchor_mode','feature_data_source')[:20]))"
```

重点检查：

- 四个季度是否使用各自季度模型，没有跨季度静默回退。
- `asof_date`、`source_market_date`、财务结束日期和公告/来源日期是否可追溯。
- 历史日期没有使用更晚市场数据。
- `raw_result`、解释字段、原始/调整后目标区间是否存在。
- 失败结果是否明确记录错误，而不是继续暴露陈旧成功结果。
- 重复运行没有产生不符合自然键的重复历史快照。

对于 Fusion 结果，还要检查：

- `PredictiveValuationCurrent.report_type` 和 `PredictiveValuationSnapshot.report_type` 均为 `FUSION`。
- `raw_result.fusion.components` 是否包含成功和失败组件状态。
- `raw_result.fusion.normalized_weights` 的权重之和约等于 1。
- 部分成功时 `data_status=PARTIAL_SUCCESS`，全部成功时 `data_status=COMPLETE`。
- Fusion 的 `asof_date`、市场来源日期、财务结束日期和组件模型版本可追溯。

## 13. 常见故障处理

### 13.1 配置或模型校验失败

现象：`config not found`、`serving pointer not found`、`Invalid predictive valuation serving artifact`。

处理顺序：

1. 确认当前工作目录和 `DJANGO_SETTINGS_MODULE`。
2. 打印并核对 `settings.BASE_DIR` 下的配置实际路径。
3. 检查模型根目录、风险目录和 serving pointer 是否存在。
4. 检查 Q1/H1/Q3/FY 映射与实际工件文件名。
5. 检查模型包 `feature_cols` 和特征契约版本。
6. 修正后重新执行 `validate`，通过后再回填。

### 13.2 找不到证券或范围为空

现象：`Unknown stock ts_codes`、dry-run 显示证券数为 0。

处理：

- 使用 `market_data.Security.ts_code` 的标准格式，例如 `000001.SZ`。
- 确认证券 `asset_type` 为股票，而不是指数或其他资产。
- `--scope ts-code` 必须同时提供 `--ts-codes`。
- 先用单证券 dry-run 验证，不要直接扩大到全量。

### 13.3 没有可用市场交易日期

现象：`No completed market trading date is available for the default backfill end date`。

处理：

- 检查 `MarketBarDailyHistory` 是否有交易日期。
- 使用明确的 `--end-date` 仅在该日期已有完整市场数据时执行。
- 不要用当前自然日期替代最后一个已完成交易日。

### 13.4 单个预测失败

现象：日志包含证券、报告类型、as-of 日期和 `Valuation prediction failed`。

处理：

1. 记录失败证券、报告类型、面板来源日期和完整错误前缀。
2. 检查对应财务字段是否缺失、单位是否正确、市场特征是否陈旧。
3. 检查模型包与该报告类型是否匹配。
4. 单独对该证券执行 dry-run 和小范围回填。
5. 只有确认输入修复后，才重跑相同范围。

### 13.5 全部预测失败

当前实现会将运行置为 `FAILED` 并返回非零。不要将其当作“没有数据所以正常完成”。优先检查：

- 模型工件和 sklearn 版本。
- 特征列是否能按顺序重建。
- 历史市场数据是否覆盖面板 `source_as_of_date`。
- PostgreSQL 中预测特征表是否已迁移。
- 运行时是否连接到了错误的数据库。

### 13.6 事件消费失败

事件会保留 `FAILED` 状态、错误信息和重试次数。先处理根因，再使用受控批次重试：

```powershell
& $py manage.py predictive_valuation consume-events `
  --limit 50 --retry-failed
```

不要通过手工删除事件记录来“清空队列”。需要保留事件幂等键和审计轨迹。

### 13.7 `.bat` 找不到 `manage.py`

检查 `PROJECT_ROOT` 是否从 `schedule\setup` 向上两级定位到 `manniu_backend`。在脚本修复前，使用 PowerShell 直接进入后端目录执行命令。

## 14. 安全与数据安全规则

- 预测估值只读模型工件，不得由回填任务覆盖 `outputs` 下的模型文件。
- 任何批量写入前先执行 dry-run，并保留命令日志。
- 不执行删除全部、清空表、覆盖历史快照等破坏性操作。
- 不在命令输出、批处理日志或文档中记录数据库凭据、令牌和完整连接串。
- 不把预测结果解释为交易指令；预测估值模块没有自动交易权限。
- 发生部分失败时，必须保留失败计数和错误信息，不得只报告成功数量。
- 模型版本、特征契约版本和数据来源必须可追溯，不能用新的模型覆盖历史证据。

## 15. 最小验收清单

### 首次历史初始化

- [ ] PostgreSQL 连接正确，未使用 SQLite。
- [ ] `financials` 原始数据和披露日期已准备。
- [ ] `market_data` 交易历史覆盖目标范围。
- [ ] `validate` 通过，四个季度模型均有明确映射。
- [ ] `backfill-features --dry-run` 范围符合预期。
- [ ] 单证券特征回填成功，Latest 未被历史回填错误覆盖。
- [ ] `backfill-valuations --dry-run` 面板数量符合预期。
- [ ] 单证券估值回填成功，`ok/fail` 已核对。
- [ ] 历史结果的市场日期不晚于对应时间点。
- [ ] 重复运行没有产生异常重复快照。
- [ ] 全量回填完成后，`status` 与运行记录一致。

### 日常事件刷新

- [ ] 上游财务和市场数据同步已完成。
- [ ] `detect-events` 使用了有界 `--limit`。
- [ ] `consume-events` 使用了有界 `--limit`。
- [ ] 失败事件已检查原因，必要时显式使用 `--retry-failed`。
- [ ] 事件成功状态只在预测写入完成后出现。
- [ ] 刷新后抽样核对当前结果的日期、模型版本和数据来源。

## 16. 当前实现与目标设计的差异

以下项目在设计文档中有明确目标，但当前操作时仍应按代码实际行为判断：

- 断点续跑、chunk completion watermark 和 `--run-key` 恢复尚未作为当前命令接口提供。
- `--dry-run` 当前主要验证参数、配置和范围，不保证完成设计文档要求的全部源数据覆盖审计。
- 当前 `backfill-valuations` 允许部分成功后将运行标记为成功，运维必须读取 `fail` 计数。
- 当前命令支持显式 `--report-types FUSION` 历史回填；缺省报告类型仍由活动配置决定，默认只处理 Q1、H1、Q3、FY。Fusion 的代表性 fixture parity、strict-live 失败语义和完整目标字段逐项核对仍需单独验收。
- 三层展示模板、网关读取契约和严格的所有锚点模式读取规则属于后续产品层能力，不能用当前 CLI 输出替代。
- `schedule/setup/predictive_valuation.bat` 的项目根目录和解释器路径需要按部署环境校正后再用于自动调度。

当代码实现与本文档或设计文档不一致时，应先记录差异并以实际命令输出、数据库状态和版本化模型工件为准；涉及接口契约或数据库字段变更时，应先确认变更方案再修改实现。
