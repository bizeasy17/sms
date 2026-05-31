# Valuation Update Scheduling

先读总览：`docs/valuation-overview.md`

这份文档聚焦“快报、快照缓存、预热和调度”。如果你想先理解整个估值链路，再回来看这里，会更容易。

This project now supports scheduled valuation-config updates through a management command.

## 1. Command

Run due tasks:

```powershell
python manage.py updatevaluationconfigs --market CN --run-due
```

Preview only:

```powershell
python manage.py updatevaluationconfigs --market CN --run-due --dry-run
```

Run all enabled tasks:

```powershell
python manage.py updatevaluationconfigs --market CN --run-all
```

Run specific tasks:

```powershell
python manage.py updatevaluationconfigs --market CN --tasks sw_mapping_sync,sw_params_refresh
```

## 2. Config And State Files

- Schedule config: `static/valuation_config/update_schedule_CN.json`
- Runtime state: `static/valuation_config/update_schedule_state_CN.json`

The state file is created/updated automatically after execution.

## 3. Default Cadence

- `sw_mapping_sync`: every 14 days
- `sw_params_refresh`: every 30 days
- `keyword_rules_refresh`: every 90 days

You can tune cadence and command kwargs in `update_schedule_CN.json`.

## 4. Suggested Windows Task Scheduler Setup

Create a scheduled task that runs daily and executes:

```powershell
Push-Location "c:/Users/HANJ29/Development/code/sms"; & "c:/Users/HANJ29/Development/vdev1/Scripts/Activate.ps1"; Push-Location "smartinvestor_be"; python manage.py updatevaluationconfigs --market CN --run-due; Pop-Location; Pop-Location
```

Daily trigger + `--run-due` gives stable cadence while still supporting urgent manual runs.

## 5. Parameter-Layer Logic (Quick Summary)

- L3 targets are not raw medians; they are median-driven and bounded by base anchors:
	- `target = clip(median, base * lower_ratio, base * upper_ratio)`
- L2/L1 targets are weighted aggregations of child nodes, using member count as weight:
	- `param_parent = sum(w_i * param_i) / sum(w_i)` with `w_i = member_count_i`

This makes outputs responsive to market changes while avoiding unstable jumps from one-day extremes.

## 6. Express VIP Fast-Report Impact

Valuation snapshot loading now attempts `tushare pro.express_vip` and applies conservative adjustments when available:

- Profit growth (`peg_growth_yoy_pct`) prefers fast-report YoY fields.
- Net profit and revenue can be updated via a blended scheme (fast-report priority with fallback).
- Interim periods are annualized conservatively before blending to avoid over-amplifying one quarter.

Result: when a stock publishes a strong earnings express (for example, `688002.SH`), PE/PS/PEG valuation paths can reflect it earlier than waiting for full periodic statements.

## 7. Single-Stock Verification Switch

`estmktv` now supports a diagnostic switch to show where profit/growth inputs come from and how express data changes effective values:

```powershell
python manage.py estmktv --tscode 688002.SH --match-business-industries --business-match-level L2 --business-topn 2 --show-source --show-citic-levels --show-profit-source
```

When `--show-profit-source` is enabled, output includes:

- `profit_data_source` (for example: `fina_indicator_income`, `express_vip`, `express_vip_blended`)
- snapshot dates (`profit_snapshot_trade_date`, `profit_snapshot_end_date`, `express_end_date`, `express_ann_date`)
- key metrics with base-to-effective transition:
	- `peg_growth_yoy_pct(base->effective)`
	- `netprofit(base->effective)`
	- `revenue(base->effective)`
- `express_blend_alpha`

This switch is intended for earnings-window observability: you can verify immediately whether quick-report data has entered the single-stock valuation path.

## 8. Strict Matching Rules For Express Data

To avoid stale or future-leak quick reports affecting valuation, `estmktv` now supports strict express matching controls:

```powershell
python manage.py estmktv --tscode 688002.SH --show-profit-source --express-max-age-days 180
```

Disable strict rules only for debugging:

