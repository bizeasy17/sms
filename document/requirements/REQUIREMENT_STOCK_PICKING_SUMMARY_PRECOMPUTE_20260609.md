# 需求说明：估值选股改造为预聚合 Summary 读表加速（UAT）

## 1. 背景与问题
当前实时选股接口在首轮查询时存在明显延迟，尤其在以下条件下体感较重：
- 范围：沪市（scope=60）
- 口径：Q1
- 财务条件：不应用（apply_financial_filters=0）

已观测到的典型现象：
- 首轮请求总耗时可达数十秒。
- 主要耗时集中在估值快照构建阶段，而不是分页阶段。
- 前端初始化阶段可能存在额外预热请求，导致用户体感进一步放大。

## 2. 目标
将实时接口从“在线临时全量计算”改造为“离线预聚合 + 在线读表分页”，实现：
1) 首轮查询耗时显著下降（目标 p95 <= 2 秒，优先范围：沪深主流 scope）。
2) 翻页稳定低延迟（目标 p95 <= 400ms）。
3) 与现有接口响应结构保持兼容，前端无需大改。
4) 支持回退到旧逻辑，确保上线风险可控。

## 3. 服务归属（待确认）
- 归属服务：smartinvestor_be
- 归属接口：GET /stock-pick-valuation/{trade_date}/{scope}/
- 主要实现文件：smartinvestor_be/api/views.py
- 离线任务：smartinvestor_be/prediction/management/commands（新增 command）
- 数据模型：建议放在 valuation 或 prediction app（待最终确认）

## 4. 设计原则
1) 在线查询只做轻计算：分页、轻筛选、格式化。
2) 重计算前移到离线任务：快照汇总、评分、排序主键生成。
3) 接口兼容优先：返回字段名不变，减少前端变更。
4) 可灰度与可回滚：支持 summary 命中失败时回退旧逻辑。

## 5. 变更范围（方案级）
### 5.1 新增预聚合结果表（建议名）
`stock_pick_summary_latest`

建议最小字段：
- 查询维度字段
  - trade_date
  - freq
  - scope_bucket
  - market
  - picking_mode
  - earnings_report_type
  - valuation_pick_strategy
  - priority_policy_base（可选，若离线阶段固化主排序策略）
- 标识字段
  - ts_code
  - name
- 展示与筛选字段（按当前接口常用字段最小集）
  - close_qfq
  - pct_change_qfq
  - valuation_method
  - valuation_price
  - valuation_market_cap
  - valuation_gap_pct
  - valuation_status
  - valuation_score
  - buy_candidate
  - risk_level
  - signal_score
  - target_return_pct
  - valuation_profit_report_type
  - valuation_profit_report_end_date
  - valuation_profit_report_ann_date
  - valuation_snapshot_updated_at
- 排序辅助字段
  - sort_score_primary
  - sort_score_secondary
  - sort_risk_rank
  - sort_price
- 元数据字段
  - source_batch_id
  - summary_version
  - created_at
  - updated_at

唯一键建议：
- (trade_date, freq, scope_bucket, market, picking_mode, earnings_report_type, valuation_pick_strategy, ts_code)

索引建议：
- 过滤索引：
  - (trade_date, freq, scope_bucket, picking_mode, earnings_report_type, valuation_pick_strategy)
- 排序索引：
  - (trade_date, freq, scope_bucket, picking_mode, earnings_report_type, valuation_pick_strategy, sort_score_primary DESC)
- 单股票索引：
  - (ts_code)

### 5.2 新增离线构建任务
新增管理命令（建议名）：
- `precompute_stock_pick_summary`

建议参数：
- --trade-date
- --freq（默认 D）
- --scope（支持 60/00/30/68/WATCHLIST）
- --picking-mode（baseline/predictive）
- --earnings-report-type（ALL/Q1/H1/Q3/FY/FUSION/EXP）
- --valuation-pick-strategy（baseline/first/best_score/median/min/max）
- --rebuild（是否重建）
- --dry-run（仅计算不落库）

任务职责：
1) 复用现有选股核心逻辑计算“全量候选 + 主排序”。
2) 将结果写入 summary 表（upsert）。
3) 记录 source_batch_id 和 summary_version。

### 5.3 在线接口读取策略（兼容）
在实时接口中引入“summary-first”策略：
1) 优先按查询参数读取 summary 表并分页返回。
2) 未命中或异常时，回退旧实时链路。
3) 响应 meta 新增（可选）：
   - summary_hit: true/false
   - summary_version
   - fallback_reason（仅回退时）

### 5.4 前端改动范围（最小）
- 默认无需改动字段映射。
- 可选优化：展示 meta.summary_hit 供排查。
- 可选优化：移除首屏 warmup 请求，避免重复首轮重算。

## 6. 非目标（本期不做）
1) 不重写选股评分体系。
2) 不变更前端筛选交互语义。
3) 不处理历史全量回算（仅先覆盖最新交易日）。
4) 不在本期引入复杂多级缓存治理策略。

## 7. 风险与应对
风险：
1) 预聚合与在线旧链路结果不一致。
2) 离线任务失败导致 summary 不可用。
3) 表膨胀导致查询回退。

应对：
1) 上线前做新旧结果对比（样本+全量指标）。
2) 保留旧链路回退开关。
3) 控制 summary 保留窗口（例如仅最近 N 个交易日）。
4) 保证关键索引到位后再切流。

## 8. 验收标准
1) 在 scope=60、Q1、apply_financial_filters=0 下：
   - 首轮查询 p95 <= 2 秒。
   - 翻页 p95 <= 400ms。
2) 同一查询条件下，新旧链路的：
   - total_filtered 一致（允许 0 容忍差异）。
   - 前 50 名 ts_code 一致率 >= 98%。
3) 接口在 summary 未命中时可自动回退，功能不中断。
4) 线上可观测 summary_hit、fallback_rate、接口 p95。

## 9. 实施顺序（建议）
1) 建表与索引（不切流）。
2) 完成离线命令并产出单日样本数据。
3) 增加 summary-first 读取与回退逻辑（默认灰度关闭）。
4) 对比验证通过后灰度开启。
5) 完成观察期后设为默认。

## 10. 回滚方案
1) 配置开关关闭 summary-first，立即回退旧实时链路。
2) 保留已建表但停止写入任务。
3) 问题定位后再按批次重建 summary 数据。

## 11. 待确认项
1) summary 表落在哪个 app（valuation / prediction）？
2) 首期覆盖范围是否仅限：freq=D、scope in {60,00,30,68}？
3) 前 50 名一致率阈值是否接受 98%（用于灰度验收）？
4) 是否同意首屏移除 warmup 请求以进一步降低体感延迟？
