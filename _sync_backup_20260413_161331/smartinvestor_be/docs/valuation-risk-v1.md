# Valuation Risk V1.5+ 设计与实现说明

## 1. 范围与目标

本文档说明 `valuation_risk` V1.5+ 增强版（`v1_5_ruleset_20260411`）的实现逻辑。

目标：
- 为传统估值结果提供可解释风险评估；
- 支持实时接口返回（active variant + by_variant）；
- 支持历史口径回刷（例如 2025Q1、2025H1）；
- 与估值计算解耦，独立运行和落库。

实现位置：
- 风险引擎：`valuation_risk/services/risk_engine.py`
- 历史回刷命令：`valuation_risk/management/commands/prefillvaluationrisk.py`
- 接口接入：`api/views.py` 中 `get_stock_valuation_methods`

---

## 2. 输入数据

风险引擎 `build_valuation_risk_payload(...)` 主要读取以下输入：

- 标识字段：`ts_code`, `market`, `trade_date`, `valuation_variant`
- 财报口径字段：`profit_report_type`, `profit_report_end_date`, `profit_report_ann_date`, `profit_data_source`
- 估值方法结果：`rows`（方法名 + 估值价）
- 估值摘要：`summary`（组合估值价、保守估值价）
- 阈值参数：`base_band_pct`

有效估值方法定义：
- `valuation_method` 非空；
- `valuation_price` 可转成数值且大于 0。

---

## 3. 风险因子与打分

### 3.1 因子列表（15个）

1. `method_coverage`（方法覆盖度）
2. `method_dispersion`（方法分歧度）
3. `core_method_presence`（核心方法结构）
4. `report_freshness`（财报时效性）
5. `data_completeness`（口径字段完备度）
6. `report_alignment`（报告类型一致性）
7. `gap_pressure`（估值偏离压力）
8. `profit_source`（利润口径来源）
9. `variant_dependency`（估值变体依赖）
10. `leverage_stress`（杠杆压力）
11. `liquidity_structure`（流动性结构）
12. `profitability_quality`（盈利质量）
13. `receivable_pressure`（应收压力）
14. `inventory_pressure`（存货压力）
15. `goodwill_pressure`（商誉压力）

### 3.2 因子评分规则

#### A. 方法覆盖度 `_score_method_coverage`

- `count >= 5` -> 10
- `count == 4` -> 20
- `count == 3` -> 40
- `count == 2` -> 70
- `count == 1` -> 90
- `count == 0` -> 100

含义：可交叉验证的方法越少，风险越高。

#### B. 方法分歧度 `_score_method_dispersion`

设有效估值价集合为 $P$，中位数为 $m$，标准差为 $\sigma$，分歧率为：

$$
\text{dispersion} = \frac{\sigma}{m}
$$

映射到风险分：

$$
\text{score} = \mathrm{clamp}\left(\frac{\text{dispersion}}{0.35} \times 100,\ 0,\ 100\right)
$$

特殊情形：
- 只有 1 个方法 -> 75
- 中位数无效（`<=0`）-> 65

#### C. 财报时效性 `_score_freshness`

按 `trade_date - profit_report_ann_date` 的天数分段：
- `<=45` 天 -> 10
- `<=120` 天 -> 28
- `<=240` 天 -> 55
- `>240` 天 -> 78
- 日期缺失 -> 55

#### D. 利润口径来源 `_score_profit_source`

- `fina_indicator_income` -> 15
- `express_vip_blended` -> 48
- `express_vip` -> 68
- 其他非空来源 -> 35
- 空 -> 45

#### E. 估值变体依赖 `_score_variant_dependency`

- `default` -> 10
- `sw_l3_baseline*` -> 35
- `business_match*` -> 58
- 其他 -> 42

#### F. 核心方法结构 `_score_core_method_presence`

关注 `PE/PB/PS` 核心方法覆盖，覆盖越低风险越高。

#### G. 口径字段完备度 `_score_data_completeness`

检查以下关键字段缺失：
- `profit_report_type`
- `profit_report_end_date`
- `profit_report_ann_date`
- `profit_data_source`

缺失按规则累加风险分并夹到 `[0,100]`。

#### H. 报告类型一致性 `_score_report_alignment`

检查 `profit_report_type` 与 `profit_report_end_date` 是否匹配：
- Q1 -> 0331
- H1 -> 0630
- Q3 -> 0930
- ANNUAL -> 1231

#### I. 估值偏离压力 `_score_gap_pressure`

基于 `summary.composite_valuation_gap_pct` / `summary.conservative_valuation_gap_pct` 的绝对值分段评分。

#### J. 杠杆压力 `_score_leverage_stress`

基于 `financial_profile.debt_to_assets` 分段评分：
- `<=45%` -> 12
- `45%-60%` -> 28
- `60%-75%` -> 52
- `>75%` -> 74
- 缺失 -> 38

