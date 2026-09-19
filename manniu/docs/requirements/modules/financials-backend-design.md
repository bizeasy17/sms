# Financials Backend Design

## 1 Status And Ownership

`financials` is an already registered `manniu_backend` Django app. It owns the ingestion, PostgreSQL persistence, auditability, period/as-of selection, and read-optimized snapshots of Tushare corporate financial data. Its read-only financial and disclosure routes are exposed through `api_gateway`; ingestion and other data-write operations remain internal.

`financials` consumes `market_data.Security` for stock identity and listing lifecycle. `market_data` remains the owner of trading bars, market master data, and Tushare market-data ingestion. `financials` supports research, valuation, selection, backtesting, and decision support only; it must never create or execute trading orders.

## 2 Source Coverage

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

## 3 Architecture

```mermaid
flowchart LR
    TushareDisc[Tushare disclosure_date] --> DiscAdapter[Disclosure schedule adapter]
    DiscAdapter --> DiscRepo[financials_disclosure_record]
    DiscRepo --> EventDetector[Disclosure event detector]
    EventDetector --"(ts_code, period) events"--> StmtAdapter[Statement & event adapter]
    TushareFin[Tushare financial endpoints] --> StmtAdapter
    StmtAdapter --> Normalize[Validation and normalization]
    Normalize --> Raw[Endpoint raw-record repositories]
    Raw --> Consumer[valuation, selection, backtesting, sentiment]
    Raw --> API[api_gateway]
    Access[access_control] --> API
    DiscAdapter --> Run[Financial ingestion runs & watermarks]
    StmtAdapter --> Run
```

Financial data updates are event-driven: the upstream `disclosure_date` endpoint serves as the primary event definition source. When new announcements, confirmed actual disclosure dates (`actual_date`), or modified schedules are detected from `disclosure_date`, the system identifies the affected securities and reporting periods `(security_id, period)`. The statement and event adapters (`income_vip`, `balancesheet_vip`, `cashflow_vip`, `fina_indicator_vip`, `fina_audit`, `fina_mainbz_vip`, `forecast_vip`, `express_vip`, `dividend`) then execute targeted queries for only the affected symbols rather than scanning the entire market. Downstream consumers own any model-specific projection rebuild after raw records commit.

Operationally, this event-driven design has two complementary paths. The daily job requests `disclosure_date` by `ann_date` for the run date, selects confirmed `actual_date=run_date` rows, and targets only those `(security_id, period)` values. The quarterly job remains an operator-run reconciliation/backfill path for missed daily runs, late disclosure changes, or incomplete endpoint coverage; it does not replace the daily path.

For the current predictive valuation contract, `predictive_valuation` reads the
`income_vip`, `balancesheet_vip`, `cashflow_vip`, `fina_indicator_vip`, and
`disclosure_date` raw records, then rebuilds its own
`PredictiveFinancialFeaturePanel` and `PredictiveFinancialFeatureLatest`. The
`forecast_vip`, `express_vip`, `dividend`, `fina_audit`, and `fina_mainbz_vip` records
remain auditable raw data but are not currently consumed by that predictive feature
builder. Running `sync_financials` therefore does not imply that predictive
projections or prediction snapshots have been refreshed.

After the affected raw rows and ingestion watermark commit, `financials` is the
sole owner of disclosure-event recognition and publication. It publishes a
committed, idempotent `FINANCIAL_DISCLOSED` event for each affected
`(security_id, report_period, source_revision)` identity. The event is not a
valuation event table owned by `financials`; it is an internal upstream event
read boundary consumed by `traditional_valuation` and `predictive_valuation`.
Those consumers copy the event into their own event-state tables and own all
projection rebuild and valuation refresh work. A financial ingestion run must
not call either valuation engine directly.

The downstream event boundary is:

```python
financials.list_disclosure_events(
    *, after_version=None, asof_date=None, security_ids=None, limit=500,
) -> DisclosureEventBatch
```

Only committed events are returned. Each event includes `event_key`,
`source_version`, `security_id`, `financial_end_date`, `ann_date`,
`effective_date`, affected endpoint/revision metadata, and detection time.
Events are retained for replay until the configured retention policy expires;
consumers advance independent checkpoints and acknowledge only after local
event-table insertion. Repeated disclosure rows and revisions are idempotent,
while a material amendment receives a new source revision and event key.

