# metrics 后端模块设计文档

## 1 文档信息

- 模块：`manniu_backend/metrics`
- 所属服务：UAT `manniu_backend`
- 文档状态：设计基线与对齐建议
- 关联实现：`metrics/services/health_scoring_service.py`、`metrics/services/model_topn_scoring.py`、`metrics/views.py`
- 设计范围：普通财务六维健康评分、模型 TopN 特征六维评分、企业增长潜力信号（CGPS）及其各自的数据与响应契约
- 非目标：本文件不授权直接变更评分代码、API 行为或数据库结构；实施前应按变更流程确认接口和持久化字段

## 2 设计定位与原则

`metrics` 将已落库的财务、行情及模型特征转换为可解释的评分结果。普通财务六维描述公司基本面状态；TopN 特征六维描述指定模型版本所选特征在六个分析维度上的分布与评分；企业增长潜力信号（CGPS）使用独立的七个增长证据维度评估未来业绩改善的相对信号。三类结果目的、维度和算法不同，不应互相覆盖、混称或被当作同一算法的不同参数。

核心原则：

1. 普通财务评分和 TopN 评分各自使用稳定的六维领域键；CGPS 使用独立的七维键。股票类型或行业差异通过显式 profile 表达，不改变各自的维度身份。
2. 原始值、单位、报告期、行情时点、数据来源和计算版本可追溯；评分不能替代原始证据。
3. 模型特征重要性/预测方向不等价于财务指标的好坏方向。预测解释与健康评分分别表达。
4. 缺失、低覆盖、降级数据和不可比结果显式返回，不以静默中性分伪装为有效证据。
5. 维度归属、归一化、权重、行业分位和特殊行业规则必须显式、可测试、可版本化。
6. `metrics` 只读取项目内已落库事实或受控内部 provider，不在用户请求中直接回源外部数据源；不产生买卖指令或自动交易行为。

## 3 评分类型的产品定义

| 项目 | 普通财务六维 | TopN 特征六维 | 企业增长潜力信号（CGPS） |
| --- | --- | --- | --- |
| 回答的问题 | 这家公司的基本面在六个常规领域表现如何？ | 某个模型版本选出的 TopN 特征分别落在哪些领域，其观测值和评分如何？ | 已披露财报中哪些增长证据相对同业转强，综合信号是否有足够覆盖？ |
| 核心输入 | 报告期财务指标及指定 as-of 行情/估值数据 | 模型版本、特征排序清单、特征值快照、报告期与行情时点 | as-of 时点可见的利润表、资产负债表、现金流量表、财务指标和行业 peer 样本 |
| 维度来源 | 稳定领域维度；可按股票类型选择不同证据与 profile | 稳定领域维度；特征按版本化映射规则归类 | 版本化七维增长证据规则；首期适用非金融企业 |
| 解释属性 | 描述性基本面评价，不是估值目标或投资建议 | 模型特征诊断与可选的业务质量评分；不能把预测贡献直接称为健康度 | 同行相对的业绩改善信号，不是增长概率、估值结论或投资建议 |
| 必要版本 | `scoring_version`、`profile_version` | `model_version`、`feature_set_version`、`mapping_version`、`normalization_version`、`profile_version` | `calculation_version`、`peer_mapping_version`、`profile_version` |

普通财务评分和 TopN 评分的六个规范维度键：

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

#### 4.1.1 竞争位置指标实现基线

UAT 已实现收入份额变化主路径，版本为 `health-score-peer-position-v1`，行业映射版本为 `security-industry-v1`。该指标评估公司相对可比同行的竞争位置，而不是公司绝对市值规模。当前仅替换原来含市值代理的 `growth_tech` 与通用兜底 profile；其它 profile 原本没有市值规模代理，本次不扩展到这些 profile。ROIC 备选和历史样本区分度评估尚未完成。

