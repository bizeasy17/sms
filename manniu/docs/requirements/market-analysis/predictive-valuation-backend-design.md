# Predictive Valuation Module Design

## Status And Scope

This document defines the predictive valuation design for `manniu_backend`. The
model-compatible financial feature tables, prediction/event/run control tables, feature
builder, and operator CLI baseline are implemented and migrated to PostgreSQL. Model
inference, event consumption, historical backfill, scheduling, and gateway integration
remain pending.

The module ports the serving approach of
`tushare_earnings_service/earnings_forecast/services/pipeline.py` while using the
existing `market_data` and `financials` applications in the same PostgreSQL database.
It produces a probability-weighted valuation signal, bounded return range, target
price range, target market-cap range, risk level, and traceability metadata.

## Ownership Boundaries

`predictive_valuation` owns:

- Loading approved static model bundles and model-serving metadata.
- Constructing online feature rows from shared projections.
- Inference, imputation, regime-aware target mapping, and explanation payloads.
- Prediction snapshots, event-consumption state, run audit records, and error state.
- CLI orchestration for historical initialization and incremental refresh.

`market_data` remains the owner of securities, prices, valuation fundamentals, market
regime inputs, and per-security regime inputs. `financials` remains the owner of raw
financial endpoints and disclosure data. `predictive_valuation` owns the financial
feature projections required by its active model feature contract.

The module must not duplicate trading, fundamental, raw financial, or disclosure tables.
It stores only model-specific financial feature projections plus predictive inference
data. All reads and writes use the existing PostgreSQL connection; SQLite is not
supported.

## Configuration And Static Artifacts

### Environment Variables

Add the following documented variables to the project's `.env` example. Existing
database configuration is reused and must not be duplicated under a second URL.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PREDICTIVE_VALUATION_ENABLED` | `false` | Enables CLI/scheduled inference. |
| `PREDICTIVE_VALUATION_CONFIG` | `predictive_valuation/configs/default.yaml` | Active YAML profile, resolved from `BASE_DIR`. |
| `PREDICTIVE_VALUATION_MODEL_ROOT` | `predictive_valuation/outputs` | Read-only root for model bundles and serving pointer. |
| `PREDICTIVE_VALUATION_RISK_DATA_ROOT` | `predictive_valuation/outputs_risk` | Read-only risk-dataset root. |
| `PREDICTIVE_VALUATION_LOOKBACK_YEARS` | `5` | Default history range for initialization. |
| `PREDICTIVE_VALUATION_EVENT_DEBOUNCE_SECONDS` | `900` | Per-security event coalescing window. |
| `PREDICTIVE_VALUATION_MAX_FEATURE_GAP_DAYS` | `5` | Maximum market-feature staleness in live mode. |
| `PREDICTIVE_VALUATION_STRICT_LIVE_FEATURES` | `true` | Rejects stale/missing live feature rows instead of dataset fallback. |

All paths must be resolved relative to `settings.BASE_DIR` unless explicitly absolute.
The process must validate that configured artifacts remain within their configured roots,
that the serving pointer exists, and that the selected bundle contains `feature_cols`.

### `configs/` Layout

Proposed files:

```text
predictive_valuation/
  configs/
    default.yaml
    production.yaml
    schema.yaml
  outputs/
    serving.yaml
    model_versions/<model-version>/models_Q1.joblib
    model_versions/<model-version>/models_H1.joblib
    model_versions/<model-version>/models_Q3.joblib
    model_versions/<model-version>/models_FY.joblib
  outputs_risk/
    <risk-dataset-version>/...
