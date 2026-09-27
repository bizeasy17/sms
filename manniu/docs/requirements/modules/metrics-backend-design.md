# metrics 后端模块设计文档

## 1 文档信息

- 模块：`manniu_backend/metrics`
- 所属服务：UAT `manniu_backend`
- 文档状态：设计基线与对齐建议
- 关联实现：`metrics/services/health_scoring_service.py`、`metrics/services/model_topn_scoring.py`、`metrics/views.py`
- 设计范围：普通财务六维健康评分、模型 TopN 特征六维评分、两者的数据与响应契约
- 非目标：本文件不授权直接变更评分代码、API 行为或数据库结构；实施前应按变更流程确认接口和持久化字段

## 2 设计定位与原则

`metrics` 将已落库的财务、行情及模型特征转换为可解释的评分结果。普通财务六维描述公司基本面状态；TopN 特征六维描述指定模型版本所选特征在六个分析维度上的分布与评分。两类结果相关但语义不同，不应互相覆盖、混称或被当作同一算法的不同参数。

核心原则：

1. 六个维度使用稳定的领域键；股票类型或行业差异通过显式 profile 表达，不改变响应维度身份。
2. 原始值、单位、报告期、行情时点、数据来源和计算版本可追溯；评分不能替代原始证据。
3. 模型特征重要性/预测方向不等价于财务指标的好坏方向。预测解释与健康评分分别表达。
4. 缺失、低覆盖、降级数据和不可比结果显式返回，不以静默中性分伪装为有效证据。
5. 维度归属、归一化、权重、行业分位和特殊行业规则必须显式、可测试、可版本化。
6. `metrics` 只读取项目内已落库事实或受控内部 provider，不在用户请求中直接回源外部数据源；不产生买卖指令或自动交易行为。

## 3 两类评分的产品定义

| 项目 | 普通财务六维 | TopN 特征六维 |
| --- | --- | --- |
| 回答的问题 | 这家公司的基本面在六个常规领域表现如何？ | 某个模型版本选出的 TopN 特征分别落在哪些领域，其观测值和评分如何？ |
| 核心输入 | 报告期财务指标及指定 as-of 行情/估值数据 | 模型版本、特征排序清单、特征值快照、报告期与行情时点 |
| 维度来源 | 稳定领域维度；可按股票类型选择不同证据与 profile | 稳定领域维度；特征按版本化映射规则归类 |
| 解释属性 | 描述性基本面评价，不是估值目标或投资建议 | 模型特征诊断与可选的业务质量评分；不能把预测贡献直接称为健康度 |
| 必要版本 | `scoring_version`、`profile_version` | `model_version`、`feature_set_version`、`mapping_version`、`normalization_version`、`profile_version` |

六个规范维度键：

| 规范键 | 名称 | 解释边界 | 常见证据示例 |
| --- | --- | --- | --- |
| `growth_momentum` | 增长动能 | 收入、利润与经营规模的增长及其持续性 | `or_yoy`、`tr_yoy`、`netprofit_yoy` |
| `profitability_quality` | 盈利质量 | 资本回报、资产回报、利润率与盈利结构 | `roe`、`roe_dt`、`roa`、`grossprofit_margin`、`netprofit_margin` |
| `cashflow_resilience` | 现金流韧性 | 经营现金创造、利润现金转化及现金流承压能力 | `n_cashflow_act`、`ocf_to_or`、`free_cashflow`、`ocf_yoy` |
| `balance_sheet_safety` | 资产负债安全 | 杠杆、短期偿债能力和资本结构 | `debt_to_assets`、`current_ratio`、`quick_ratio`、`assets_to_eqt` |
| `valuation_position` | 估值与市场位置 | 指定时点的估值水平及有清晰参照组的相对位置 | `pe_ttm`、`pb`、`ps`、行业分位、历史分位 |
| `operation_efficiency` | 经营效率与周转 | 资产周转、营运效率及可观测的经营效率指标 | `assets_turn`、`turnover_rate`、周转/营运指标 |

上述证据是白名单候选，不代表每个股票类型均有足够数据，也不构成无条件等权计分。`total_mv`、市值层级和单纯行业代码不应默认解释为估值便宜、经营效率或质量更好；只有明确产品语义、方向及适用性后才可作为评分证据。

## 4 当前 UAT 实现基线

### 4.1 普通财务评分

`health_scoring_service.compute_score` 先依据行业、主营文本等将股票分类，再由 `_source_dimensions` 为股票类型构造六个评分项。不同类型的六项名称、证据和权重不同，例如成长科技、稳定消费、金融地产、重制造使用不同代理指标；结果项 key 目前也包含 `growth_quality`、`asset_quality_proxy` 等类型专属名称，并非统一的六个规范键。默认六项权重合计为 1，但组成随 profile 改变。