#### K. 流动性结构 `_score_liquidity_structure`

基于 `financial_profile.ca_to_assets` 分段评分：
- `<20%` -> 72
- `20%-30%` -> 55
- `30%-40%` -> 32
- `40%-70%` -> 18
- `>70%` -> 28
- 缺失 -> 42

#### L. 盈利质量 `_score_profitability_quality`

基于 `roe/roe_dt`、`netprofit_margin`、`gross_margin` 组合打分。
低 ROE/低净利率/低毛利率会叠加风险分，字段缺失会施加轻度惩罚。

#### M. 应收压力 `_score_receivable_pressure`

基于 `financial_profile.ar_to_assets` 分段评分：
- `<=10%` -> 12
- `10%-20%` -> 30
- `20%-35%` -> 55
- `>35%` -> 75
- 缺失 -> 35

#### N. 存货压力 `_score_inventory_pressure`

基于 `financial_profile.inventory_to_assets` 分段评分：
- `<=12%` -> 15
- `12%-25%` -> 35
- `25%-40%` -> 58
- `>40%` -> 78
- 缺失 -> 38

#### O. 商誉压力 `_score_goodwill_pressure`

基于 `financial_profile.goodwill_to_assets` 分段评分：
- `<=5%` -> 10
- `5%-15%` -> 32
- `15%-30%` -> 55
- `>30%` -> 76
- 缺失 -> 30

---

## 4. 总分、等级与置信度

### 4.1 总分（0-100）

加权公式：

$$
\text{risk\_score} = 0.15C + 0.15D + 0.07M + 0.09F + 0.07S + 0.06K + 0.07A + 0.04V + 0.04G + 0.05L + 0.05Q + 0.05P + 0.04R + 0.04I + 0.03W
$$

其中：
- $C$ = 覆盖度分
- $D$ = 分歧度分
- $M$ = 核心方法结构分
- $F$ = 时效性分
- $S$ = 来源分
- $K$ = 字段完备度分
- $A$ = 报告一致性分
- $V$ = 变体依赖分
- $G$ = 偏离压力分
- $L$ = 杠杆压力分
- $Q$ = 流动性结构分
- $P$ = 盈利质量分
- $R$ = 应收压力分
- $I$ = 存货压力分
- $W$ = 商誉压力分

最终分值夹到 `[0, 100]`。

### 4.2 风险等级 `_risk_level`

- `HIGH`: `score >= 66`
- `MEDIUM`: `33 <= score < 66`
- `LOW`: `score < 33`

### 4.3 因子严重级别 `_severity`

- `HIGH`: `factor_score >= 70`
- `MEDIUM`: `40 <= factor_score < 70`
- `LOW`: `< 40`

触发定义：`is_triggered = (factor_score >= 40)`。

### 4.4 置信度

初始 85，按信息完备性扣减：
- 有效方法数 `< 3` 扣 15
- `profit_report_ann_date` 缺失扣 10
- `profit_data_source` 缺失扣 10

最终夹到 `[0,100]`。

---

## 5. 风险调整输出（不直接改写估值原值）

返回 `adjustment`：

- `valuation_discount_pct`
  - 计算：`min(0.35, max(0.03, risk_score / 250))`
- `effective_band_pct`
  - 计算：`base_band_pct * (1 + risk_score / 100)`
- `adjusted_composite_valuation_price`
  - 计算：`composite * (1 - discount_pct)`
- `adjusted_conservative_valuation_price`
  - 计算：`conservative * (1 - discount_pct)`

说明：
- 这是风险视角下的校准建议值，原估值 `summary` 不被覆盖。

---

## 6. 接口返回结构

`get_stock_valuation_methods` 新增字段：

- `valuation_risk`
  - 当前 `active_valuation_variant` 对应风险结果
- `valuation_risk_by_variant`
  - 各 variant 的风险映射

接口仍返回原有：
- `summary`, `summary_by_variant`, `data`, `data_by_variant` 等字段

---

## 7. 历史回刷（25Q1/25H1）

命令：`manage.py prefillvaluationrisk`

关键参数：
- `--target-report-type`：`Q1/H1/Q3/ANNUAL/FY`
- `--target-fiscal-year`：财年（如 `2025`）
- `--ts-code`：单股可选
- `--offset --limit`：分批处理
- `--dry-run`：仅打印不落库

示例：

```powershell
python manage.py prefillvaluationrisk --ts-code 000016.SZ --target-report-type Q1 --target-fiscal-year 2025 --dry-run
python manage.py prefillvaluationrisk --target-report-type H1 --target-fiscal-year 2025 --offset 0 --limit 500
```

落库策略：
- 以 `(ts_code, trade_date, market, valuation_variant, profit_report_type)` 做 `update_or_create`
- 每次重算会先清空旧因子，再写入新因子明细

---

## 8. 当前边界与后续计划