1. `total_mv` 不再作为普通财务健康分的计分因子，也不映射成竞争力分。市值可作为独立的行情/规模信息展示，但不影响六维总分、维度等级或健康结论。不得仅把 `competition_proxy` 改名为“竞争力”而继续使用市值公式。
2. 首选因子为**可比上市同行收入份额的三年变化**。在同一财报期、合并口径、报告类型和版本化细分行业 peer cohort 内，以同一收入字段计算 `peer_revenue_share(t) = company_revenue(t) / sum(peer_revenue(t))`，再计算 `share_change_3y = peer_revenue_share(t) - peer_revenue_share(t-3y)`。整个 cohort 必须使用同一收入定义；主营业务收入与公司总营收不可混用。仅在 cohort 映射稳定、分母有效且两端时期可比时计算。
3. ROIC 可作为未来独立备选，但当前没有实现。ROIC 字段公式、税项、投入资本组成、财年对齐方式和来源必须在启用前固定并版本化；收入份额与 ROIC 不得平均或静默互换，不同 `metric_basis` 的结果不得直接作时间序列比较。当前收入份额不可用时不尝试 ROIC。
4. 当前 cohort 使用相同报告期、`report_type`、`comp_type` 和收入字段；只纳入公告日不晚于 as-of、当时已上市且未退市的证券，并要求目标及同行在当前期和三年前同期均有正收入。按收入份额变化的平均名次计算 0–100 同行百分位，至少需要 20 家共同有效证券（含目标证券）。不足 20 家、行业/期间/口径缺失或原始收入无效时，竞争位置为 `NOT_AVAILABLE`，不回退到 `total_mv`、0 分或中性 50 分。证据记录 peer 数、行业及映射来源、样本期间、报告口径、收入字段、as-of、basis 和版本。
5. 本节不增加第七个评分维度：首期竞争位置因子并入 `growth_quality`，与已有营收增长共同组成增长维度。复合权重沿用旧市值代理的预算：`growth_tech` 为营收增长 0.20 + 同行因子 0.15，通用兜底为 0.20 + 0.14。缺少某一因子时只计入另一因子的可用权重；两者都缺失时维度为 `NOT_AVAILABLE`。总分按可用权重重归一。
6. `total_mv` 可作为行情规模信息展示，但不进入本次相关维度或健康总分。固定其它输入只改变总市值，评分应保持不变；peer 因子改变时评分可变化。
7. 普通评分响应返回 `scoring_version`、`profile_version`、`peer_mapping_version`、总覆盖率、维度 `available_weight/status`。总覆盖低于 80% 时总分为 `null`、状态为 `INSUFFICIENT_DATA`；否则按可用维度权重重归一，部分覆盖为 `PARTIAL`。注意：该版本只将同行/营收因子的缺失计入增长维度可用权重，其他既有 profile 因子的缺失回退语义尚未全面改造。

已由定向测试覆盖：20 家共同有效样本的百分位计算、19 家时不可用、总市值变化不影响竞争分、缺失增长和 peer 因子不计可用权重。历史样本校准、口径冲突扩展测试、ROIC 备选路径及跨版本历史可比性仍待完成。

#### 当前计算步骤

1. `_context` 按证券分别读取财务指标、利润表、资产负债表、现金流量表和主营构成各自最新的记录，排序依据为报告期、公告日和记录 ID；各表当前不强制对齐到同一个 `end_date`，因此输入可能来自不同报告期。现金流同一报告期/公告日有多个版本时优先选择 `raw_payload.update_flag=1`。行情特征读取指定 `asof_date` 之前最新的日行情/基本面记录；未传日期时使用当前最新日快照。收入优先取 `total_revenue`，为空时回退 `revenue`；毛利率优先取指标表 `grossprofit_margin`，必要时从收入和营业成本计算。竞争位置同行比较使用目标记录选定的单一收入字段，不混用 `total_revenue` 与 `revenue`。
2. `_classify` 根据行业、主营范围和主营构成关键词计算股票类型候选，再应用噪声词、冲突规则及配置兜底，选择一个 profile。当前 profile 包括 `growth_tech`、`stable_consumer`、`stable_income`、`cyclical_resource`、`finance_realestate`、`heavy_manufacturing` 和通用兜底。
3. 对输入值使用下列函数，归一化后截断至 `[0,100]`：

	- 正向：`N+(x; low, high) = clip(100 * (x - low) / (high - low))`。
	- 负向：`N-(x; low, high) = 100 - N+(x; low, high)`。
	- 当前 `_normalize_positive` 将缺失值替换为 `0` 后归一；显式回退还包括 `current_ratio` 缺失按 `1`、`pe_ttm` 缺失按 `30`。因此缺失值可能实际影响分数，普通评分当前并非只对有效证据重归一。
	- `total_mv` 不参与普通财务健康分计分。现金流评分使用同一报告期的经营现金流率和自由现金流率（分别为经营现金流/营业收入、自由现金流/营业收入，单位为百分比），不直接对人民币金额归一化；两项分别按 `[-20%,50%]` 正向线性映射并截断至 `[0,100]`，再取平均。绝对现金流金额不直接参与该维度评分。

各 profile 的六项（括号为权重）由以下表达式组成；`rev=N+(or_yoy;-20,60)`、`profit=N+(netprofit_yoy;-30,80)`、`cash=(N+(operating_cashflow_margin;-20,50)+N+(free_cashflow_margin;-20,50))/2`、`safe=(N-(debt_pct;20,85)+N+(current_ratio 或缺失回退 1;0.8,2.5))/2`、`value=N-(pe_ttm 或缺失回退 30;5,80)`、`profitability=(N+(roe;0,25)+N+(netprofit_margin;0,40))/2`。现金流率按百分点计算；`debt_pct` 为统一到百分点后的资产负债率；下表未展开的 `N+`、`N-` 均按上述定义：

