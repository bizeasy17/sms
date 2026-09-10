# Predictive Valuation CLI Design

## 1 Status And Purpose

This document defines the operator-only `predictive_valuation` Django command for
`manniu_backend.predictive_valuation`. The currently implemented command supports
`validate`, `build-features`, `backfill-features`, `backfill-valuations`,
`detect-events`, `consume-events`, `refresh`, and `status`. Resumable runs and
chunk-level completion watermarks remain planned work.

The CLI constructs model-compatible financial feature panels from persisted `financials`
raw records, then produces predictive valuation snapshots from persisted `market_data`
and predictive financial feature records. It never calls Tushare during prediction,
never exposes an HTTP endpoint, and never creates or executes trading orders.

All state is stored in the shared PostgreSQL `manniu` database. The command is not
available through `api_gateway`; `api_gateway` is a read-only downstream consumer of
completed snapshots through an internal query service.

## 2 Command Interface

```text
python manage.py predictive_valuation \
  validate|build-features|backfill-features|backfill-valuations|detect-events|consume-events|refresh|status \
  [--scope all|ts-code] [--ts-codes CODE[,CODE...]] \
  [--start-date YYYYMMDD|--history-years N] [--end-date YYYYMMDD] \
  [--report-types Q1[,H1,Q3,FY]] [--horizon HORIZON] \
  [--run-key RUN_KEY] [--limit N] [--retry-failed] [--dry-run]
```

### 2.1 Subcommands

| Subcommand | Status | Purpose |
| --- | --- | --- |
| `validate` | Implemented baseline | Validates PostgreSQL access, configuration, serving-pointer structure, required tables, model-root containment, and every configured quarterly production model. |
| `build-features` | Implemented baseline | Rebuilds the current point-in-time predictive financial panel/latest records for an explicit security scope. |
| `backfill-features` | Implemented baseline | Rebuilds historical point-in-time `PredictiveFinancialFeaturePanel` rows across a bounded date interval. |
| `backfill-valuations` | Implemented baseline | Produces append-only historical `PredictiveValuationSnapshot` rows from eligible historical panels and market features. |
| `detect-events` | Implemented financial-disclosure baseline | Detects idempotent disclosure events from persisted `FinancialDisclosureRecord` rows. |
| `consume-events` | Implemented baseline | Claims bounded pending events, rebuilds required features, runs one inference per affected security/report period, and completes or fails the event. |
| `refresh` | Implemented baseline | Runs event detection followed by consumption. It never initiates a historical backfill. |
| `status` | Implemented baseline | Reports feature, snapshot, event, and run counts. |

## 3 Argument Rules

- `--scope` defaults to `all` for historical backfills and requires either `all` or
  `ts-code`. `--scope ts-code` requires `--ts-codes`; all codes must be canonical stock
  `market_data.Security.ts_code` values and at most 16 characters.
- `--start-date` and `--history-years` are mutually exclusive. For either backfill
  command, the default is `--history-years 5` when no explicit start date is supplied.
  `--end-date` defaults to the latest completed market-data trading date.
- `--history-years` is a positive integer and is valid only for historical backfill
  commands. An explicit start date is required for exceptional ranges outside the normal
  five-year window.
- `--report-types` defaults to the active configuration's `model.report_types`:
  `Q1,H1,Q3,FY`. Values outside that set are rejected before reads or writes.
- `--horizon` defaults to `1M`. It is part of the valuation snapshot identity and must
  be an approved configured value.
- `--run-key` is optional for a new execution. A supplied key must refer to an unfinished
  compatible run when resume support is implemented; until then it is rejected rather
  than ignored.
- `--limit` bounds one invocation's securities, feature panels, or claimed events. It is
  mandatory for operator diagnostics that do not explicitly select a symbol scope.
- `--dry-run` validates arguments, configuration, feature/model compatibility, source
  coverage, and planned work. It writes no feature rows, snapshots, current rows, runs,
  events, or watermarks.

## 4 Feature History Backfill

`backfill-features` rebuilds only predictive-owned feature projections. It does not
synchronize financial data and does not call Tushare. `financials` raw records and
`market_data.Security` are prerequisites.

```text
python manage.py predictive_valuation backfill-features \
  --scope all --history-years 5 --report-types Q1,H1,Q3,FY --dry-run
```