The adapter owns explicit endpoint projections, Tushare paging, transient-error handling, and secret-safe errors. Normalization owns `NaN` conversion, scalar conversion, endpoint date selection, and deterministic row signatures. Repositories own PostgreSQL writes. Query services select only data that was public at an explicit `as_of_date`; public API handlers must delegate to those services after `access_control` authorization.

## 4 PostgreSQL Persistence Design

### 4.1 Raw Endpoint Records

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

### 4.2 Consumer Projections

Raw endpoint records optimize audit and replay. `financials` does not own generic
feature-panel or latest-feature tables. Each downstream domain owns its own projection
schema and rebuild policy so persisted fields match its feature contract.
`predictive_valuation`, for example, owns its point-in-time financial panel/latest
projections and constructs them from the approved raw records before inference. The
financial ingestion run may report affected securities and periods, but it does not
rebuild these downstream projections; projection freshness and rebuild counts belong
to the downstream consumer run.

## 5 As-Of And Revision Rules

Financial data is publication-time sensitive. A feature used on trade date $t$ may only use a raw record with an effective public date no later than $t$:

$$
effectiveDate = actualDate \;\text{when present, otherwise}\; annDate
$$

Rows without both dates are retained for audit but excluded from consumer time-sensitive
projections until a valid date is available. A `disclosure_date` revision causes the
relevant consumer's versioned, idempotent projection rebuild. An amendment creates a
new raw signature or source revision and does not erase the previous evidence.

Forecasts, express reports, dividends, and audits may have multiple events per period.
They remain endpoint records and are selected by explicit consumer policy; they are not
silently merged into a statement value. Backtests must request an explicit `as_of_date`;
each consumer enforces its own point-in-time projection boundary.

## 6 Ingestion Control And Reliability

`FinancialIngestionRun` stores endpoint list, requested scope/date coverage, start/finish time, status, source/accepted/upserted/rejected counts, pagination/retry counts, and sanitized error summary. `FinancialIngestionWatermark` is unique by `(endpoint, scope_key)` and records the last complete announcement-date or endpoint-specific source cursor.

Endpoint writes occur in transactions per bounded page/chunk. A successful chunk writes raw records and its counters together. A watermark advances only after every requested page and coverage check succeeds. Logs, database records, and errors must never contain `TUSHARE_TOKEN`, database passwords, or raw connection strings.

## 7 API Gateway And Auth Integration Requirements

This section defines the financials integration contract with `api_gateway` and
`manniu_auth`/`access_control`. It is a requirements boundary, not an
implementation of HTTP views, auth models, or financial query services.

### 7.1 Integration ownership

The request path must be:

```mermaid
sequenceDiagram
        participant Client
        participant Gateway as api_gateway
        participant Access as access_control / manniu_auth
        participant Financials as financials query service
        participant DB as PostgreSQL

        Client->>Gateway: GET financial endpoint + Bearer token
        Gateway->>Access: authenticate(request, required_scopes)
        Access-->>Gateway: principal, session, scopes, request context
        Gateway->>Financials: bounded typed query with as-of boundary
        Financials->>DB: read-only indexed query
        DB-->>Financials: records and provenance
        Financials-->>Gateway: typed result/status
        Gateway-->>Client: versioned success/error envelope
```

Responsibilities are split as follows:

| Component | Financial integration responsibility | Explicit non-responsibility |
| --- | --- | --- |
| `api_gateway` | Route/version, request parsing, symbol/date/dataset allowlists, pagination limits, auth context, response envelope, error mapping, rate limiting, audit context | Financial calculations, as-of row selection, Tushare calls, raw ORM queries, writes |
| `manniu_auth` / `access_control` | Bearer token validation, session/user status, required Scope checks, principal context, authorization-denied audit event | Financial data visibility rules, report-period selection, query construction |
| `financials` | Typed read services, effective-public-date filtering, revision/provenance selection, domain statuses | Public HTTP routes, token validation, role management, cross-domain response envelopes |

Gateway views must call public `financials` query services and must not import
financial models, Tushare adapters, management commands, or Django `QuerySet`
objects directly. The query service must return a typed result containing at
least `found`, `status`, `records`, `provenance`, and `warnings`; it must not
return a DRF `Response`.

### 7.2 External routes

All routes use the existing Gateway base path and response contract:

```text
GET /api/v1/market-analysis/securities/:ts_code/financials
GET /api/v1/market-analysis/securities/:ts_code/disclosures
GET /api/v1/market-analysis/securities/:ts_code/financials/overview
```

