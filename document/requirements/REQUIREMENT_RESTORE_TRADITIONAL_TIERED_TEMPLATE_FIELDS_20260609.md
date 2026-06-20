# REQUIREMENT_RESTORE_TRADITIONAL_TIERED_TEMPLATE_FIELDS_20260609

## 1. 背景
- 当前 UAT 前端 `估值一览 -> 传统估值 -> 三档估值+仓位` 依赖后端字段：
  - `traditional_tiered_template`
  - `traditional_tiered_template_by_variant`
- 现网接口 `GET /api/stocks/{ts_code}/valuation/methods/`（UAT 5001）未返回上述字段，导致前端进入 fallback 模板逻辑。

## 2. 服务归属确认
- 变更服务：`smartinvestor_be`
- 变更接口：`GET /api/stocks/{ts_code}/valuation/methods/`
- 变更文件：`smartinvestor_be/api/views.py`

## 3. 需求目标
- 在当前 `views.py` 版本接口返回中补齐：
  - `traditional_tiered_template_by_variant`
  - `traditional_tiered_template`
- 保证字段缺失时前端仍可 fallback，不破坏兼容。

## 3.1 阶段二目标（权威口径）
- 后端返回值应由后端三档模板逻辑直接计算，不以“前端 fallback 对齐”为目标。
- 三档模板计算口径包含：
  - 风格识别（growth/stable/balanced）
  - 模板权重与区间倍率
  - 方法价 winsor 截尾
  - 单调性修正（conservative <= balanced <= aggressive）
  - 波动分层仓位建议
- 前端仅展示后端模板，fallback 只保留兜底角色。

## 3.2 阶段三目标（行业状态化三档）
- 以 `business_match` 行业变体为核心驱动三档估值，而非仅使用统一风格模板。
- 对不同产业状态应用差异化三档规则：
  - 高成长（如半导体、光电通信）
  - 平衡发展
  - 稳健价值
  - 周期资源（如化工、有色、煤炭等）
- 每个状态至少同时差异化以下维度：
  - 方法权重矩阵（conservative/balanced/aggressive 三套）
  - 三档最小间距规则（tier gap）
  - 区间倍率（range multiplier）
  - 仓位建议策略（position guidance）
- 最终输出保持接口兼容（字段不删），新增解释字段用于可审计。

## 3.3 设计原则
- 业务一致性：同一股票在同一请求下，三档由单一后端规则计算并稳定复现。
- 行业优先：行业状态判定优先使用行业编码映射（SW L1/L2/L3），关键词仅作为兜底。
- 多变体稳健：先按每个行业变体计算三档，再按置信度加权汇总为顶层三档。
- 可解释：返回状态判定依据、变体权重、间距修正前后值。
- 安全降级：在低覆盖、低置信度、高分歧时自动切保守状态并扩大安全边际。

## 3.4 规则模型设计
### 3.4.1 行业状态判定（Regime Resolver）
- 输入：
  - `valuation_variant`（含 business_match 的行业层级/行业代码/行业名称）
  - 指标画像（roe、gross_margin、debt_to_assets 等）
  - 方法可用性与离散度（method coverage + dispersion）
- 输出：
  - `selected_regime`（high_growth/balanced/stable_value/cyclical_resource）
  - `regime_confidence`（0-1）
  - `regime_reasons`（命中规则与分数贡献）

### 3.4.2 Regime 参数模板（Template Packs）
- 每个 regime 内定义：
  - 三档方法权重矩阵
  - 三档最小间距基准（down/up gap）
  - 波动调整因子（high/medium/low）
  - 区间倍率
  - 仓位建议映射
- 现有 `TRADITIONAL_TIER_SCHEMES` 与 `TRADITIONAL_TIER_MIN_GAP_RULES` 继续保留，扩展为 regime 级配置源。

### 3.4.3 多变体汇总（Variant Blend）
- 对每个变体先独立计算三档：`template_by_variant[variant]`。
- 变体权重建议：
  - `variant_weight = match_score_norm * data_quality_weight * coverage_weight`
- 顶层三档：
  - 对各变体三档目标价按 `variant_weight` 加权求和。
  - 之后执行单调约束与最小间距约束。