For every selected security and report period in range, the command:

1. Selects raw `income`, `balancesheet`, `cashflow`, and `fina_indicator` records from
   `financials` for the financial `end_date`.
2. Resolves the effective public date as `FinancialDisclosureRecord.actual_date` when
   present, otherwise the relevant raw record `ann_date`.
3. Excludes a row whose effective public date is absent or later than the requested
   historical as-of boundary.
4. Writes `PredictiveFinancialFeaturePanel` using direct typed raw-field mappings only.
   It must not derive `cash_ratio` or `ocf_to_or`, and must not substitute similarly
   named fields such as `short_borrow` for `st_borr`.
5. Records source record IDs and direct field lineage in `raw_payload`.

The historical command does not update `PredictiveFinancialFeatureLatest`; that table is
reserved for current serving data. Feature rows upsert by `(security, end_date,
report_type, source_as_of_date)`. Re-running an identical scope converges to the same
state, while a raw-record/disclosure revision updates only the matching projection key.

## 5 Historical Valuation Backfill

`backfill-valuations` consumes persisted predictive financial panels and persisted market
history. It must not trigger raw-financial ingestion, fetch market data, or construct an
unpersisted financial join.

```text
python manage.py predictive_valuation backfill-valuations \
  --scope all --history-years 5 --report-types Q1,H1,Q3,FY --horizon 1M --dry-run
```

For every eligible feature panel, the command:

1. Resolves the report type and loads exactly the matching production artifact from
   `serving.yaml`: Q1 to `models_Q1.joblib`, H1 to `models_H1.joblib`, Q3 to
   `models_Q3.joblib`, and FY to `models_FY.joblib`.
2. Rejects unsupported report types, missing model mappings, model paths outside
  `PREDICTIVE_VALUATION_MODEL_ROOT`, or missing artifacts. A declared sklearn version
  that differs from the running environment emits an explicit compatibility warning but
  does not block the run. It never falls back to a different quarter's model.
3. Selects the latest completed market trading row on or before the panel's
   `source_as_of_date`. It calculates all market rolling features using only rows at or
   before that anchor date.
4. Reindexes the feature frame to the bundle's ordered `feature_cols`, then applies the
   model-version imputation statistics. It records the missing/imputed feature list and
   data-source provenance in the snapshot explanation.
5. Executes the configured classifier and regressor, maps output to bounded target return,
   price, market-cap, action, confidence, and risk values, and creates an append-only
   `PredictiveValuationSnapshot`.
6. Upserts `PredictiveValuationCurrent` only when the snapshot represents the newest
   current eligible as-of date for its `(security, horizon, model_version)` key.

The snapshot idempotency key is `(security, asof_date, horizon, model_version,
feature_contract_version)`. A rerun with unchanged inputs must not duplicate a snapshot.
A changed artifact hash, model version, or feature-contract version creates a separately
auditable result rather than overwriting historical evidence.

## 6 Ordering And Prerequisites

### 6.1 Initial Five-Year Initialization

1. Confirm `market_data` historical bars and daily fundamentals cover the target window.
2. Confirm `financials` raw records and public dates cover requested securities/report
   periods; synchronize financial data separately before this command if needed.
3. Run `predictive_valuation validate`; resolve or explicitly accept any printed model
  runtime compatibility warning before broad production backfill.
4. Run `backfill-features --dry-run`, reconcile planned rows and missing raw-field counts,
   then run the non-dry command.
5. Compare a representative sample of rebuilt panels with the legacy earnings feature
   panel before mass valuation writes.
6. Run `backfill-valuations --dry-run`, including a model compatibility and market-feature
   freshness check.
7. Run the bounded non-dry valuation backfill and reconcile snapshot count, failure count,
   model versions, and quarterly coverage.
8. Enable event-driven refresh only after the five-year baseline completes successfully.

Feature backfill can run before historical valuation backfill, but valuation backfill must
not start while feature backfill is mutating the same security scope. A lock derived from
`(command, scope_key, date_range, report_types)` prevents conflicting runs.

### 6.2 Event-Driven Refresh

1. Complete market-data and financial raw-data ingestion.
2. Detect market-regime, security-regime, and public financial-disclosure changes.
3. For each claimed event, rebuild only affected predictive feature panels.
4. Run the report-type-specific inference using the newly rebuilt panel.
5. Commit the snapshot/current update and mark the event succeeded together.

