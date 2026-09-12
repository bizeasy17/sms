# Financials Sync CLI Design

## 1 Status And Purpose

The operational model has two complementary paths: `daily` is the scheduled actual-date driven refresh, while `quarterly` remains the operator-run reconciliation/backfill path for data missed by daily ingestion. `backfill` remains the initial or explicitly ranged historical load.

This document defines the operator-only `sync_financials` command for the `financials` app. Because corporate financial reports (Q1 quarterly report, semi-annual report, Q3 quarterly report, and annual report) are disclosed on a quarterly basis, financial data synchronization is event-driven rather than daily. The upstream `disclosure_date` endpoint serves as the primary disclosure event detector: discovering newly announced, confirmed (`actual_date`), or modified report schedules drives targeted statement and event synchronization strictly for the affected securities and reporting periods. The command organizes operations under `backfill`, `quarterly` (event-driven), and `daily` modes.

The command owns financial raw-record ingestion, disclosure event detection, ingestion-run accounting, and watermarks. Predictive financial feature projections are owned and rebuilt by `predictive_valuation` in a separate step. A successful `sync_financials` run must not be interpreted as proof that predictive feature tables or prediction snapshots have been refreshed.

## 2 Endpoint Sets

```text
disclosure: disclosure_date (event definition source)
statement: income_vip, balancesheet_vip, cashflow_vip, fina_indicator_vip
event: forecast_vip, express_vip, dividend, fina_audit, fina_mainbz_vip
```

The default sync set includes all ten endpoints. Operators may select a subset only with `--endpoints`. In quarterly event-driven synchronization, `disclosure_date` runs first to detect active disclosure events and extract the affected `(ts_code, period)` targets, which then direct targeted queries to the statement and event endpoints. The resulting raw records may be consumed by downstream projection builders after ingestion commits.

Endpoint synchronization and model-feature consumption are separate concerns. `predictive_valuation` currently builds its module-owned projections from `income_vip`, `balancesheet_vip`, `cashflow_vip`, `fina_indicator_vip`, and `disclosure_date` raw records. Synchronizing `forecast_vip`, `express_vip`, `dividend`, `fina_audit`, or `fina_mainbz_vip` persists auditable raw data, but does not by itself add those records to the predictive feature panel; they are not part of the current predictive feature contract.

## 3 Command Interface

```text
python manage.py sync_financials \
  --mode daily|backfill|quarterly \
  [--endpoints ENDPOINT[,ENDPOINT...]] \
  [--scope all|ts-code|event-driven|announcement-date|actual-date] [--ts-codes CODE[,CODE...]] \
  [--period YYYYMMDD|--actual-date YYYYMMDD|--start-date YYYYMMDD|--history-years N] [--end-date YYYYMMDD] \
  [--page-size N] [--max-pages N] [--batch-size N] [--dry-run]
```

### 3.1 Argument Rules

- `--mode backfill` defaults to `--history-years 5` when no explicit start date is provided. `--start-date` and `--history-years` are mutually exclusive; explicit date ranges are required for exceptional older history.
- `--mode quarterly` is designed for periodic quarterly financial updates. It defaults to `--scope event-driven`, querying `disclosure_date` for the target report period or disclosure window to identify affected stocks, then fetching statements and events only for those stocks. It targets a specific report period via `--period YYYYMMDD` (e.g. `20250331`, `20250630`, `20250930`, `20251231`) or defaults to the latest active quarterly report period. It rejects multi-year historical start/year arguments.
- `--mode daily` is the scheduled daily path. It defaults to `--scope actual-date`, requests `disclosure_date(ann_date=run_date)`, then synchronizes all other endpoints only for deduplicated `(ts_code, period)` targets with `actual_date=run_date`. `--actual-date YYYYMMDD` is optional and defaults to the run date for replay verification. Daily mode requires `disclosure_date` and rejects `--period`, `--start-date`, and `--history-years`.
- `--scope event-driven` is the default for `--mode quarterly`; it uses `disclosure_date` delta events to determine which securities and report periods to sync.
- `--scope ts-code` requires canonical, comma-separated codes that exist as stock `market_data.Security` records. Statement and event endpoints sync only for the specified symbols.
- `--scope all` triggers an all-market scan for the target period/range, primarily used in initial historical backfills.
- `--scope announcement-date` is valid only for `disclosure_date`; it pages each requested date, filters optional symbol prefixes/codes, and avoids a full per-symbol scan.
- `--scope actual-date` is valid for `daily`; it is driven by the confirmed `actual_date` field and never performs an all-market financial endpoint scan.
- `--page-size`, `--max-pages`, and `--batch-size` have safe endpoint-specific defaults and hard limits. Page-limit exhaustion is a failed incomplete run, never a successful partial sync.
- `--dry-run` validates command combinations and plans requests without calling Tushare or writing raw records, run state, watermarks, or projections.

## 4 Endpoint Execution Design

### 4.1 Symbol And Endpoint History

For each selected stock and endpoint, the adapter uses explicit supported parameters, trying endpoint-safe date forms only where documented: `start_date/end_date`, `ann_date/end_date`, report `period`, then code-only requests. It requests a bounded page with `limit` and `offset`, stops on an empty/short page, and detects repeated first-row signatures to prevent an infinite pagination loop.

The response is normalized before persistence: `NaN` becomes null, nested provider values become JSON text, date candidates are selected from `ann_date`, `f_ann_date`, `publish_date`, `end_date`, and `period`, and a deterministic normalized row signature is calculated. Records upsert by their raw-table natural key. Any new endpoint field is either accepted into an approved raw JSON payload or rejected under a strict schema policy; it must not trigger uncontrolled runtime DDL.

### 4.2 Disclosure-Date Range Sync & Event Detection

