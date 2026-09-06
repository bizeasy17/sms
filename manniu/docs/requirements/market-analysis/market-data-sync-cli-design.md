# Market Data Sync CLI Design

## Status And Purpose

This document defines the operator-only `sync_market_data` Django command. Its initial implementation supports argument validation, the default five-year backfill window, Tushare master/company/daily dataset handlers, direct `stk_factor` stock-bar ingestion, PostgreSQL history/latest upserts, and run/watermark recording. It must never be exposed through `api_gateway` or a public HTTP endpoint.

The initial implementation does not yet provide paged historical retrieval, retry/backoff, persisted chunk-level resume, named index universes, weekly/monthly physical tables, or `resample`. It rejects unavailable `resample` and named-index-universe requests rather than silently running an incomplete alternative.

The command supports deterministic historical backfill, EOD daily refresh, persisted restart points, revision-safe upserts, and nonzero failure status for incomplete coverage. It supports analysis data only and must never place or automate trading orders.

## Source And Target Coverage

| Dataset value | Asset scope | Tushare API | Target models | Provider frequency |
| --- | --- | --- | --- | --- |
| `security-master` | Stocks | `stock_basic` | `Security`, `Province`, `Industry` | Initial full load, daily delta |
| `index-master` | Indices | `index_basic` | `Security` | Initial full load, daily delta |
| `company-profile` | Stocks | `stock_company` | `CompanyProfile`, `Province`, `City` | Initial full load, daily delta |
| `stock-bars` | Stocks | `stk_factor` | `MarketBarDailyHistory`, `MarketBarLatest` | Daily |
| `stock-fundamentals` | Stocks | `daily_basic` | `StockDailyFundamentalHistory`, `StockDailyFundamentalLatest` | Daily |
| `stock-cost` | Stocks | `cyq_perf` | `StockCostDistributionHistory`, `StockCostDistributionLatest` | Daily |
| `index-bars` | Indices | `index_daily` | `MarketBarDailyHistory`, `MarketBarLatest` | Daily |
| `index-fundamentals` | Indices | `index_dailybasic` | `IndexDailyFundamentalHistory`, `IndexDailyFundamentalLatest` | Daily |
| `corporate-actions` | Stocks | `dividend` | Planned `CorporateActionEvent`, adjustment-rebuild jobs | Daily event scan |
| `resample` | Stocks and indices | None; persisted daily data | Planned weekly/monthly history and latest rows | After daily completion |

`security-master` and `index-master` are prerequisites for all datasets that reference `Security`. `company-profile` requires stock securities. `corporate-actions` runs after stock bars and can trigger a stock-specific adjusted-history rebuild. `resample` consumes completed daily history only and never requests Tushare.

## Command Interface

```text
python manage.py sync_market_data \
  --dataset security-master|index-master|company-profile|stock-bars|stock-fundamentals|stock-cost|index-bars|index-fundamentals|corporate-actions|resample \
  --mode backfill|daily \
  [--scope all|ts-code|index-universe] [--ts-codes CODE[,CODE...]] \
  [--start-date YYYYMMDD|--history-years N] [--end-date YYYYMMDD] \
  [--frequency D|W|M] [--resume-run RUN_ID] \
  [--overlap-days N] [--page-size N] [--max-pages N] [--dry-run]
```

### Argument Rules

