# 预测估值后端设计

## 1 状态与范围

本文档定义 `manniu_backend` 的目标预测估值设计，并以当前 `tushare_earnings_service` 实现作为兼容性基线。基线由 `EarningsForecastPipeline.predict`、`EarningsForecastPipeline.predict_fusion` 以及 `refresh_signal_snapshot` 命令定义。Maniu 可以替换存储和数据访问适配器，但在增加产品级增强功能之前，必须保留其可观察的计算、路由、可追溯性、持久化和失败语义。

模型兼容的财务特征表、预测/事件/运行控制表、特征构建器以及操作员 CLI 骨架已存在于 Maniu 中，并使用 PostgreSQL。Maniu 当前的推理和持久化路径仍是基础实现，尚未视为与参考基线兼容。事件消费、历史初始化、调度、网关集成和三层展示模板，均为在证明基线对等之后才实施的分阶段增强功能。

该模块移植 `tushare_earnings_service/earnings_forecast/services/pipeline.py` 的服务方式，同时使用同一 PostgreSQL 数据库中现有的 `market_data` 和 `financials` 应用。它必须首先复现参考服务的概率和盈利加权信号、质量风险修正、受限回报区间、目标价格和市值区间、市场状态和整体市场调整、季度/融合路由，以及可追溯性元数据。

## 2 参考基线与差距分析

### 2.1 参考执行契约

参考实现有三项不同职责：

1. `predict` 选择报告类型模型和特征锚点，执行推理及层级插补，将结果映射为动作/风险/量化目标，并返回完整的追踪载荷。
2. `predict_fusion` 分别针对 `Q1`、`H1`、`Q3` 和 `FY` 独立调用 `predict`，容忍单个组件失败，并使用报告类型、新鲜度和置信度权重组合成功的组件。
3. `refresh_signal_snapshot` 解析股票代码/截至日期/报告类型工作集，调用推理，从市场锚点补充缺失的目标市值值，并持久化最新和/或历史预测。

命令默认采用最新对齐：没有显式的截至日期范围即表示 `anchor_mode=live_latest` 和一次当前运行。提供任一显式截至日期参数会自动禁用最新对齐，并启用时间点重放。支持请求的报告类型为 `Q1`、`H1`、`Q3`、`FY`、`FUSION` 和 `LATEST`；默认工作集是四种独立季度类型。

### 2.2 必需对等性与有意增强

| 领域 | 参考行为 | Maniu 目标 |
| --- | --- | --- |
| 模型路由 | 生产/候选服务槽位或显式模型版本；季度特定包；不允许静默跨季度回退 | 必须实现基线对等 |
| 特征选择 | 优先实时数据库特征；可选版本化数据集回退；`ann` 或 `live_latest` 锚点 | 必须实现基线对等；部署策略启用严格实时模式 |
| 插补 | 按序 `feature_cols`；股票近期中位数、行业中位数、全局中位数 | 必须实现基线对等 |
| 信号 | 分类器上涨概率加回归器盈利增长；可配置权重与评分区间 | 必须实现基线对等 |
| 风险 | 由评分推导的等级，随后应用可配置财务质量惩罚与风险上调 | 必须实现基线对等 |
| 量化目标 | 评分、概率、盈利、行业排名、风险、波动率、市场状态及整体市场估值调整 | 必须实现基线对等 |
| 输出区间 | 调整后和原始的回报、价格与市值中值/低值/高值 | 必须实现基线对等 |
| 融合 | 部分成功的加权融合，并带有组件/失败审计细节 | 必须实现基线对等 |
| 持久化 | latest/history/both 模式、幂等历史重放、完整 `raw_result`、失败快照、全部失败时非零退出 | 必须实现基线对等 |
| 增量刷新 | 财务端点 `imported_at` 水位线及重叠窗口 | 必须实现基线对等，或提供有文档记录的等效事件水位线 |
| 共享状态服务 | 参考实现于其管道中计算/回退 | Maniu 增强：消费规范的 `market_data` 状态，但不改变映射语义 |
| 三层模板 | 参考服务不生成 | Maniu 的附加增强，在基线对等后实现 |
| 事件状态/运行审计 | 参考命令以批处理为导向 | Maniu 的运行增强，在基线对等后实现 |

因此，当前设计的最大差距不仅在于模型加载。一个仅持久化单一评分和单一目标的基础 Maniu 实现，遗漏了参考服务的季度身份、来源与锚点元数据、原始/调整后区间、质量防护、全市场调整、融合审计、回退状态、失败状态和重放幂等性。这些缺失阻碍可靠比较，必须在将三层或事件驱动层视为可生产使用之前补齐。