| profile | 六项分数（key、权重、公式） |
| --- | --- |
| `growth_tech` | `growth_quality` 0.35：`N+(or_yoy;-20,60)`（因子预算 0.20）与三年同行收入份额变化百分位（0.15）按可用因子权重合成；`profit_conversion` 0.18 `N+(netprofit_yoy;-30,80)`；`cash_runway` 0.16 `cash`；`rd_intensity_proxy` 0.16 `N+(gross_margin;20,70)`；`tech_moat_proxy` 0.15 `N+(roe_dt;0,20)`。 |
| `stable_consumer` | `moat_proxy` 0.20 `N+(gross_margin;20,75)`；`profitability` 0.18 `profitability`；`channel_proxy` 0.16 `N-(assets_to_eqt;1,8)`；`growth_stability` 0.16 `(rev+profit)/2`；`cash_quality` 0.16 `cash`；`shareholder_return` 0.14 `N+(dv_ttm;0,8)`。 |
| `stable_income` | `cash_stability` 0.20 `cash`；`dividend_support` 0.18 `N+(dv_ttm;0,8)`；`earnings_stability` 0.16 `N-(abs(netprofit_yoy);0,80)`；`leverage_safety` 0.16 `safe`；`valuation_defense` 0.16 `value`；`moderate_growth` 0.14 `N+(or_yoy;-10,25)`。 |
| `cyclical_resource` | `profit_elasticity` 0.20 `profit`；`cost_proxy` 0.18 `N+(gross_margin;5,50)`；`financial_safety` 0.16 `N-(debt_pct;20,85)`；`capital_discipline` 0.16 `cash`；`operation_proxy` 0.16 `N+(ocf_yoy;-50,100)`；`cycle_position_proxy` 0.14 `(value+N+(dv_ttm;0,10))/2`。 |
| `finance_realestate` | `asset_quality_proxy` 0.20 `N-(debt_pct;30,90)`；`capital_safety` 0.18 `N-(assets_to_eqt;1,20)`；`profitability` 0.16 `N+(roe;3,20)`；`risk_exposure_proxy` 0.16 `N-(netprofit_yoy;-100,80)`；`valuation_safety` 0.16 `value`；`growth_space_proxy` 0.14 `rev`。 |
| `heavy_manufacturing` | `capital_efficiency` 0.20 `N+(roe;0,20)`；`order_proxy` 0.18 `rev`；`capacity_proxy` 0.16 `N+(assets_to_eqt;0.8,5)`；`profitability` 0.16 `profitability`；`operation_efficiency` 0.16 `N+(ocf_yoy;-50,100)`；`financial_safety` 0.14 `safe`。 |
| 通用兜底 | `growth_quality` 0.34：`rev`（因子预算 0.20）与三年同行收入份额变化百分位（0.14）按可用因子权重合成；`income_quality` 0.18 `N+(gross_margin;10,80)`；`profit_path` 0.16 `profit`；`cash_runway` 0.16 `cash`；`light_asset_proxy` 0.16 `N+(roa;0,20)`。 |

每项分数截断后乘可用权重求和，并对可用权重重归一；各 profile 名义权重合计为 1。增长维度 `weight` 保留名义权重，`available_weight/status` 反映实际可用因子。总覆盖低于 80% 时总分为 `null`；否则等级阈值为 A `>=85`、B `>=70`、C `>=55`、D `>=40`，否则 E。评分版本为 `health-score-peer-position-v1`，profile 及同行映射版本随结果输出。其它既有维度仍存在缺失值回退行为，解释时须检查 `evidence`。

### 4.2 TopN 特征评分

`metrics/views.py` 以 `score_topn`（默认 20，允许 6–20）控制实际参与评分的特征数，以 `store_topn`（默认 50，允许 20–50）控制取回特征清单数量；`use_top20_dimension=true` 时加载特征值并调用 `rebuild_score`。provider 元信息包括 `model_version`、`report_type`、`model_scope`、`model_degraded` 和 `model_degrade_reason`。

当前 UAT TopN 评分已切换至 `topn-dimension-v2`：六维固定权重为增长 0.18、盈利 0.18、现金流 0.16、资产安全 0.16、估值 0.16、经营 0.16；特征通过 `FEATURE_SCHEMA` 显式映射，不使用关键词或未知特征的动态均衡 fallback。字段 schema 声明规范单位、业务方向、变换 ID 和是否可计分。`score_topn` 默认 20（范围 6–20），`store_topn` 默认 50（范围 20–50）；先按模型顺序去重并排除 `fiscal_year`，取前 `score_topn` 项。若入选经营周转特征少于 2 项，则从已取回候选中补入经营特征，并按替换优先级移除可替换项；候选不足时不强行补齐。该替换会改变最终计分子集，返回结果应以 `feature_dimension_mapping` 中的映射及逐特征结果为准。

特征值来自已落库 `_context` 与普通评分证据，不直接在 metrics 请求中回源。财务特征按最新报告期读取，估值/排名特征使用 `asof_date` 前的行情快照；模型 TopN 清单按 `report_type` 选择。行业/历史 rank 在普通特征上下文中以 `[0,1]` 小数分位计算。对于 `roe`、`roe_dt`、`netprofit_margin`、`gross_margin`/`grossprofit_margin`、`assets_turn`，若可取得同一财务期 peer 样本，TopN 评分使用其同业百分位覆盖固定区间归一；同业有效样本少于 20 时改用同一财务期全市场样本。行业/市场百分位 override 以 0–100 分提供给 TopN 变换，不改变原始特征值。

