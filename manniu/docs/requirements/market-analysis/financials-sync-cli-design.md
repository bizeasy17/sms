# Financials Sync CLI Design

## Status And Purpose

This document defines the planned operator-only `sync_financials` command for the `financials` app. Because corporate financial reports (Q1 quarterly report, semi-annual report, Q3 quarterly report, and annual report) are disclosed on a quarterly basis, financial data synchronization is event-driven rather than daily. The upstream `disclosure_date` endpoint serves as the primary disclosure event detector: discovering newly announced, confirmed (`actual_date`), or modified report schedules drives targeted statement and event synchronization strictly for the affected securities and reporting periods. The command organizes operations under `backfill` and `quarterly` (event-driven) modes. It is design only; no command or data write is implemented.

## Endpoint Sets

```text
disclosure: disclosure_date (event definition source)
statement: income_vip, balancesheet_vip, cashflow_vip, fina_indicator_vip
event: forecast_vip, express_vip, dividend, fina_audit, fina_mainbz_vip
```

The default sync set includes all ten endpoints. Operators may select a subset only with `--endpoints`. In quarterly event-driven synchronization, `disclosure_date` runs first to detect active disclosure events and extract the affected `(ts_code, period)` targets, which then direct targeted queries to the statement and event endpoints before projection rebuilds.

## Command Interface

```text
python manage.py sync_financials \
  --mode backfill|quarterly \
  [--endpoints ENDPOINT[,ENDPOINT...]] \
  [--scope all|ts-code|event-driven|announcement-date] [--ts-codes CODE[,CODE...]] \
  [--period YYYYMMDD|--start-date YYYYMMDD|--history-years N] [--end-date YYYYMMDD] \
  [--page-size N] [--max-pages N] [--batch-size N] [--dry-run]
```

### Argument Rules

- `--mode backfill` defaults to `--history-years 5` when no explicit start date is provided. `--start-date` and `--history-years` are mutually exclusive; explicit date ranges are required for exceptional older history.
- `--mode quarterly` is designed for periodic quarterly financial updates. It defaults to `--scope event-driven`, querying `disclosure_date` for the target report period or disclosure window to identify affected stocks, then fetching statements and events only for those stocks. It targets a specific report period via `--period YYYYMMDD` (e.g. `20250331`, `20250630`, `20250930`, `20251231`) or defaults to the latest active quarterly report period. It rejects multi-year historical start/year arguments.
- `--scope event-driven` is the default for `--mode quarterly`; it uses `disclosure_date` delta events to determine which securities and report periods to sync.
- `--scope ts-code` requires canonical, comma-separated codes that exist as stock `market_data.Security` records. Statement and event endpoints sync only for the specified symbols.
- `--scope all` triggers an all-market scan for the target period/range, primarily used in initial historical backfills.
- `--scope announcement-date` is valid only for `disclosure_date`; it pages each requested date, filters optional symbol prefixes/codes, and avoids a full per-symbol scan.
- `--page-size`, `--max-pages`, and `--batch-size` have safe endpoint-specific defaults and hard limits. Page-limit exhaustion is a failed incomplete run, never a successful partial sync.
- `--dry-run` validates command combinations and plans requests without calling Tushare or writing raw records, run state, watermarks, or projections.

## Endpoint Execution Design

### Symbol And Endpoint History

For each selected stock and endpoint, the adapter uses explicit supported parameters, trying endpoint-safe date forms only where documented: `start_date/end_date`, `ann_date/end_date`, report `period`, then code-only requests. It requests a bounded page with `limit` and `offset`, stops on an empty/short page, and detects repeated first-row signatures to prevent an infinite pagination loop.

The response is normalized before persistence: `NaN` becomes null, nested provider values become JSON text, date candidates are selected from `ann_date`, `f_ann_date`, `publish_date`, `end_date`, and `period`, and a deterministic normalized row signature is calculated. Records upsert by their raw-table natural key. Any new endpoint field is either accepted into an approved raw JSON payload or rejected under a strict schema policy; it must not trigger uncontrolled runtime DDL.