## 3 所有权边界

`predictive_valuation` 负责：

- 加载经批准的静态模型包和模型服务元数据。
- 从共享投影构建在线特征行。
- 推理、插补、状态感知的目标映射及解释载荷。
- 预测快照、事件消费状态、运行审计记录和错误状态。
- 用于历史初始化与增量刷新的 CLI 编排。

`market_data` 仍拥有证券、价格、估值基本面、市场状态输入和每只证券状态输入。`financials` 仍拥有原始财务端点和披露数据。`predictive_valuation` 拥有其活动模型特征契约所需的财务特征投影。

该模块不得复制交易、基本面、原始财务或披露表。它只存储模型专用财务特征投影和预测推理数据。所有读写均使用现有 PostgreSQL 连接；不支持 SQLite。

## 4 配置与静态工件

### 4.1 环境变量

将以下有文档记录的变量加入项目的 `.env` 示例。复用现有数据库配置，不得在第二个 URL 下重复配置。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PREDICTIVE_VALUATION_ENABLED` | `false` | 启用 CLI/定时推理。 |
| `PREDICTIVE_VALUATION_CONFIG` | `predictive_valuation/configs/default.yaml` | 活动 YAML 配置文件，从 `BASE_DIR` 解析。 |
| `PREDICTIVE_VALUATION_MODEL_ROOT` | `predictive_valuation/outputs` | 模型包和服务指针的只读根目录。 |
| `PREDICTIVE_VALUATION_RISK_DATA_ROOT` | `predictive_valuation/outputs_risk` | 风险数据集的只读根目录。 |
| `PREDICTIVE_VALUATION_LOOKBACK_YEARS` | `5` | 初始化的默认历史区间。 |
| `PREDICTIVE_VALUATION_EVENT_DEBOUNCE_SECONDS` | `900` | 按证券进行事件合并的时间窗口。 |
| `PREDICTIVE_VALUATION_MAX_FEATURE_GAP_DAYS` | `5` | 实时模式下市场特征允许的最大陈旧天数。 |
| `PREDICTIVE_VALUATION_STRICT_LIVE_FEATURES` | `true` | 拒绝陈旧/缺失的实时特征行，而非回退至数据集。 |
| `PREDICTIVE_VALUATION_SERVING_SLOT` | `production` | 未提供显式模型版本时，选择 `production` 或 `candidate`。 |
| `PREDICTIVE_VALUATION_ALLOW_DATASET_FALLBACK` | `false` | 仅为明确批准的离线运行允许版本化数据集回退。 |

除非明确为绝对路径，所有路径均必须相对于 `settings.BASE_DIR` 解析。进程必须验证配置工件仍位于配置根目录内、服务指针存在，且所选包包含 `feature_cols`。

### 4.2 `configs/` 布局

建议文件：

```text
predictive_valuation/
  configs/
    default.yaml
    production.yaml
    schema.yaml
  outputs/
    serving.yaml
    model_versions/<model-version>/models_Q1.joblib
    model_versions/<model-version>/models_H1.joblib
    model_versions/<model-version>/models_Q3.joblib
    model_versions/<model-version>/models_FY.joblib
  outputs_risk/
    <risk-dataset-version>/...
