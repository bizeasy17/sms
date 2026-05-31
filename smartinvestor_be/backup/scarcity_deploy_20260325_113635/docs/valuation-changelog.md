# 估值变更日志

先读总览：[docs/valuation-overview.md](docs/valuation-overview.md)

这份文档记录估值体系的重要功能变更，面向人工阅读。

如果你要看程序配置里的机器可读日志，可以同时参考：

- `static/valuation_config/valuation_defaults_CN.json` 中的 `changelog`
- `static/valuation_config/valuation_defaults_US.json` 中的 `changelog`

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