```powershell
python manage.py estmktv --tscode 688002.SH --show-profit-source --no-strict-express-match
```

Rule 1: Announcement visibility (`ann_date <= trade_date`)

- Meaning: a quick report can be used only if it was already announced on or before the valuation date.
- Why: prevents future-data leakage in backtest or historical replay.
- Failure example: valuation date is `20260301`, but express `ann_date` is `20260305`.
- Block reason in output: `ann_date_after_trade_date` (or `ann_date_missing` if absent).

Rule 2: Reporting period consistency (`express_end_date >= base_end_date`)

- Meaning: express period must be at least as new as the base financial period (`fina_indicator`/`income`).
- Why: prevents mixing an older period express row into a newer baseline statement.
- Failure example: baseline end date is `20251231`, express end date is `20250930`.
- Block reason in output: `express_end_before_base_end` (or `express_end_date_missing` when baseline exists).

Rule 3: Freshness window (`trade_date - ann_date <= N days`)

- Meaning: express row expires after a configurable number of days from announcement.
- Default: `N = 180` via `--express-max-age-days 180`.
- Why: express rows are usually always queryable after first release, but old rows should not keep driving current valuation.
- Block reason in output: `ann_date_stale`.

When strict mode is enabled, only rows that pass all rules are applied.
`--show-profit-source` prints diagnostics including:

- `strict_express_match`
- `express_max_age_days`
- `express_apply_reason`
- `express_block_reason`

## 9. Batch Prefill Also Supports Strict Express Switches

`prefillvaluationsnapshot` now accepts the same express strictness controls, so offline snapshot warming and single-stock valuation use consistent data-eligibility rules.

The scheduled task `valuation_snapshot_prefill` is configured with `express_max_age_days=180` in `update_schedule_CN.json`, so weekly/monthly batch runs stay aligned with the strict default behavior.

It also now supports a refresh strategy switch:

- `missing`: only fill missing snapshots
- `all`: recalculate everything in scope
- `disclosure`: only recalculate stocks whose latest report / express disclosure date is newer than the existing snapshot update time

Use default strict mode:

```powershell
python manage.py prefillvaluationsnapshot --scope 60 --dry-run --express-max-age-days 180
```

Disable strict mode only for comparison/debugging:

```powershell
python manage.py prefillvaluationsnapshot --scope 60 --dry-run --no-strict-express-match
```

Run disclosure-driven incremental refresh:

```powershell
python manage.py prefillvaluationsnapshot --scope 60 --dry-run --refresh-policy disclosure --express-max-age-days 180
```

When `--refresh-policy disclosure` is used, command summary now includes:

- `disclosure_refreshed`: number of stocks recalculated due to newer disclosures
- `skipped_unchanged`: number of stocks skipped because no newer disclosure signal exists
- `disclosure_refresh_reasons`: reason breakdown, for example `express_vip_ann_date`, `income_ann_date`, `fina_indicator_ann_date`

### 9.1 Profit Buckets (formal + blended)

`prefillvaluationsnapshot` now supports `--profit-buckets`:

- `auto`: legacy-compatible behavior (single run with `allow_express_adjustment=True`)
- `formal`: force formal-only (`allow_express_adjustment=False`)
- `blended`: blended-enabled only (`allow_express_adjustment=True`)
- `both`: run formal + blended buckets in one command (recommended)

Current scheduler baseline in UAT uses `profit_buckets=both` for `valuation_snapshot_prefill`.

Important runtime behavior:

1. `both` does not guarantee two persisted rows for every key.
2. If blended eligibility fails, blended bucket can fall back to formal source.
3. Command now de-duplicates same-batch conflict keys to avoid PostgreSQL `ON CONFLICT DO UPDATE ... cannot affect row a second time`.

Frontend read policy (paired with buckets):

1. List/detail API first filters candidates by requested `report_type` (`Q1/H1/Q3/FY`).
2. Within the same report type, it selects latest snapshot by bucket dimension (`profit_data_source`).
3. Detail API no longer hard-excludes express-based rows when report type is explicitly requested.

