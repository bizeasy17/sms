# Financials Backend Design

## Status And Ownership

`financials` is an already registered but currently empty `manniu_backend` Django app. It will own the ingestion, PostgreSQL persistence, auditability, period/as-of selection, and read-optimized snapshots of Tushare corporate financial data. No financial models, migrations, sync command, public API, or data write is implemented by this design.

`financials` consumes `market_data.Security` for stock identity and listing lifecycle. `market_data` remains the owner of trading bars, market master data, and Tushare market-data ingestion. `financials` supports research, valuation, selection, backtesting, and decision support only; it must never create or execute trading orders.

## Source Coverage

| Domain dataset | Tushare endpoint | Primary use |
| --- | --- | --- |
| Income statement | `income_vip` | Revenue, profit, EPS, historical statements |
| Balance sheet | `balancesheet_vip` | Assets, liabilities, equity, debt and liquidity |
| Cash flow | `cashflow_vip` | Operating, investing, and financing cash flow |
| Performance forecast | `forecast_vip` | Forecast range and expected profit change |
| Performance express | `express_vip` | Earnings flash updates |
| Dividend/corporate action | `dividend` | Cash/share dividends and ex-date data |
| Financial indicators | `fina_indicator_vip` | ROE, ROA, margins, growth, solvency, turnover |
| Audit opinion | `fina_audit` | Audit result and fees |
| Main business composition | `fina_mainbz_vip` | Segment/product/region sales and profit |
| Disclosure schedule | `disclosure_date` | Announcement, planned, actual, and modified dates |

All source records retain the provider response identity and dates. The data model does not collapse revisions into a single untraceable row.

## Architecture

```mermaid
flowchart LR
    Tushare[Tushare Pro financial endpoints] --> Adapter[financials adapter]
    Adapter --> Normalize[Validation and normalization]
    Normalize --> Raw[Endpoint raw-record repositories]
    Raw --> AsOf[As-of and feature projection services]
    AsOf --> Snapshot[Financial feature snapshots and panels]
    Snapshot --> Consumer[valuation, selection, backtesting, sentiment]
    Snapshot --> API[Future api_gateway]
    Access[Future access_control] --> API
    Adapter --> Run[Financial ingestion runs and watermarks]
```

The adapter owns explicit endpoint projections, Tushare paging, transient-error handling, and secret-safe errors. Normalization owns `NaN` conversion, scalar conversion, endpoint date selection, and deterministic row signatures. Repositories own PostgreSQL writes. Query services select only data that was public at an explicit `as_of_date`; public API handlers must delegate to those services after `access_control` authorization.

## PostgreSQL Persistence Design

### Raw Endpoint Records

Each Tushare endpoint uses a dedicated raw-record table instead of a single sparse mega-table. Every table has a `security_id` foreign key to `market_data.Security`, original `ts_code`, provider dates, `row_signature`, `source_revision_at` when available, `source`, `imported_at`, and raw endpoint fields.

The common natural key is `(security_id, ann_date, end_date, period, row_signature)`. `row_signature` is a SHA-1 or equivalent deterministic hash of normalized provider fields that distinguish repeated rows, such as business-composition item or dividend proposal. It permits different valid disclosures for the same report date while making identical repeats idempotent.

| Planned table | Endpoint | Core fields | Required indexes |
| --- | --- | --- | --- |
| `financials_income_record` | `income_vip` | revenue, total revenue, operating/total/net profit, attributable profit, EPS | unique natural key; `(security_id, end_date DESC)`; `(ann_date)` |
| `financials_balance_sheet_record` | `balancesheet_vip` | total assets/liabilities/equity, cash, receivables, inventory, short/long borrowings | same |
| `financials_cashflow_record` | `cashflow_vip` | operating, investing, financing, net cash change | same |
| `financials_forecast_record` | `forecast_vip` | forecast type, change range, profit range | same |
| `financials_express_record` | `express_vip` | revenue, net profit, assets, EPS | same |
| `financials_dividend_record` | `dividend` | cash/share distribution, record date, ex-date | natural key; `(security_id, ex_date DESC)`; `(ann_date)` |
| `financials_indicator_record` | `fina_indicator_vip` | profitability, growth, margin, solvency, turnover, cash-flow ratios | same |
| `financials_audit_record` | `fina_audit` | audit result, audit fee | same |
| `financials_main_business_record` | `fina_mainbz_vip` | item/category, sales, profit | same |
| `financials_disclosure_record` | `disclosure_date` | announcement, planned, actual, modified disclosure dates | natural key; `(ann_date, security_id)`; `(security_id, end_date DESC)` |