当前基础归一化主要为区间线性映射并截断至 `[0, 100]`，负向指标通过反向映射处理。部分缺失值会在 `_normalize_positive` 中按 `0` 参与计算，另有 current ratio、PE 等显式默认值；因此当前总分不等于“只对有效证据重归一化后的分数”，需要结合 evidence 判断完整性。当前响应含 `stock_type`、`dimension_scores`、`dimension_weights`、`risk_flags` 和 `snapshot_asof_date`，但没有完整的维度可用性/覆盖率与评分版本合同。

设计结论：普通评分应继续允许股票类型 profile 使用不同有效证据，但 API 对外维度身份应规范化；代理项作为维度内 `factors` 返回，并标出 `proxy`、数据状态与 profile。缺值应区分“指标缺失”“行业不适用”“provider 降级”，不能用零值或中性分隐藏。

### 4.2 TopN 特征评分

`metrics/views.py` 以 `score_topn`（默认 20，允许 6–20）控制实际参与评分的特征数，以 `store_topn`（默认 50，允许 20–50）控制取回特征清单数量；`use_top20_dimension=true` 时加载特征值并调用 `rebuild_score`。provider 元信息包括 `model_version`、`report_type`、`model_scope`、`model_degraded` 和 `model_degrade_reason`。

当前 UAT TopN 评分已切换至 `topn-dimension-v2`：六维权重仍为增长 0.18、盈利 0.18、现金流 0.16、资产安全 0.16、估值 0.16、经营 0.16；特征通过 `FEATURE_SCHEMA` 显式映射，不再使用关键词或动态均衡 fallback。字段 schema 声明规范单位、业务方向、变换 ID 和是否可计分。行业/历史 rank 统一要求 `[0,1]` 百分位；`debt_to_assets` 支持比例值转百分点并返回输入单位与转换记录。PE/PB/PS、杠杆、增长、回报率等使用各自有版本的变换；未经定义、无单调业务含义的原始金额/换手率仅作为证据，不直接计入维度分。

缺失、非法、未映射和仅证据特征分别输出状态。缺失或非法值不计分；未知特征进入顶层 `unmapped_features`，不会动态分配；无可计分特征的维度分为 `null`，维度间按可用固定权重重归一化，全部不可用时总分为 `null`、等级为 `N/A`。响应增加 `score_type`、`score_status`、特征覆盖率、可用维度权重，以及 `scoring_version`、`feature_schema_version`、`mapping_version`、`normalization_version`、`dimension_weight_version` 和 `profile_version`。特征项同时区分模型 `predictive_direction` 与业务 `business_direction`；前者只用于贡献解释，不改变业务质量归一化分。

本版使用静态通用 schema/profile，尚未引入行业分位 peer 样本门槛、银行等专属 profile 或配置化 schema 文件；这些属于后续经验证后再纳入的策略，不影响本版明确单位、映射、缺失和版本状态的目标。

## 5 TopN 对齐差异与实测

### 5.1 差异分析

| 对齐点 | ASI_DEV 源端表现 | UAT v2 表现 | 设计判断与建议 |
| --- | --- | --- | --- |
| 特征候选上下文 | `_build_top20_dimension_payload` 可基于 Top50 候选补位/调整经营维度特征 | 直接按模型排序取前 `score_topn` 项；不做维度补位 | 候选池与计分子集继续分开定义；如增加补位，必须作为版本化 profile policy |
| 维度映射 | 显式映射与规则之外，含 operation 最低特征数等替换/补位 | `FEATURE_SCHEMA` 显式映射；未知键返回 `UNMAPPED` 并从计分排除 | 继续扩充受审查的 schema；不要恢复关键词或按负载动态分配 |
| 金融/房地产等特殊类型 | 存在行业/类型代理指标与维度规则 | 当前使用通用 `generic` profile，无行业专属 TopN 代理规则 | 只在业务含义、公式、单位、来源及适用范围经验证后增加 profile；不为追逐单次分数复制特例 |
| 盈利与资产安全归一化 | 部分场景采用同业分位或类型专用逻辑 | 使用版本化固定区间变换；当前未启用行业分位 | 后续如引入同业分位，需最小样本数、peer cohort、时点及 fallback 状态；固定区间可作为显式 fallback |
| 现金流特征 | 个别行业可选用行业代理比率或经营特征 | 绝对金额现金流仅作证据；可比率特征才进入评分 | 绝对金额需先规模标准化，不能直接与比率/变化率混合评分 |
| 方向语义 | 业务映射和模型清单共同参与部分处理 | `predictive_direction` 仅用于贡献解释；`business_direction` 决定业务分的单调方向 | 保持两种方向独立；预测贡献不能替代业务质量方向 |
| 单位与 rank | 规则依赖各特征映射/输出口径 | rank 明确为 `[0,1]`；债务比率可转为百分点并带转换元数据 | 每个新增 feature 必须声明单位、范围和方向；不接受静默尺度猜测 |
| 缺失与容错 | 有 alias/fallback 与较宽容错路径 | 缺失、非法、未映射、仅证据分别标记；未评分项不进入均值；维度/总分带覆盖状态 | 低覆盖由调用方根据 `score_status`、覆盖率和可用权重解释，不用中性分伪装完整证据 |
| 降级特征清单 | 某些源端请求因训练数据集路径缺失退回 artifact | UAT 通过 provider 字段暴露降级标志 | 降级清单必须在响应/日志中可识别，不能与指定训练版本的正常清单混为一谈 |