#### 当前特征归一化与聚合

对可计分特征先按 schema 计算 `[0,100]` 的业务分；普通区间变换为 `clip(100 * (x-low)/(high-low))`，负向区间反转为 `100-score`。主要范围如下，区间外截断：

| transform | 输入范围 | 方向/计算 |
| --- | --- | --- |
| `growth_percent_v1` | `[-50,100]` | 正向线性 |
| `return_percent_v1` | `[-30,30]` | 正向线性 |
| `roe_percent_v1` / `roe_dt_percent_v1` | `[0,25]` / `[0,20]` | 正向线性 |
| `quarterly_roe_percent_v1` / `roa_percent_v1` | `[-10,20]` / `[0,15]` | 正向线性 |
| `margin_percent_v1` / `eps_v1` | `[-5,40]` / `[-50,100]` | 正向线性 |
| `cashflow_ratio_percent_v1` | `[-20,50]` | 正向线性 |
| `debt_percent_v1` / `leverage_multiple_v1` | `[20,90]` / `[1,10]` | 负向线性；`debt_to_assets` 比例输入（绝对值 `<=1`）先乘 100 |
| `liquidity_ratio_v1` / `assets_turn_v1` | `[0,3]` / `[0,2]` | 正向线性 |
| `pe_multiple_v1` / `pb_multiple_v1` / `ps_multiple_v1` | `[5,80]` / `[0.5,10]` / `[0.5,10]` | 负向线性 |
| `dividend_yield_v1` | `[0,8]` | 正向线性 |
| `rank_low_better_v1` / `rank_high_better_v1` | `[0,1]` | `100*(1-x)` / `100*x` |
| `cash_amount_v1` / `revenue_size_v1` | CNY | `clip(50 + 50*tanh(x/1e9))` |

未列入可计分 schema 的特征、schema 中 `scoreable=false` 的证据特征不会进入分数。`MISSING`、`INVALID`、`UNMAPPED`、`EVIDENCE_ONLY` 均保留诊断状态，不作为 50 分或 0 分参与特征均值。对每个维度，使用计分特征的绝对模型权重作加权平均；若这些权重合计为 0，则对计分特征做算术平均。预测方向只用于贡献解释，不乘入业务维度分。维度权重仍采用固定六维权重；总分为有分数的维度按其固定权重加权后，除以可用维度权重之和，即对可用维度重归一。

`feature_coverage` 为成功计分特征数/入选特征数；`feature_weight_coverage` 为已计分特征绝对模型权重/入选特征绝对模型权重。维度无计分项为 `NOT_AVAILABLE`，部分特征未计分为 `PARTIAL`，全部维度均可用时仍可能因入选证据特征未计分而使总状态为 `PARTIAL`。总等级阈值与普通评分相同（A `>=85`、B `>=70`、C `>=55`、D `>=40`、否则 E）；没有可用维度时总分为 `null`、等级 `N/A`。当前不设置最低覆盖率门槛，因此低覆盖时仍可能返回可用维度重归一后的总分。

缺失、非法、未映射和仅证据特征分别输出状态。缺失或非法值不计分；未知特征进入顶层 `unmapped_features`，不会动态分配；无可计分特征的维度分为 `null`，维度间按可用固定权重重归一化，全部不可用时总分为 `null`、等级为 `N/A`。响应增加 `score_type`、`score_status`、特征覆盖率、可用维度权重，以及 `scoring_version`、`feature_schema_version`、`mapping_version`、`normalization_version`、`dimension_weight_version` 和 `profile_version`。特征项同时区分模型 `predictive_direction` 与业务 `business_direction`；前者只用于贡献解释，不改变业务质量归一化分。

`industry_code` 的含义需要与数据库字段 `Security.industry_id` 区分：前者是预测特征构建器根据 `Security.industry.name` 生成的数值类别输入，后者只是 `Industry` 表的数据库主键，两者不可互换，也不是 Tushare/SW 的官方行业代码。当前预测构建器将本地行业名称集合排序后按位置编码，未知行业使用配置的 `unknown_code`（默认 `-1`）；因此该数值依赖本地行业集合，不应视为跨环境稳定的行业标识。以 UAT 当前数据为例，300502.SZ 的行业名称为“通信设备”、`industry_id=132`，预测构建器当前得到 `industry_code=97.0`；该 `97.0` 仅是当前映射快照的类别序号。

当前 `metrics` TopN 六维输入没有把预测构建器生成的 `industry_code` 注入评分特征值；同时 `FEATURE_SCHEMA` 将其定义为 `valuation_position` 下的类别型、仅证据特征，不参与计分。因此模型 TopN 清单选中该特征时，评分会显示其值缺失并使估值维度状态为 `PARTIAL`，但这不表示股票缺少行业分类，也不应把数据库 `industry_id` 或其它行业代码直接填入替代。若要消除该状态，须先定义可复现、版本化的行业编码来源及评分/覆盖语义，再单独评审接口与 schema 变更。