```

`default.yaml` contains no secrets. It names the model version, artifact paths,
feature-contract version, target-return caps, classifier/regressor settings, imputation
settings, risk thresholds, and market-regime profiles. `production.yaml` may override
only deploy-time values. `schema.yaml` records the versioned feature contract and
expected numeric-unit conventions.

`outputs/` and `outputs_risk/` are immutable inputs to serving. Training/publishing is
outside this module's scheduled inference jobs. A serving pointer promotion is an
explicit deployment operation with its own audit record; a batch job must never
overwrite model artifacts.

### Quarterly Production Model Routing

Production inference is report-type-specific. `serving.yaml` contains one production
model version and a required `production.models` mapping for `Q1`, `H1`, `Q3`, and `FY`.
Each mapping entry names its corresponding `models_Q1.joblib`, `models_H1.joblib`,
`models_Q3.joblib`, or `models_FY.joblib` artifact and matching metrics file.

The inference service resolves the bundle from the selected feature panel's report type:

| Feature panel report type | Required production artifact |
| --- | --- |
| `Q1` | `production.models.Q1` / `models_Q1.joblib` |
| `H1` | `production.models.H1` / `models_H1.joblib` |
| `Q3` | `production.models.Q3` / `models_Q3.joblib` |
| `FY` | `production.models.FY` / `models_FY.joblib` |

The artifact registry fails when the report type is unsupported or its configured bundle
is missing or outside the configured model root. A declared sklearn version different
from the running version emits an explicit compatibility warning and is recorded in run
output; it does not block prediction. The registry must never silently fall back to a
different quarter's model. The operator `validate` command checks all configured
report-type mappings before a batch or event consumer runs.

## Shared Feature Contract

The reference pipeline loads its ordered feature names from `model_bundle.joblib` and
uses `reindex(columns=feature_cols)`, followed by hierarchical imputation. The Maniu
implementation must preserve that behavior: model bundle order is authoritative, and
missing columns become null before imputation rather than raising a dataframe error.

The online feature builder combines these sources:

| Source | Required contribution |
| --- | --- |
| `market_data` | security identity/industry, latest eligible close, market cap, valuation ratios, liquidity/return/volatility windows, benchmark and security regime inputs |
| `predictive_valuation.PredictiveFinancialFeaturePanel` | module-owned point-in-time financial feature row selected by `source_as_of_date <= as-of date` and requested report period |
| `predictive_valuation.PredictiveFinancialFeatureLatest` | module-owned current live financial feature projection |
| `financials.FinancialDisclosureRecord` | report/disclosure change detection and the financial-data availability boundary |

The predictive pipeline must rebuild affected module-owned financial feature rows before
every prediction. The panel selection is point-in-time safe: choose the newest row for
the security where `source_as_of_date` is not later than the inference date. Historical
initialization must never use a newer latest row to predict an older trading date.

### Module-Owned Financial Feature Schema

The former `financials_feature_panel` and `financials_feature_latest` tables have been
removed. `PredictiveFinancialFeaturePanel` and `PredictiveFinancialFeatureLatest` replace
them with the model-compatible names required by the reference pipeline: income
(`n_income`, `n_income_attr_p`, `basic_eps`, `diluted_eps`), indicators (`roe_dt`,
`q_dt_roe`, `tr_yoy`, liquidity ratios, `assets_turn`, `ocf_to_or`), balance-sheet, and
cash-flow fields are persisted without lossy field renaming.

`PredictiveFinancialFeatureBuilder` reads only typed `financials` raw income,
balance-sheet, cash-flow, indicator, and disclosure records. It resolves each report's
effective disclosure date, upserts point-in-time panel rows, and updates the latest row
from the newest eligible panel before inference begins. Predictive serving must never
build an unpersisted raw-table join.

Every persisted predictive financial feature must be a direct field mapping from an
approved financial raw-record column. The builder must not derive, synthesize, or use a
different-field substitute for a model feature. In particular, `cash_ratio` and
`ocf_to_or` must come from `FinancialIndicatorRecord.cash_ratio` and
`FinancialIndicatorRecord.ocf_to_or`; they must not be recomputed from balance-sheet or
income/cash-flow values. `q_dt_roe`, `st_borr`, `lt_borr`, and
`n_incr_cash_cash_equ` likewise require their corresponding typed raw fields. A missing
raw source remains null for model imputation and is recorded in feature provenance.

The financial ingestion schema and repository must persist all fields in the active
model contract before a predictive panel rebuild. Existing raw payloads may be used for
a one-time, auditable typed-field backfill only when the value is copied directly from
the provider field of the same name. This preserves compatibility with the legacy
`earnings_financial_feature_panel` feature distribution.

Feature values must be normalized according to `schema.yaml`. In particular,
ratio-scale upstream values must not be mixed with percentage-scale model features.

## Predictive Domain Persistence

The only proposed predictive tables are:

| Model | Key | Purpose |
| --- | --- | --- |
| `PredictiveValuationSnapshot` | `security`, `asof_date`, `model_version`, `feature_contract_version` | Append-only inference result and raw/explain payload. |
| `PredictiveValuationCurrent` | `security`, `horizon`, `model_version` | Latest serving projection; upserted after a successful snapshot. |
| `PredictiveValuationEventState` | `security`, `event_type`, `event_key` | Idempotent event consumption, debounce, and retry state. |
| `PredictiveValuationRun` | `run_key` | Batch/manual run lifecycle and aggregate counts. |

Each snapshot records source market date, financial `end_date`, `ann_date`,
`source_as_of_date`, report type, model/artifact hash, feature-contract version, input
data source, market regime, security regime, trigger type, and error text. Prediction
values include raw and market-adjusted target ranges so consumers can select a display
policy without recalculating a target.

No event is marked consumed until its prediction transaction has committed. Failed
events retain their error and retry count; a later event with the same idempotency key
does not create duplicate snapshots.

## Inference Service

Proposed package shape:

```text
predictive_valuation/
  services/
    artifact_registry.py
    financial_feature_builder.py
    feature_builder.py
    regime_service.py
    inference_service.py
    event_service.py
  management/commands/
    predictive_valuation.py