- `--dataset` is required and accepts exactly one dataset per command invocation. Orchestration scripts invoke datasets in dependency order rather than combining unrelated writes in one transaction.
- `--mode backfill` uses the following start-date precedence: a compatible `--resume-run` uses its persisted next unfinished chunk; an explicit `--start-date` uses that date; otherwise `--history-years` determines the start date relative to the resolved `--end-date`. `--history-years` defaults to `5`, so a first backfill downloads the latest five years by default. `--start-date` and `--history-years` are mutually exclusive.
- `--history-years` accepts a positive whole number. It is valid only with `--mode backfill`; daily mode rejects it. It controls the initial or explicitly requested history window only and never rewinds a newer successful watermark unless the operator supplies an explicit `--start-date`.
- `--end-date` defaults to the last completed trading date. The calculated default backfill start date is the same calendar date five years before the resolved end date; source responses and the approved trading calendar determine the actual available trading dates.
- `--mode daily` rejects `--start-date` and uses the last completed trading date plus an overlap window. The default overlap is the matching `IngestionWatermark.overlap_days`, initially `3`.
- `--scope all` is the default for master and daily all-market endpoints. `--scope ts-code` requires `--ts-codes`; it accepts only canonical comma-separated Tushare codes, each at most 16 characters. `--scope index-universe` requires a configured, named universe and is valid only for index datasets.
- `--frequency` is omitted or `D` for all provider-backed datasets. `W` and `M` are valid only for `resample`; provider-backed weekly/monthly requests are rejected.
- `--page-size` and `--max-pages` have endpoint-specific safe defaults and hard upper bounds. Hitting `--max-pages` is a failure, not a successful partial run.
- `--dry-run` performs argument validation, source request planning, response validation, and reports planned chunks. It writes no domain records, `IngestionRun`, or `IngestionWatermark` records.

## Dataset Contracts

### Security And Index Masters

`security-master` calls `stock_basic` with explicit fields: `ts_code`, `symbol`, `name`, `area`, `industry`, `fullname`, `market`, `exchange`, `list_status`, `list_date`, `delist_date`, and `is_hs`. It upserts one `Security(asset_type='STOCK')` per `ts_code`, keeps the raw provider area/industry values, and resolves normalized `Province` and versioned Tushare `Industry` references. It must not overwrite registered company province/city fields from `stock_company`.

`index-master` calls `index_basic` for each supported market, with explicit code, name, market/exchange, publisher, category, base date, list date, and status fields available from the provider. It upserts `Security(asset_type='INDEX')`. Index codes longer than 16 characters are rejected before database writes and recorded as data-quality failures.

Both master datasets run an initial full load. Daily mode refreshes the provider's current master list and marks no unseen security as delisted without an explicit provider lifecycle status; temporary provider omissions are reported for reconciliation.

### Company Profiles And Derived Geography

`company-profile` calls `stock_company` once per supported exchange (`SSE`, `SZSE`, `BSE`) with explicit fields: `ts_code`, `exchange`, `chairman`, `manager`, `reg_capital`, `setup_date`, `province`, `secretary`, `city`, `introduction`, `website`, `email`, `office`, `employees`, `main_business`, and `business_scope`.

The adapter normalizes trimmed province and city names, then upserts `Province`, `City(province, name)`, and `CompanyProfile`. Missing province/city remains null and produces an ingestion-quality record; it must not default either value to Shanghai. The command preserves raw `province_name` and `city_name` for traceability. Region is resolved only through an active `ProvinceRegionMapping`; no row is invented for an unmapped province.

### Stock Bars And Adjustment Factors

`stock-bars` requests Tushare `stk_factor`, not `daily` plus `adj_factor`. Required fields are `ts_code`, `trade_date`, raw `open`, `high`, `low`, `close`, `pre_close`, `change`, `pct_change`, `vol`, `amount`, `adj_factor`, and qfq/hfq OHLC/pre-close fields. `vol` maps to `volume`, and `adj_factor` maps directly to `MarketBarDailyHistory.adj_factor`. The provider qfq/hfq values are persisted directly after numeric validation; qfq/hfq `change` and `pct_change` are calculated locally from their adjusted close and pre-close values because Tushare does not return those four derived columns.

The adapter must reject a nonempty `stk_factor` payload missing its required adjusted-price columns; it must not silently publish null qfq/hfq fields. This replaces the initial `daily`-only stock-bar implementation, which cannot populate adjusted history.

Daily all-market bar retrieval is preferred when querying a single completed `trade_date`. Historical backfill splits date intervals and securities into bounded chunks. Each successful chunk upserts `MarketBarDailyHistory`, conditionally updates `MarketBarLatest(frequency='D')`, records counters, and commits atomically.