```

`default.yaml` 不包含密钥。它指定模型版本、工件路径、特征契约版本、目标回报上限、分类器/回归器设置、插补设置、风险阈值和市场状态配置文件。`production.yaml` 仅可覆盖部署时的值。`schema.yaml` 记录版本化特征契约及预期数值单位规范。

`outputs/` 和 `outputs_risk/` 是服务的不可变输入。训练/发布不属于该模块的定时推理作业。服务指针晋升是一项显式部署操作，应有独立审计记录；批处理作业绝不能覆盖模型工件。

### 4.3 季度生产模型路由

生产推理针对报告类型。`serving.yaml` 包含 `production` 和可选的 `candidate` 槽位。每个槽位标识一个版本化数据集，以及 `Q1`、`H1`、`Q3` 和 `FY` 所必需的模型映射。
每个映射条目命名相应的 `models_Q1.joblib`、`models_H1.joblib`、`models_Q3.joblib` 或 `models_FY.joblib` 工件及匹配的指标文件。

显式的 `model_version` 覆盖服务槽位。否则，推理服务根据请求的或最新符合条件的特征面板报告类型解析包：

| 特征面板报告类型 | 所需生产工件 |
| --- | --- |
| `Q1` | `production.models.Q1` / `models_Q1.joblib` |
| `H1` | `production.models.H1` / `models_H1.joblib` |
| `Q3` | `production.models.Q3` / `models_Q3.joblib` |
| `FY` | `production.models.FY` / `models_FY.joblib` |

`FUSION` 不是第五个模型工件。它是成功的季度特定预测的加权组合，并以报告类型/模型版本 `FUSION`/`fusion` 持久化，作为服务身份。`LATEST` 选择最新可用报告类型，并路由至该季度模型。

当报告类型不受支持，或其配置包缺失或位于配置模型根目录之外时，工件注册表必须失败。声明的 sklearn 版本与运行版本不同会发出明确的兼容性警告，并记录于运行输出；但不阻止预测。注册表绝不能静默回退到另一个季度的模型。操作员 `validate` 命令会在批处理或事件消费者运行前检查所有已配置报告类型映射。

## 5 共享特征契约

参考管道从所选模型包加载有序特征名称，并使用 `reindex(columns=feature_cols)`，之后进行层级插补。Maniu 实现必须保持该行为：模型包顺序具有权威性，缺失列在插补前变为空值，而不是引发 dataframe 错误。

在线特征构建器组合以下来源：

| 来源 | 所需贡献 |
| --- | --- |
| `market_data` | 证券身份/行业、最新符合条件的收盘价、市值、估值比率、流动性/回报/波动率窗口、基准与证券状态输入 |
| `predictive_valuation.PredictiveFinancialFeaturePanel` | 模块拥有的时间点财务特征行，通过 `source_as_of_date <= as-of date` 及请求报告期选择 |
| `predictive_valuation.PredictiveFinancialFeatureLatest` | 模块拥有的当前实时财务特征投影 |
| `financials.FinancialDisclosureRecord` | 报告/披露变更检测以及财务数据可用性边界 |

预测管道必须在预测前重建受影响的模块拥有的财务特征行。在 `ann` 模式下，它选择最新符合条件的披露，并将其锚定到最接近公告日期的市场特征行；若距离相同，优先选取当日或之后的行。在 `live_latest` 模式下，它选择最新市场特征行。显式截至日期重放只能使用截至该日期已可获得的市场和财务信息。历史初始化绝不能使用较新的最新行来预测较早的交易日期。

优先使用实时数据库特征。版本化数据集回退只有在离线兼容性明确启用时才允许，且必须设置 `feature_data_source=dataset_fallback` 与 `live_feature_compliant=false`。严格实时模式会引发类型化 `LIVE_FEATURE_UNAVAILABLE` 失败，其中包含请求截至日期、来源交易日期、数据来源和特征间隔天数；不得静默伪造当前结果。

### 5.1 模块拥有的财务特征架构

原 `financials_feature_panel` 和 `financials_feature_latest` 表已移除。`PredictiveFinancialFeaturePanel` 和 `PredictiveFinancialFeatureLatest` 取代它们，并采用参考管道所需的模型兼容名称：收入（`n_income`、`n_income_attr_p`、`basic_eps`、`diluted_eps`）、指标（`roe_dt`、`q_dt_roe`、`tr_yoy`、流动性比率、`assets_turn`、`ocf_to_or`）、资产负债表及现金流字段均在不造成有损字段重命名的情况下持久化。

`PredictiveFinancialFeatureBuilder` 仅读取类型化的 `financials` 原始利润表、资产负债表、现金流、指标和披露记录。它解析每份报告的有效披露日期，更新或插入时间点面板行，并在推理开始前从最新符合条件的面板更新最新行。预测服务绝不能构建未经持久化的原始表连接。

每个已持久化的预测财务特征都必须是获批准财务原始记录列的直接字段映射。构建器不得派生、合成或使用不同字段来替代模型特征。特别是，`cash_ratio` 和 `ocf_to_or` 必须来自 `FinancialIndicatorRecord.cash_ratio` 与 `FinancialIndicatorRecord.ocf_to_or`；不得由资产负债表或利润表/现金流值重新计算。`q_dt_roe`、`st_borr`、`lt_borr` 和 `n_incr_cash_cash_equ` 同样要求对应的类型化原始字段。缺失的原始来源保持为空以供模型插补，并记录在特征来源追踪中。

在重建预测面板之前，财务摄取架构和仓储必须持久化活动模型契约中的所有字段。仅当值直接从同名提供商字段复制时，现有原始载荷可用于一次性、可审计的类型化字段回填。这保证与遗留 `earnings_financial_feature_panel` 特征分布的兼容性。

特征值必须按照 `schema.yaml` 归一化。尤其不得混用比率尺度的上游值和百分比尺度的模型特征。

## 6 权威预测三层模板

本节是 Maniu 增强，并非参考服务对等性基线的一部分。只有当底层已持久化预测匹配下文所述参考字段和计算时，才可启用。

之后，预测估值从已持久化推理结果生成附加的三层展示模板。三层为 `conservative`、`balanced` 和 `aggressive`；每层包含目标价格/区间、预期回报/区间、风险等级和仓位指引。它们在模型推理及状态感知目标映射之后生成。它们不是模型特征、独立模型工件，也不是交易指令。

### 6.1 共享行业状态契约

在基线对等之后，预测估值调用 `traditional_valuation` 使用的相同后端 `industry_regime_service` 和版本化 SW 映射。它提供来自 `market_data` 的规范证券/行业身份，以及所选财务面板和推理质量元数据。返回契约为：

```text
selected_regime: high_growth | balanced | stable_value | cyclical_resource
regime_confidence: 0..1
regime_source: exact | parent | keyword | fallback
regime_reasons, industry_code, mapping_version, fallback_reason
```

代码规范化和查找按精确行业/指数映射、SW 父级遍历、关键字规则，然后可解释的 `balanced` 回退进行。因此，没有显式规则的代码绝不会产生无法解释的 `none` 状态。仅当缺失此后端元数据时，前端才可保留兼容性回退；前端不得维护独立的权威前缀映射。

预测路径有意不消费 `business_match` 变体，也不计算 `variant_weights`/`blend`：其批准的输入契约针对每个报告类型/截至日期身份，只包含一个证券、一个特征面板和一个推理结果。添加行业变体模型推理是独立的模型契约变更，不在三层服务范围内。

### 6.2 层级构建与降级

活动模型的封顶目标回报/价格输出是均衡层锚点。所选行业状态选择一个版本化模板包，其中包括下/上限区间乘数、最小层级间隔和仓位指引上限。已确认的 `market_data` 市场/证券状态以及推理风险/质量可以收窄或扩大该模板包，但不能改变规范行业状态结果。应用这些控制后，映射器强制执行：

$$
conservative \le balanced \le aggressive
$$

并强制记录的最小下行/上行间隔。它记录间距修正前后的值。低 `regime_confidence`、降级/陈旧的实时特征、高推理不确定性或 `BEAR`/`RISK_OFF` 市场数据状态会调用配置的保守回退：扩大下行保护并限制激进仓位。严格实时特征模式仍具有权威性；不符合资格的预测应返回其现有类型化失败，而不是伪造层级模板。

### 6.3 持久化与读取契约

`PredictiveValuationSnapshot` 存储不可变的 `predictive_tiered_template`，以及用于生成它的源预测/区间值。只有最近的预测成功时，`PredictiveValuationCurrent` 才存储相应的最新模板。后续刷新失败会以明确失败状态替换当前基线字段，并清除模板，而不是将陈旧模板作为当前结果保留。至少，成功模板包含：

- `conservative`、`balanced`、`aggressive`，每项具有价格/回报区间与仓位指引；
- `selected_regime`、`regime_confidence`、`regime_source`、`regime_reasons`、`industry_code` 和 `mapping_version`；
- 带有配置规则和修正前/后目标的 `tier_spacing`；
- 模型/风险/市场/证券状态输入、区间乘数以及 `downgrade_applied`/`downgrade_reason`。

模板是对既有目标区间字段的补充。未来网关响应只能从已持久化的快照/当前行暴露它，同时包含 `asof_date`、`source_market_date`、`financial_end_date`、`model_version` 及映射/模板版本。禁止请求时推理、行业查找写入或前端重新计算。

## 7 预测领域持久化

预测表及其身份如下：

| 模型 | 键 | 用途 |
| --- | --- | --- |
| `PredictiveValuationSnapshot` | `security`、`report_type`、`asof_date` | 幂等历史/重放结果与完整原始/解释载荷。相同键的重复遗留行会合并为最新行。 |
| `PredictiveValuationCurrent` | `security`、`report_type` | 每个报告身份的最新服务预测；每次尝试刷新均会替换。 |
| `PredictiveValuationEventState` | `security`、`event_type`、`event_key` | 幂等事件消费、去抖和重试状态。 |
| `PredictiveValuationRun` | `run_key` | 批量/手动运行生命周期及汇总计数。 |

`report_type` 是 `Q1`、`H1`、`Q3`、`FY` 或 `FUSION` 之一。模型版本和特征契约是追踪字段，而不是当前行身份的一部分；否则模型晋升会留下多个相互竞争的当前行。可通过 `latest`、`history` 或 `both` 存储模式独立选择当前/历史写入。

每个当前/历史行存储参考摘要列：

- `signal_score`、`target_return_pct`、`target_price`、`target_market_cap`、`action`、`risk_level`、`model_version`、`asof_date` 和 `feature_data_source`；
- `batch_key`、`refresh_reason`、`refresh_detail`、`market_regime`、`stock_regime`、`triggered_at` 和 `last_error`；
- 用于立场、置信度、概率组件和盈利组件的紧凑 `explain` 字段；
- 完整不可变的 `raw_result`，包括原始及调整后低/中/高目标、模型/报告路由、财务元数据、质量防护、市场调整和融合组件审计。

历史记录还存储 `snapshot_source`、`anchor_mode`、财务报告/结束/公告/财年元数据、`run_key`、`is_backfill` 和 `backfill_run_id`。启用回填保留时，按证券保留配置数量的最近且不同的财务季度结束日期。

失败预测会为尝试的报告身份写入类型化中性快照：评分和目标为空、`HOLD`、`MEDIUM`、空原始结果，以及已填充的 `last_error`。这有意使最新失败可见，而不是将看似新鲜的陈旧成功结果提供服务。当每项尝试预测都失败时，运行以非零退出；部分成功则完成，并包含失败计数及按组件/报告的诊断信息。

成功快照还可记录不可变的 `predictive_tiered_template`，包括其行业状态映射和间距/降级审计载荷。该附加字段永不替代 `raw_result` 或基线目标区间。

在预测事务提交之前，不得标记事件已消费。失败事件保留其错误和重试计数；后续具有相同幂等键的事件不得创建重复快照。

## 8 推理服务

建议包结构：

```text
predictive_valuation/
  services/
    artifact_registry.py
    financial_feature_builder.py
    feature_builder.py
    regime_service.py
    inference_service.py
    event_service.py
  management/commands/
    predictive_valuation.py
