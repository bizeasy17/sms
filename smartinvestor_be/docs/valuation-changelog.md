# 估值变更日志

先读总览：[docs/valuation-overview.md](docs/valuation-overview.md)

这份文档记录估值体系的重要功能变更，面向人工阅读。

如果你要看程序配置里的机器可读日志，可以同时参考：

- `static/valuation_config/valuation_defaults_CN.json` 中的 `changelog`
- `static/valuation_config/valuation_defaults_US.json` 中的 `changelog`

## Backlog

1. 估值模块拆分收尾：清理 `prediction/utils/prediction_util.py` 中历史估值实现，仅保留与 `prediction/utils/valuation_util.py` 的兼容导出。
2. 文档与示例路径统一：把估值入口说明从 `prediction/utils/prediction_util.py` 迁移到 `prediction/utils/valuation_util.py`。
3. 传统估值展示一致性（默认 vs 行业变体）继续优化：当默认与行业都具备三大核心法（PE/PB/PS）时，评估进一步统一组合展示口径，降低前端“默认/行业估值差几十倍”的感知落差，并补充可解释字段（如 `composite_mode`/核心方法清单）。
4. 预测信号跨报告期跳变诊断模板：补充单股 `Q1/H1/Q3/FY` 对照输出（`target_price/target_price_low/target_price_high`、`target_return_pct`、`pred_earnings_growth`、`signal_score`、`action/risk_level`、`quantitative_target.components`），并在前端文案明确“中枢目标价 vs 乐观上沿目标价”口径，避免将 `target_price_high` 误读为主目标价。

## 2026-04-18

## 2026-04-21

### 已实现：传统估值 summary 优化双轨输出与前台接入

本次把传统估值优化正式接入到后端 summary 层与前台展示层，目标不是改写单方法估值，
而是让 `composite/conservative/market_style` 在跨时间维度上更稳健，同时保留原值可解释性。

实现内容：

1. `api/views.py` 新增传统优化函数：

- `_compute_traditional_price_stats`
- `_compute_traditional_reliability_weight`
- `_apply_traditional_return_optimization`
- `_build_traditional_summary_optimized`

2. `get_stock_valuation_methods` 返回新增：

- `summary_optimized`
- `summary_normalized_to_latest_share_optimized`
- `summary_by_variant_optimized`
- `summary_by_variant_normalized_to_latest_share_optimized`

3. 选股结果接口同步返回：

- `composite_valuation_price_raw/optimized`
- `conservative_valuation_price_raw/optimized`
- 以及对应 return/gap/meta 字段

4. 前台已接入：

- 快览组件显示传统估值原值/优化值
- 选股结果页显示组合/保守估值原值/优化值

设计约束：

1. 单方法 `PE/PB/PS/PEG/FCFF/DDM` 保持原值，不做黑盒平滑。
2. 优化只发生在 summary 层，属于稳健性后处理。
3. 可靠度来自方法覆盖度、方法分歧与风险分，而不是照搬预测信号分数。

### 已实现：603799 传统优化双锚点验证脚本扩展

`tmp_huayou_603799_backtest.py` 现已同时输出传统估值优化前后结果，并对两套锚点给出稳定性代理指标：

1. `announcement`
2. `rolling`

新增导出字段：

1. `traditional_target_optimized`
2. `traditional_ret_pct_optimized`
3. `traditional_method_count`
4. `traditional_dispersion_ratio`
5. `traditional_reliability_weight`

新增控制台摘要指标：

1. `std`
2. `mean_abs_change`
3. `max_abs_change`
4. `directional_hit_rate`
5. `naive_ar1_rmse`

用途：后续每次调整 `TRADITIONAL_RETURN_*` 参数，都可以直接用同一脚本检查 announcement/rolling 是否同时变稳。

### 已实现：prefill 双桶落库与调度参数统一

本次针对“所有财报口径支持 formal + blended 共存”完成以下改造：

