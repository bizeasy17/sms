# metrics 评分快照持久化与检索后端设计

## 1 文档信息

- 模块：`manniu_backend/metrics`
- 文档状态：设计提案，数据库字段与 API 契约待确认
- 需求：[requirements.md](requirements.md)
- 算法定义基线：[metrics-backend-design.md](../modules/metrics-backend-design.md)
- 持久化：PostgreSQL
- 非目标：本设计不直接授权新增模型、迁移、公开 API 或改变既有评分算法

## 2 设计目标与边界

为常规财务六维、TopN 特征六维和 CGPS 提供统一的快照检索外壳，同时保留三套评分的类型、维度和 provenance 差异。算法继续由各自 service 计算；持久化适配器接收已计算结果，不在数据库模型或查询 view 中复制评分规则。

本设计仅覆盖后端结果存储、幂等、历史和查询。算法因子、权重、coverage 语义遵循算法定义基线；前端展示、定时调度和批量回填策略需另行评审。

## 3 建议数据模型

字段为实现前的候选契约。长度、精度、删除策略和唯一约束须结合现有 `Security` 模型、API 使用方及数据规模确认后再迁移。

### 3.1 `MetricsScoreSnapshot` 评分快照主表

| 字段 | 建议类型 | 说明 |
| --- | --- | --- |
| `id` | BigAutoField | 主键 |
| `security_id` | FK → `market_data.Security` | 证券引用；建议 `PROTECT`，避免历史快照因证券删除而丢失 |
| `score_type` | varchar(40) | `FINANCIAL_HEALTH_6D`、`MODEL_TOPN_6D`、`COMPANY_GROWTH_POTENTIAL` |
| `asof_date` | DateField | 本次评分的信息/市场时点 |
| `financial_end_date` | DateField, nullable | 实际使用的财务报告期 |
| `market_asof_date` | DateField, nullable | TopN/常规评分使用的行情快照日 |
| `report_type` | varchar(16), nullable | 模型清单或财报口径适用时记录 |
| `score` | Decimal(6,2), nullable | 0–100；不可用时为 NULL |
| `label` | varchar(32), nullable | 按对应算法版本生成，不跨评分类型统一解释 |
| `score_status` | varchar(32) | `VALID`、`PARTIAL`、`INSUFFICIENT_DATA`、`NOT_APPLICABLE`、`DEGRADED` 等状态 |
| `coverage` | Decimal(6,4), nullable | 按评分类型原有语义保存；未知或不适用时为 NULL，不伪造统一覆盖值 |
| `calculation_version` | varchar(64), nullable | 算法版本，例如 CGPS calculation version |
| `scoring_version` | varchar(64), nullable | 常规评分版本 |
| `profile_version` | varchar(64), nullable | 股票类型/行业 profile 版本 |
| `peer_mapping_version` | varchar(64), nullable | 同行映射版本 |
| `model_version` | varchar(128), nullable | TopN 模型版本 |
| `feature_set_version` | varchar(128), nullable | TopN 特征清单版本 |
| `mapping_version` | varchar(64), nullable | TopN 特征映射版本 |
| `normalization_version` | varchar(64), nullable | TopN 归一化版本 |
| `dimension_weight_version` | varchar(64), nullable | 维度权重版本 |
| `score_topn` / `store_topn` | PositiveSmallInteger, nullable | TopN 实际计分数和候选数 |
| `model_scope` / `model_degraded` / `model_degrade_reason` | 类型化可空字段 | TopN provider 来源和降级信息 |
| `source_periods` | JSONB | 各来源实际报告期、公告日期和记录引用摘要 |
| `warnings` | JSONB | 可读诊断列表 |
| `input_fingerprint` | varchar(64) | 规范化输入与版本的摘要，用于幂等识别 |
| `created_at` | DateTimeField | 写入时间；历史快照不原位覆盖 |

主表保存跨类型通用的检索字段；类型专属版本字段可空，但写入校验需保证对应 `score_type` 的必要 provenance 完整。`coverage` 不强行统一既有常规六维当前尚无覆盖率的语义。

### 3.2 `MetricsScoreDimension` 维度明细表

建议字段：`id`、`snapshot_id`（FK，级联删除仅用于显式清理策略）、`dimension_key`、`dimension_name`、`weight`、`score`（nullable）、`status`、`available_weight`（nullable）、`evidence`（JSONB）。对 `(snapshot_id, dimension_key)` 建唯一约束。

该表保留算法原始维度键，不将普通财务 profile 专属键映射成 TopN 或 CGPS 键。关系化的 `dimension_key`、`score` 和 `status` 支持维度级筛选；`evidence` 保存因子/特征原值、单位、方向、分位、peer 样本、来源和缺失原因。若后续需要按单因子高频检索，再评估独立 factor/evidence 表，不在首期过度拆表。

## 4 写入与幂等流程

1. 各评分 service 产生完整结果对象；适配层按 `score_type` 校验其必需版本、日期、状态及维度结构。
2. 规范化参与计算的来源记录标识/输入快照及算法版本，计算 `input_fingerprint`。
3. 在一个 PostgreSQL 事务中写入快照主表和全部维度明细；任何明细写入失败则整个快照回滚。
4. 在主表对 `(security_id, score_type, input_fingerprint)` 建复合唯一约束。相同证券、类型和 fingerprint 重复写入时返回已有快照，不重复创建；来源事实或算法版本改变并导致 fingerprint 改变时创建新历史记录。
5. 不更新既有快照的分数或证据。纠正错误需保留旧记录审计痕迹，并采用显式失效/替代标记策略；该标记字段及授权规则待确认。
6. 查询接口只读快照，不隐式调用评分 service、不回源 Tushare、不触发落库。