Acceptance checks (quick):

1. Scheduler args check:

```powershell
python manage.py updatevaluationconfigs --market CN --run-due --dry-run
```

2. Snapshot coexistence check (same key, different bucket):

```powershell
python manage.py shell -c "from django.db.models import Count; from prediction.models import StockValuationSnapshot as S; q=S.objects.filter(profit_report_type='ANNUAL', profit_report_end_date='2025-12-31').values('ts_code','trade_date','valuation_method').annotate(bucket_n=Count('profit_data_source', distinct=True)).filter(bucket_n__gt=1); print('coexist_keys=', q.count()); print(list(q[:20]))"
```

Dry-run check for scheduled kwargs:

```powershell
python manage.py updatevaluationconfigs --market CN --run-due --dry-run
```

When output for `valuation_snapshot_prefill` shows each step includes `profit_buckets=both`, scheduler and command behavior are aligned.

## 10. Operational Threshold Template For Full Refresh

`prefillvaluationsnapshot` should not run with `--refresh` as a routine weekly job.
Use `--refresh` only when valuation inputs or valuation logic have changed enough that existing snapshots are no longer trustworthy.

Recommended default policy:

- Normal mode: run prefix-batched prefill without `--refresh` so the system only fills missing snapshots.
- Event mode: run prefix-batched prefill with `--refresh` only after material valuation-input changes.

### 10.1 When Full Refresh Is Recommended

Run a full refresh when any of the following happens:

1. Valuation logic changes

- Examples: changes to express eligibility, blending rules, DCF/DDM formulas, target interpretation, or method defaults.
- Recommended action: full refresh.

2. SW valuation template changes are material

- Examples: after `syncswvaluation --params-only` the generated template set shows broad changes in `target_pe`, `target_pb`, `target_ps`, `target_peg`, or `required_return`.
- Practical threshold: if sampled industries show about 10%+ change in core targets, or changes are widespread across many industries, treat it as material.
- Recommended action: full refresh.

3. Disclosure-window fundamental updates are concentrated

- Examples: quarterly / annual reporting season, or a visible wave of `express_vip` releases across the market.
- Practical threshold: if you expect a meaningful share of the market to have updated profit / revenue / growth inputs, do one full refresh after the main disclosure window.
- Recommended action: full refresh once per disclosure wave, not every week inside the same wave.

4. Data repair or backfill happened upstream

- Examples: Tushare fields were corrected, ETL mapping changed, historical financial rows were repaired.
- Recommended action: full refresh.

5. Method coverage changed

- Examples: you added `peg`, `fcff_dcf`, `ddm`, or changed the default method set for cache warm-up.
- Recommended action: full refresh or at least a full-market fill for the new methods.

### 10.2 When Full Refresh Is Not Needed

## 11. UAT Market-Style Refresh Policy (2026-04-14)

To keep market-style valuation responsive on non-disclosure days while preserving disclosure-driven recalculation, UAT now uses a dual-track refresh policy:

1. Disclosure incremental refresh (existing)

- Entry: `earnings_refresh.bat`
- Core mode: `--refresh-policy disclosure`
- Scope: candidate-only stocks from disclosure/export pipeline

2. Full-market refresh on weekday 1/3/5 (new)

- Entry: `valuation_full_refresh_135.bat`
- Trigger behavior: run only when Windows DayOfWeek is `1/3/5`, otherwise exit 0
- Scope split: `60`, `68`, `00`, `30`, `8`
- Core args:
	- `--refresh-policy all`
	- `--enable-market-style --market-style-profile adaptive`
	- `--price-anchor-mode market_now`

The daily entry script `daily_valuation_due_runner.bat` now calls `valuation_full_refresh_135.bat` after `updatevaluationconfigs --run-due`.

Operational notes:

1. This 1/3/5 full refresh is configured for UAT only.
2. Do not duplicate this schedule in DEV unless explicitly required.
3. Keep disclosure-refresh and full-refresh logs separately under `output/logs` for easier replay and incident tracing.