### Corporate Actions And Adjustment Rebuilds

`corporate-actions` is a planned post-stock-bars event scan using Tushare `dividend`. It requests dividend event identity and status fields plus `ann_date`, `record_date`, `ex_date`, cash/share distribution fields, and update fields required to detect provider revisions.

For each new or materially revised ex-date event, the command creates or updates a future `CorporateActionEvent` record and schedules exactly one idempotent full retained-history `stk_factor` refresh for the affected stock. The refresh upserts historical qfq/hfq data, recalculates the `MarketBarLatest` daily row, and invalidates only that security's EOD cache entries. It remains a planned feature until its event table, rebuild command, locking, and tests are implemented.

### Stock Fundamentals And Cost Distribution

`stock-fundamentals` calls `daily_basic` and requests: `ts_code`, `trade_date`, `close`, `turnover_rate`, `turnover_rate_f`, `volume_ratio`, `pe`, `pe_ttm`, `pb`, `ps`, `ps_ttm`, `dv_ratio`, `dv_ttm`, `total_share`, `float_share`, `free_share`, `total_mv`, and `circ_mv`. It preserves the documented source units: share counts in ten thousand shares and market capitalizations in ten thousand yuan.

`stock-cost` calls `cyq_perf` and requests: `ts_code`, `trade_date`, `his_low`, `his_high`, `cost_5pct`, `cost_15pct`, `cost_50pct`, `cost_85pct`, `cost_95pct`, `weight_avg`, and `winner_rate`.

Both datasets normalize `NaN`, infinity, and empty numeric cells to null before decimal conversion. They upsert history by `(security_id, trade_date)` and update a latest row only when the source date is newer, or the source date matches with a newer source revision timestamp. Backfilling older history must never downgrade a latest snapshot.

### Index Bars And Index Fundamentals

`index-bars` resolves index codes from `Security(asset_type='INDEX')` or the requested named index universe, then calls `index_daily`. Required fields are `ts_code`, `trade_date`, `open`, `high`, `low`, `close`, `pre_close`, `change`, `pct_chg`, `vol`, and `amount`. It maps `pct_chg` and `vol` as for stock bars. Index adjustment columns remain null because no approved index adjustment-factor source exists.

`index-fundamentals` calls `index_dailybasic` and requests all required fields: `ts_code`, `trade_date`, `pe`, `pe_ttm`, `pb`, `turnover_rate`, `turnover_rate_f`, `total_mv`, and `float_mv`. It writes only for securities whose `asset_type` is `INDEX`; a stock code returned by a malformed payload is rejected.

Historical index requests are paginated backward from the requested end date. Paged records are deduplicated by `(ts_code, trade_date)` before persistence. Daily index refresh uses the same overlap upsert policy as stock daily datasets.

### Weekly And Monthly Resampling

`resample` reads completed daily PostgreSQL data only. It requires `--frequency W` or `--frequency M`, never calls Tushare, and runs only after the matching daily watermark is complete.

It creates weekly/monthly bar records using open/pre-close first value, high maximum, low minimum, close/adjustment factor last value, volume/amount/change sums, and recalculated percentage changes. Fundamentals use documented period-end rules and cost distribution uses the final daily observation. The initial command implementation may reject `resample` until the weekly/monthly physical tables are migrated; it must not silently write W/M data into a daily table.

## Execution Ordering

### Initial Historical Backfill

1. Run `security-master --mode backfill`.
2. Run `index-master --mode backfill`.
3. Run `company-profile --mode backfill`.
4. Run `stock-bars`, `stock-fundamentals`, and `stock-cost` independently. Without an explicit date argument, each first run uses `--history-years 5`.
5. Run `index-bars` and `index-fundamentals` independently for configured index universes. Without an explicit date argument, each first run uses `--history-years 5`.
6. Verify complete daily coverage, then run weekly and monthly `resample` after its physical tables exist.