本版使用静态通用 schema/profile，尚未引入行业分位 peer 样本门槛、银行等专属 profile 或配置化 schema 文件；这些属于后续经验证后再纳入的策略，不影响本版明确单位、映射、缺失和版本状态的目标。

## 5 TopN 对齐差异与实测

### 5.1 差异分析

| 对齐点 | ASI_DEV 源端表现 | UAT v2 表现 | 设计判断与建议 |
| --- | --- | --- | --- |
| 特征候选上下文 | `_build_top20_dimension_payload` 可基于 Top50 候选补位/调整经营维度特征 | 按模型排序取前 `score_topn` 项；经营周转特征少于 2 项时可从候选池替换补入 | 保持候选池与计分子集分开；替换规则应版本化并记录最终清单及替换理由 |
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

## 10 企业增长潜力信号（CGPS）

### 10.1 定位与边界

CGPS（Corporate Growth Potential Signal，企业增长潜力信号）回答“截至指定信息时点，这家公司相对可比公司有哪些未来业绩改善证据”。综合结果为“增长潜力综合分”，范围 0–100。它是**第三种独立评分类型**，不得并入普通财务六维、TopN 特征六维或预测估值模型；高分是同行相对信号，不是未来增长概率、目标价或投资建议。

本章只定义需求算法，不授权直接变更 API、数据库结构或评分代码。计算只读消费 PostgreSQL 中已落库财报事实和版本化行业映射，不在请求中回源 Tushare。首期适用一般工商及非金融企业；银行、保险、证券、多元金融的报表经济含义不同，返回 `NOT_APPLICABLE`，待专属 profile 经验证后再支持。

七个稳定维度键及 `cgps-v1` 初始权重如下：

| 维度键 | 维度名称 | 权重 | 关注信号 |
| --- | --- | ---: | --- |
| `demand_momentum` | 需求与收入动能 | 20% | 单季度收入增速及其加速度 |
| `order_visibility` | 订单与收入能见度 | 15% | 合同负债、预收款相对收入的变化 |
| `profitability_leverage` | 盈利能力与经营杠杆 | 15% | 营业利润增长、毛利率和净利率变化 |
| `earnings_quality` | 利润质量与可持续性 | 15% | 扣非利润增长、非经常性利润占比 |
| `cash_conversion` | 回款与现金转化 | 15% | 销售回款、经营现金流与利润的匹配 |
| `growth_investment` | 成长投入与产能准备 | 10% | 研发、资本开支和在建工程强度 |
| `balance_operation_safety` | 资产负债与营运安全 | 10% | 应收、库存、杠杆、流动性和周转 |
| **合计** | **七维** | **100%** | 固定权重 |

维度键和顺序固定，权重集中配置且总和必须为 1。任何字段、公式、权重、行业适用范围或阈值变化都必须升级 `calculation_version`，不能静默改变已发布口径。

### 10.2 数据时点与单季度口径

1. 计算必须指定 `asof_date`，只使用 `ann_date` 或实际公告日 `f_ann_date` 不晚于该日的信息，并返回所用报告期、公告日期和来源记录。
2. 历史回测必须还原当时可见的财报版本；不可仅按当前 `update_flag=1` 选最新记录，因为后续更正可能造成前视偏差。
3. 利润表、资产负债表、现金流量表和财务指标按同一 `end_date`、合并口径和报告类型对齐；报告期不一致时相关维度标记部分或缺失，不得拼成完整季度。
4. 单季度流量优先使用 Tushare 单季合并报表 `report_type=2` 或明确的 `q_*` 指标。仅有累计值时按同一会计年度相邻累计数相减：Q2=半年累计−Q1，Q3=前三季度累计−半年累计，Q4=全年累计−前三季度累计。资产负债表时点余额不得作累计差分。
5. 单季度同比增长为 `g_x(t)=100*(x_q(t)/x_q(t-4)-1)`。基期为零、缺失或正负跨越时标记 `INVALID_BASE`，不生成极端增长率；金额统一为人民币元，比例/百分点单位显式声明，不猜测尺度。

### 10.3 同行百分位归一化

金额、比率和增长率不可直接相加。每个因子在相同报告期、报告类型和行业 peer cohort 中计算百分位，行业映射须版本化。行业有效样本少于 20 家时回退至相同报告期和报告类型的非金融全市场样本；回退样本仍少于 20 家时该因子不可用。

同值使用平均名次。样本数为 `N`、平均名次为 `rank_avg`：

```text
P+(x) = 100 * (rank_avg - 1) / (N - 1)   # 越高越好
P-(x) = 100 - P+(x)                     # 越低越好
```

百分位范围为 `[0,100]`。因子结果需保留原始值、单位、方向、peer 范围、样本数和回退状态；缺失、非法、未知方向或低样本因子不赋 0/50。