### Disclosure-Date Range Sync & Event Detection

`disclosure_date` runs by `ann_date` from `--start-date` through `--end-date` or by target report `period`. For announcement date scanning, it calls:

```text
pro.disclosure_date(ann_date=YYYYMMDD, limit=PAGE_SIZE, offset=OFFSET)
```

It continues until an empty or short page, filters requested symbol scope, normalizes `ann_date`, `end_date`, `pre_date`, `actual_date`, and `modify_date`, then upserts each record by the common raw natural key. The event detector compares ingested disclosure records against watermarks and prior states to generate the list of newly disclosed or updated `(security_id, period)` events.

## Backfill And Quarterly Ordering

### Initial Backfill

1. Confirm `market_data.Security` stock master coverage.
2. Backfill statement endpoints and event endpoints for the latest five years by default.
3. Backfill `disclosure_date` by announcement-date range covering the same window.
4. Reconcile raw records, then build `FinancialFeaturePanel` and `FinancialFeatureLatest` for each eligible as-of date.

### Quarterly Refresh (Event-Driven)

1. **Disclosure Event Discovery**: Refresh `disclosure_date` across the quarterly disclosure window / target period to capture planned, actual (`actual_date`), and amended dates. Detect newly disclosed or updated `(ts_code, period)` events.
2. **Targeted Ingestion**: For the detected securities and periods, perform targeted fetching of statement endpoints (`income_vip`, `balancesheet_vip`, `cashflow_vip`, `fina_indicator_vip`) and event endpoints (`forecast_vip`, `express_vip`, `dividend`, `fina_audit`, `fina_mainbz_vip`), eliminating unnecessary full-market queries.
3. **Incremental Projection Rebuild**: Rebuild projections (`FinancialFeaturePanel` and `FinancialFeatureLatest`) for securities/periods changed by new raw statement or disclosure records.
4. **Reconcile And Watermark**: Reconcile endpoint coverage, projection freshness, and advance watermarks.

Independent endpoints may run in parallel, but two runs cannot write the same `(endpoint, scope, page/date)` set. A scoped lock prevents conflicting writes and projection rebuilds.

## Reliability, Output, And Exit Behavior

Tushare access uses the server-side `TUSHARE_TOKEN` from `manniu_backend/.env`; it is never a CLI argument or log value. Requests have explicit timeouts and retry only documented transient/rate-limit errors using bounded exponential backoff with jitter.

Each run outputs endpoint, scope, requested/completed coverage, source/accepted/upserted/rejected counts, page/retry count, projection rebuild count, and final watermark. A failed endpoint, malformed required response, failed transaction, repeated-page loop, or max-page exhaustion returns nonzero and prevents that endpoint watermark from advancing.

## Test Case Definition

### Core Flow

- A statement endpoint fetches multiple pages, deduplicates normalized rows, and idempotently upserts its raw table.
- `disclosure_date` paginates a requested announcement-date range without a full-symbol scan.
- `disclosure_date` delta event detection correctly drives targeted statement and event endpoint queries for affected securities.
- A five-year default backfill calculates the expected date window and creates no writes in dry-run mode.
- A changed disclosure date triggers a bounded as-of panel/latest projection rebuild.

### Boundary Scenarios

- A multiple-row business-composition or dividend response produces distinct raw signatures.
- A page shorter than the configured limit ends pagination normally.
- A repeated page signature terminates as a failure rather than looping indefinitely.
- A quarterly report revision or amended disclosure updates the raw record and projection for the affected symbol.
- An event-driven run with zero new disclosure events skips statement fetching with zero unnecessary Tushare requests.

### Failure Scenarios

- Missing Tushare credentials, invalid endpoint/scope combinations, or conflicting date arguments fail before a request.
- A required response-column failure, retry exhaustion, page-limit exhaustion, or transaction error preserves the prior watermark.
- Logs and persisted error summaries contain no token, password, or connection-string value.