### 3.4.4 风险降级策略（Guardrails）
- 若任一条件满足则触发降级：
  - `regime_confidence < 阈值`
  - `valid_method_count < 阈值`
  - `dispersion > 阈值`
- 降级动作：
  - regime 向 `stable_value`/`balanced` 回退
  - 增大 conservative 安全边际
  - 收缩 aggressive 推荐仓位上限

## 3.5 接口返回设计（兼容+增量）
- 保留现有字段：
  - `traditional_tiered_template`
  - `traditional_tiered_template_by_variant`
- 在模板对象内新增解释字段（增量，不破坏旧前端）：
  - `selected_regime`
  - `regime_confidence`
  - `regime_reasons`
  - `variant_weights`
  - `tier_spacing`（已含 before/after）
  - `downgrade_applied` / `downgrade_reason`

## 3.6 配置化与可运营性
- 建议新增配置文件（后续可热更新）：
  - `smartinvestor_be/static/valuation_config/traditional_regime_rules_CN.json`
- 内容包含：
  - 行业编码映射（SW code -> regime）
  - regime 参数包
  - 降级阈值
- 代码内常量保留为默认值，配置加载失败时安全回退。

## 3.7 分阶段实施计划
1. Phase A（低风险）
- 引入行业编码映射优先级，稳定 `selected_regime`。
- 保持单变体计算路径不变。

2. Phase B（核心）
- 打通多变体三档计算与顶层 blend。
- 增加 `variant_weights` 和 `regime_confidence` 返回。

3. Phase C（校准）
- 基于历史样本按行业回测，校准：
  - regime 阈值
  - gap 参数
  - 仓位建议阈值
- 输出校准报告到 `docs/`。

## 3.10 实施状态（2026-06-09）
- Phase A 已实现（UAT）：
  - 在 `smartinvestor_be/api/views.py` 新增 industry-code-first 判定规则（`TRADITIONAL_REGIME_CODE_RULES`）。
  - `traditional_tiered_template` 构建时新增 `industry_code` 入参，并优先基于行业编码命中 regime。
  - 命中依据写入 `style_reasons`（如 `industry_code_prefix=80108`）。
  - 保持接口兼容：原字段不删除，仅增强判定逻辑。
- 函数级验证样例：
  - `801080.SI` -> `high_growth`
  - `801030.SI` -> `cyclical_resource`
  - `801780.SI` -> `stable_value`

- Phase B 已实现（UAT）：
  - 顶层 `traditional_tiered_template` 改为按 `traditional_tiered_template_by_variant` 做多变体加权融合。
  - 新增融合解释字段：
    - `variant_weights`
    - `variant_weights_detail`
    - `blend`（applied/dominant_variant/active_variant/variant_count）
  - 融合后仍执行单调约束 + 最小间距约束 + 仓位建议重算。
  - `traditional_tiered_template_by_variant` 保持原样，保证兼容与可追溯。

- Frontend 接入调整（UAT）：
  - `StockValuationQuickView` 的三档模板选择优先级调整为：
    1) `traditional_tiered_template`（顶层融合）
    2) `traditional_tiered_template_by_variant[active_variant]`
    3) 前端 fallback
  - 在“三档估值+仓位”区域新增小字号融合说明（dominant_variant + top 权重预览），用于解释当前三档来源。

## 3.11 预测三档范围收敛（2026-06-10）
- 仅实现：`行业编码 -> regime` 映射，并作用于预测三档风格判定。
- 不实现：
  - 预测行业变体融合（预测链路当前无行业变体输入）
  - 预测 `variant_weights/blend` 解释层
- 目标：
  - 保持预测三档现有输入结构不变（以 signal-compare/earnings payload 为主）
  - 在有行业编码时，预测三档 styleKey/styleLabel 优先由行业regime确定
  - 行业编码缺失时，回退现有可信度分层逻辑（high_confidence/balanced/low_confidence）