### 10.4 七维因子和计算公式

以下 `R_TTM` 为报告期最近四个单季度营业收入之和；`Δ_yoy(z)=z(t)-z(t-4)`。每个维度对有效因子按其配置权重重归一，但有效因子权重覆盖率低于该维度配置权重的 50% 时，该维度为 `NOT_AVAILABLE`；有缺项且达到门槛时标记 `PARTIAL`。

1. **需求与收入动能**：`g_rev` 为单季度营业收入同比增速，优先 `q_sales_yoy`，否则以单季度 `revenue` 计算；`accel_rev = g_rev(t)-g_rev(t-1)`，单位为百分点。`S1 = 0.65*P+(g_rev) + 0.35*P+(accel_rev)`。
2. **订单与收入能见度**：`cl_ratio=contract_liab/R_TTM`，`prepay_ratio=prepayment/R_TTM`；分别计算相对上年同期变化 `d_cl`、`d_prepay`。`S2 = 0.60*P+(d_cl) + 0.40*P+(d_prepay)`。二者是收入能见度代理，不等同于已确认订单；合同资产不作正向订单因子。
3. **盈利能力与经营杠杆**：`g_op` 为单季度营业利润同比增速，优先 `q_op_yoy`；`d_gross_margin`、`d_net_margin` 为 `q_gsprofit_margin`、`q_netprofit_margin` 同比百分点变化。`S3 = 0.40*P+(g_op) + 0.30*P+(d_gross_margin) + 0.30*P+(d_net_margin)`。
4. **利润质量与可持续性**：`g_deducted_profit` 为同口径单季度扣非归母净利润同比增速；`dtprofit_to_profit` 为扣非净利润/净利润（分母须为正）；`nop_to_ebt` 为非营业利润/利润总额（利润总额须为正，越低越好）。`S4 = 0.50*P+(g_deducted_profit) + 0.30*P+(dtprofit_to_profit) + 0.20*P-(nop_to_ebt)`。
5. **回款与现金转化**：`salescash_to_or` 为销售收现/营业收入，`ocf_to_or` 为经营现金流/营业收入，`ocf_to_profit` 为经营现金流/营业利润（营业利润非正时不计）。均使用同期间单季度值。`S5 = 0.40*P+(salescash_to_or) + 0.35*P+(ocf_to_or) + 0.25*P+(ocf_to_profit)`。
6. **成长投入与产能准备**：计算 `rd_intensity=rd_exp/R_TTM`、`capex_intensity=c_pay_acq_const_fiolta/R_TTM`、`cip_intensity=cip/R_TTM` 相比上年同期的变化 `d_rd`、`d_capex`、`d_cip`。`S6_base = 0.40*P+(d_rd) + 0.30*P+(d_capex) + 0.30*P+(d_cip)`。投入上升不无条件加分：若 `S1<50` 或 `S5<40`，则 `S6=min(S6_base,50)`；否则 `S6=S6_base`。
7. **资产负债与营运安全**：`gap_ar=g_accounts_receiv-g_rev`、`gap_inv=g_inventories-g_rev`；另计算资产周转变化 `d_assets_turn`、`debt_to_assets` 和 `current_ratio`。`S7 = 0.25*P-(gap_ar) + 0.25*P-(gap_inv) + 0.20*P-(debt_to_assets) + 0.15*P+(current_ratio) + 0.15*P+(d_assets_turn)`。合同资产增速超过收入时作为风险解释证据，不在本版本单独加分。

### 10.5 综合分和数据状态

设固定维度权重为 `w_d`，有效维度集合为 `A`：

```text
coverage = sum(w_d for d in A) / sum(w_d for all applicable dimensions)
CGPS = sum(w_d * S_d for d in A) / sum(w_d for d in A)
```

仅当 `coverage >= 80%` 且 `demand_momentum`、`profitability_leverage`、`cash_conversion`、`balance_operation_safety` 四个核心维度均有效时返回数值分；否则 `CGPS=null`、状态为 `INSUFFICIENT_DATA` 并列出缺项。达到门槛但有非核心维度缺失时标记 `PARTIAL`，返回 coverage 和实际参与权重；不以 0 或 50 补缺。

解释标签按版本化阈值：`>=80` 强、`65–<80` 偏强、`45–<65` 中性、`30–<45` 偏弱、`<30` 弱。结果须保留 `score_type=COMPANY_GROWTH_POTENTIAL`、`calculation_version`、`profile_version`、`asof_date`、报告期/公告日、peer 范围、七维分数/状态/权重、因子原值/单位/方向/分位、coverage、缺失原因和 warnings。具体 API 请求/响应字段须另行确认，本章不冻结 API 契约。

### 10.6 回测和验收