1. `prefillvaluationsnapshot` 新增 `--profit-buckets {auto,formal,blended,both}`，并支持 `both` 单次任务内双桶计算与写入。
2. `StockValuationSnapshot` upsert 冲突键与数据库唯一约束对齐，补入 `profit_data_source`，修复 `there is no unique or exclusion constraint matching the ON CONFLICT specification`。
3. 双桶同批写入增加批内冲突键去重，修复 `ON CONFLICT DO UPDATE command cannot affect row a second time`。
4. 调度任务 `valuation_snapshot_prefill`（`update_schedule_CN.json` 与 `updatevaluationconfigs.py` 默认模板）统一配置 `profit_buckets=both`。

影响：

1. 存储层可稳定承载 formal / blended 并存（按唯一键分桶）。
2. 实际是否形成双口径并存仍受 blended 资格约束；`both` 表示双桶尝试，不是每个键必然两条。

## 2026-04-14

### 已实现：market_style 估值流程文档化与口径收敛

本次围绕 market_style 的核心目标是三件事：

1. 手动补历史与定时刷新使用不同价格锚点，避免“历史回填逻辑”影响“日常贴盘”。
2. API 在财报过滤场景不再跨口径兜底注入 market_style。
3. UAT 日常调度增加周一/三/五全量刷新，保证非披露日也能随市场变动更新。

涉及文件：

1. `prediction/management/commands/prefillvaluationsnapshot.py`
2. `api/views.py`
3. `daily_valuation_due_runner.bat`
4. `valuation_full_refresh_135.bat`（UAT 新增）

#### A. market_style 估值链路（prefill）

`prefillvaluationsnapshot` 的执行链路（与 market_style 相关）如下：

1. 先用 `get_stock_valuation_snapshot` 获取利润口径、公告日期与基础估值输入。
2. 按 `price_anchor_mode` 决定估值价格锚点日期 `valuation_trade_date`：
	- `disclosure_aligned`：公告对齐（公告后首个交易日）；
	- `market_now`：直接使用刷新当日 `trade_date`；
	- `auto`：有强制财报期时走 `disclosure_aligned`，否则走 `market_now`。
3. 用同一个 `valuation_trade_date` 贯穿：
	- 快照查询（去重/存在性判断）
	- 估值计算（含 market_style）
	- `StockValuationSnapshot` 写入
	- `StockValuationSnapshotLatest.latest_trade_date` 更新

这一步保证“估值输入日期”和“入库日期”一致，不再出现口径错位。

#### B. 财报过滤下的 market_style 展示约束（API）

`get_stock_valuation_methods` 现在区分两种场景：

1. 无财报过滤（最新口径）：允许 market_style fallback 推断，用于增强可读性。
2. 有财报过滤（`earnings_report_type`/`valuation_fiscal_year`/`report_end_date`/`express_only`）：禁用 fallback，只展示该口径真实存在的 market_style 行。

修复前，“其他财报窗口也看到 market_style”主要来自 fallback 的跨口径注入；修复后该问题已收敛。

#### C. 本次确认的刷新策略

本次确定采用“双轨刷新”：

1. 披露增量刷新：保留 `earnings_refresh.bat` 的 `--refresh-policy disclosure`，用于处理新财报/快报发布。
2. 固定全量贴盘刷新（UAT）：新增 `valuation_full_refresh_135.bat`，仅在周一/三/五执行 `--refresh-policy all --price-anchor-mode market_now`，分前缀 `60/68/00/30/8` 全市场更新。

#### D. 验证结论（本次）

1. `prefillvaluationsnapshot --help` 已可见 `--price-anchor-mode {auto,disclosure_aligned,market_now}`。
2. `auto` 行为符合预期：
	- 常规刷新（无强制财报期）=> `market_now`
	- 指定财报期（如 FY 2024）=> `disclosure_aligned`
3. 财报过滤 API 验证通过：
	- 过滤口径下 `market_style` 不再跨期透出；
	- 最新口径仍可展示 market_style。

## 2026-03-24