## 3.12 预测三档实现建议（最小改动）
- 位置：`smartinvestor_fe/src/components/StockValuationQuickView.vue`（当前预测三档主要在 `predictiveTieredTemplate` computed 内生成）
- 输入来源：
  - 优先从 `active variant` 元数据或传统模板里读取 `industry_code`
  - 与传统三档共用行业编码前缀映射（保持一致）
- 规则：
  - 命中高成长编码：预测 styleKey 置为 `high_confidence`（或映射标签 `growth_regime`）
  - 命中稳健编码：预测 styleKey 下调到 `balanced/low_confidence` 区间
  - 命中周期编码：预测 styleLabel 显示周期风格，并调整目标混合系数（mix）及仓位建议阈值
- 回退：无行业编码或无法命中时沿用现有信号分逻辑。

## 3.13 预测三档验收（本阶段）
- 仅校验风格映射是否生效，不要求预测融合权重字段。
- 样本检查：
  - 半导体/光通信样本：style 应偏成长
  - 化工样本：style 应偏周期
- 兼容性：
  - 不影响预测接口字段与旧前端渲染路径。

## 3.14 全局收敛目标：消除 industry_regime=none（2026-06-10）
- 目标：
  - 对预测三档 fallback 路径，尽量实现“有行业编码即有regime”；避免仅靠个股打补丁。
- 范围：
  - UAT `smartinvestor_fe/src/components/StockValuationQuickView.vue`
  - 不新增预测行业变体融合，不修改预测接口结构。

## 3.15 统一映射策略（全局）
- 单一规则源：
  - 前端预测 fallback 的 `PREDICTIVE_REGIME_CODE_RULES` 与后端传统 `TRADITIONAL_REGIME_CODE_RULES` 前缀集合保持一致（按 regime 语义映射）。
- 规则扩展（最小必要）：
  - growth：补齐 `8515`、`8517`（与后端 high_growth 对齐）
  - cyclical：保留并补齐后端已有 80102/80103/.../80121 与 8503x 关键前缀
  - defensive：补齐后端 stable_value 对应前缀（80178/80179/80188/80195/80196 等）
- 回退策略：
  - 有编码且命中：直接使用映射结果
  - 有编码但未命中：
    - 将 `industry_regime` 标记为 `balanced`（不再返回 none），同时在 reasons 记录 `industry_regime=fallback_balanced`
  - 无编码：沿用信号分阈值逻辑，并记录 `industry_code=-`

## 3.16 验收标准（全局）
- 对存在行业编码的样本，`reasons` 中不再出现 `industry_regime=none`。
- 典型样本：
  - 8515xx/8517xx -> growth
  - 8503xx/8010x资源链 -> cyclical
  - 80178/80179/80188/80195/80196 -> defensive
- 兼容性：
  - 预测模板结构不变；仅 styleKey/styleLabel/reasons 可能变化。

## 3.17 全行业覆盖目标（传统+预测统一）
- 用户目标：行业映射不再依赖“少量前缀白名单”，而是覆盖 SW 行业全集；传统估值与预测估值共用同一套映射结果。
- 覆盖定义：
  - 以 `smartinvestor_be/static/valuation_config/sw_industry_mapping_CN.json`（SW2021）作为行业全集来源。
  - 对有行业编码的样本，必须可稳定得到 regime（或明确降级原因），不允许“未知但无解释”。

## 3.18 统一规则源与所有权
- 服务所有权（建议）：
  - 由 `smartinvestor_be` 统一实现行业编码标准化与 regime 映射。
  - `smartinvestor_fe` 不再维护独立 regime 前缀表，只消费后端返回的 regime/原因字段。
- 单一规则源：
  - 后端读取 SW 行业全集，并维护“行业码/指数码 -> regime”映射表。
  - 传统三档与预测三档均调用同一后端映射函数，避免规则漂移。

## 3.19 映射生成逻辑（全覆盖）
- 输入：
  - 行业标识候选：`industry_code`、`index_code`（如 `801xxx.SI`）、历史兼容码（如 `85xxxx.SI`）。
- 标准化：
  - 去后缀、提取数字主码、统一长度与父级回溯（L3 -> L2 -> L1）。