Do not run a full refresh in these cases:

1. Only trading prices moved, but no new financial or express data arrived.
2. Only a small number of stocks published new information and real-time fallback is acceptable.
3. You only want to keep cache coverage high for newly queried stocks.

In these cases, keep using normal prefill without `--refresh`.

### 10.3 Suggested Practical Cadence

Recommended operating model:

1. Monthly baseline

- Run scheduled prefix-batched prefill without `--refresh`.

2. Disclosure-window refresh

- Run one manual prefix-batched full refresh after the main quarterly / annual disclosure wave.

3. Logic / template change refresh

- Run one manual full refresh immediately after valuation rules or SW templates materially change.

### 10.4 Recommended Commands

Normal monthly fill-missing run:

```powershell
python manage.py updatevaluationconfigs --market CN --tasks valuation_snapshot_prefill
```

Manual disclosure-window full refresh by prefix:

```powershell
python manage.py prefillvaluationsnapshot --scope 60 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 68 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 00 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 30 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 8 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh
```

Disclosure-window incremental refresh by prefix (preferred default):

```powershell
python manage.py prefillvaluationsnapshot --scope 60 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 68 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 00 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 30 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 8 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
```

Candidate-driven incremental refresh (current `earnings_refresh.bat` behavior):

1. Export disclosure candidates with `exportdisclosurecandidates`.
2. Run `prefillvaluationsnapshot` by prefix with `--codes-file` to process candidate-only stocks.
3. Prefixes without candidates are skipped before invoking Django command.

Default mode:

- `earnings_refresh.bat` now defaults to `CANDIDATE_POLICY=disclosure-only` for daily scheduler runs.
- This keeps daily runs focused on disclosure-driven deltas.

Manual backfill mode:

- Use `earnings_refresh_backfill.bat` when you need to include missing methods / backfill targets (`CANDIDATE_POLICY=all`).

Useful debug switches for `earnings_refresh.bat`:

- `set CANDIDATE_EXTRA_ARGS=--limit 200`
- `set PREFILL_EXTRA_ARGS=--dry-run --limit 2`

These switches are optional and mainly for UAT verification.

### 10.5 One-Line Rule

If cached valuation assumptions changed, run full refresh.
If only cache coverage is incomplete, run normal prefill.

## 11. UAT Recommended Scheduler Plan

Goal: keep daily trading/prediction stable, and add dedicated valuation-refresh jobs around disclosure windows.

### 11.1 Existing Daily Chain (Keep As Is)

- Task: `daily_funda_prediction.bat`
- Cadence: Mon-Fri
- Purpose: pull daily data, features/prediction, and run candidate picking.

This is not a full valuation-template refresh job.

### 11.2 Add A Daily Due-Runner For Config Sync

Create a daily task (off-hours) to run due valuation maintenance tasks:

```powershell
python manage.py updatevaluationconfigs --market CN --run-due
```

Why: `--run-due` respects cadence in `update_schedule_CN.json` and keeps SW mapping/params fresh without hard-coding dates.

### 11.3 Add Disclosure-Window Incremental Refresh Task

Create a separate task to run:

```powershell
earnings_refresh.bat
```

Recommended disclosure windows:

- Earnings express: `01-15` to `03-10`
- Q1 reports: `04-01` to `05-10`
- H1 reports: `07-15` to `09-05`
- Q3 reports: `10-10` to `11-05`
- Annual reports: `03-01` to `05-05`

During each window, run once per trading day after market close.

### 11.4 Windows Task Scheduler Reliability Settings

- Run mode: `Run whether user is logged on or not`
- Retry: every 10 minutes, max 2 retries
- Stop timeout: 2-3 hours
- Keep command logs in `output/logs/`

### 11.5 Example schtasks Commands (Template)

Daily due-runner:

```powershell
schtasks /Create /TN "\\BASF\\ML\\UAT\\Valuation Due Runner" /TR "C:\\Windows\\System32\\cmd.exe /c C:\\Users\\HANJ29\\Development\\web\\UAT\\smartinvestor_be\\daily_valuation_due_runner.bat" /SC DAILY /ST 21:30 /F
```