`ts_code` is normalized to an exchange-suffixed code before the domain call.
The Gateway must reject an ambiguous or unknown symbol and must never pass an
unresolved user string to the financial query service.

`/financials` accepts:

| Parameter | Required | Contract |
| --- | --- | --- |
| `dataset` | yes | `income`, `balance_sheet`, `cashflow`, `indicator`, `forecast`, `express`, `dividend`, `audit`, or `main_business` |
| `asof_date` | conditional | Required for historical/as-of access; `YYYY-MM-DD`; cannot be future-dated |
| `end_date` | no | Report period, `YYYY-MM-DD`; must be a valid provider period boundary |
| `start_date` | no | Publication/report date lower bound; requires `end_date` and the bounded range rules |
| `page` | no | Positive integer, default `1` |
| `page_size` | no | Default `50`, maximum `200` |

`/disclosures` accepts `start_date`, `end_date`, `asof_date`, `page`, and
`page_size`. It returns disclosure schedule records and effective-public-date
provenance, not raw provider payloads.

The Gateway must enforce the global history limits from the API Gateway design:
default maximum 366 calendar days and maximum 2,000 records per request. A
request outside those limits returns `RANGE_TOO_LARGE`; it must not silently
truncate or fall back to the latest snapshot.

### 7.3 Scope and data classification

Financial routes require authentication even when listed as public API catalog
entries. Scope checks are additive:

| Request/data class | Required Scope | Notes |
| --- | --- | --- |
| Current public financial record query without a date range | `market_analysis:read` | Still applies effective-date and dataset allowlists |
| Historical query with `asof_date`, `start_date/end_date`, or report history | `market_analysis:read` + `market_analysis:history` | The additional Scope prevents broad historical access by default |
| Disclosure calendar query | `market_analysis:read`; add `market_analysis:history` for bounded historical ranges | Current schedule is not anonymous access |
| Raw endpoint payload, import run status, rejected rows, sanitized operator diagnostics | `financials:operator_read` | Never included in ordinary financial responses |
| Service-to-service ingestion or rebuild trigger | No public Gateway route | Use an independently issued service identity and an internal command boundary |

`is_staff` and `is_superuser` do not replace these API Scope checks. Auth must
evaluate active user/session/token state and the token's current revocation
status before the Gateway invokes a query service. Scope failures return
`403 SCOPE_REQUIRED`; authentication failures return `401` using the shared
Gateway error envelope.

### 7.4 Request and response contract

Successful responses use the shared `success`, `api_version`, `request_id`,
`data`, and `meta` envelope. Every financial record returned to a consumer
must include, where available:

- `ts_code`, `dataset`, `end_date` and the provider report period;
- `ann_date`, `actual_date`, and computed `effective_date`;
- `source`, `source_revision` or equivalent revision identity;
- `data_status` and warnings when records are incomplete or stale.

The domain query service must apply this predicate before pagination:

```text
effective_date IS NOT NULL AND effective_date <= requested_asof_date
```

where `effective_date = actual_date` when valid, otherwise `ann_date`. The
Gateway may validate the requested date and range, but must not implement this
selection rule itself. Pagination metadata must describe the filtered result,
not the raw table count.

The following semantics are required:

| Condition | HTTP/result behavior |
| --- | --- |
| Valid query with no matching record | `200` with `data_status=NOT_AVAILABLE`, or `404 RESULT_NOT_FOUND` only when the route contract requires one specific result |
| Requested record exists only after `asof_date` | `200` with no future row, or `409 ASOF_CONFLICT` when an exact requested period/version was required; never leak the future row |
| Valid data with missing optional fields | `200`, preserve nulls and return a warning; do not synthesize zero |
| Domain dependency unavailable | `503 UPSTREAM_DEPENDENCY_UNAVAILABLE` with `retryable=true` |
| Invalid dataset, symbol, date, or range | `400` with `INVALID_REQUEST`, `INVALID_SYMBOL`, `INVALID_DATE`, or `RANGE_TOO_LARGE` |
| Operator-only data without operator Scope | `403 SCOPE_REQUIRED` |

Raw provider columns not approved by the public contract must remain in the
raw persistence layer and must not be exposed through these routes. Diagnostic
details are Scope-sensitive: ordinary users receive stable reason codes only;
SQL, stack traces, connection strings, file paths, tokens, and provider
credentials are never returned.

