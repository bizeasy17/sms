# REQUIREMENT_THS_MONEYFLOW_RANKING_TAB_20260616

## 1. 背景
- 当前行业页已经支持 THS 行业列表与行业轮动展示。
- TuShare 提供 `moneyflow_cnt_ths`，可获取 THS 板块维度资金流数据。
- 现阶段仅 THS 有该资金流接口，SW/其他行业类型暂无等价来源。

## 2. 目标
- 建立一个仅面向 THS 行业的简单评分模型，核心由三类因子构成：
  - 30 日资金流
  - 位置
  - 波动率
- 资金流数据先入库，支持每日同步更新。
- 评分任务按月运行，输出 TopN THS 板块排名。
- 前端在行业页新增一个 Tab，放在“行业轮动”之后，展示资金流评分榜单（交互风格与行业轮动一致）。

## 3. 范围
- 数据侧：THS 板块资金流的日增量同步与本地持久化。
- 计算侧：月度评分与 TopN 排名结果快照。
- 展示侧：行业页新增“资金流评分”Tab（仅 THS 下显示/生效）。

## 4. 非目标
- 不扩展到 SW、行业变体、基本信息行业。
- 不做复杂机器学习模型，仅做规则评分。
- 不在本期实现实时分钟级刷新。

## 5. 服务归属（待你确认）
- 建议服务归属：
  - 数据同步与评分计算：smartinvestor_be
  - 页面展示：smartinvestor_fe
- 本功能默认不依赖额外新服务，不跨仓新增中台。

## 6. 数据与存储设计（草案）

### 6.1 数据源
- TuShare: `moneyflow_cnt_ths`
- 主键建议：`trade_date + ts_code(板块代码)`

### 6.2 入库策略
- 每日任务：拉取当日（或最近交易日）增量并 upsert。
- 回补策略：支持按日期范围补拉（命令行参数）。
- 数据去重：按唯一键 upsert，避免重复写入。

### 6.3 建议表结构（草案）
- 表名建议：`ThsIndustryMoneyflowDaily`
- 字段建议：
  - `trade_date` (date, index)
  - `industry_code` (varchar, index)
  - `industry_name` (varchar)
  - `net_amount` / `net_pct`（按 TuShare 实际字段对齐）
  - `raw_payload` (json, 可选)
  - `updated_at`
- 约束建议：`unique(trade_date, industry_code)`

### 6.4 评分结果快照表（草案）
- 表名建议：`ThsIndustryMoneyflowScoreSnapshot`
- 字段建议：
  - `run_id` (varchar, index)
  - `asof_date` (date, index)
  - `industry_code` (varchar, index)
  - `industry_name` (varchar)
  - `score_total` (float)
  - `score_moneyflow_30d` (float)
  - `score_position` (float)
  - `score_volatility` (float)
  - `rank` (int)
  - `created_at`

## 7. 评分模型（V1 草案）

### 7.1 因子定义
1. 30 日资金流因子
- 统计最近 30 个交易日资金流累计值（或累计占比）。
- 横截面标准化为 0-100 分（分位或 min-max）。

2. 位置因子
- 用板块 close 相对最近 N 日区间位置表示（建议 N=60）。
- 位置定义示例：
  - `position = (close - rolling_low) / (rolling_high - rolling_low)`
- 再映射到 0-100 分。

3. 波动率因子
- 用近 30/60 日收益率波动率。
- 波动率越低分越高（反向映射）。

### 7.2 总分公式（初版）
- 建议权重：
  - 30 日资金流：0.50
  - 位置：0.30
  - 波动率：0.20
- `score_total = 0.50 * moneyflow_score + 0.30 * position_score + 0.20 * volatility_score`

### 7.3 排名输出
- 每次月度任务输出 TopN（默认 N=20，可配置 10/20/50）。

## 8. 调度与任务

### 8.1 每日任务
- 新增 daily 步骤：同步 THS moneyflow 日数据。
- 失败策略：记录错误并可重试，不影响其他步骤。

### 8.2 每月任务
- 新增 monthly 步骤：执行评分并生成 run 快照。
- 输出落盘（json）+ 入库（快照表）。

## 9. API 契约（草案）

### 9.1 获取最新评分榜
- `GET /api/industry-universe/moneyflow/latest/`
- Query:
  - `top_n` (optional, default 20)
  - `market` (default CN)
  - `industry_type` 固定/默认 `ths`
- Response（示例字段）:
  - `data[]`: `industry_code`, `industry_name`, `score_total`, `score_breakdown`, `rank`, `asof_date`
  - `meta`: `run_id`, `generated_at`, `top_n`, `total_candidates`, `scoring_version`