Disclosure-window refresh (manual enable/disable by season):

```powershell
schtasks /Create /TN "\\BASF\\ML\\UAT\\Valuation Earnings Refresh" /TR "C:\\Windows\\System32\\cmd.exe /c C:\\Users\\HANJ29\\Development\\web\\UAT\\smartinvestor_be\\earnings_refresh.bat" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 22:00 /F
```

Create/update daily task and optional backfill task via script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_valuation_refresh_tasks.ps1 -WhatIf
powershell -ExecutionPolicy Bypass -File scripts/setup_valuation_refresh_tasks.ps1 -CreateBackfillTask
```

Notes:

- `earnings_refresh.bat` defaults to `CANDIDATE_POLICY=disclosure-only` (daily lightweight mode).
- `earnings_refresh_backfill.bat` forces `CANDIDATE_POLICY=all` (manual catch-up mode).
- Backfill task is created disabled by default.

Use `daily_valuation_due_runner.bat` for full due-task execution (`--run-due`). Keep `biweekly.bat` for explicit SW mapping sync if needed.

### 11.6 Auto Toggle Earnings-Refresh Task By Date Window

You can use script `scripts/toggle_earnings_refresh_task.ps1` to auto-enable/disable
`Valuation Earnings Refresh` task by disclosure windows.

Dry-run check:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/toggle_earnings_refresh_task.ps1 -WhatIf
```

Create task if missing and apply state:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/toggle_earnings_refresh_task.ps1 -CreateIfMissing
```

Test with a specific date:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/toggle_earnings_refresh_task.ps1 -AsOfDate 2026-04-20 -WhatIf
```

Recommended: add one daily scheduler entry for this toggle script (for example 21:10),
then keep `Valuation Earnings Refresh` at 22:00. The toggle decides if refresh task should be enabled that day.

Example task:

```powershell
schtasks /Create /TN "\\BASF\\ML\\UAT\\Valuation Refresh Toggle" /TR "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -ExecutionPolicy Bypass -File C:\\Users\\HANJ29\\Development\\web\\UAT\\smartinvestor_be\\scripts\\toggle_earnings_refresh_task.ps1" /SC DAILY /ST 21:10 /F
```

### 11.7 Why Weekly Refresh Still Matters

Even with announcement-date anchoring in prediction, keeping a weekly refresh is still valuable.

- Prediction target price is usually anchored to the feature row closest to the latest announcement date, so it should not drift with every daily close.
- Weekly refresh is therefore not for forcing target-price re-pricing on normal market moves.
- Weekly refresh is mainly for operational consistency:
	- catch newly disclosed data / corrected upstream data and re-anchor when needed,
	- repair partial batch failures and degraded fallback rows,
	- reduce cross-symbol staleness so market-wide snapshots stay on a comparable freshness level,
	- keep BE/FE reads stable by refreshing persisted snapshot quality rather than relying on ad-hoc online recompute.

Practical interpretation:

- `target_price`: event-driven update (new disclosure, model/version change, meaningful data correction).
- `return_pct`: can still be recomputed against latest market close for trading-facing display.

This keeps valuation targets stable enough for interpretation while preserving timely market-facing signals.

## 12. UAT Root Scheduler Tasks Under BASF/ML/Valuation

Besides project-local tasks, UAT now also maintains a root-level orchestration group under Windows Task Scheduler folder `\BASF\ML\Valuation`.