- 使用按公告时点还原财报版本的滚动样本外回测，不得用后续修订数据回填历史，也不得随机打散时间序列。
- 分别评估未来 2 个季度和未来 4 个季度的收入、扣非归母净利润增长；基期非正、退市/停牌和报告缺失样本须有明确处理规则。
- 报告分数分组的后续业绩均值/中位数、最高分组相对全样本 lift、Spearman 秩相关、行业分层、覆盖率及不同版本表现，并与收入/扣非利润增速等简单基准比较。
- 对基期非正、累计转单季、财报修订、同行不足与回退、因子缺失、投入上升但需求/现金走弱、金融行业不适用和覆盖门槛建立确定性验证。
- 同一输入快照和算法版本结果必须确定；未通过样本外验证或覆盖不足时标注实验性，不作为生产预测结论。

## 11 三类评分结果持久化与检索

本节将常规财务六维、TopN 特征六维和 CGPS 的结果持久化与搜索列为 metrics 的后续需求。本文档及配套详细设计只定义目标和候选方案，不代表数据库 schema 或公开 API 已批准；实施前必须确认字段、唯一性、权限及请求/响应契约。需求和字段提案分别见 [metrics 评分持久化需求](../metrics/requirements.md) 与 [metrics 评分快照后端设计](../metrics/backend-design.md)。

### 11.1 目标与边界

1. 将三类评分结果及其维度、因子/特征证据持久化到 PostgreSQL，支持按证券和评分类型搜索当前及历史结果。
2. 查询读取已保存快照，不隐式触发重算，也不在请求过程中回源 Tushare 或其他外部数据源。
3. 三种评分类型及其算法、维度键和权重保持独立；不能因共用存储而把不同类型分数直接视为同一口径。
4. 持久化是 metrics 内部结果能力，不增加自动买卖、下单或资金操作行为。

### 11.2 评分类型与结果快照

建议统一快照主表使用稳定的 `score_type` 区分结果：

| `score_type` | 评分类型 | 维度身份 |
| --- | --- | --- |
| `FINANCIAL_HEALTH_6D` | 常规财务六维 | 保留当前评分 profile 实际输出的维度 key，不强制改成 TopN 键 |
| `MODEL_TOPN_6D` | TopN 特征六维 | 保留 TopN 维度映射键、实际计分特征集合及模型版本 |
| `COMPANY_GROWTH_POTENTIAL` | CGPS | 固定使用第 10 章定义的七个维度键 |

每条快照候选字段包括：证券引用、评分类型、`asof_date`、实际财务报告期、适用时的行情快照日、总分、标签、状态、coverage、来源期摘要、warnings、输入 fingerprint 和创建时间。类型专属 provenance 按需记录：常规评分保存 scoring/profile 版本；TopN 保存 model/report type/model scope、feature set、TopN 参数、mapping/normalization 版本及 provider 降级状态；CGPS 保存 calculation/profile/peer mapping 版本、公告时点、peer 范围与样本数。

总分不可用时保存 `NULL` 与明确状态/缺失原因；常规六维当前没有统一 coverage 定义，不得为了共用 schema 伪造 coverage 值。上述字段及长度/精度均为候选项，实施前须与现有模型及调用方确认。

### 11.3 维度与证据明细

建议以维度明细表关联快照，至少保存 `dimension_key`、名称、权重、nullable 分数、状态、可用权重和 evidence。对 `(snapshot_id, dimension_key)` 建唯一约束。维度 key 原样保留各评分算法语义，不作跨类型重命名。

Evidence 保存可审计的因子/特征原值、规范单位、业务方向、归一化分/百分位、来源字段与报告期、peer 范围和样本数、缺失/非法/降级原因。TopN 的逐特征证据与 CGPS 的逐因子证据应可通过快照详情读取。首期不为每个 evidence 字段单独建列；如后续需要高频按因子值筛选，再依据查询负载评估关系化明细表和索引。

### 11.4 写入、历史与幂等

1. 各评分 service 继续负责计算；独立持久化适配层按 `score_type` 校验结果和必需 provenance。
2. 主快照和全部维度在同一 PostgreSQL 事务内写入；任一明细失败则整体回滚。
3. 对规范化输入快照及算法版本计算 fingerprint；主表以 `(security_id, score_type, input_fingerprint)` 复合唯一约束保证幂等，相同三元组重复写入不生成重复结果。
4. 不同算法版本或输入 fingerprint 的结果作为独立历史快照保留，不原位覆盖既有分数和证据。旧结果的失效/替代标记机制在实现前确认。
5. 仅由受控计算/刷新流程触发写入；列表和详情查询均为只读操作。

### 11.5 搜索与查询

建议提供评分快照列表和详情查询。候选过滤项包括证券代码、证券名称、`score_type`、as-of 日期范围、财报期、状态、总分区间、标签、`dimension_key` 和维度分数区间；列表支持分页及按日期/分数排序，默认最新快照优先。详情返回完整 provenance、维度和 evidence；列表仅返回摘要，避免默认加载大型 TopN evidence。

索引候选：证券 + 类型 + as-of 日期、类型 + as-of 日期 + 状态、类型 + 总分、`(security_id, score_type, input_fingerprint)` 复合唯一键，以及维度 key + 维度分 + 状态。Evidence 初期不默认建立 JSONB 全量索引，须以代表性查询验证索引必要性和写入成本。