### 9.2 触发重算（可选）
- `POST /api/industry-universe/moneyflow/recompute/`
- Body:
  - `top_n` (optional)
  - `market` (optional)
- 仅管理用途，前端可先不暴露。

### 9.3 Run 历史（可选）
- `GET /api/industry-universe/moneyflow/runs/`
- `GET /api/industry-universe/moneyflow/runs/{run_id}/`
- 与行业轮动 run 展示风格保持一致。

## 10. 前端交互（草案）
- 页面：行业页（SwIndustryView）
- Tab：在“行业轮动”之后新增“资金流评分”Tab。
- 仅当 `selectedIndustryType === 'ths'` 时有效展示。
- 列表项信息：
  - 行业名称/代码
  - 综合分
  - 三因子分项
  - 近 30 日资金流关键指标（可选）
- 点击某个板块后：
  - 复用现有行业选中逻辑，联动中栏历史图与右栏成分股。

## 11. 配置项（草案）
- `THS_MONEYFLOW_SYNC_ENABLED` (bool)
- `THS_MONEYFLOW_SCORE_ENABLED` (bool)
- `THS_MONEYFLOW_TOPN_DEFAULT` (int, default 20)
- `THS_MONEYFLOW_LOOKBACK_DAYS` (int, default 30)
- `THS_MONEYFLOW_SCORE_WEIGHTS` (json or separate floats)

## 12. 验收标准
- 每日任务可将 THS moneyflow 数据增量写入本地库。
- 每月任务可生成评分 run，且能查询 TopN。
- 行业页在 THS 下新增 Tab 可正常展示榜单。
- 点击榜单项可联动现有历史图和成分股区域。
- 非 THS 行业类型不受影响。

## 13. 风险与回退
- 风险：TuShare 接口限流/字段变动导致同步中断。
- 风险：历史窗口不足时评分不稳定。
- 回退：
  - 关闭新 Tab 开关。
  - 停用新调度步骤，不影响既有行业轮动链路。

## 14. 待你确认（进入开发前必答）
1. 服务归属是否确认：`smartinvestor_be`（数据同步+评分）与 `smartinvestor_fe`（展示）？
2. 评分权重是否确认使用 `0.50 / 0.30 / 0.20`？
3. TopN 默认值是否确认 20？
4. 月度任务是否固定放在现有 `monthly.bat` 中执行？
5. 是否需要同时提供 run 历史查询接口（还是先只做 latest）？

## 15. V2 同步补充（2026-06-16）

- 变更来源：将 DEV 已验证的 THS moneyflow v2 评分逻辑同步到 UAT。
- 同步目标：`smartinvestor_be` 的 moneyflow 评分函数与 latest 接口 meta。

### 15.1 新增持续建仓判定（仅 N 类型启用）

1. 启动信号（10日）：`mf_10_sum > 0` 且 `mf_10_pos_days >= 6`
2. 持续信号（30日）：`mf_30_sum > 0` 且 `mf_30_pos_days >= 16` 且 `mf_30_sum >= mf_10_sum * 1.2`
3. 趋势信号（60日）：`mf_60_sum > 0` 且 `mf_60_slope > 0`

### 15.2 标签与加分

- `NONE`: +0
- `EARLY`: +2
- `SUSTAINING`: +5
- `STRONG`: +8

### 15.3 输出兼容策略

1. 保留原始口径：`score_total_v1`
2. 新增升级口径：`score_total_v2`
3. 对外 `score_total` 映射为 `score_total_v2`
4. `meta.scoring_version` 升级为 `ths_moneyflow_v2`
5. `meta` 新增 `accumulation_rule_version`

### 15.4 验证步骤

1. 执行：`manage.py refresh_ths_moneyflow_score_monthly --top-n 20 --lookback-days 30 --ths-index-type N`
2. 访问 latest 接口，确认 `meta.scoring_version=ths_moneyflow_v2`
3. 样本行业核对新增字段：
  - `accumulation_level`
  - `accumulation_bonus`
  - `accumulation_signals`
  - `accumulation_metrics`

### 15.5 前台刷新体验优化（2026-06-16）

1. moneyflow 与 rotation 的刷新按钮显示 loading 状态。
2. 刷新过程列表区域展示 skeleton，占位完成后再渲染新列表。
3. 刷新请求附加 `_ts` 参数，降低中间层缓存导致的“看起来未刷新”问题。
4. 前端加入请求令牌，避免慢请求回包覆盖较新一次刷新结果。

### 15.6 成分为空板块排除（2026-06-16）

- 规则：若 THS 板块个股成分数 `member_count=0`，该板块不得进入资金流评分榜单。
- 原因：成分为空的板块缺乏可交易对象，进入榜单没有实际意义。
- 实现范围：评分生成阶段与 latest 展示阶段均应排除，避免旧快照残留。