These tasks point to batch files under `C:\Users\HANJ29\Development\web\UAT\` and are intended to be the main operational entry points.

### 12.1 Scheduled Pipeline Tasks

- `\BASF\ML\Valuation\UAT Daily Pipeline`
	- Trigger: daily, `21:30`
	- Target batch: `C:\Users\HANJ29\Development\web\UAT\daily.bat`
- `\BASF\ML\Valuation\UAT Weekly Pipeline`
	- Trigger: weekly on `SAT`, `21:30`
	- Target batch: `C:\Users\HANJ29\Development\web\UAT\weekly.bat`
- `\BASF\ML\Valuation\UAT Monthly Pipeline`
	- Trigger: monthly on day `1`, `21:30`
	- Target batch: `C:\Users\HANJ29\Development\web\UAT\monthly.bat`
- `\BASF\ML\Valuation\UAT Quarterly Pipeline`
	- Trigger: every 3 months on day `1`, `21:30`
	- Target batch: `C:\Users\HANJ29\Development\web\UAT\quarterly.bat`

## 13. 估值优化

本节用于记录当前 UAT 的最小可用优化：在不改动上游 earnings 服务模型的前提下，
对 BE 输出侧的预测收益做稳健性约束和跨期校准，降低时点敏感性和极值噪声。

### 13.1 改造目标

1. 稳健性约束（Robustness）

- 对预测收益率进行上下限裁剪，避免异常极值影响排序与推荐。
- 对预测收益率与传统收益率的分歧施加上限。
- 根据信号分数与财报时效计算收缩权重，将预测收益向传统收益适度收缩。

2. 跨期校准（Cross-period Calibration）

- 使用线性校准对输出收益率进行跨期缩放：
	- `calibrated = bias + slope * constrained`
- 目标是减少“公告锚点好、月末滚动弱”的时点偏差。

### 13.2 代码落点

1. 预测收益优化函数

- 文件：`api/views.py`
- 新增函数：
	- `_calc_return_pct_simple`
	- `_clip_float`
	- `_compute_predictive_reliability_weight`
	- `_apply_predictive_return_optimization`

2. 接入路径

- Watchlist/Result 估值返回路径：在 `predictive_optimistic_return_pct_map`、`predictive_conservative_return_pct_map` 写入前应用优化。
- Predictive picking 路径：在 `target_return_pct`、`target_return_low_pct`、`target_return_high_pct` 写入前应用优化。

### 13.3 配置参数（settings.py）

新增参数（均支持环境变量覆盖）：

- `PREDICTIVE_RETURN_OPTIMIZATION_ENABLED`
- `PREDICTIVE_RETURN_ROBUSTNESS_ENABLED`
- `PREDICTIVE_RETURN_CALIBRATION_ENABLED`
- `PREDICTIVE_RETURN_MIN_PCT`
- `PREDICTIVE_RETURN_MAX_PCT`
- `PREDICTIVE_RETURN_DIVERGENCE_CAP_PCT`
- `PREDICTIVE_RETURN_SHRINK_WEIGHT_MIN`
- `PREDICTIVE_RETURN_SHRINK_WEIGHT_MAX`
- `PREDICTIVE_RETURN_STALE_HALF_LIFE_DAYS`
- `PREDICTIVE_RETURN_CALIBRATION_BIAS`
- `PREDICTIVE_RETURN_CALIBRATION_SLOPE`

默认建议（当前 UAT 已使用）：

- 裁剪区间：`[-40, 120]`
- 分歧上限：`35` pct
- 收缩权重：`[0.35, 0.85]`
- 时效半衰：`180` 天
- 线性校准：`bias=0.0, slope=0.85`

### 13.4 运维建议

1. 参数调优节奏

- 每月基于最近滚动回测（rolling/monthly）复核一次 `slope` 和分歧上限。

2. 验证口径

- 并行观察两套锚点：
	- 财报发布日锚点
	- 月末 rolling 锚点
- 若 rolling 的正收益占比/均值长期显著弱于公告锚点，优先调整 `slope` 和收缩权重上限。

3. 风险提示

- 当前校准为线性最小方案，不替代完整时序模型重训。
- 当行业 regime 明显切换时，需重新回测并调整参数。

### 13.5 传统估值优化框架

这次新增的不是“把传统估值改成另一套算法”，而是在 summary 层加一个稳定性后处理框架，
让组合估值和保守估值同时保留原值与优化值。

核心思路：

1. 不改各单方法原始输出

- `PE/PB/PS/PEG/FCFF/DDM` 的单方法估值价仍保持可解释原值。
- 优化只作用在 `composite/conservative/market_style` summary 层。

2. 用传统估值自身信息构造可靠度

- 方法覆盖度：`method_count`
- 方法分歧度：`dispersion_ratio`
- 风险分：`valuation_risk.risk_score`（若可用）

3. 对 summary 收益率做保守收缩与校准

- 先把 raw return 裁剪到区间内。
- 再根据可靠度向 `0%` 收缩，而不是机械向预测信号或其他外部目标收缩。
- 最后用线性校准做跨期缩放：
	- `optimized = bias + slope * shrunk`

当前后端新增函数：

- `api/views.py`
	- `_compute_traditional_price_stats`
	- `_compute_traditional_reliability_weight`
	- `_apply_traditional_return_optimization`
	- `_build_traditional_summary_optimized`

接口新增字段：

1. 详情/快览接口

- `summary_optimized`
- `summary_normalized_to_latest_share_optimized`
- `summary_by_variant_optimized`
- `summary_by_variant_normalized_to_latest_share_optimized`

2. 结果页选股接口

- `composite_valuation_price_raw`
- `composite_valuation_price_optimized`
- `conservative_valuation_price_raw`
- `conservative_valuation_price_optimized`
- 以及对应的 `*_return_pct_*`、`*_gap_pct_optimized`、`traditional_optimization_meta`

### 13.6 传统优化参数与当前调优结论

`settings.py` 中新增参数（支持环境变量覆盖）：

- `TRADITIONAL_RETURN_OPTIMIZATION_ENABLED`
- `TRADITIONAL_RETURN_CALIBRATION_ENABLED`
- `TRADITIONAL_RETURN_MIN_PCT`
- `TRADITIONAL_RETURN_MAX_PCT`
- `TRADITIONAL_RETURN_DISPERSION_REF`
- `TRADITIONAL_RETURN_SHRINK_WEIGHT_MIN`
- `TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX`
- `TRADITIONAL_RETURN_CALIBRATION_BIAS`
- `TRADITIONAL_RETURN_CALIBRATION_SLOPE`

当前 UAT 默认值与含义：

1. 收益率裁剪区间

- `TRADITIONAL_RETURN_MIN_PCT = -50`
- `TRADITIONAL_RETURN_MAX_PCT = 150`
- 目的：防止 summary 层因极端估值价导致排序与展示失真。

2. 分歧参考阈值

- `TRADITIONAL_RETURN_DISPERSION_REF = 0.35`
- 含义：当方法间分歧接近或超过 `35%` 时，可靠度开始明显下降。

3. 收缩权重区间

- `TRADITIONAL_RETURN_SHRINK_WEIGHT_MIN = 0.35`
- `TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX = 0.85`
- 含义：即使可靠度较低，也保留一部分原始传统估值表达；即使可靠度较高，也保留一定保守收缩。

4. 线性校准

- `TRADITIONAL_RETURN_CALIBRATION_BIAS = 0`
- `TRADITIONAL_RETURN_CALIBRATION_SLOPE = 0.9`
- 当前选择 `0.9` 而不是 `1.0`，是为了先做温和收敛，避免过度压缩传统估值的方向信息。

当前调优原则：

1. 先保方向，不先追求最大收益率。
2. 优先降低跨期跳变幅度，再看正收益命中是否退化。
3. 若 `rolling` 与 `announcement` 都显示 RMSE/波动收敛且方向命中不恶化，再接受参数。

### 13.7 603799 双锚点验证

本次已把传统优化接入 `tmp_huayou_603799_backtest.py`，并用两套锚点并行验证：

1. `announcement`

- 财报公告可见后的首个交易日为锚点。
- 用于观察“最贴近信息披露时点”的稳定性。

2. `rolling`

- 报告期后滚动市场锚点。
- 用于观察“更接近日常前台使用场景”的稳定性。

脚本会同时输出：

- `traditional_target`
- `traditional_ret_pct`
- `traditional_target_optimized`
- `traditional_ret_pct_optimized`
- `traditional_method_count`
- `traditional_dispersion_ratio`
- `traditional_reliability_weight`

并追加两组稳定性/可预测性代理指标：

- `std`
- `mean_abs_change`
- `max_abs_change`
- `directional_hit_rate`
- `naive_ar1_rmse`

建议做法：

1. 每次调 `TRADITIONAL_RETURN_*` 参数后，至少重跑一次 `announcement + rolling` 双锚点。
2. 如果只在 `announcement` 好、但 `rolling` 明显变差，优先降低 `TRADITIONAL_RETURN_CALIBRATION_SLOPE` 或下调 `TRADITIONAL_RETURN_SHRINK_WEIGHT_MAX`。
3. 如果波动仍偏大，先收紧 `TRADITIONAL_RETURN_MAX_PCT`，再考虑进一步下调 `DISPERSION_REF`。

The helper script used to create or update these four tasks is:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\HANJ29\Development\web\UAT\setup_uat_root_schedule_tasks.ps1
```