### 5.2 同一 Top10 输入对照

以下固定模型版本 `dev_20260404_mix_q1h1_base_q3fy_v2`、H1 财务期（`20260630`）、行情日（`20260924`）和 Top10 排名清单。源端分数取自实际 `_build_top20_dimension_payload` 冻结输出；UAT 分数由当前 `topn-dimension-v2` 使用冻结 UAT 特征值重新计算。差值定义为 `UAT v2 - ASI_DEV`：

| 股票 | ASI_DEV 总分/等级 | UAT v2 总分/等级 | 差值 | v2 特征覆盖率 | 可用维度权重 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `688002.SH` 睿创微纳 | 72.93 / B | 66.68 / C | -6.25 | 90% | 68% |
| `000002.SZ` 万科A | 29.72 / E | 11.48 / E | -18.24 | 60% | 52% |
| `000001.SZ` 平安银行 | 61.43 / C | 30.59 / E | -30.84 | 90% | 68% |

逐维结果（`源端 / UAT v2`）：

| 股票 | 增长 | 盈利 | 现金流 | 资产安全 | 估值 | 经营 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 睿创微纳 | 100.00 / 100.00 | 70.50 / 59.39 | 50.00 / 不可用 | 79.29 / 77.69 | 40.10 / 26.39 | 94.64 / 不可用 |
| 万科A | 16.57 / 16.57 | 43.17 / 6.36 | 0.71 / 不可用 | 17.84 / 11.52 | 50.00 / 不可用 | 50.00 / 不可用 |
| 平安银行 | 35.55 / 35.55 | 56.83 / 27.55 | 100.00 / 不可用 | 50.00 / 0.00 | 86.39 / 59.00 | 43.61 / 不可用 |

这不是严格相同原始值的实验：源端 view 会从自己的数据库覆盖/重算行情 rank，并使用模糊 alias；冻结 UAT 快照则保留 rank 小数比例和精确 `q_dt_roe`。核对到源端 `pe_rank_120d`/`pe_ind_rank` 出现 0–100 值（例如 100），而 UAT schema 要求 `[0,1]`；源端 `q_dt_roe` 曾匹配为 `roe_dt`/`roe`，且 `basic_eps` 在源端 evidence 缺失、在 UAT 快照中有值。源端还对金融/地产类型生成银行式派生因子，成长科技场景将原始现金流金额转入经营维度；UAT v2 对绝对现金流金额仅留证据，不参与评分。因此表格反映的是固定报告期下两侧完整取值与策略路径的差异，不能将总分差全部归因于归一化算法。

为进一步观察输入变化，将源端输出中 Top10 特征的实际值回填给 UAT v2 后，总分分别为睿创微纳 `68.33`、万科A `9.28`、平安银行 `28.12`。这仍不是两端完全同算法输入：源端总分包含 TopN 之外的行业派生/维度补位及空维度中性分；同时源端 0–100 rank 在 UAT `[0,1]` schema 下会被判为 `INVALID`。此对照说明跨端核验应先在 adapter 层统一同一来源、as-of 时点和 rank 单位，再解释策略差异。

覆盖风险：v2 目前即使 `score_status=PARTIAL` 仍会返回可用维度重归一后的总分和等级。万科A仅有 52% 固定维度权重可用，却仍返回总分 `11.48`；该结果应视为低覆盖诊断值，不宜与完整覆盖分数或源端等级直接排名。最低可用权重门槛尚需产品确认后实施。