## 2026-03-25

### 已实现：仅在 composite 层引入当前市值影响

为保持单方法可解释性，本次仅调整组合估值（composite）聚合，不改各单方法输出。

实现要点：

1. 在 `api/views.py` 的买点汇总逻辑中，先根据 `valuation_price + valuation_market_cap` 反推当前市值（中位数稳健聚合）。
2. 按当前市值区间映射温和系数（默认：小盘 1.05、中盘 1.02、大盘 0.99、超大盘 0.96）。
3. 仅对 `base_composite_price` 乘系数，得到新的 `composite_valuation_price`。
4. `conservative_valuation_price` 与单方法估值（`pe/pb/ps/fcff_dcf/ddm/peg/scarcity_overlay`）不受影响。
5. `buy_candidate_reason` 增加 `size_factor` 审计字段，便于回放。

影响：

1. 前台摘要中的组合估值价、组合偏离和相关打分会随市值分层轻微变化。
2. 保守估值与单方法展示保持原口径。

### 已实现：`scarcity-profile=auto` 四因子风险状态机（确认/冷却/熔断）

`estmktv` 的 `--scarcity-profile auto` 已从简化信号切换为四因子风险状态机，新增：

1. 风险分：`vol_z`、`risk_disp`、`data_gap`、`dd_z` 按 `risk_weights` 加权。
2. 反抖：`confirmation_days=3` 连续确认后才切档。
3. 冷却：切档后 `cooldown_days=5` 内抑制来回切换。
4. 缺失回退：因子不足时按 `missing_policy.fallback_profile` 回退（默认 `balanced`）。
5. 熔断：触发 `extreme_flags` 或 `extreme_risk_min` 后强制 `conservative`，持续 `force_days`。

配置文件：

1. `static/valuation_config/scarcity_auto_profile_CN.json`

配置项：

1. `risk_weights`
2. `thresholds`
3. `hysteresis`
4. `confirmation_days`
5. `cooldown_days`
6. `missing_policy`
7. `circuit_breaker`
8. `legacy_signal_weights`
9. `fallback_profile`

状态持久化：

1. `static/valuation_config/scarcity_auto_state_CN.json`

说明：

1. 状态按 `ts_code` 维护 `last_profile/pending_profile/pending_count/cooldown_until/force_conservative_until`。
2. `--show-source` 下会输出完整 auto 决策理由（风险分、阈值、滞回、状态机模式、因子可用性）。

### 已实现：`scarcity-profile=auto` 阈值与权重配置化

`estmktv` 的 `--scarcity-profile auto` 不再将阈值与权重硬编码在命令内部，而是改为读取配置文件：

1. `static/valuation_config/scarcity_auto_profile_CN.json`

配置项：

1. `signal_weights.score`
2. `signal_weights.confidence`
3. `thresholds.conservative_min`
4. `thresholds.balanced_min`
5. `fallback_profile`

说明：

1. 当配置缺失或字段异常时，命令会回落到内置默认值，保证运行稳定。
2. `--show-source` 下会打印 `signal/weights/thresholds` 组成的 auto 决策理由，便于审计与回放。

### 已实现：全量估值快照预热纳入 `scarcity_overlay` 入库

调度任务 `valuation_snapshot_prefill` 的默认 methods 已补充 `scarcity_overlay`，覆盖前缀批次：

1. `60`
2. `68`
3. `00`
4. `30`
5. `8`

影响：

1. `prefillvaluationsnapshot` 在全量预热时会把 `scarcity_overlay` 作为独立 `valuation_method` 写入 `StockValuationSnapshot` 与 `StockValuationSnapshotLatest`。
2. 使用 `updatevaluationconfigs --run-due` 执行到 `valuation_snapshot_prefill` 时，会自动携带该方法，无需额外手工传参。

### 已实现：`estmktv` 自动化稀缺性参数填补与 `auto` 档位

`estmktv` 新增两项能力：