### 12.2 Manual Service Launcher / Stopper

For local UAT service operations, two manual tasks are also registered under the same folder.

- `\BASF\ML\Valuation\UAT Service Launcher`
	- Target batch: `C:\Users\HANJ29\Development\web\UAT\start_uat_services.bat`
	- Purpose: open four service windows for:
		- `smartinvestor_etl` Django on `5000`
		- `smartinvestor_be` Django on `5001`
		- `tushare_earnings_service` Django on `5002`
		- `smartinvestor_fe` Vite dev server
- `\BASF\ML\Valuation\UAT Service Stopper`
	- Target batch: `C:\Users\HANJ29\Development\web\UAT\stop_uat_services.bat`
	- Purpose: close the four launcher windows first, then kill Django listeners on ports `5000/5001/5002` as fallback

Create/update scripts:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\HANJ29\Development\web\UAT\setup_uat_service_launcher_task.ps1
powershell -ExecutionPolicy Bypass -File C:\Users\HANJ29\Development\web\UAT\setup_uat_service_stopper_task.ps1
```

Manual run examples:

```powershell
schtasks /Run /TN "\BASF\ML\Valuation\UAT Service Launcher"
schtasks /Run /TN "\BASF\ML\Valuation\UAT Service Stopper"
```

### 12.3 Operational Notes

- These root tasks are the preferred operator-facing entry points; older project-local tasks can still exist for debugging or partial reruns.
- Current task logon mode is `Interactive only`, which is acceptable for manual UAT operation but not ideal for headless server-style scheduling.
- If you later want unattended execution, recreate or change the tasks with a dedicated run account and `Run whether user is logged on or not`.

## 13. Annual Outlook After Q1/H1/Q3

Yes, this is feasible and recommended.

CLI runbook: `docs/annual-outlook-cli-runbook.md`

### 13.1 Practical Two-Layer Design

1. FY Forecast Layer
- Inputs: latest disclosed quarterly fundamentals, YoY trend, seasonality, industry context.
- Outputs: full-year revenue/net profit/EPS in three scenarios (`base`, `bull`, `bear`).

2. Valuation Outlook Layer
- Feed scenario outputs into valuation methods (`PE/PS/PB/DCF`).
- Produce target-price range, upside/downside, and key assumption sensitivity.

### 13.2 Minimum Viable Workflow (Current Commands)

For each target stock, run:

```powershell
python manage.py estmktv --tscode 688002.SH --trade_date 20260331 --show-source --show-profit-source --express-max-age-days 180
```

Then generate scenario outputs by varying profit assumptions externally (script/notebook) and re-running valuation.

### 13.3 Suggested Next Build Step

Add a batch command, for example `annualoutlook`, to:

- read a stock list;
- generate FY base/bull/bear forecast;
- call valuation for each scenario;
- export one CSV report for PM/research review.

This keeps quarterly forecasting and valuation outlook reproducible and auditable in UAT.