## 6 推荐目标设计

### 6.1 统一特征契约，不统一所有业务规则

为每个模型特征维护可校验的 schema：

| 字段 | 约定 |
| --- | --- |
| `feature_key` / `feature_schema_version` | 稳定机器键与 schema 版本；别名通过显式 alias 表维护 |
| `unit` / `valid_range` | 明确 CNY、比例、百分点、次数、百分位等单位及允许范围 |
| `dimension_key` | 六个规范键之一；无明确归属时为 `UNMAPPED`，不动态均衡分配 |
| `business_direction` | 业务质量方向：`higher_better`、`lower_better`、`target_range` 或 `non_monotonic` |
| `predictive_direction` | 模型预测方向，单独保留；不得自动解释为经营质量方向 |
| `transform_id` | 归一化函数/参数版本；输出 `[0,100]` 的可解释尺度 |
| `source_field` / `source_period` | 原始事实来源、报告期/交易日及 as-of 边界 |
| `value_status` | `AVAILABLE`、`MISSING`、`INVALID`、`STALE`、`UNMAPPED` 或 `DEGRADED` |
| `profile_id` | 可选股票类型策略；记录行业、peer cohort、最小样本数和 fallback 规则 |

特征清单、特征值快照、映射规则和归一化策略应作为可独立追溯的版本化输入。TopN 候选数与实际参与计分数分别记录；响应至少携带 `model_version`、`feature_set_version`、`score_topn`、`store_topn`、`mapping_version`、`normalization_version`、`profile_version`、报告期、as-of 日期和降级状态。

### 6.2 维度映射与特征选择

1. 使用显式 `feature_key → dimension_key` 注册表；别名只解决同一指标的命名差异，不允许近似字符串匹配误把不同字段当成同一证据。
2. `score_topn` 按模型排序清单选择；`store_topn` 只决定候选/展示池。profile 替换或补位只能在独立、版本化策略中发生，输出原始 rank、最终 rank、替换理由和被排除项。
3. 每个维度可设置最低有效特征数或最低有效权重覆盖率。未达门槛时标记 `PARTIAL`/`NOT_AVAILABLE`，不可用 50 伪装完整结果。
4. 一个原始指标不可因别名或多个候选同时进入多个维度重复计权；派生指标必须列出来源及与原指标的去重规则。
5. 银行等特殊业务型可定义 profile-specific 派生指标（如现金流率代理），但只有在指标反映该行业经济实质、数据可稳定获得且不会重复计量时采用。其公式、字段单位、样本边界和有效期限必须明确；房地产不自动套用银行规则。

### 6.3 归一化、权重和缺失值

- 每项变换都以标准化后的业务单位为输入，输出 `[0,100]`；校验单位、极值和方向。百分位建议内部统一存储为 `[0,1]`，API 元数据明确显示单位；不得将 0–1 百分位按 0–100 公式直接计算。
- 业务质量分只使用 `business_direction`；模型方向和贡献另行输出。若特征没有可辩护的业务单调方向，它可以作为模型解释证据，但不进入健康度均值。
- 行业分位需要记录 peer group、as-of、有效样本数、并列值策略。有效样本低于配置门槛时走明确的固定区间 fallback，不能静默混用行业与全市场基准。
- 建议 TopN v1 保持现有维度权重 `18/18/16/16/16/16` 作为兼容起点，但在 `dimension_weight_version` 中版本化；只有经历史回测和覆盖审查后才调整。普通评分继续使用经确认的股票类型 profile 权重，不复用 TopN 权重。
- 每维分数只对有效、可归一化且可解释的特征计算，并返回 `available_weight`/`feature_coverage`/`missing_features`。总分采用有效维度权重重归一化，同时设置最低覆盖门槛；门槛以下总分状态为 `NOT_AVAILABLE`。缺失值不是 0，也不是默认中性 50。
- 中性值 50 仅能作为一个被明确命名的“中性先验”策略使用；必须标注为插补值、计入缺失覆盖率并做敏感性测试，不得当作实测值。
- 原始金额特征原则上先转为有经济含义的规模比率、同比/差分或分位再参与打分；原始金额可留作证据，不因金额大而自动得高分。

### 6.4 普通财务评分契约

普通财务评分使用规范六维作为输出 key，`profile_id` 仅决定维度内因子、权重、方向和适用性。维度结果包含 `score`、`status`、`available`、`available_weight`、`evidence`、`factors`、`missing_metrics` 和 `source_periods`；总结果包含 `scoring_version`、`profile_version`、`available_weight`、`missing_dimensions`、`data_status`、`snapshot_asof_date` 及风险标记。