The orchestrator may parallelize independent stock fundamental/cost and index dataset runs, but never two runs that can write the same dataset/scope/date natural keys. A lock derived from `(dataset, scope_key, frequency)` prevents concurrent conflicting runs.

Examples:

```text
# Default initial backfill: the latest five calendar years ending on the last completed trade date.
python manage.py sync_market_data --dataset stock-bars --mode backfill --scope all

# Reduced initial window to minimize source calls and storage.
python manage.py sync_market_data --dataset stock-fundamentals --mode backfill --history-years 2

# Controlled exceptional historical range; explicit dates are required for a range longer than the default.
python manage.py sync_market_data --dataset index-bars --mode backfill --start-date 20100101 --end-date 20191231
```

### Daily EOD Refresh

1. Refresh security and index masters, then company profiles if provider updates are expected.
2. Resolve the last completed trading date using an approved trading calendar.
3. Refresh stock bars and index bars with the overlap window.
4. Refresh stock fundamentals, stock cost distribution, and index fundamentals with the same completed-date policy.
5. Scan `dividend` events and complete any affected stock-specific adjusted-history rebuilds.
6. Reconcile data coverage and latest snapshots.
7. Resample completed weekly/monthly periods once daily watermarks are successful.

The command never treats a weekday as a trading day merely because it is not a weekend. If the trading calendar cannot resolve the completed trading date, it exits nonzero and advances no daily watermark.

### Windows Batch Schedules

`manniu_backend/schedule/daily.bat` is the daily operator entry point. It uses `C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe`, resolves the backend root from the script location, and runs these implemented daily datasets in dependency order: `security-master`, `index-master`, `company-profile`, `stock-bars`, `stock-fundamentals`, `stock-cost`, `index-bars`, and `index-fundamentals`.

`manniu_backend/schedule/market_data_init.bat` is the initial operator entry point. It uses the same virtual environment and dependency order with `--mode backfill`. For the daily historical datasets, the command's default `--history-years 5` bounds the first backfill to five years; master and company datasets refresh their available provider records. Each invocation creates `manniu_backend/log/market_data/market_data_init_YYYYMMDD_HHMMSS.log`, containing command output, errors, dataset progress, and the final status. Generated logs are excluded from version control.

Both batch files are fail-fast: a nonzero `sync_market_data` exit stops the batch immediately and returns nonzero to its scheduler. They do not invoke unavailable `resample`, named index universes, or `--resume-run` functionality. Neither file logs environment-variable values, database credentials, or the Tushare token.

## Run State, Transactions, And Watermarks

Each non-dry run creates an `IngestionRun` in `PENDING`, records its requested scope and dates, changes to `RUNNING` before the first provider call, and ends in `SUCCEEDED` or `FAILED`. Counters include source, accepted, upserted, rejected, duplicate, retry, and failed-scope counts. Error text is sanitized to exclude `TUSHARE_TOKEN`, passwords, and raw connection strings.

Each chunk runs in one transaction:

1. Validate and deduplicate the provider payload.
2. Upsert history rows through the dataset natural key.
3. Update eligible latest rows without allowing older history to replace newer snapshots.
4. Persist chunk counts and source-date coverage.
5. Commit.

Only after all chunks complete and reconciliation passes may the command set the relevant `IngestionWatermark.last_complete_source_date`, `last_complete_run`, and `status='SUCCEEDED'`. A malformed payload, unhandled provider error, exhausted retry budget, missing partition, or page-limit truncation marks the run failed and leaves that watermark unchanged.

## Provider Reliability And Data Quality

