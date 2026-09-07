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
    <model-version>/model_bundle.joblib
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

`PredictiveFinancialFeatureBuilder` reads only `financials` raw income, balance-sheet,
cash-flow, indicator, and disclosure records. It resolves each report's effective
disclosure date, upserts point-in-time panel rows, and updates the latest row from the
newest eligible panel before inference begins. Predictive serving must never build an
unpersisted raw-table join.

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

`artifact_registry` validates and caches bundle metadata. `financial_feature_builder`
rebuilds the predictive module's panel/latest rows from financial raw records before
every inference. `feature_builder` then performs point-in-time market and financial
joins and emits a named feature row plus provenance. `inference_service` loads the
classifier/regressor bundle, applies ordered feature reindexing and hierarchical
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