A failed event preserves its error and retry count and remains retryable. No event is
marked succeeded until its associated snapshot transaction commits.

## 7 Run State, Transactions, And Recovery

Every non-dry historical command creates a `PredictiveValuationRun` with command, scope,
date window, report types, horizon, active model versions, artifact hashes, and feature
contract version. Its status progresses from `PENDING` to `RUNNING`, then `SUCCEEDED` or
`FAILED`.

Work is chunked by security and report period. A chunk transaction writes its feature
projection or snapshot/current rows, persists counters, and commits. Failed chunks do not
advance a completion watermark or mark their run scope complete. Once resume is
implemented, the run stores the next unfinished `(security_id, end_date, report_type)`
key and resumes only remaining chunks.

`PredictiveValuationEventState` is the idempotency and retry record for event consumption;
it is not used as a substitute for a historical backfill watermark.

## 8 Operator Output And Exit Status

The CLI emits compact, sanitized summaries. It never prints `TUSHARE_TOKEN`, database
credentials, raw connection strings, complete provider payloads, or model internals.

A successful feature backfill reports run key, requested/completed date interval, security
count, candidate/eligible/upserted/skipped panel counts, direct-source null count, and
failure count. A successful valuation backfill additionally reports processed feature rows,
snapshot/current upsert counts, per-quarter model counts, imputed-feature count, and
market-feature gap failures.

Exit code `0` means all requested chunks completed and reconciliation passed. Invalid
arguments, missing prerequisites, feature-contract mismatch, missing/stale market feature
input, failed chunk, unreconciled coverage gap, or incomplete
page/resume state returns nonzero. No partial backfill may be reported as successful.

## 9 Windows Batch Schedules

Implemented operator script under `manniu_backend/schedule/`:

| Script | Command | Purpose |
| --- | --- | --- |
| `predictive_valuation.bat backfill` | `backfill-features`, then `backfill-valuations` | Bounded historical feature and valuation initialization. |
| `predictive_valuation.bat refresh` | `detect-events`, then `consume-events` | Event-driven financial-disclosure, market-regime, and security-regime refresh. |

Each script resolves `manniu_backend` from its own location, sets
`DJANGO_SETTINGS_MODULE=config.settings`, uses the approved model-serving Python runtime,
creates a timestamped log under `manniu_backend/log/predictive_valuation/`, and stops on
the first nonzero command. Batch files must not use semicolons inside `cmd.exe` command
chains and must not log environment values or credentials.

## 10 Test Case Definition

### 10.1 Core Flow

- A default `backfill-features` invocation resolves exactly five calendar years and plans
  Q1/H1/Q3/FY panels from direct financial raw fields.
- A historical feature row uses no raw record or disclosure information newer than its
  source-as-of date.
- A default `backfill-valuations` selects Q1/H1/Q3/FY production bundle mappings based on
  the feature panel report type and records the selected model version/hash.
- A repeated feature or valuation backfill converges by its documented natural key.
- A latest/current valuation read model is updated only by a newer eligible snapshot.

### 10.2 Boundary Scenarios

- A security with no disclosure record uses the relevant raw record `ann_date` as its
  public-date fallback.
- A non-trading disclosure date anchors to the latest prior completed market trading row.
- A feature panel missing a direct raw source keeps that field null and records lineage;
  it is not replaced with a derived calculation.
- A quarterly panel is rejected when its corresponding production model mapping is absent;
  the command must not use Q3 as fallback.
- A historical feature rebuild does not modify `PredictiveFinancialFeatureLatest`.

### 10.3 Failure Scenarios

- An invalid scope/date/report-type combination fails before data writes.
- A missing financial raw prerequisite, model artifact, incomplete feature contract, or
  stale market input fails the affected chunk and returns nonzero. A model/runtime version
  mismatch emits a compatibility warning and remains visible in run output.
- A failed chunk rolls back its feature/snapshot/current data and does not advance run
  completion state.
- A duplicate event cannot create duplicate historical snapshots.
- Dry-run writes no feature data, snapshot/current rows, run state, event state, or
  completion watermarks.

## 11 TODO List

- [ ] 按本文档完成预测估值 CLI 实现、干运行和失败回滚验证及单元测试，并在测试通过后更新本条状态。