### 7.4.1 Financial overview fusion contract

`GET /api/v1/market-analysis/securities/:ts_code/financials/overview` is the
read-only fusion endpoint for the research home fundamental evidence module. It
combines the latest public income, cash-flow, and indicator records for one
security. It does not call Tushare, write PostgreSQL, rebuild projections, or
calculate valuation signals.

Request parameters:

| Parameter | Required | Contract |
| --- | --- | --- |
| `asof_date` | no | `YYYY-MM-DD`, defaults to today, cannot be future-dated |
| `report_type` | no | `LATEST` (default); selects the latest public report period available at `asof_date` |

The response uses the standard Gateway envelope. `data.period` is the selected
report period, `data.report_type` is the source report type, and
`data.metrics` contains the stable keys `revenue`, `gross_margin`, `roe`,
`operating_cash_flow`, `net_profit`, `ebit`, `net_margin`, and
`debt_to_assets`.

Each metric is an object with `value`, `yoy`, `yoy_unit`, `rolling12`,
`rolling12_unit`, `period`, `source_dataset`, and `available`. Amount values
use CNY. Rate values use percentage points. Amount `yoy` values are ratios
(`0.18` means 18%); rate `yoy` values are percentage-point differences.
`rolling12` is the sum of the latest four quarterly cumulative amount records
for amount metrics, and the latest available value for rate metrics. A missing
source value remains `null`; no zero is synthesized.

Source mapping is fixed: `income.revenue`, `indicator.grossprofit_margin`,
`indicator.roe`, `cashflow.n_cashflow_act`, `income.n_income_attr_p` with
`n_income` fallback, `income.operate_profit` for the current EBIT proxy,
`indicator.netprofit_margin`, and `indicator.debt_to_assets` respectively.
`meta.data_status` is `COMPLETE` when at least one metric is available and
`NOT_AVAILABLE` otherwise; partial gaps are represented at metric level.

### 7.4.2 Lightweight fundamental evaluation framework

The fundamental and financial-filing tab needs a small, explainable evaluation
layer rather than a valuation model. Its purpose is to turn the existing public
financial records into a consistent description of growth, profitability, cash
flow quality, and balance-sheet risk. It must not produce a buy/sell decision,
an intrinsic value, or an automatic trading action.

#### Scope and data boundary

The first version may use only records already owned by `financials`:

| Evaluation use | Existing source fields | Output used by the frontend |
| --- | --- | --- |
| Growth | `income.revenue`, `income.n_income_attr_p` with `n_income` fallback, `indicator.or_yoy`, `indicator.netprofit_yoy` | Revenue/profit trend and growth signal |
| Profitability | `indicator.roe`, `indicator.roe_dt`, `indicator.roa`, `indicator.grossprofit_margin`, `indicator.netprofit_margin` | Core metrics and profitability trend |
| Cash-flow quality | `cashflow.n_cashflow_act`, `indicator.ocf_to_or`, income net profit | Operating cash-flow metric and cash-flow quality signal |
| Solvency | `indicator.debt_to_assets`, `indicator.current_ratio`, `indicator.quick_ratio`, `indicator.cash_ratio`, balance-sheet liabilities/assets when needed | Debt/risk signal |
| Operating efficiency | `indicator.assets_turn` | Optional supporting metric; not part of the first overall score |
| Evidence and freshness | `ann_date`, `actual_date`, `end_date`, `report_type`, `source_revision_at`, `disclosure_date` | Report archive, as-of boundary, data status |

`forecast`, `express`, `dividend`, `audit`, and `main_business` remain available
as filing evidence and future signal inputs, but do not enter the first overall
score. In particular, forecast values must not be mixed with reported values.
The evaluator reads PostgreSQL through `financials` query services and never
calls Tushare from a public request.

#### Evaluation dimensions and weights

The overall score is an integer in `[0, 100]`, calculated only from available
dimension scores. The default weights are growth `30`, profitability `30`, cash
flow quality `25`, and solvency `15`. If a dimension has no valid input, its
weight is removed and the remaining dimensions are re-normalized; the response
must expose `available_weight` and `missing_dimensions` so a partial score is
never presented as complete evidence.