```

`artifact_registry` 验证并解析与每个面板财务报告类型匹配的生产包。`financial_feature_builder` 在每次推理之前，从财务原始记录重建预测模块的面板/最新行。`feature_builder` 随后执行时间点市场和财务连接，并生成带有来源追踪的命名特征行。`inference_service` 加载报告类型特定的分类器/回归器包，应用有序特征重索引和层级插补（证券近期历史、行业中位数、包全局中位数），然后通过有上限、风险和状态感知的目标区间映射评分。`event_service` 以事务方式检测、合并、认领和完成事件。

### 8.1 信号与动作映射

分类器返回范围为 $$[0,1]$$ 的 `valuation_up_prob`。可选回归器返回预测盈利增长。盈利增长会被裁剪至配置边界并归一化到 $$[0,1]$$；缺失增长贡献中性值 $$0.5$$。使用归一化权重：

$$
signal\_score = 100 \times (w_p \times valuation\_up\_prob + w_e \times earnings\_norm)
$$

默认权重为 $$w_p=0.7$$ 和 $$w_e=0.3$$。配置的评分区间将评分映射为 `STRONG_BUY`、`BUY`、`HOLD`、`REDUCE` 或 `SELL`；后端动作将这些映射为 `BUY`、`BUY`、`HOLD`、`SELL_PART` 和 `SELL`。基础风险在评分 $$\ge 65$$ 时为 `LOW`，评分 $$\ge 50$$ 时为 `MEDIUM`，否则为 `HIGH`。

可选质量风险防护随后直接评估来源于财务数据的值，包括经营现金流质量、利润/现金流不匹配、应收账款/营收和存货/营收。它扣减有上限的评分惩罚，且只能提高风险。最终评分再次通过评分区间。输出记录每条触发规则、指标值、阈值、评分惩罚和风险上调。

### 8.2 量化估值映射

受限的中值回报是在风险缩放前的四个配置组件之和：

$$
r = risk\_scale \times (r_{score} + r_{probability} + r_{earnings} + r_{industry})
$$

其中，评分以 50 为中心，概率以 0.5 为中心，盈利增长被裁剪，行业百分位数被反转，因此行业内较低的估值百分位数允许更高上行。结果受市场状态特定绝对回报上限约束。可选的高置信度增长尾部仅在评分、概率、盈利增长、风险及允许的市场状态全部满足配置门槛时，才可提高该上限。

回报带结合基础带、已实现波动率乘数和风险填充，并受配置限制。这些市场调整前的值作为 `*_raw` 持久化。服务随后使用配置的指数权重与 PE/PB/换手率指标权重计算整体市场估值百分位数。它对 $$(1+r)$$ 应用配置的高估、中性或低估乘数，然后再次裁剪。调整后的回报、价格和市值中值/低值/高值与原始值一并持久化。当命令层缺失目标市值，但存在价格和当前市值时，按以下方式确定性推导：

$$
target\_market\_cap = current\_market\_cap \times
\frac{target\_price}{current\_price}
$$

### 8.3 融合映射

融合独立调用每个请求季度模型。对每个成功组件：

$$
w_q = base\_weight_q \times e^{-age\_days/half\_life\_days}
\times confidence\_weight
$$

权重在成功组件间归一化。概率、盈利增长和所有可用目标字段被独立加权；缺失低/高字段使用配置回退带。载荷记录归一化权重、其基础/新鲜度/置信度因子、来源日期、模型版本、实时特征合规性及失败组件。仅当没有任何组件成功时融合才失败；但在严格实时模式下，任一非实时组件会使融合不符合资格。

Maniu 服务路径默认采用严格实时特征。数据集回退仅允许在活动配置文件显式启用时用于离线历史初始化；其使用必须在快照中持久化。这比参考命令的兼容性默认值更严格，必须纳入对等性测试。

## 9 CLI 与批处理作业

建议的唯一入口为：

```text
python manage.py predictive_valuation <subcommand> [options]
```

| 子命令 | 默认行为 |
| --- | --- |
| `validate` | 验证环境、服务指针、特征契约、数据库访问和所需共享数据覆盖范围。不执行写入。 |
| `backfill` | 初始化过去五个自然年的幂等历史预测。重放相同的证券/报告/截至日期键会更新该历史身份，而非重复创建。覆盖时要求显式 `--start-date`/`--end-date`。在操作批准前，默认使用 `--dry-run`。 |
| `detect-events` | 检测市场状态、证券状态及新可用的披露事件；仅创建幂等的待处理事件。 |
| `consume-events` | 认领并预测符合条件的待处理事件，具有有界重试和去抖。 |
| `refresh` | 执行 `detect-events` 后执行 `consume-events`；不进行回填。 |
| `status` | 报告最新运行、待处理/失败事件、活动模型和特征新鲜度。 |

Maniu 命令必须暴露等效控制：股票代码范围/文件、全量与增量刷新、`changed_since` 加重叠小时、offset/limit、批处理和刷新元数据、模型版本或服务槽位、锚点模式/最新对齐、存储模式、截至日期/范围/频率、报告类型、历史季度保留、节流和严格失败处理。选项名称可遵循 Maniu CLI 约定，但其持久化含义必须保持兼容。

没有显式股票列表时，增量刷新选择已批准财务端点行的 `imported_at` 晚于最近历史快照时间减去重叠窗口的不同证券。若无历史锚点，则回退到符合条件的完整证券池。工作顺序按证券代码、截至日期、请求报告类型确定性排序。

每次运行报告尝试的工作项、成功数、失败数、已清理的历史行、耗时、批处理键以及按证券/报告的诊断信息。`--strict` 在首次失败时停止。没有 `--strict` 时部分失败可继续，但零成功预测且存在一个或多个失败时仍必须引发命令错误，以避免调度器在虚假成功时推进检查点。

初始批处理作业建议：

| 作业 | 命令 | 调度意图 |
| --- | --- | --- |
| `predictive_valuation_backfill` | `predictive_valuation backfill --years 5` | 仅手动/接入时使用；可按运行键恢复。 |
| `predictive_valuation_event_scan` | `predictive_valuation detect-events` | 市场和财务摄取完成后执行。 |
| `predictive_valuation_event_consumer` | `predictive_valuation consume-events` | 扫描后运行；可为重试更频繁地运行。 |

作业调度器必须声明顺序：市场数据摄取，然后财务摄取和特征投影重建，然后事件扫描，最后事件消费。命令按运行类别和范围加锁；建议的通用控制为 `--security`、`--asof-date`、`--limit`、`--run-key`、`--dry-run` 和 `--retry-failed`。

## 10 事件契约

事件检测基于共享 PostgreSQL 的拉取方式，这使其与当前批量摄取兼容，并避免跨应用进程内信号。

| 事件类型 | 检测基线 | 受影响范围 | 触发条件 |
| --- | --- | --- | --- |
| `MARKET_REGIME_CHANGED` | 已持久化的先前基准状态 | 市场范围 | 当前分类的基准状态与上一次成功处理的状态不同。 |
| `SECURITY_REGIME_CHANGED` | 已持久化的先前证券状态 | 单只证券 | 已去抖的分类证券状态与其上一次成功状态不同。 |
| `FINANCIAL_DISCLOSED` | 披露水位线加投影新鲜度 | 单只证券 | 披露行变为可用/发生变化，且匹配的特征面板行可用。 |

披露事件必须首先重建模块拥有的财务特征行，然后通过 `PredictiveFinancialFeaturePanel.source_as_of_date` 进行门控，确保新财务数据不会针对陈旧的投影特征触发推理。市场范围事件以确定性方式向符合条件的活动证券扇出并分块；它们不得持有一个长时间数据库事务。

### 10.1 市场数据状态契约

`predictive_valuation` 消费来自规范 `market_data` 状态服务的市场和证券风格分类。它不得复制分类器、读取另一预测服务的私有状态，或在特征构建或事件消费期间调用 Tushare。所有状态读取使用已完成的 PostgreSQL EOD 行和显式 `asof_date`。

支持的读取边界为：

```python
from market_data.services.regime import (
  get_market_regime,
  get_security_regime,
  get_regime_state,
)