- Use the server-side `TUSHARE_TOKEN` from `manniu_backend/.env`; the token is never accepted as a CLI argument.
- Set explicit network timeouts. Retry only transient network and documented rate-limit errors with bounded exponential backoff and jitter.
- Validate schema before row processing; an invalid required schema fails the chunk before writes.
- Normalize nullable provider date fields before parsing: Pandas `NaN` and blank values become null, while a nonempty invalid date fails the affected chunk.
- Reject codes longer than 16 characters, invalid dates, values exceeding database precision, negative volume/amount, and invalid asset-type/dataset combinations.
- Canonicalize and deduplicate provider rows before database access. Record rejected rows with a reason code and sanitized field summary.
- Treat max-page exhaustion as incomplete coverage and return nonzero; do not advance a partial backfill watermark.
- Use PostgreSQL upserts, not `ignore_conflicts=True`, for overlap refreshes so corrected recent provider values are persisted.

## Operator Output And Exit Status

The command prints a compact per-dataset summary: run ID, mode, scope, requested and completed date coverage, source/accepted/upserted/rejected counts, retry count, failed scope count, and final watermark date. It must not print tokens, database passwords, or raw provider payloads.

Exit code `0` means every requested scope completed, coverage reconciled, and all eligible watermarks advanced. Any partial scope failure, validation failure, rate-limit exhaustion, pagination truncation, database transaction failure, or unreconciled gap returns nonzero. This prevents UAT schedules from treating an incomplete run as successful.

## Test Case Definition

### Core Flow

- Each dataset value maps to its documented Tushare endpoint, target history/latest models, and required field projection.
- A valid daily stock-bar payload and factor payload are joined, upserted, and update the daily latest row in one transaction.
- Valid `daily_basic`, `cyq_perf`, `index_daily`, and `index_dailybasic` payloads populate their documented history/latest targets with preserved source units.
- A successful bounded backfill persists run counters and advances only its matching dataset/scope/frequency watermark.
- A daily overlap payload revises an existing date and updates history and latest data without creating duplicate natural keys.
- A `dividend` event affecting a stock schedules exactly one retained-history `stk_factor` rebuild and updates its historical qfq/hfq values.

### Boundary Scenarios

- `company-profile` keeps null province/city unknown and never creates a Shanghai default.
- Historical stock requests are chunked; all-market daily requests use one completed trading date where the provider supports it.
- A 16-character index code is accepted; a longer code is rejected before persistence.
- A backfill older than the latest snapshot writes history but leaves the latest row unchanged.
- A duplicate dividend event cannot queue a concurrent duplicate rebuild.
- `resample` rejects provider-backed W/M use and refuses to run before weekly/monthly tables exist.

### Failure Scenarios

- Missing required columns, invalid dates, invalid decimals, or negative volume/amount fail the affected chunk and prevent its watermark advance.
- A page limit or exhausted retry budget returns nonzero and marks the run failed.
- A transaction error rolls back history, latest, chunk counters, and watermark changes together.
- An initial backfill without date arguments resolves the default five-year window before any provider request.
- An explicit `--start-date` combined with `--history-years`, nonpositive `--history-years`, or `--history-years` used in daily mode fails before any provider request.
- Logs and exception summaries are checked to ensure tokens and database credentials never appear.
- A failed dividend rebuild leaves the event pending and does not advance the adjusted-history watermark.
- The daily and initial batch files use the specified `ASI_DEV/.venv` interpreter, run datasets in dependency order, and stop at the first failed command.

## Implementation Sequence

1. Completed: add CLI argument parsing and pure validation tests for datasets, modes, scopes, dates, default five-year windows, frequency rules, and unavailable feature rejection.
2. Completed: implement initial Tushare master/company/daily adapters, normalization, PostgreSQL upserts, history/latest updates, and run/watermark lifecycle with mocked fundamental-ingestion tests.
3. Add bounded endpoint-specific paging, timeouts, retry/backoff, source-revision comparison, and sanitized exception tests.
4. Add persisted chunk-level resume and scoped locks; until this step completes, `--resume-run` is explicitly rejected rather than silently ignored.
5. Replace the initial stock-bar `daily` path with `stk_factor` direct qfq/hfq persistence, then implement `dividend` event detection and stock-specific adjusted-history rebuilds.
6. After weekly/monthly physical tables are approved and migrated, implement `resample` and its completeness checks.