Date fields are PostgreSQL `DATE` when supplied in valid `YYYYMMDD` format. Provider values that have no date meaning remain text. Financial amounts and ratios use documented `NUMERIC` precision, not floats: monetary quantities and shares use `NUMERIC(24, 4)`, per-share values use `NUMERIC(18, 6)`, and percentages/ratios use signed `NUMERIC(18, 6)`. The implementation must document the provider unit for each endpoint field and never silently convert units.

### Read Models

Raw endpoint records optimize audit and replay. Downstream high-frequency consumers read two projection tables:

- `FinancialFeaturePanel`: one row per `(security_id, end_date, report_type, source_as_of_date)`, assembled from the latest valid source records published no later than `source_as_of_date`. It contains the approved core income, balance-sheet, cash-flow, and indicator fields used by valuation, selection, backtesting, and sentiment.
- `FinancialFeatureLatest`: one row per `security_id`, derived from the newest eligible `FinancialFeaturePanel`; it contains the `end_date`, `ann_date`, `source_as_of_date`, report type, core features, and projection timestamp.

`FinancialFeaturePanel` has unique `(security_id, end_date, report_type, source_as_of_date)`, `(security_id, source_as_of_date DESC)`, `(end_date, report_type, security_id)`, and `(ann_date, security_id)` indexes. `FinancialFeatureLatest` has unique `security_id`, `(end_date DESC)`, and only measured, approved screening indexes. The latest table removes `MAX(end_date)` scans over millions of raw records from frontend stock lists and valuation cards.

## As-Of And Revision Rules

Financial data is publication-time sensitive. A feature used on trade date $t$ may only use a raw record with an effective public date no later than $t$:

$$
effectiveDate = actualDate \;\text{when present, otherwise}\; annDate
$$

Rows without both dates are retained for audit but excluded from time-sensitive projections until a valid date is available. `disclosure_date` revisions update the effective-date selection only through a versioned, idempotent projection rebuild. An amendment creates a new raw signature or source revision and does not erase the previous evidence.

Forecasts, express reports, dividends, and audits may have multiple events per period. They remain endpoint records and are selected by explicit consumer policy; they are not silently merged into a statement value. Backtests must request an explicit `as_of_date`; live valuation/selection reads `FinancialFeatureLatest` only when its source-as-of date is not later than the requested date.

## Ingestion Control And Reliability

`FinancialIngestionRun` stores endpoint list, requested scope/date coverage, start/finish time, status, source/accepted/upserted/rejected counts, pagination/retry counts, and sanitized error summary. `FinancialIngestionWatermark` is unique by `(endpoint, scope_key)` and records the last complete announcement-date or endpoint-specific source cursor.

Endpoint writes occur in transactions per bounded page/chunk. A successful chunk writes raw records and its counters together. A watermark advances only after every requested page and coverage check succeeds. Logs, database records, and errors must never contain `TUSHARE_TOKEN`, database passwords, or raw connection strings.

## Consumer And API Boundary

No API is defined or implemented. Future `api_gateway` read APIs must accept bounded symbol/date/range queries and delegate to `financials` as-of query services. `access_control` must authorize public reads before the service call. Operational import runs, raw endpoints, error details, and broad export access are operator-only.

## Test Case Definition

### Core Flow

- Every endpoint maps to its dedicated raw model, deterministic natural key, and documented projection fields.
- A repeated normalized provider row upserts idempotently, while a material revision remains auditable.
- An eligible statement/indicator set builds one panel row and updates the matching latest row.
- A historical as-of projection uses only disclosure records public on or before the requested date.

### Boundary Scenarios

- Multiple dividend or main-business rows for one security/report period remain distinct through row signatures.
- Missing/invalid optional publication dates are retained as raw data but excluded from time-sensitive projections.
- Latest-feature reads use the one-row snapshot rather than scanning raw history.
- A provider field not in a typed projection remains in the endpoint raw payload under the endpoint schema policy.

### Failure Scenarios

- A malformed required endpoint payload, exhausted page limit, or failed chunk leaves the endpoint watermark unchanged.
- A projection cannot use a statement whose effective date is after the requested as-of date.
- Tokens, passwords, and connection strings are absent from command output and persisted error summaries.
- No financial calculation or API path creates an automatic trading action.

## Implementation Sequence

1. Confirm concrete table names, core typed field list/units for every endpoint, row-signature policy, and effective-date precedence.
2. Implement raw endpoint models, run/watermark models, PostgreSQL migrations, indexes, and model-contract tests.
3. Implement adapter, normalization, pagination, and endpoint repository upserts with mocked Tushare tests.
4. Implement disclosure-date ingestion and as-of panel/latest projection rebuilds with no-lookahead tests.
5. Implement the operator CLI, backfill/daily scheduling, reconciliation artifacts, and failure exit behavior.
6. Confirm API and authorization contracts before implementing read endpoints.