`disclosure_date` runs by `ann_date` from `--start-date` through `--end-date` or by target report `period`. For announcement date scanning, it calls:

```text
pro.disclosure_date(ann_date=YYYYMMDD, limit=PAGE_SIZE, offset=OFFSET)
```

It continues until an empty or short page, filters requested symbol scope, normalizes `ann_date`, `end_date`, `pre_date`, `actual_date`, and `modify_date`, then upserts each record by the common raw natural key. The event detector compares ingested disclosure records against watermarks and prior states to generate the list of newly disclosed or updated `(security_id, period)` events.

For the daily path, the adapter requests only `ann_date=run_date`. The event detector combines newly returned disclosure rows with persisted rows and selects `actual_date=run_date`; this ensures a report first discovered today is not missed while repeated daily runs remain idempotent.

## 5 Backfill And Quarterly Ordering

### 5.1 Initial Backfill

1. Confirm `market_data.Security` stock master coverage.
2. Backfill statement endpoints and event endpoints for the latest five years by default.
3. Backfill `disclosure_date` by announcement-date range covering the same window.
4. Reconcile raw records. If predictive features are required, invoke the separately owned `predictive_valuation` feature-builder workflow for the affected securities and report periods; this is not performed by `sync_financials`.

### 5.2 Quarterly Refresh (Event-Driven)

1. **Disclosure Event Discovery**: Refresh `disclosure_date` across the quarterly disclosure window / target period to capture planned, actual (`actual_date`), and amended dates. Detect newly disclosed or updated `(ts_code, period)` events.
2. **Targeted Ingestion**: For the detected securities and periods, perform targeted fetching of statement endpoints (`income_vip`, `balancesheet_vip`, `cashflow_vip`, `fina_indicator_vip`) and event endpoints (`forecast_vip`, `express_vip`, `dividend`, `fina_audit`, `fina_mainbz_vip`), eliminating unnecessary full-market queries.
3. **Downstream Handoff**: Report the affected securities and periods after raw records commit. `predictive_valuation` may then rebuild its own `PredictiveFinancialFeaturePanel` and `PredictiveFinancialFeatureLatest` rows using its feature contract and as-of rules.
4. **Reconcile And Watermark**: Reconcile endpoint coverage and advance financial ingestion watermarks. Projection freshness is tracked by the downstream predictive run, not by this financial ingestion run.

### 5.3 Daily Actual-Date Refresh

1. Request `disclosure_date` for the run date using `ann_date=YYYYMMDD`.
2. Persist the disclosure rows and select all unique `(ts_code, period)` rows whose confirmed `actual_date` equals the run date.
3. Fetch the nine non-disclosure statement/event endpoints only for those targets.
4. Advance watermarks only after all targeted endpoint requests succeed. A run with zero due reports performs no financial endpoint requests and does not trigger a predictive projection rebuild.

Daily refresh is the normal production path. Quarterly event-driven refresh remains available to reconcile missed daily runs, late upstream disclosure changes, or incomplete endpoint coverage across a target report period.

Independent endpoints may run in parallel, but two runs cannot write the same `(endpoint, scope, page/date)` set. A scoped lock prevents conflicting financial ingestion writes. Any predictive projection lock belongs to the `predictive_valuation` workflow.

## 6 Reliability, Output, And Exit Behavior

Tushare access uses the server-side `TUSHARE_TOKEN` from `manniu_backend/.env`; it is never a CLI argument or log value. Requests have explicit timeouts and retry only documented transient/rate-limit errors using bounded exponential backoff with jitter.

Each run outputs endpoint, scope, requested/completed coverage, source/accepted/upserted/rejected counts, page/retry count, impacted-security count, and final watermark. `projection_rebuild_count` is retained on the ingestion-run record for compatibility but is currently always `0`; it is a legacy placeholder and has no runtime meaning until an explicit downstream integration contract is implemented. Predictive projection rebuild counts belong to the separate predictive valuation run. A failed endpoint, malformed required response, failed transaction, repeated-page loop, or max-page exhaustion returns nonzero and prevents that endpoint watermark from advancing.

## 7 Test Case Definition

### 7.1 Core Flow

- A statement endpoint fetches multiple pages, deduplicates normalized rows, and idempotently upserts its raw table.
- `disclosure_date` paginates a requested announcement-date range without a full-symbol scan.
- `disclosure_date` delta event detection correctly drives targeted statement and event endpoint queries for affected securities.
- A five-year default backfill calculates the expected date window and creates no writes in dry-run mode.
- A changed disclosure date produces an affected-security/report-period handoff that a separate predictive valuation workflow can use for a bounded as-of panel/latest rebuild.

### 7.2 Boundary Scenarios

- A multiple-row business-composition or dividend response produces distinct raw signatures.
- A page shorter than the configured limit ends pagination normally.
- A repeated page signature terminates as a failure rather than looping indefinitely.
- A quarterly report revision or amended disclosure updates the raw record; the downstream predictive workflow independently rebuilds the affected module-owned projection when requested.
- An event-driven run with zero new disclosure events skips statement fetching with zero unnecessary Tushare requests.

### 7.3 Failure Scenarios

- Missing Tushare credentials, invalid endpoint/scope combinations, or conflicting date arguments fail before a request.
- A required response-column failure, retry exhaustion, page-limit exhaustion, or transaction error preserves the prior watermark.
- Logs and persisted error summaries contain no token, password, or connection-string value.

## 8 TODO List

- [ ] 按本文档完成财务同步 CLI 的失败恢复验证和单元测试，并在测试通过后更新本条状态。
- [ ] 明确并实现 financials 到下游消费者的 affected-security/report-period handoff；在此之前不得将 `projection_rebuild_count` 解释为实际重建数量。
