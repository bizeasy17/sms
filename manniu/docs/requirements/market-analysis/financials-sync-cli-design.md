# Financials Sync CLI Design

## Status And Purpose

This document defines the planned operator-only `sync_financials` command for the `financials` app. It follows the two complementary reference patterns: symbol/endpoint full-history sync for statements and indicators, plus announcement-date pagination for `disclosure_date`. It is design only; no command or data write is implemented.

## Endpoint Sets

```text
statement: income_vip, balancesheet_vip, cashflow_vip, fina_indicator_vip
event: forecast_vip, express_vip, dividend, fina_audit, fina_mainbz_vip
disclosure: disclosure_date
```

The default sync set includes all ten endpoints. Operators may select a subset only with `--endpoints`; dependency-safe schedules run disclosure after the other financial endpoints so publication dates are available for projection rebuilds.

## Command Interface

```text
python manage.py sync_financials \
  --mode backfill|daily \
  [--endpoints ENDPOINT[,ENDPOINT...]] \
  [--scope all|ts-code|announcement-date] [--ts-codes CODE[,CODE...]] \
  [--start-date YYYYMMDD|--history-years N] [--end-date YYYYMMDD] \
  [--page-size N] [--max-pages N] [--batch-size N] [--dry-run]
```

### Argument Rules

- `--mode backfill` defaults to `--history-years 5` when no explicit start date is provided. `--start-date` and `--history-years` are mutually exclusive; explicit date ranges are required for exceptional older history.
- `--mode daily` uses a configurable announcement-date overlap, defaulting to 14 calendar days, to capture late filings and amended disclosures. It rejects historical start/year arguments.
- `--scope ts-code` requires canonical, comma-separated codes that exist as stock `market_data.Security` records. Statement and event endpoints use symbol scope.
- `--scope announcement-date` is valid only for `disclosure_date`; it pages each requested date, filters optional symbol prefixes/codes, and avoids a full per-symbol scan.
- `--page-size`, `--max-pages`, and `--batch-size` have safe endpoint-specific defaults and hard limits. Page-limit exhaustion is a failed incomplete run, never a successful partial sync.
- `--dry-run` validates command combinations and plans requests without calling Tushare or writing raw records, run state, watermarks, or projections.

## Endpoint Execution Design

### Symbol And Endpoint History

For each selected stock and endpoint, the adapter uses explicit supported parameters, trying endpoint-safe date forms only where documented: `start_date/end_date`, `ann_date/end_date`, report `period`, then code-only requests. It requests a bounded page with `limit` and `offset`, stops on an empty/short page, and detects repeated first-row signatures to prevent an infinite pagination loop.

The response is normalized before persistence: `NaN` becomes null, nested provider values become JSON text, date candidates are selected from `ann_date`, `f_ann_date`, `publish_date`, `end_date`, and `period`, and a deterministic normalized row signature is calculated. Records upsert by their raw-table natural key. Any new endpoint field is either accepted into an approved raw JSON payload or rejected under a strict schema policy; it must not trigger uncontrolled runtime DDL.

### Disclosure-Date Range Sync

`disclosure_date` runs by `ann_date` from `--start-date` through `--end-date`. For each date, it calls:

```text
pro.disclosure_date(ann_date=YYYYMMDD, limit=PAGE_SIZE, offset=OFFSET)
```

It continues until an empty or short page, filters requested symbol scope, normalizes `ann_date`, `end_date`, `pre_date`, `actual_date`, and `modify_date`, then upserts each record by the common raw natural key. This design avoids downloading all symbols just to discover newly announced reports.

## Backfill And Daily Ordering

### Initial Backfill

1. Confirm `market_data.Security` stock master coverage.
2. Backfill statement endpoints and event endpoints for the latest five years by default.
3. Backfill `disclosure_date` by announcement-date range covering the same window.
4. Reconcile raw records, then build `FinancialFeaturePanel` and `FinancialFeatureLatest` for each eligible as-of date.

### Daily Refresh

1. Refresh selected statement/event endpoints using recently listed stocks plus the announcement-date overlap policy where supported.
2. Refresh `disclosure_date` over the 14-day overlap.
3. Rebuild projections for securities/periods changed by raw or disclosure records.
4. Reconcile endpoint coverage, projection freshness, and watermarks.

Independent endpoints may run in parallel, but two runs cannot write the same `(endpoint, scope, page/date)` set. A scoped lock prevents conflicting writes and projection rebuilds.

## Reliability, Output, And Exit Behavior

Tushare access uses the server-side `TUSHARE_TOKEN` from `manniu_backend/.env`; it is never a CLI argument or log value. Requests have explicit timeouts and retry only documented transient/rate-limit errors using bounded exponential backoff with jitter.

Each run outputs endpoint, scope, requested/completed coverage, source/accepted/upserted/rejected counts, page/retry count, projection rebuild count, and final watermark. A failed endpoint, malformed required response, failed transaction, repeated-page loop, or max-page exhaustion returns nonzero and prevents that endpoint watermark from advancing.

## Test Case Definition

### Core Flow

- A statement endpoint fetches multiple pages, deduplicates normalized rows, and idempotently upserts its raw table.
- `disclosure_date` paginates a requested announcement-date range without a full-symbol scan.
- A five-year default backfill calculates the expected date window and creates no writes in dry-run mode.
- A changed disclosure date triggers a bounded as-of panel/latest projection rebuild.

### Boundary Scenarios

- A multiple-row business-composition or dividend response produces distinct raw signatures.
- A page shorter than the configured limit ends pagination normally.
- A repeated page signature terminates as a failure rather than looping indefinitely.
- A late announcement inside the daily overlap updates the raw record and projection.

### Failure Scenarios

- Missing Tushare credentials, invalid endpoint/scope combinations, or conflicting date arguments fail before a request.
- A required response-column failure, retry exhaustion, page-limit exhaustion, or transaction error preserves the prior watermark.
- Logs and persisted error summaries contain no token, password, or connection-string value.