1. `--scarcity-profile auto`：按 `score * confidence` 自动选择 `conservative / balanced / aggressive`。
2. 运行前自动补齐缺失的 `scarcity_kwargs` 关键键位（`enabled/beta/cap_pct/score/confidence/confidence_floor`）。

说明：

1. 该能力是运行时策略，不改模板文件。
2. 当 `--show-source` 打开时，会打印自动档位决策理由与自动补齐信息，便于审计。

### 已落地：航天装备Ⅲ（857411.SI）稀缺性参数校准（生产安全版）

本次将 857411.SI 的 `scarcity_kwargs` 明确落到模板配置中，采用保守默认：

1. `enabled=true`
2. `beta=0.35`
3. `cap_pct=30`
4. `confidence_floor=0.35`

目的：

1. 在保留稀缺性溢价表达能力的同时，限制过度放大风险。
2. 作为默认参数用于线上日常估值，不追求一次性补齐市场缺口。

### 已实现：estmktv 增加 `--scarcity-profile` 运行时覆盖能力

管理命令 `estmktv` 新增参数：

1. `--scarcity-profile conservative`
2. `--scarcity-profile balanced`
3. `--scarcity-profile aggressive`
4. `--scarcity-profile off`

说明：

1. 该参数为“运行时覆盖”，不改静态模板文件。
2. 覆盖会统一作用于单行业、业务匹配、多行业回退等分支，便于 A/B 对比。
3. 配合 `--show-source` 可打印生效的 `scarcity_kwargs`。

### 已执行：申万参数全量重建并补齐行业稀缺默认值

本次执行了全量参数重建：

1. `python manage.py syncswvaluation --params-only --progress-every 20`

重建后发现 L2 层有 4 个行业未携带 `scarcity_kwargs`（聚合子行业不足场景），已补齐默认值：

1. `801045.SI`（特钢Ⅱ）
2. `801217.SI`（本地生活服务Ⅱ）
3. `801768.SI`（社交Ⅱ）
4. `801786.SI`（其他银行Ⅱ）

补齐口径：

1. `enabled=true`
2. `beta=1.0`
3. `cap_pct=80.0`
4. `confidence_floor=0.35`

最终覆盖率：

1. L1: 31/31
2. L2: 134/134
3. L3: 337/337

## 2026-03-23

### 已实现：历史锚点分量估值按 `valuation_variant` 独立落库

为解决“原始 PE/PB/PS 与历史锚点 PE/PB/PS 无法并排对比”的问题，已实现按参数签名区分 variant 的落库策略。

实现内容：

1. 在 `prediction/utils/prediction_util.py` 中，为历史锚点估值生成参数签名（示例：`hist_y3-5-10_q50_m120`）。
2. 在 `estimate_all_supported_methods` 中，除保留 `sw_history` 聚合结果外，新增输出历史锚点分量行（`pe`/`pb`/`ps`）并携带签名 `valuation_variant`。
3. `api/views.py` 与 `prefillvaluationsnapshot.py` 的变体解析逻辑升级为“优先使用行内显式 `valuation_variant`”，保证历史分量行不会被折叠为 `default`。
4. `validation_loader` 允许模板透传 `sw_history_kwargs`，用于统一管理历史窗口与分位参数。

效果：

1. 同一 `valuation_method`（如 `pe`）可同时存储 `default` 与历史签名 variant。
2. 支持按 `valuation_method + valuation_variant` 进行查询、审计和对比回测。

### 已修复：`valuation_variant` 的 NaN/空值归一化

为避免部分 DataFrame 行把缺失变体误写成字符串 `nan`，本次补充了统一归一化规则：

1. 在 API 估值读取路径中，对 `valuation_variant` 做 `NaN/空值 -> default` 归一化。
2. 在预热命令去重与落库前，同样执行 `NaN/空值 -> default` 归一化。
3. 对 `pe/pb/ps` 的 API 展示口径，默认仅读取 `default` variant；`sw_history` 仍使用历史签名 variant。

效果：

