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
python manage.py prefillvaluationsnapshot --scope 60 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 68 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 00 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 30 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh
python manage.py prefillvaluationsnapshot --scope 8 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh
```

Disclosure-window incremental refresh by prefix (preferred default):

```powershell
python manage.py prefillvaluationsnapshot --scope 60 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 68 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 00 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 30 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
python manage.py prefillvaluationsnapshot --scope 8 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
```

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

## 12. Annual Outlook After Q1/H1/Q3

Yes, this is feasible and recommended.

CLI runbook: `docs/annual-outlook-cli-runbook.md`

### 12.1 Practical Two-Layer Design

1. FY Forecast Layer
- Inputs: latest disclosed quarterly fundamentals, YoY trend, seasonality, industry context.
- Outputs: full-year revenue/net profit/EPS in three scenarios (`base`, `bull`, `bear`).

2. Valuation Outlook Layer
- Feed scenario outputs into valuation methods (`PE/PS/PB/DCF`).
- Produce target-price range, upside/downside, and key assumption sensitivity.

### 12.2 Minimum Viable Workflow (Current Commands)

For each target stock, run:

```powershell
python manage.py estmktv --tscode 688002.SH --trade_date 20260331 --show-source --show-profit-source --express-max-age-days 180
```

Then generate scenario outputs by varying profit assumptions externally (script/notebook) and re-running valuation.

### 12.3 Suggested Next Build Step

Add a batch command, for example `annualoutlook`, to:

- read a stock list;
- generate FY base/bull/bear forecast;
- call valuation for each scenario;
- export one CSV report for PM/research review.

This keeps quarterly forecasting and valuation outlook reproducible and auditable in UAT.