market = get_market_regime(
  asof_date=asof_date,
  benchmark_ts_code="000001.SH",
)
security = get_security_regime(
  security=security,
  asof_date=asof_date,
)
```

服务解析请求截至日期当日或之前的最新已完成来源日期。对于数据不足或陈旧，它返回类型化降级结果，而不是伪造中性特征行。预测特征构建器将返回的状态元数据持久化于特征来源追踪：

```text
market_regime: BULL | BEAR | BALANCE
security_regime: GROWTH | BALANCE | DEFENSIVE | RISK_OFF
market_regime_source
security_regime_source
market_regime_source_trade_date
security_regime_source_trade_date
regime_classifier_version
regime_row_count
regime_status
```

### 10.2 市场状态语义

市场分类器使用来自 `market_data.MarketBarDailyHistory` 的已完成 `000001.SH` 基准收盘序列。它要求至少 80 条有效行，并计算 MA20、MA60、收盘价/MA60、20 日波动率和 60 日回撤。默认状态和阈值为：

| 条件 | 状态 |
| --- | --- |
| `MA20 > MA60`、`close/MA60 >= 1.03` 且 `drawdown60 > -0.12` | `BULL` |
| `MA20 < MA60` 且（`close/MA60 <= 0.97` 或 `drawdown60 <= -0.12`） | `BEAR` |
| 其他有效观测 | `BALANCE` |

如果暂定 `BULL` 状态的 20 日波动率 $$\ge 0.028$$，分类器将其降级为 `BALANCE`。这些阈值属于 `market_data`；预测模型配置可以定义确认状态如何缩放目标回报和区间，但不得重新定义状态本身。

### 10.3 证券状态语义

证券分类器使用来自 `market_data.MarketBarDailyHistory` 的至少 60 个有效正收盘价，并按以下有序规则集运行：

1. 当 `ma20 < ma60` 且（`close/ma60 <= 0.94` 或 `drawdown60 <= -0.18`）时为 `RISK_OFF`。
2. 当 `ma20 < ma60`，或 `close/ma60 < 0.98`，或 `drawdown60 <= -0.10`，或波动率 $$\ge 0.035$$ 时为 `DEFENSIVE`。
3. 当 `ma20 > ma60`、`close/ma60 >= 1.02`、回撤 `> -0.08` 且波动率 `< 0.03` 时为 `GROWTH`。
4. 否则为 `BALANCE`。

有效行少于 60 条时，分类器返回 `INSUFFICIENT_DATA`。该结果可以记录在诊断中，但不能触发状态事件或替换确认状态。

### 10.4 状态事件消费

`market_data` 持久化 `MarketRegimeSnapshot`、`SecurityRegimeSnapshot`、`MarketRegimeState`、`SecurityRegimeState` 和幂等的 `RegimeEvent` 行。首次有效市场或证券观测会建立基线，不触发预测刷新。无效或空结果不推进状态。

证券状态变更要求对新状态连续两次观测。待处理状态和待处理计数保存在 `SecurityRegimeState`；只有确认转换才会创建 `SECURITY_STYLE_CHANGED`。市场转换仅当旧状态和新状态均有效且不同才会创建。

预测事件服务按以下方式映射上游事件：

| `market_data` 事件 | 预测范围 | 预测刷新 |
| --- | --- | --- |
| `MARKET_STYLE_CHANGED` | 市场/全体证券 | 对符合条件的活动证券进行确定性有界扇出 |
| `SECURITY_STYLE_CHANGED` | 单只证券 | 仅该证券当前符合条件的报告面板 |
| `FINANCIAL_DISCLOSED` | 单只证券/报告期 | 重建特征，然后预测受影响报告期 |

若在现有事件载荷中遇到旧内部名称 `MARKET_REGIME_CHANGED` 和 `SECURITY_REGIME_CHANGED`，它们仅是兼容性别名。新事件必须使用 `MARKET_STYLE_CHANGED` 和 `SECURITY_STYLE_CHANGED`，并保留来源分类器版本、旧/新状态、来源交易日期、指标、检测时间和稳定事件键。

市场风格事件不得为整个证券池持有一个事务。检测器应创建有界子工作，或消费者应认领有界分块。证券风格事件绝不能扇出至其他证券。具有相同来源版本和范围的重复事件是幂等的，且不得创建重复预测快照。

### 10.5 状态感知推理与刷新元数据

推理服务可在其目标映射、回报上限、风险缩放或解释载荷中使用确认的市场/证券状态。它必须记录用于预测的状态及精确来源日期。降级或陈旧的状态输入必须遵循配置的显式回退配置文件，或在严格模式下使预测不符合资格；不得静默将陈旧状态显示为当前状态。

每个事件触发的预测快照记录下列刷新原因之一：

- `MARKET_REGIME_SWITCH`
- `STOCK_REGIME_SWITCH`
- `FINANCIAL_DISCLOSURE`
- `MONTHLY_FULL_REFRESH`
- `MANUAL_REFRESH`

仪表板/最新读取路径仅消费已持久化的 `PredictiveValuationSnapshot` 或 `PredictiveValuationCurrent` 行。加载预测卡片不得调用 `get_market_regime`、`get_security_regime` 或推理服务，以任何会写入或计算新预测的方式运行。

## 11 消费者与 API 边界

`predictive_valuation` 不定义、路由、序列化或暴露公共 HTTP API。其公共边界是由 `api_gateway` 在授权后使用的内部只读查询服务。CLI 和调度器命令仍是唯一写入入口。

在另行确认接口契约后，`api_gateway` 可以暴露当前、历史和运行状态的预测估值读取。网关请求验证、版本控制、序列化、响应信封、分页和错误映射由 `api_gateway` 拥有；在网关调用有界的预测估值查询服务之前，`access_control` 对调用方进行授权。

任何网关响应必须标识 `asof_date`、`source_market_date`、`financial_end_date` 和 `model_version`，以使客户端不能将陈旧输入展示为当前估值。任何请求时路径均不得调用 Tushare、写入预测、更改模型工件或执行交易动作。

## 12 实施关卡

1. 冻结一组代表性的参考夹具，涵盖 `Q1`、`H1`、`Q3`、`FY` 和部分成功的 `FUSION`，包括 `raw_result` 及已持久化的 latest/history 行。
2. 确认每个预测特征的原始财务字段映射，包括百分比/比率单位规则。
3. 确认四个预测持久化模型以及 `api_gateway` 的内部读取查询契约，包括 `(security, report_type)` 当前键和 `(security, report_type, asof_date)` 历史键。
4. 实现并比较季度路由、锚点选择、层级插补、质量风险防护、原始/调整后量化目标和融合组件审计。
5. 在识别现有市场/财务作业后，确认调度所有权和确切执行频率。
6. 在层级服务前，确认共享行业状态服务/配置、SW 映射版本生命周期、预测层级乘数/间距/仓位上限，以及附加网关响应架构。
7. 在任何五年数据库回填前，针对 PostgreSQL 运行 `predictive_valuation validate`，并输出并排本地工件。
8. 要求在报告/模型身份、评分/动作/风险、原始和调整后目标区间、市场调整、特征来源、财务元数据和失败语义方面达到对等。数值比较使用有文档记录的容差；分类和身份字段必须精确一致。
9. 验证代表性的成长型、周期型、稳定价值型和未映射 SW 样本：所有已编码样本必须返回可解释状态；完整模板必须有序，满足其记录的间隔，并为相同的行业代码保留与传统路径相同的状态。
10. 仅在基线对等、历史快照覆盖、重放幂等性和全部失败退出检查通过后，启用三层模板和事件作业。

本文档更新未授权任何公共 API 契约变更。在后端实施开始前，必须审查并确认数据库字段以及内部/公共请求响应字段。实施随后按基线优先的顺序推进：单季度对等、融合对等、latest/history 持久化对等，接着是共享状态、三层、事件、调度器和网关增强。