- 规则优先级：
  1) 显式映射表精确命中（code/index）
  2) 父级行业回溯命中（利用 SW 层级 parent_code）
  3) 行业名称关键词规则命中
  4) 仍未命中则标记 `fallback_balanced`，并输出 `fallback_reason`
- 输出：
  - `selected_regime`、`regime_source`（exact/parent/keyword/fallback）、`regime_reason`。

## 3.20 传统与预测应用路径
- 传统估值：
  - 复用统一映射函数，替换/兼容现有 `TRADITIONAL_REGIME_CODE_RULES` 前缀逻辑。
- 预测估值：
  - 优先消费后端返回的 `selected_regime`；仅在后端缺失时才前端兜底。
  - 前端兜底逻辑降到最小，并与后端字段一致展示原因。

## 3.21 验收与测试（全覆盖）
- 覆盖率测试：
  - 用 SW 映射全集跑批，输出 `mapped_count/total_count/mapped_ratio`。
  - 验收阈值：`mapped_ratio = 100%`（有编码集合）；未命中必须带 `fallback_reason`。
- 一致性测试：
  - 同一行业编码在传统与预测路径返回同一 `selected_regime`。
- 回归样本：
  - 成长、周期、防守、边缘编码（历史85码）各至少 10 例。

## 3.22 风险与回滚（全覆盖）
- 风险：
  - SW 源数据更新导致 regime 抖动；需版本化映射并记录 `mapping_version`。
- 回滚：
  - 回滚到上一版映射快照（配置级回滚），不回退接口字段。

## 3.23 建议映射表接入（2026-06-10）
- 新增规则源优先级：
  1) `smartinvestor_be/static/regime_mapping_suggested_v1.csv` 的 `suggested_regime`
  2) SW 全量映射 + 前缀/关键词/继承逻辑
- 约束：
  - 仅当 `suggested_regime` 属于 `{high_growth, stable_value, cyclical_resource, balanced}` 时生效。
  - 覆盖键同时支持 `index_code` 与 `industry_code`（统一数字化后匹配）。
- 可解释性：
  - reason 标注为 `suggested_v1:<regime>`。

## 3.24 tmp 归档与约定（2026-06-10）
- 目录约定：
  - `smartinvestor_be/tmp/` 作为唯一临时脚本与中间文件目录。
  - 根目录历史 `tmp*`、`.tmp*`、`__tmp*`、`_tmp*` 文件归档到 `smartinvestor_be/tmp/archive_root_20260610/`。
- 后续规范：
  - 新生成临时文件统一放在 `smartinvestor_be/tmp/` 下，不再放仓库根目录。

## 3.8 验收标准（阶段三）
- 行业差异化：
  - 半导体/光电通信样本应稳定命中 `high_growth`。
  - 化工样本应稳定命中 `cyclical_resource`。
- 三档有效分离：
  - `conservative < balanced < aggressive` 且最小间距满足 regime 规则。
- 可解释性：
  - 返回中可见 `selected_regime/regime_confidence/variant_weights/tier_spacing`。
- 兼容性：
  - 老前端仅读取原字段时不报错。

## 3.9 回滚策略
- 配置层回滚：禁用 regime 配置，回退到内置 balanced 默认模板。
- 逻辑层回滚：关闭多变体 blend，仅保留当前单变体模板输出。

## 4. 实现约束
- 不调整既有 `summary`/`summary_by_variant` 计算口径。
- 使用最小改动，避免影响选股接口与预测接口。
- 模板计算迁移为后端权威规则，前后端一致性由“同一后端输出”保证。

## 5. 验收标准
- 请求：
  - `/api/stocks/301080.SZ/valuation/methods/?freq=D&valuation_band_pct=0.1&earnings_report_type=Q1`
- 返回顶层包含：
  - `traditional_tiered_template`
  - `traditional_tiered_template_by_variant`
- 三档数值可复现当前前台值：
  - conservative: 24.57
  - balanced: 33.15
  - aggressive: 35.80
- 不影响既有字段结构（老字段保持可用）。

## 6. 风险与回滚
- 风险：模板字段新增后，若下游严格 schema 校验，可能需要同步白名单。
- 回滚：仅回滚 `views.py` 新增模板字段逻辑与返回字段。
