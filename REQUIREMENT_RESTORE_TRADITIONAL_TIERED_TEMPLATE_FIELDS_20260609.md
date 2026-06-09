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