### 11.5.1 入库管理命令与 daily job 边界

首期提供 Django management command 手工计算并持久化指定证券、as-of 日期和评分类型，支持显式证券清单及 `--scope all` 两种范围、dry-run，并以 `--batch-size`（默认 100）按证券分批打印处理区间、累计进度、结果计数和耗时；命令须使用与服务相同的评分 service 和持久化适配层，不复制算法逻辑。命令名称、参数及 TopN 所需 model/report 参数以配套后端设计的确认结果为准。

首期不修改 `scripts/daily.bat`。待手工运行、幂等性、耗时和失败退出码验证后，再单独评审 daily job 的调度频率、证券范围、重试、日志与断点策略。

URL、参数名、分页格式、默认页大小、认证授权和错误响应须复用 API Gateway 约定，并在实现前确认；本节不冻结公开 API 契约。查询缺失分数时不得将 `NULL` 当成 0；查询不得触发评分重算。

### 11.6 状态和数据可追溯性

有效、部分、数据不足、不适用和降级状态应按原评分算法保留。CGPS 的公告时点和历史版本遵循 10.2；TopN 降级结果须保留 model/provider 降级标志；常规六维也须保留其 profile 与数据来源期。无论状态如何，保存的结果都应能通过类型和版本追溯到对应算法基线，不以 0 或 50 插补缺失数据。

### 11.7 测试用例定义

1. 三种评分类型分别保存和读取，验证 score type、算法 provenance 与各自维度 key 原样往返。
2. 保存部分维度、缺失 evidence、`INSUFFICIENT_DATA`、CGPS `NOT_APPLICABLE` 和 TopN 降级结果，验证 NULL、状态与原因保留。
3. 相同 `(security_id, score_type, input_fingerprint)` 的重复/并发写入只产生一个快照；改变任一键成员时保留独立历史记录。
4. 对证券、类型、日期、状态、总分和维度分组合筛选，验证分页、排序及 NULL 分数边界。
5. 主表或任一维度写入失败时验证事务回滚；无效类型、重复维度 key 和非法分数应明确拒绝。
6. 验证查询不触发重算或外部数据访问，并按确认后的权限范围隔离数据。
7. 在 PostgreSQL 上验证唯一约束、索引、并发幂等和代表性搜索性能；不以 SQLite 替代。
8. 竞争位置收入份额主路径：20 家共同有效同行时返回 0–100 百分位，并记录收入字段、行业映射来源/版本、两期财报、报告口径及 as-of。
9. 竞争位置失败边界：共同有效样本少于 20、目标缺少任一期有效收入、报告口径不匹配或公告晚于 as-of 时返回 `NOT_AVAILABLE`，不得回退市值、0 分或中性分。
10. 竞争位置不变量：仅改变 `total_mv` 不改变相关 profile 得分；增长和 peer 因子分别缺失时仅对有效因子计可用权重，两者都缺失则增长维度不可用。
11. 竞争位置总分覆盖：验证有效权重重归一、`PARTIAL` 和 coverage 低于 80% 时总分 `null`/`INSUFFICIENT_DATA`；历史样本区分度及 ROIC 备选需在 TODO-10 完成后另行验证。

### 11.8 TODO List

- [ ] TODO-01（对应 11.2–11.3）：确认快照/维度字段、类型枚举、证据粒度、精度和删除策略。
- [ ] TODO-02（对应 11.4）：确认 fingerprint 组成及历史结果失效/替代规则。
- [ ] TODO-03（对应 11.5–11.6）：确认搜索 API 字段、分页/排序、认证授权和错误语义。
- [x] TODO-04（对应 11.2–11.4、11.7）：两张 PostgreSQL 结果表、复合幂等写入和定向测试已完成；6 项 metrics 测试通过。
- [x] TODO-05（对应 11.5.1、11.7）：手工入库 CLI 已实现，单证券三类评分 dry-run 通过。
- [ ] TODO-06（对应 11.5）：确认 HTTP 搜索/详情 API 请求响应和权限契约后实现查询接口。
- [ ] TODO-07（对应 11.5.1）：完成 CLI 稳定性验证后，另行接入 `scripts/daily.bat` 并验证失败重试和日志。
- [ ] TODO-08（对应 4.1）：使用跨行业历史样本验证现金流率 `[-20%,50%]` 归一阈值及其区分度，再评估是否需要分行业 profile。
- [x] TODO-09（对应 4.1.1）：收入份额三年变化主路径、20 家 peer 门槛、不可用状态/可用权重覆盖、评分及映射版本已实现；定向测试覆盖20/19家样本和市值不变量。此项不代表历史样本区分度或 ROIC 备选已验收。
- [ ] TODO-10（对应 4.1.1）：用跨行业历史样本评估收入份额因子的覆盖率、区分度和权重；另行定义 ROIC 公式/来源及独立版本后再评审是否实现备选路径。
