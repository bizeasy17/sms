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

## 14. Traditional History Backfill Runbook

This section documents the recommended process for traditional valuation history backfill when the goal is:

- write history rows only;
- avoid updating the realtime snapshot and latest tables;
- keep only the first business-match industry candidate;
- backfill the full year 2024.

### 14.1 BAT Support Status

Repository root already includes:

```powershell
backfill_traditional_history_event_driven_2024_2025.bat
```

That script now does three useful things:

1. it exports event dates and per-date financial code files via `export_backfill_event_dates`;
2. it calls `prefillvaluationsnapshot --backfill-history-only`, so writes are limited to `StockValuationSnapshotHistory`.
3. it accepts an optional trailing numeric argument for `business-match-topn`, and forwards it to `prefillvaluationsnapshot`.

Current positional argument order is:

1. `start_date`
2. `end_date`
3. `scope`
4. `methods` (optional, comma-separated)
5. `cadence_days` (optional, numeric)
6. `business_match_topn` (optional, numeric)

Example: if the target is "only first matched industry", pass the last numeric argument as `1`.

### 14.2 Recommended Method Set

For pure traditional valuation history backfill, prefer excluding `sw_history`:

```powershell
pe,pb,ps,peg,fcff_dcf,ddm
```

If you intentionally want the default mixed method set, use:

```powershell
sw_history,pe,pb,ps,peg,fcff_dcf,ddm
```

The `business-match-topn` limit only controls the number of `business_match` variants. It does not change the internal `sw_history` anchor logic.

### 14.3 2024 Full-Year Backfill Command

Preferred direct BAT usage from the repository root:

```powershell
cmd /c "backfill_traditional_history_event_driven_2024_2025.bat 2024-01-01 2024-12-31 ALL pe,pb,ps,peg,fcff_dcf,ddm 30 1"
```

Meaning of the trailing arguments:

- `30`: cadence days
- `1`: keep only the first business-match industry candidate

If you need an explicit step-by-step PowerShell version, the equivalent expanded process is below.

Run the following PowerShell from the repository root:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/DEV"
$py = "c:/Users/HANJ29/Development/vdev1/Scripts/python.exe"
$start = "2024-01-01"
$end = "2024-12-31"
$scope = "ALL"
$methods = "pe,pb,ps,peg,fcff_dcf,ddm"

New-Item -ItemType Directory -Force "logs" | Out-Null
$eventDates = "logs/event_dates_traditional_2024.txt"
$eventReasons = "logs/event_dates_traditional_2024_reasons.csv"
$financialCodesDir = "logs/event_codes_traditional_2024"
New-Item -ItemType Directory -Force $financialCodesDir | Out-Null

& $py "tushare_earnings_service/manage.py" export_backfill_event_dates `
	--start-date $start `
	--end-date $end `
	--scope $scope `
	--output-file $eventDates `
	--reasons-file $eventReasons `
	--financial-apis disclosure_date,express_vip,income,fina_indicator_vip `
	--financial-date-codes-dir $financialCodesDir `
	--cadence-days 30

if ($LASTEXITCODE -ne 0) { throw "export_backfill_event_dates failed" }

$fullRefreshDates = @{}
Get-Content $eventReasons | Select-Object -Skip 1 | ForEach-Object {
	$parts = $_.Split(",", 2)
	if ($parts.Count -ge 2) {
		if ($parts[1] -match "cadence:" -or $parts[1] -match "regime:") {
			$fullRefreshDates[$parts[0].Trim()] = $true
		}
	}
}

Get-Content $eventDates | ForEach-Object {
	$d = $_.Trim()
	if (-not $d) { return }

	if ($fullRefreshDates.ContainsKey($d)) {
		& $py "smartinvestor_be/manage.py" updatevaluationconfigs --market CN --run-due
		if ($LASTEXITCODE -ne 0) { throw "updatevaluationconfigs failed at $d" }

		& $py "smartinvestor_be/manage.py" prefillvaluationsnapshot `
			--trade-date $d `
			--scope $scope `
			--freq D `
			--refresh-policy all `
			--price-anchor-mode market_now `
			--profit-buckets both `
			--backfill-history-only `
			--business-match-topn 1 `
			--methods $methods
	}
	else {
		$codesFile = Join-Path $financialCodesDir "$d.txt"
		if ((Test-Path $codesFile) -and ((Get-Item $codesFile).Length -gt 0)) {
			& $py "smartinvestor_be/manage.py" prefillvaluationsnapshot `
				--trade-date $d `
				--scope $scope `
				--codes-file $codesFile `
				--freq D `
				--refresh-policy all `
				--price-anchor-mode market_now `
				--profit-buckets both `
				--backfill-history-only `
				--business-match-topn 1 `
				--methods $methods
		}
	}

	if ($LASTEXITCODE -ne 0) { throw "prefillvaluationsnapshot failed at $d" }
}
```

### 14.4 What This Process Actually Does

1. Generate all event dates for 2024.
2. Identify full-refresh dates triggered by `cadence` or `regime` reasons.
3. On those dates, refresh valuation templates first via `updatevaluationconfigs --run-due`.
4. Run `prefillvaluationsnapshot` in history-only mode for each event date.
5. Limit business-match expansion to one candidate with `--business-match-topn 1`.

### 14.5 Key Parameters

- `--backfill-history-only`: write only `StockValuationSnapshotHistory`; do not update realtime snapshot tables.
- `--business-match-topn 1`: keep at most one `business_match` variant per stock/date/method path.
- `--refresh-policy all`: recompute everything inside the current per-date processing scope.
- `--price-anchor-mode market_now`: anchor backfill rows to the market price of the trade date.
- `--profit-buckets both`: keep formal and blended buckets aligned with the current batch-prefill baseline.

### 14.6 Verification After Run

Minimum checks:

1. confirm there are no failed dates in the run log;
2. confirm duplicate `business_match` variants no longer exist in 2024 history rows.

Example duplicate check:

```powershell
python manage.py shell -c "from django.db.models import Count; from valuation.models import StockValuationSnapshotHistory as H; q=H.objects.filter(trade_date__gte='2024-01-01', trade_date__lte='2024-12-31', valuation_variant__startswith='business_match|').values('ts_code','trade_date','valuation_method').annotate(n=Count('id')).filter(n__gt=1); print('duplicate_business_match_keys=', q.count()); print(list(q[:20]))"
```

If `duplicate_business_match_keys` is `0`, the top-1 industry constraint is working as expected.

### 14.7 Operational Note

The BAT now supports forwarding `business-match-topn`. Keep using the expanded PowerShell version only when you want to inspect or modify intermediate event-date handling in a more explicit way.