利润表、资产负债表、现金流量表和指标表必须按公开披露有效时点对齐；财务期使用同一个 `end_date`，行情与估值使用明确的 `asof_date`，不得把预测值混入已披露事实。若各来源报告期不一致，应返回实际来源期和部分状态，而不是隐式拼成一个“完整季度”。

普通评分与 financials 文档中的 `fundamental-lite-v1` 四维基本面评价需分别命名、版本化；二者的目的、维度、权重和 API 字段不可互换。上层聚合或 UI 若同时展示，必须带 `score_type`/版本标签。

### 6.5 TopN 响应语义

TopN 响应除模型与算法 provenance 外，建议在每个特征项中返回 `feature_key`、`rank`、`dimension_key`、`raw_value`、`unit`、`normalized_score`、`business_direction`、`predictive_direction`、`model_weight`、`value_status`、`matched_source` 和 `transform_id`。维度项返回 `score`、`weight`、`feature_count`、`feature_coverage`、`status`、`evidence`、`feature_items`、`mapping_policy` 和 `fallbacks`。

总结果明确 `score_type: MODEL_TOPN_DIMENSION`，且与普通评分使用不同的版本字段。模型清单缺失或降级时保留降级状态；未取得 TopN 清单时可按既有 API 兼容策略返回普通评分，但不得把普通评分冒充为 TopN 六维评分。

## 7 边界与调用流程

- `financials` / `market_data`：提供已落库事实及来源时点；负责同步，不由 metrics 在用户请求中采集。
- 预测估值 provider：提供指定模型、report type 和股票类型下的特征清单及模型元信息；必须区分训练数据正常产物与 artifact fallback。
- `metrics`：解析评分模式、获取适配后的特征值、执行评分并生成 provenance；算法核心应可用显式输入脱离 Django 查询层验证。
- API 视图：负责参数校验、provider 编排、错误映射和兼容响应，不承载特征映射/归一化业务规则。
- 前端：按 `score_type` 展示对应名称、完整度及依据，不自行计算分数或把模型预测贡献解释为经营好坏。

当前 `score` 视图的 `use_top20_dimension` 是请求开关，不应成为长期唯一的语义合同。后续若调整 API，应先确认请求与响应字段兼容性；本设计文档本身不改 API。

## 8 版本迁移与验收

TopN v2 已按直接切换方式替换旧 UAT 评分语义；后续验证与扩展按以下顺序进行：

1. **契约补齐**：将当前静态 schema 中的有效范围、数据来源约束和 alias 规则补齐为可审查配置；不改变当前已声明版本的语义。
2. **黄金样本验证**：对同一股票、同一模型版本、同一特征快照记录 v2 逐特征映射、覆盖率、各维分及总分，形成可重复核对样本。
3. **策略评审**：逐项审查行业 profile、行业分位、代理特征及 feature 替换策略；由业务确认公式和样本门槛后再启用并升级版本。
4. **兼容与回滚**：前端按 `score_type` 和 `score_status` 识别可用性；保留旧算法版本的回算/回滚途径，避免不同版本结果被直接比较。

验收至少包括：

- 六个规范维度 key 固定且顺序稳定；股票类型策略只改变证据/profile，不改变维度身份。
- 同一版本、同一输入快照重复计算结果确定；普通评分和 TopN 评分均能独立调用、独立标识。
- 每个参与计分的 feature 都能追溯原值、单位、来源、映射规则、归一化版本及方向；未映射项有明确状态。
- 覆盖 rank 为 0–1、0–100 两种输入及非法范围时的显式校验；禁止尺度猜测造成静默满分/反向评分。
- 覆盖缺失值、全维缺失、低样本行业分位、模型降级、重复别名、方向冲突、负向指标和银行/非银行 profile。
- 对同一 snapshot 做 source/UAT golden comparison，比较特征取值、映射、逐维分、有效权重、总分与等级，并将允许误差和预期 profile 差异写入用例。
- 生产降级、低覆盖或不同 `model_version`/`feature_set_version` 的结果不能被误标为可直接比较。

## 9 本轮结论

当前证据支持先统一 TopN 特征 schema、单位、映射、缺失状态及版本 provenance，而非直接复制源端所有 operation 补位、银行代理或行业分位实现。源端规则只有在能解释业务差异、具有稳定数据输入、可清晰定义方向与回退并通过分行业验证时，才纳入独立 profile。普通六维与 TopN 六维保持两种 `score_type`，共用数据质量和审计规范，但不强求相同指标、权重或总分含义。