```

`artifact_registry` validates and resolves the production bundle matching each panel's
financial report type. `financial_feature_builder`
rebuilds the predictive module's panel/latest rows from financial raw records before
every inference. `feature_builder` then performs point-in-time market and financial
joins and emits a named feature row plus provenance. `inference_service` loads the
report-type-specific classifier/regressor bundle, applies ordered feature reindexing and hierarchical
imputation (security recent history, industry median, bundle global median), then maps
the score through capped, risk- and regime-aware target ranges. `event_service` detects,
coalesces, claims, and completes events transactionally.

The serving path defaults to strict live features. Dataset fallback is permitted only for
offline historical initialization when the active profile explicitly enables it; its use
must be persisted in the snapshot.

## CLI And Batch Jobs

The proposed single entry point is:

```text
python manage.py predictive_valuation <subcommand> [options]
```

| Subcommand | Default behavior |
| --- | --- |
| `validate` | Validates environment, serving pointer, feature contract, database access, and required shared-data coverage. Performs no writes. |
| `backfill` | Initializes append-only historical predictions for the previous five calendar years. Requires explicit `--start-date`/`--end-date` to override. Uses `--dry-run` by default until operational approval. |
| `detect-events` | Detects market-regime, security-regime, and newly available disclosure events; creates idempotent pending events only. |
| `consume-events` | Claims and predicts eligible pending events with bounded retries and debounce. |
| `refresh` | Runs `detect-events` followed by `consume-events`; does not backfill. |
| `status` | Reports latest run, pending/failed events, active model, and feature freshness. |

Initial batch-job proposals:

| Job | Command | Schedule intent |
| --- | --- | --- |
| `predictive_valuation_backfill` | `predictive_valuation backfill --years 5` | Manual/onboarding only; resumable by run key. |
| `predictive_valuation_event_scan` | `predictive_valuation detect-events` | After market and financial ingestion completes. |
| `predictive_valuation_event_consumer` | `predictive_valuation consume-events` | Runs after the scan; may run more frequently for retries. |

The job scheduler must declare ordering: market-data ingestion, then financial ingestion
and feature-projection rebuild, then event scan, then event consumption. The commands
are lock-protected per run class and scope; `--security`, `--asof-date`, `--limit`,
`--run-key`, `--dry-run`, and `--retry-failed` are proposed common controls.

## Event Contract

Event detection is pull-based against shared PostgreSQL data, which makes it compatible
with current batch ingestion and avoids cross-app in-process signals.

| Event type | Detection baseline | Affected scope | Trigger condition |
| --- | --- | --- | --- |
| `MARKET_REGIME_CHANGED` | persisted prior benchmark regime | market scope | Current classified benchmark regime differs from last successfully processed regime. |
| `SECURITY_REGIME_CHANGED` | persisted prior security regime | one security | Debounced classified security regime differs from its last successful state. |
| `FINANCIAL_DISCLOSED` | disclosure watermark plus projection freshness | one security | A disclosure row becomes available/changes and the matching feature-panel row is available. |

The disclosure event must first rebuild the module-owned financial feature row, then be
gated by `PredictiveFinancialFeaturePanel.source_as_of_date` so new financial data cannot
trigger inference against stale projected features. Market-wide events fan out
deterministically to eligible active securities and are chunked; they do not hold one
long database transaction.

### Market Data Regime Contract

`predictive_valuation` consumes market and security style classification from the
canonical `market_data` regime service. It must not duplicate the classifier,
read private state from another prediction service, or call Tushare during
feature construction or event consumption. All regime reads use completed
PostgreSQL EOD rows and an explicit `asof_date`.

The supported read boundary is:

```python
from market_data.services.regime import (
  get_market_regime,
  get_security_regime,
  get_regime_state,
)

