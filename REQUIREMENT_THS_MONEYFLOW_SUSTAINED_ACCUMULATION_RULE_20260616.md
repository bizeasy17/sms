# THS 资金流“持续建仓”判定规则需求（DEV）

- 日期：2026-06-16
- 环境：DEV first
- 范围：THS 资金流评分（N 类）

## 1. 目标

在现有 `moneyflow_cnt_ths` 评分体系上，新增“持续建仓”判定层，避免仅靠单一 30 日净流入导致的误判。

## 2. 业务定义

“持续建仓”采用分层确认：

1. 短周期（10 交易日）判断“是否启动”。
2. 中周期（30 交易日）判断“是否持续”。
3. 长周期（60 交易日）判断“是否成趋势”。

## 3. 指标口径

基于同一行业 `industry_code` 的日频 `net_amount`（已在本地快照中标准化）计算：

1. `mf_10_sum`: 最近 10 个交易日净流入和。
2. `mf_30_sum`: 最近 30 个交易日净流入和。
3. `mf_60_sum`: 最近 60 个交易日净流入和。
4. `mf_10_pos_days`: 最近 10 日 `net_amount > 0` 的天数。
5. `mf_30_pos_days`: 最近 30 日 `net_amount > 0` 的天数。
6. `mf_60_slope`: 最近 60 日累计净流入序列的一阶线性斜率（正值视为趋势向上）。

## 4. 判定规则（建议默认）

### 4.1 启动（start_signal）

满足以下全部条件：

1. `mf_10_sum > 0`
2. `mf_10_pos_days >= 6`

### 4.2 持续（sustain_signal）

满足以下全部条件：

1. `mf_30_sum > 0`
2. `mf_30_pos_days >= 16`
3. `mf_30_sum >= mf_10_sum * 1.2`（避免短脉冲）

### 4.3 趋势（trend_signal）

满足以下全部条件：

1. `mf_60_sum > 0`
2. `mf_60_slope > 0`

### 4.4 综合标签

1. 若 `start_signal=false` -> `accumulation_level = NONE`
2. 若 `start_signal=true` 且 `sustain_signal=false` -> `accumulation_level = EARLY`
3. 若 `sustain_signal=true` 且 `trend_signal=false` -> `accumulation_level = SUSTAINING`
4. 若 `sustain_signal=true` 且 `trend_signal=true` -> `accumulation_level = STRONG`

## 5. 与现有评分结合

在原有总分基础上新增 `accumulation_bonus`：

1. `NONE`: +0
2. `EARLY`: +2
3. `SUSTAINING`: +5
4. `STRONG`: +8

最终分：

`score_total_v2 = min(100, score_total_v1 + accumulation_bonus)`

说明：不改原始分项（moneyflow/position/volatility）计算口径，仅追加可解释的趋势加分。

## 6. 接口与输出变更

对 `industry-universe/moneyflow/latest/` 的 `data[]` 增加字段：

1. `accumulation_level`
2. `accumulation_bonus`
3. `accumulation_signals`:
   - `start_signal`
   - `sustain_signal`
   - `trend_signal`
4. `accumulation_metrics`:
   - `mf_10_sum`
   - `mf_30_sum`
   - `mf_60_sum`
   - `mf_10_pos_days`
   - `mf_30_pos_days`
   - `mf_60_slope`

并在 `meta` 增加：

1. `scoring_version` 升级为 `ths_moneyflow_v2`
2. `accumulation_rule_version`

## 7. 验证标准

1. 命令可运行：
   - `manage.py refresh_ths_moneyflow_score_monthly --ths-index-type N`
2. 接口可返回新增字段，且老字段兼容。
3. 随机抽样 20 个行业，人工复核判定逻辑与公式一致。

## 8. 风险与回滚

1. 风险：短期数据异常导致误判。
2. 缓解：保留 `score_total_v1` 与 `score_total_v2` 双字段一段时间。
3. 回滚：配置开关关闭 `accumulation_bonus`，回退到 v1。

## 9. 待确认项（请确认）

1. 服务归属是否确认由 `smartinvestor_be` 实现（命令 + latest 接口）？
2. 默认阈值是否采用本稿（6/10、16/30、60日斜率>0）？
3. 加分档位是否采用 `0/2/5/8`？
4. 是否只在 N 类型启用（与当前策略一致）？