当前 V1.5+ 已覆盖：
- 估值稳健性（覆盖/分歧/核心结构）
- 披露质量（时效/来源/字段完备/报告一致性）
- 输出压力（组合/保守偏离）
- 变体依赖
- 资产质量代理指标（杠杆/流动性/盈利质量）
- 资产质量深层结构（应收/存货/商誉）

当前 V1.5+ 未覆盖：
- 财报文本抽取（审计意见、诉讼、减值、关联交易等）
- 深层结构化因子的行业分位校准（当前仍为统一阈值）

建议 V2：
- 引入文本/公告解析模块并落结构化因子；
- 增加行业基线分位校准；
- 将风险快照与估值快照建立明确版本关联字段。

---

## 9. 传统估值 H1 缺口回填流程（D 口径）

适用场景：
- 页面或接口在 `earnings_report_type=H1` 下出现“传统估值方法缺失”；
- 需要对 2025H1（`profit_report_end_date=2025-06-30`）进行批量修复。

口径约定（关键）：
- 默认使用日频 `freq=D`；
- 不再以周频作为默认回填口径。

### 9.1 回填前基线统计（生成缺口清单）

```powershell
python manage.py shell -c "from prediction.models import StockValuationSnapshot; from pathlib import Path; q1=set(StockValuationSnapshot.objects.filter(profit_report_type='Q1',profit_report_end_date='2025-03-31').values_list('ts_code',flat=True)); q3=set(StockValuationSnapshot.objects.filter(profit_report_type='Q3',profit_report_end_date='2025-09-30').values_list('ts_code',flat=True)); h1=set(StockValuationSnapshot.objects.filter(profit_report_type='H1',profit_report_end_date='2025-06-30').values_list('ts_code',flat=True)); missing=sorted((q1|q3)-h1); p=Path('output/h1_missing_before_2025.txt'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text('\\n'.join(missing)+('\\n' if missing else ''), encoding='utf-8'); print('before_total',len(missing)); print('before_sample',missing[:20]); print('file',str(p));"
```

### 9.2 按缺口清单批量回填（D 口径）

建议先 dry-run：

```powershell
python manage.py prefillvaluationsnapshot --codes-file output/h1_missing_before_2025.txt --trade-date 2026-04-10 --freq D --refresh-policy all --target-report-type H1 --target-fiscal-year 2025 --business-match-topn 3 --dry-run
```

确认后正式执行：

```powershell
python manage.py prefillvaluationsnapshot --codes-file output/h1_missing_before_2025.txt --trade-date 2026-04-10 --freq D --refresh-policy all --target-report-type H1 --target-fiscal-year 2025 --business-match-topn 3
```

### 9.3 回填后复核（前后对比清单）

```powershell
python manage.py shell -c "from pathlib import Path; from prediction.models import StockValuationSnapshot; p=Path('output/h1_missing_before_2025.txt'); before=[line.strip() for line in p.read_text(encoding='utf-8').splitlines() if line.strip()] if p.exists() else []; before_set=set(before); h1_now=set(StockValuationSnapshot.objects.filter(profit_report_type='H1',profit_report_end_date='2025-06-30').values_list('ts_code',flat=True)); success=sorted(before_set & h1_now); failed=sorted(before_set - h1_now); print('before_total',len(before_set)); print('success_total',len(success)); print('failed_total',len(failed)); print('success_sample',success[:20]); print('failed_sample',failed[:20]); out_dir=Path('output'); out_dir.mkdir(parents=True, exist_ok=True); (out_dir/'h1_backfill_success_2025.txt').write_text('\\n'.join(success)+('\\n' if success else ''),encoding='utf-8'); (out_dir/'h1_backfill_failed_2025.txt').write_text('\\n'.join(failed)+('\\n' if failed else ''),encoding='utf-8'); print('success_file',str(out_dir/'h1_backfill_success_2025.txt')); print('failed_file',str(out_dir/'h1_backfill_failed_2025.txt'));"
```

### 9.4 常见异常：停牌/无当日行情导致未入选

现象：
- 回填失败集中在少量股票，且日志提示“没有待处理股票”。

原因：
- `prefillvaluationsnapshot` 会先按 `trade_date + freq` 从行情表筛选候选池；
- 若股票在该锚点日无行情（停牌等），即使在 `codes-file` 中也会被过滤。

处理建议：
- 对失败股票改用“该股最新可用 D 频交易日”单独回填。

示例（两只股票分开执行）：

```powershell
python manage.py prefillvaluationsnapshot --codes-file output/tmp_000851.txt --trade-date 2025-09-26 --freq D --refresh-policy all --target-report-type H1 --target-fiscal-year 2025 --business-match-topn 3
python manage.py prefillvaluationsnapshot --codes-file output/tmp_002231.txt --trade-date 2026-01-29 --freq D --refresh-policy all --target-report-type H1 --target-fiscal-year 2025 --business-match-topn 3
```