1. 避免出现 `nan` 变体键。
2. 保证 `default` 与 `hist_...` 分支稳定可区分，且不互相污染。

### 已实现：SW 历史分位锚点 MVP（低耦合）

已完成 MVP 代码实现，核心目标是尽量减少与原有估值逻辑的耦合，便于 UAT 部署和迁移到独立估值项目。

实现内容：

1. 新增独立服务模块 `prediction/services/sw_history_quantiles.py`，封装 `sw_daily` 历史分位计算。
2. 在 `syncswvaluation` 链路中按可选开关接入历史锚点（默认开启），支持 3Y/5Y/10Y 窗口。
3. 在行业参数生成中，PE/PB 目标改为融合：行业横截面目标 + 历史分位锚点 + global_defaults 基线（并保留边界约束）。
4. 输出结构新增 `history_quantiles`、`history_anchors` 和 `target_source`，用于审计与回溯。
5. 新增命令参数：`--disable-history-anchors`、`--history-years`、`--history-quantile`、`--history-min-samples`。

说明：

1. 本次为 MVP，优先覆盖 PE/PB。
2. 设计上保持低耦合，历史分位能力可独立迁移，不影响既有估值接口使用方式。

### 规划项：引入 SW 历史分位锚点到行业估值目标参数

本次记录一个已确认的后续增强项（尚未实施代码变更）：

1. 使用 Tushare Pro 的 `sw_daily` 作为行业历史估值时间序列入口。
2. 为行业估值目标增加 3Y / 5Y / 10Y 历史分位锚点（重点 PE、PB，可选 PS）。
3. 将历史分位锚点与现有“行业横截面参数 + global_defaults 基线”进行融合，并继续保留上下限约束。

目的：

1. 降低市场整体高估或低估对行业目标参数的顺周期放大效应。
2. 提升行业估值目标在不同市场阶段的稳定性和可解释性。
3. 为 UAT 与独立估值项目同步提供统一变更记录入口。

### 公司表新增 SW 三级行业维护字段

本次变更为公司主表 `Corporation` 增加了两列：

- `sw_l3_code`
- `sw_l3_name`

目的：

1. 在公司表直接维护申万三级行业信息。
2. 让“原有行业字段 `industry`”和“SW 三级行业字段”能够长期并存。
3. 为后续行业映射、差异对账、规则修正和筛选逻辑统一提供稳定落点。

相关改动：

- 新增模型字段：`datastore/models.py`
- 新增迁移：`datastore/migrations/0011_corporation_sw_l3_fields.py`
- 新增同步命令：`python manage.py synccorporationsw`

### 新增 synccorporationsw 同步命令

新增管理命令 `synccorporationsw`，用于把：

- `static/valuation_config/sw_industry_mapping_CN.json`

中的股票到 SW 三级行业映射，批量回填到 `Corporation.sw_l3_code / sw_l3_name`。

支持能力：

- 单票同步：`--tscode`
- 预演模式：`--dry-run`
- 映射缺失时清空：`--clear-missing`
- 批量更新：`--batch-size`

这意味着后续可以直接基于数据库做如下工作：

1. 对比 `Corporation.industry` 与 `Corporation.sw_l3_name`
2. 导出行业差异 CSV
3. 建立传统行业和申万行业之间的映射规则
4. 在选股、估值、回测中复用统一行业口径

## 2026-03-13

### CN 本地化估值默认参数初始化

初始化了 A 股本地化估值默认参数：

- 调整了主要行业的估值倍数目标
- 调整了折现率和终值增长率路径
- 使默认参数更适合 A 股市场环境

对应机器日志位置：

- `static/valuation_config/valuation_defaults_CN.json`

## 使用建议

当后续估值逻辑发生以下类型变更时，建议同步更新本文件：

1. 行业模板生成逻辑变化
2. 快报/快照/缓存口径变化
3. 估值方法或权重体系变化
4. 公司表、行业表、SW 映射关系的结构变化
5. 影响选股结果解释口径的字段变化