fingerprint 的输入组成及旧记录失效/替代机制属于实施前待确认项。唯一约束必须为 `(security_id, score_type, input_fingerprint)`，不得仅用 `(security, score_type, asof_date)` 覆盖旧结果，因为同一时点可能存在不同模型清单、算法版本或来源修订。

### 4.1 管理命令提案

建议新增 Django management command `persist_metrics_scores`，负责按指定证券、as-of 日期和评分类型调用已有评分 service，并将结果通过统一适配层保存。候选参数为必填 `--asof-date`、`--score-types`、`--scope ts-codes|all`，以及与 `ts-codes` scope 配套的一个或多个 `--ts-code` 或证券文件输入；`--batch-size` 默认为 100，按证券分批并在每批开始/完成时报告范围、进度、计数和耗时；支持 `--dry-run`。选择 TopN 时另支持 `--report-type`、`--model-version`、`--score-topn`、`--store-topn`。命令输出成功、跳过、失败及幂等命中数量，并以非零退出码报告失败。dry-run 只计算和校验、不写库。

首期由用户或运维手工调用该命令；本轮不接入 `scripts/daily.bat`。daily job 接入作为后续独立 TODO，届时需确认运行频率、证券 scope、失败重试和日志契约。

## 5 索引与查询设计

建议主表索引：

- `(security_id, score_type, asof_date DESC, created_at DESC)`：查询个股最新分和历史曲线。
- `(score_type, asof_date DESC, score_status)`：按类型/时点/状态搜索。
- `(score_type, score)`：分数区间筛选；仅索引有效 score 的部分索引可在查询计划验证后采用。
- `(security_id, score_type, input_fingerprint)` 复合唯一索引：实现按证券和评分类型隔离的幂等。
- 维度表 `(dimension_key, score, status, snapshot_id)`：指定维度分数筛选和主表回连。

索引名须遵循当前 Django/PostgreSQL 项目的命名长度限制。JSONB evidence 初期不默认建立 GIN 索引；先用代表性数据验证查询频率、过滤选择性和写入成本。

### 5.1 查询 API 提案（未冻结）

- 列表：`GET /api/metrics/score-snapshots/`
- 详情：`GET /api/metrics/score-snapshots/{snapshot_id}/`
- 建议列表过滤：`score_type`、`ts_code`、`name`、`asof_from`、`asof_to`、`financial_end_date`、`score_status`、`min_score`、`max_score`、`label`、`dimension_key`、`dimension_min_score`、`dimension_max_score`。
- 建议排序：`asof_date`、`score`、`created_at`；默认 `-asof_date,-created_at`。
- 建议分页：复用现有 API Gateway 约定；单页最大条数由 API 设计评审确定。
- 详情返回主表 provenance 和完整维度 evidence；列表响应可提供维度摘要，不默认返回大量 TopN 特征明细。

具体 URL、过滤字段名称、权限策略、分页响应结构和兼容行为须在实现前确认；本提案不代表公开 API 已批准。

## 6 错误、状态与权限

- 类型键未知、必要 provenance 缺失、维度 key 重复或分数超出 `[0,100]`：写入校验失败，不生成部分快照。
- 分数不可用时保存 `score=NULL` 和明确状态/原因；查询分数区间时 NULL 不匹配任何数值范围。
- 不存在的证券或快照返回既有 API Gateway 约定的 404；非法过滤和日期范围返回校验错误。
- 认证、授权、request id、错误 envelope 和分页遵循 Gateway 设计；实现前需确认结果是全局研究数据还是需按用户隔离。默认方案为继承现有 metrics 读取权限，不新建个人数据所有权。
- 所有持久化及查询均使用 PostgreSQL；不得为单测或本地功能引入 SQLite 替代存储。

## 7 测试用例定义

1. 三种 `score_type` 的合法主表和维度数据可以事务性保存并查询；各自 provenance 和维度 key 原样往返。
2. 任一维度写入失败时主表与其他维度均不落库，验证事务原子性。
3. 相同 `(security_id, score_type, input_fingerprint)` 并发/重复写入只产生一个快照；不同证券、评分类型或 fingerprint 不互相冲突，并保留不同 fingerprint 的历史。
4. 覆盖 `VALID`、`PARTIAL`、`INSUFFICIENT_DATA`、`NOT_APPLICABLE`、TopN 降级及 NULL 分数查询。
5. 组合证券、类型、日期、状态、总分及维度筛选，验证排序、分页和边界条件。
6. 未授权请求不能读取超出其权限范围的评分数据；查询过程不调用评分 service 或外部数据源。
7. 使用 PostgreSQL 验证唯一约束、索引和事务；性能样本至少覆盖单证券历史查询及多证券分数筛选。

## 8 TODO List

- [ ] TODO-01（对应 3）：确认主表/维度表字段、删除策略、数值精度、状态枚举和历史纠错标记。
- [ ] TODO-02（对应 4–5）：确认 fingerprint 输入、索引组合、查询筛选字段和排序/分页上限。
- [ ] TODO-03（对应 5.1、6）：确认公开 API URL、请求/响应字段、权限范围及错误语义。
- [x] TODO-04（对应 3–4、7）：PostgreSQL 两表、复合幂等写入服务及定向测试已完成；6 项 metrics 测试通过。
- [x] TODO-05（对应 4.1）：`persist_metrics_scores` 手工命令已实现；单证券三类评分 dry-run 通过。
- [ ] TODO-06（对应 5.1、6）：确认并实现 HTTP 搜索/详情 API 及权限测试。
- [ ] TODO-07（对应 4.1）：CLI 验证稳定后，另行评审并接入 daily job。