| Dimension | Weight | Default primary evidence | Interpretation |
| --- | ---: | --- | --- |
| Growth | 30 | Revenue YoY and net-profit YoY | Whether scale and earnings are expanding |
| Profitability | 30 | ROE/ROE-DT, net margin, gross margin | Return and margin quality |
| Cash-flow quality | 25 | OCF YoY, OCF-to-revenue, OCF versus net profit | Whether reported profit converts to cash |
| Solvency | 15 | Debt-to-assets, current ratio, quick ratio | Balance-sheet pressure and short-term coverage |

Each dimension returns `score`, `status`, `available`, `evidence`, and
`missing_metrics`. `status` is one of `STRONG`, `HEALTHY`, `NEUTRAL`, `WEAK`,
or `NOT_AVAILABLE`; status labels are descriptive and are not investment advice.

#### Deterministic scoring rules

The following are initial configurable defaults, not hard-coded business logic.
They are applied to the normalized provider units documented by the overview
contract: rates are percentage points and amount growth is a ratio.

**Growth component scores**

- Revenue YoY and net-profit YoY each map to `0/25/50/75/100` at `<-10%`,
    `-10%..0%`, `0%..10%`, `10%..20%`, and `>=20%` respectively.
- If both are available, the growth score is their average. If only one is
    available, that component is used and `missing_metrics` records the gap.
- A negative net-profit YoY below `-20%` caps the dimension at `WEAK`, even if
    revenue is growing.

**Profitability component scores**

- ROE (prefer `roe_dt`, fallback `roe`) maps to `0/25/50/75/100` at `<0%`,
    `0%..8%`, `8%..12%`, `12%..18%`, and `>=18%`.
- Net margin maps to the same five bands using `<0%`, `0%..5%`, `5%..10%`,
    `10%..20%`, and `>=20%`; gross margin is supporting evidence and does not
    receive a second full-weight score.
- When both ROE and net margin exist, the dimension score is the average of the
    two components. Missing values do not become zero.

**Cash-flow quality component scores**

- Positive operating cash flow is required for a score above `50`.
- OCF-to-revenue maps to `0/25/50/75/100` at `<0%`, `0%..5%`, `5%..10%`,
    `10%..20%`, and `>=20%`.
- Compare OCF YoY with net-profit YoY when both are available: cash growth at
    least as high as profit growth adds `10` points (capped at `100`), while
    cash growth below `-10%` subtracts `10` points (floored at `0`).
- If OCF-to-revenue is unavailable, use current OCF sign plus the OCF/net-profit
    direction as a partial score and expose the missing metric.

**Solvency component scores**

- Debt-to-assets maps inversely to `100/75/50/25/0` at `<=30%`, `30%..50%`,
    `50%..70%`, `70%..85%`, and `>85%`.
- Current ratio maps to `0/25/50/75/100` at `<0.75`, `0.75..1.0`,
    `1.0..1.5`, `1.5..2.0`, and `>=2.0`.
- If quick ratio exists, average it with the current-ratio score; otherwise
    use current ratio alone and mark the result partial.
- Missing debt-to-assets and coverage ratios produce `NOT_AVAILABLE`; raw
    balance-sheet values must not be silently converted to a ratio without an
    explicit unit rule.

The overall status is derived from the normalized overall score: `STRONG` for
`>=80`, `HEALTHY` for `>=65`, `NEUTRAL` for `>=50`, and `WEAK` below `50`.
When available weight is below `60%`, overall status is `NOT_AVAILABLE` even if
the normalized score can be calculated. Thresholds and weights must be versioned
in the response as `evaluation_version` (initial value `fundamental-lite-v1`).

#### Trend, report archive, and signal outputs

The backend should return the complete three-year trend window ending at the
requested `asof_date` (or today when `asof_date` is omitted). The window is the
inclusive calendar range from `asof_date - 3 years` through `asof_date`, and
must use the same effective-public-date rule as the overview: a source record
is eligible only when its effective public date is not later than `asof_date`.
Within that window, return every available distinct report period rather than
truncating to the latest five periods. The periods must be ordered from oldest
to newest so the frontend can bind the trend chart's x-axis directly to the
returned sequence. The response should retain the selected period's current
evaluation in `overall`/`dimensions`; the `trend` rows represent the historical
period evaluations in the three-year window.

The evaluator must not fabricate a score for a missing report period or fill a
missing dimension with zero. Each trend row must include the report period,
available dimension scores, dimension status/availability, and source-period
metadata sufficient to explain the result. If no eligible record exists in the
three-year window, return an empty `trend` array with an explicit warning rather
than falling back to an older period outside the window. The report archive may
continue to apply its own bounded display limit; that limit must not reduce the
three-year `trend` history.