market = get_market_regime(
  asof_date=asof_date,
  benchmark_ts_code="000001.SH",
)
security = get_security_regime(
  security=security,
  asof_date=asof_date,
)
```

The service resolves the latest completed source date on or before the
requested as-of date. It returns a typed degraded result for insufficient or
stale data rather than fabricating a neutral feature row. The prediction
feature builder persists the returned regime metadata in feature provenance:

```text
market_regime: BULL | BEAR | BALANCE
security_regime: GROWTH | BALANCE | DEFENSIVE | RISK_OFF
market_regime_source
security_regime_source
market_regime_source_trade_date
security_regime_source_trade_date
regime_classifier_version
regime_row_count
regime_status
```

### Market Regime Semantics

The market classifier uses the completed `000001.SH` benchmark close series
from `market_data.MarketBarDailyHistory`. It requires at least 80 valid rows
and calculates MA20, MA60, close/MA60, 20-day volatility, and 60-day drawdown.
The default states and thresholds are:

| Condition | State |
| --- | --- |
| `MA20 > MA60`, `close/MA60 >= 1.03`, and `drawdown60 > -0.12` | `BULL` |
| `MA20 < MA60` and (`close/MA60 <= 0.97` or `drawdown60 <= -0.12`) | `BEAR` |
| Other valid observations | `BALANCE` |

If a provisional `BULL` state has 20-day volatility `>= 0.028`, the classifier
downgrades it to `BALANCE`. These thresholds belong to `market_data`; the
prediction model configuration may define how a confirmed state scales target
returns and bands, but may not redefine the state itself.

### Security Regime Semantics

The security classifier uses at least 60 valid positive close values from
`market_data.MarketBarDailyHistory` and follows this ordered rule set:

1. `RISK_OFF` when `ma20 < ma60` and (`close/ma60 <= 0.94` or
   `drawdown60 <= -0.18`).
2. `DEFENSIVE` when `ma20 < ma60`, or `close/ma60 < 0.98`, or
   `drawdown60 <= -0.10`, or volatility is `>= 0.035`.
3. `GROWTH` when `ma20 > ma60`, `close/ma60 >= 1.02`, drawdown is `> -0.08`,
   and volatility is `< 0.03`.
4. Otherwise `BALANCE`.

The classifier returns `INSUFFICIENT_DATA` when fewer than 60 valid rows exist.
That result may be recorded in diagnostics but cannot trigger a regime event or
replace a confirmed state.

### Regime Event Consumption

`market_data` persists `MarketRegimeSnapshot`, `SecurityRegimeSnapshot`,
`MarketRegimeState`, `SecurityRegimeState`, and idempotent `RegimeEvent` rows.
The first valid market or security observation establishes a baseline and does
not trigger prediction refresh. Invalid or empty results do not advance state.

Security state changes require two consecutive observations of the new state.
The pending state and pending count are held in `SecurityRegimeState`; only a
confirmed transition creates `SECURITY_STYLE_CHANGED`. A market transition is
created only when both old and new states are valid and different.

The predictive event service maps upstream events as follows:

| `market_data` event | Predictive scope | Prediction refresh |
| --- | --- | --- |
| `MARKET_STYLE_CHANGED` | Market/universe | Deterministic bounded fan-out over eligible active securities |
| `SECURITY_STYLE_CHANGED` | One security | Only that security's current eligible report panels |
| `FINANCIAL_DISCLOSED` | One security/report period | Rebuild features, then predict the affected report period |

Older internal names `MARKET_REGIME_CHANGED` and `SECURITY_REGIME_CHANGED`, if
encountered in existing event payloads, are compatibility aliases only. New
events must use `MARKET_STYLE_CHANGED` and `SECURITY_STYLE_CHANGED` and retain
the source classifier version, old/new state, source trade date, metrics,
detection time, and stable event key.

The market-style event must not hold one transaction for the entire universe.
The detector creates bounded child work or the consumer claims bounded chunks.
The security-style event never fans out to other securities. A repeated event
with the same source version and scope is idempotent and cannot create duplicate
prediction snapshots.

### Regime-Aware Inference And Refresh Metadata

The inference service may use the confirmed market/security state in its target
mapping, return caps, risk scaling, or explanation payload. It must record the
state used for the prediction and the exact source dates. A degraded or stale
regime input must either follow the configured explicit fallback profile or make
the prediction ineligible in strict mode; it must not silently present a stale
state as current.

Every event-triggered prediction snapshot records one of these refresh reasons:

- `MARKET_REGIME_SWITCH`
- `STOCK_REGIME_SWITCH`
- `FINANCIAL_DISCLOSURE`
- `MONTHLY_FULL_REFRESH`
- `MANUAL_REFRESH`

The dashboard/latest read path consumes persisted `PredictiveValuationSnapshot`
or `PredictiveValuationCurrent` rows only. Loading a prediction card must not
call `get_market_regime`, `get_security_regime`, or the inference service in a
way that writes or computes a new prediction.

## Consumer And API Boundary

`predictive_valuation` does not define, route, serialize, or expose public HTTP APIs.
Its public boundary is an internal, read-only query service used by `api_gateway` after
authorization. CLI and scheduler commands remain the only write entry points.

After a separate interface-contract confirmation, `api_gateway` may expose current,
historical, and operational-status predictive valuation reads. Gateway request validation,
versioning, serialization, response envelopes, pagination, and error mapping are owned by
`api_gateway`; `access_control` authorizes the caller before the gateway invokes a bounded
predictive-valuation query service.

Any gateway response must identify `asof_date`, `source_market_date`,
`financial_end_date`, and `model_version` so clients cannot present stale inputs as a
current valuation. No request-time path may invoke Tushare, write a prediction, alter a
model artifact, or execute a trading action.

## Implementation Gates

1. Confirm the raw-financial field mapping for every predictive feature, including
  percentage/ratio unit rules.
2. Confirm the four predictive inference persistence models and the internal read-query contract for `api_gateway`.
3. Confirm scheduling ownership and exact cadence after the existing market/financial
   jobs are identified.
4. Run `predictive_valuation validate` against PostgreSQL and write a side-by-side local
   artifact before any five-year database backfill.
5. Enable event jobs only after historical snapshot coverage and idempotency checks pass.

Implementation begins only after the relevant data, CLI, and API contracts are approved.