The report archive is assembled from disclosure and statement records and must
include `period`, `report_type`, `end_date`, `ann_date`, `effective_date`,
`data_status`, `source_revision`, and a short change summary only when derived
from available numeric evidence. The first version must not generate free-form
LLM summaries.

Signals are deterministic rule matches. Each signal contains `signal_code`,
`label`, `severity`, `status`, `asof_date`, `evidence`, `metrics`, and
`provenance`. The minimum v1 rules are:

- `EARNINGS_IMPROVING`: revenue YoY and net-profit YoY are both positive;
- `CASH_FLOW_LEADS_PROFIT`: OCF YoY exceeds net-profit YoY by at least 5pp;
- `PROFIT_CASH_MISMATCH`: net profit is positive while OCF is negative;
- `LEVERAGE_HIGH`: debt-to-assets is above 70%;
- `LIQUIDITY_PRESSURE`: current ratio is below 1.0 or quick ratio is below 0.8;
- `DATA_PARTIAL`: required evidence is missing or the latest source periods do
    not align.

Signals are evidence statements, not recommendations. `status` must be
`CONFIRMED`, `TRACKING`, or `NOT_AVAILABLE`, and every confirmed/tracking signal
must identify the source dataset and report period used.

#### Response shape for the fundamentals tab

The existing overview metric contract remains backward compatible. The tab-level
fundamentals response may add the following object under `data.evaluation` (or
return the same shape from a dedicated `/fundamentals` read route):

```json
{
    "evaluation_version": "fundamental-lite-v1",
    "overall": {"score": 76, "status": "HEALTHY", "available_weight": 100},
    "dimensions": {
        "growth": {"score": 82, "status": "STRONG", "available": true},
        "profitability": {"score": 74, "status": "HEALTHY", "available": true},
        "cash_flow_quality": {"score": 81, "status": "STRONG", "available": true},
        "solvency": {"score": 61, "status": "NEUTRAL", "available": true}
    },
    "trend": [
        {
            "period": "2023-12-31",
            "overall": {"score": 68, "status": "HEALTHY", "available_weight": 100},
            "dimensions": {},
            "source_period": "2023-12-31"
        }
    ],
    "reports": [],
    "signals": [],
    "warnings": []
}
```

The response must preserve the existing `metrics` object used by
`FundamentalEvidence`. A missing metric remains `null` with `available=false`;
the evaluator must never turn missing data into zero. All evaluation fields must
carry enough period/source metadata for the report archive and signal detail
views to link back to the approved raw records.

#### Acceptance criteria for the lightweight framework

- Identical normalized inputs and `evaluation_version` produce identical scores,
    statuses, trend rows, and signals.
- As-of queries never use a record whose effective public date is after the
    requested date, including amended disclosures.
- The overview trend covers the inclusive three-year calendar window ending at
    the requested `asof_date`, includes all eligible distinct report periods in
    that window, and returns them in ascending chronological order.
- Amounts, rates, ratios, percentage-point changes, and growth ratios retain
    their documented units end to end; `0.18` growth is displayed as `18%`, while
    a `2.1` rate change is displayed as `2.1pp`.
- Partial data returns a usable evidence module plus explicit warnings and
    available weight; it does not claim `COMPLETE` evaluation.
- Financial evaluation performs read-only PostgreSQL queries, makes no Tushare
    call, does not rebuild valuation features, and cannot trigger trading actions.
- Unit tests cover each threshold boundary, missing inputs, mixed report periods,
    negative cash flow, high leverage, as-of filtering, and signal precedence.

### 7.5 Authentication, audit, and cache requirements

- The Gateway reads `Authorization: Bearer <access_token>` and delegates token
    validation to `access_control`; it never reads token tables directly.
- Every request receives or propagates `X-Request-ID`. The same ID is passed to
    Auth, the financial query service, structured logs, and security/domain audit
    records.
- Authorization audit records contain principal, required Scope, endpoint,
    normalized symbol, result, and request ID, but never the raw Authorization
    header or token.
- Financial reads are strictly side-effect free: no Tushare fallback, import,
    watermark advancement, snapshot rebuild, or cache mutation that changes
    financial truth may occur in a public request.
- If response caching is added, the key must include API version, normalized
    parameters, `asof_date`, dataset, and authorization visibility. Operator
    diagnostics must not share a cache namespace with ordinary users.
- Gateway and Auth rate limits apply before the domain query. Query timeouts
    cancel the downstream call and return a bounded dependency error.

### 7.6 Internal query service contract

The first implementation must expose the following internal read boundaries (the
names are contract proposals and require confirmation before coding):

```python
financials.query_records(
        *, ts_code, dataset, asof_date, end_date=None,
        date_range=None, page=1, page_size=50,
)
financials.query_disclosures(
        *, ts_code, asof_date, date_range=None, page=1, page_size=50,
)
financials.query_financial_overview(
    *, ts_code, asof_date, report_type='LATEST',
)
```

All methods must use bounded, indexed PostgreSQL queries, return typed results,
and expose provenance without returning a Django `QuerySet`. They must not
accept an authorization token or make authorization decisions; the Gateway
passes the authenticated principal only when needed for audit or field-level
visibility. `query_financial_overview` additionally returns the backward-
compatible `metrics` object and versioned `evaluation` object defined in
section 7.4.2; scoring remains owned by `financials`.

### 7.7 Integration acceptance criteria

- Unauthenticated, expired, revoked, and disabled-user requests are rejected by
    the shared Auth boundary before any financial query executes.
- A user with only `market_analysis:read` can read current public financial data
    but receives `403 SCOPE_REQUIRED` for bounded historical/as-of access.
- A user with `market_analysis:read` plus `market_analysis:history` receives
    only records public on or before `asof_date`, including after a disclosure
    amendment and repeated ingestion.
- `financials:operator_read` is required for raw payload and run-status routes;
    no such route is added to the ordinary public API catalog.
- Gateway tests prove symbol/date/dataset/range validation and shared error
    envelopes; financials tests prove effective-date filtering and revision
    provenance independently of HTTP.
- An integration test proves the chain
    `Bearer token -> access_control -> financial query service -> PostgreSQL`
    and verifies that the query path performs no Tushare call or database write.
- Audit/log assertions prove that request IDs and authorization outcomes are
    retained while tokens, passwords, connection strings, and stack traces are
    absent.

## 8 Test Case Definition

### 8.1 Core Flow

- Every endpoint maps to its dedicated raw model, deterministic natural key, and documented projection fields.
- `disclosure_date` detects new/amended disclosure events and accurately drives targeted statement and event ingestion for affected securities without all-market scanning.
- A repeated normalized provider row upserts idempotently, while a material revision remains auditable.
- An eligible statement/indicator set is available for an authorized downstream consumer projection rebuild.
- A consumer historical as-of projection uses only disclosure records public on or before the requested date.

### 8.2 Boundary Scenarios

- Multiple dividend or main-business rows for one security/report period remain distinct through row signatures.
- Missing/invalid optional publication dates are retained as raw data but excluded from time-sensitive projections.
- Consumers that require latest projections maintain their own one-row snapshots rather than scanning raw history.
- A provider field not in a typed projection remains in the endpoint raw payload under the endpoint schema policy.

### 8.3 Failure Scenarios

- A malformed required endpoint payload, exhausted page limit, or failed chunk leaves the endpoint watermark unchanged.
- A projection cannot use a statement whose effective date is after the requested as-of date.
- Tokens, passwords, and connection strings are absent from command output and persisted error summaries.
- No financial calculation or API path creates an automatic trading action.

## 9 Implementation Sequence

1. Confirm concrete table names, core typed field list/units for every endpoint, row-signature policy, and effective-date precedence.
2. Implement raw endpoint models, run/watermark models, PostgreSQL migrations, indexes, and model-contract tests.
3. Implement adapter, normalization, pagination, and endpoint repository upserts with mocked Tushare tests.
4. Implement disclosure-date ingestion and event detection for the daily actual-date path and quarterly reconciliation path; downstream domains rebuild their own as-of projections with no-lookahead tests.
5. Implement the operator CLI, daily scheduling, backfill/quarterly reconciliation, artifacts, and failure exit behavior.
6. Confirm API and authorization contracts before implementing read endpoints.

## 10 TODO List

- [x] 事件发布：基于已提交的 disclosure/财务原始记录提供幂等的 `FINANCIAL_DISCLOSED` 内部事件读取接口，供传统估值和预测估值导入各自 event 表；提交后重放测试仍待补充。
- [ ] 需求确认：确认 10 个 Tushare endpoint 的 typed fields、provider units、日期字段、表名、索引和 row signature 规则。
- [ ] 需求确认：确认 `effective_date = actual_date` 优先、否则使用 `ann_date` 的 as-of 规则，以及无有效公开日期记录的消费边界。
- [ ] 需求确认：确认 `api_gateway` 路由、统一响应封套、错误码、分页和日期范围限制。
- [ ] 需求确认：确认 `market_analysis:read`、`market_analysis:history`、`financials:operator_read` 的授权范围和默认角色绑定。
- [ ] 数据模型：实现 10 个 endpoint 对应的 raw record 模型、公共 provenance 字段、自然键和 PostgreSQL 索引。
- [ ] 数据模型：实现 `FinancialIngestionRun`、`FinancialIngestionWatermark` 及其状态、计数器、唯一约束和索引。
- [ ] 数据库：生成并应用 PostgreSQL migrations，确认不使用 SQLite，校验金额、比例、日期和文本字段精度/长度。
- [ ] 规范化：实现 provider 空值、日期、数值、单位和 deterministic row signature 的规范化逻辑。
- [ ] 采集：实现 Tushare adapter、分页、重试、限流、secret-safe error，以及按 disclosure event 定向拉取数据。
- [ ] 持久化：实现按 bounded page/chunk 的事务写入、幂等 upsert、修订保留和 watermark 仅成功推进规则。
- [x] 查询服务：实现 `financials.query_records()` 和 `financials.query_disclosures()` 的 typed read service、bounded query 和 provenance 返回。
- [ ] 查询服务：实现 effective-date/as-of 过滤、报告期选择、多事件选择策略和 `NOT_AVAILABLE`、`STALE`、`PARTIAL_SUCCESS` 等状态。
- [x] Auth 接入：通过 `access_control` 校验 Bearer token、用户/会话状态、token 撤销状态和所需 Scope，不在 financials 内维护第二套权限。
- [x] Gateway 接入：实现 financials/disclosures 只读路由、参数白名单、证券代码规范化、分页/日期范围校验和统一错误映射。
- [ ] Gateway 接入：增加 financial overview 融合只读路由，保持标准认证、as-of 和字段裁剪契约。
- [ ] 评判框架：实现 `fundamental-lite-v1` 的增长、盈利能力、现金流质量、偿债能力四维规则评分、缺失降级、趋势、档案和信号输出。
- [ ] 评判框架：确认阈值、权重、状态文案和 `data.evaluation`/`/fundamentals` 响应形状后再编码，禁止将评分解释为估值或交易建议。
- [ ] Gateway 接入：接入 `X-Request-ID`、结构化审计、限流、超时和响应字段裁剪，确保普通用户无法读取 raw/operator 数据。
- [x] API 目录：将已审核的 financials 只读 endpoint 加入 Public API catalog；不公开导入运行、raw payload 和运维接口。
- [ ] 测试：补充模型契约、自然键、索引、迁移和字段精度测试。
- [ ] 测试：补充 adapter mock、分页/重试、空值规范化、幂等 upsert、修订审计和 watermark 失败回滚测试。
- [ ] 测试：补充 financial overview 的来源字段、同比、rolling12、缺失值和 as-of 边界测试。
- [ ] 测试：补充轻量评判框架的阈值边界、权重归一化、部分数据、趋势、信号和 evaluation version 测试。
- [ ] 测试：补充 disclosure event 定向同步测试，证明 daily actual-date 和 quarterly reconciliation 都不会触发全市场扫描。
- [ ] 测试：补充 as-of/no-lookahead、无效日期、未来披露、重复披露和多 dividend/main-business 行测试。
- [ ] 测试：补充 Gateway/Auth 集成测试，覆盖未登录、过期/撤销 token、disabled 用户、缺少 Scope 和 operator Scope。
- [ ] 测试：验证 API 请求只读，不调用 Tushare、不写 financials 表、不推进 watermark、不触发快照重建。
- [ ] 安全验收：检查日志、审计、响应和错误中不包含 Token、密码、Tushare token、数据库连接串、堆栈和内部路径。
- [ ] 运维：实现 operator CLI、daily 调度、backfill/quarterly 调度、reconciliation artifact、失败退出码和恢复/重跑说明。
- [ ] 验证：运行 Django checks、迁移检查、financials 单元测试、Gateway/Auth 集成测试和最小 PostgreSQL smoke test。
- [ ] 文档：补充部署配置、Scope 初始化、API catalog、查询服务调用示例和回滚/重跑操作说明。
