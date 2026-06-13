# Requirement: Earnings Predict API Live-Feature Contract V1

- Date: 2026-06-13
- Environment: UAT (DEV-first sync required before rollout)
- Status: Confirmed

## 1. Goal

Enable left predictive valuation card to satisfy strict business requirement:

- Use selected report-period financial data.
- Use request-time available trading and fundamental features.
- Reject non-live feature sources instead of silently returning fallback values.

Mandatory capability confirmed by user:

- Upstream must provide predictive valuation built from features constructed at request-time asof context.

## 2. Service Ownership (must confirm)

- Upstream inference contract owner: earnings forecast service (`/api/forecast/predict/`)
- Consumer and orchestration owner: `smartinvestor_be` (`get_earnings_signal_compare`)
- UI rendering owner: `smartinvestor_fe`

This requirement assumes upstream service owns request-time feature construction behavior.

## 3. Contract Change Scope

### In scope

- Add live-feature enforcement parameters on predict API.
- Add explicit feature-source and request-time metadata in predict response.
- Add deterministic rejection error when live features are unavailable.

### Out of scope

- Model training changes.
- New model versions.
- Snapshot backfill jobs.

## 4. Upstream API Contract (proposed)

Endpoint:

- `POST /api/forecast/predict/`

### 4.1 Request Parameters

- `ts_code` (required, string)
- `report_type` (required, enum: `Q1|H1|Q3|FY|FUSION`)
- `serving_slot` (optional, enum: `production|candidate`, default `production`)
- `model_version` (optional, string)
- `anchor_mode` (required for this flow, must be `live`)
- `financial_end_date` (optional, string `YYYY-MM-DD`): selected report-period financial anchor
- `asof_date` (required for strict realtime mode, string `YYYY-MM-DD`): request-time target date
- `require_live_features` (required for strict realtime mode, boolean): when true, non-live feature sources must be rejected
- `feature_source_preference` (optional, enum): `live_db_only|live_db_first` (default `live_db_only` when `require_live_features=true`)

### 4.2 Response Fields (result)

- Existing fields retained.
- Add/guarantee fields:
  - `feature_data_source` (enum): `live_db|dataset_fallback|fusion|unknown`
  - `feature_trade_date` (string `YYYY-MM-DD`): actual feature snapshot trade date
  - `request_asof_date` (string `YYYY-MM-DD`): echoed request asof date
  - `live_feature_compliant` (boolean)
  - `live_feature_gap_days` (integer|null): days between `request_asof_date` and `feature_trade_date`

### 4.3 Rejection Behavior (strict)

When `require_live_features=true` and service cannot build `live_db` features:

- Return HTTP 422
- Body:
  - `code`: `LIVE_FEATURE_UNAVAILABLE`
  - `message`: short reason
  - `detail.feature_data_source`: actual fallback source
  - `detail.request_asof_date`
  - `detail.feature_trade_date` (if available)
  - `detail.live_feature_gap_days` (if available)

No silent fallback to `dataset_fallback` is allowed in strict mode.

## 5. Consumer Contract in smartinvestor_be

For `get_earnings_signal_compare` latest view:

- Send `anchor_mode=live`.
- Send selected report-period `financial_end_date` when available.
- Send `asof_date` = request date.
- Send `require_live_features=true`.

If upstream returns `LIVE_FEATURE_UNAVAILABLE`:

- Keep response `code=0` for compare endpoint compatibility.
- Set latest card payload to deterministic empty/degraded state.
- Set compare meta:
  - `latest_source_used = predict_non_live_rejected`
  - `latest_live_feature_ok = false`
  - `latest_degrade_reason = LIVE_FEATURE_UNAVAILABLE`

Right card remains snapshot-only selected-report latest value.

## 6. Backward Compatibility

- Existing predict clients without new params continue working under legacy behavior.
- Strict live enforcement is opt-in by request params.

## 7. Acceptance Criteria

1. With `require_live_features=true`, predict never returns `dataset_fallback` success payload.
2. Strict request either returns live-compliant success or `LIVE_FEATURE_UNAVAILABLE`.
3. Compare endpoint latest card reflects strict result without pretending fallback is realtime.
4. Right card remains unaffected and continues snapshot-only behavior.
5. For selected report-type requests, financial fields must be bound to the latest available report-period under selected `report_type` as of request-time constraints.
6. Future/unavailable period must not be force-anchored (for example selecting `Q3` does not mean forcing `2026-Q3` when it is not available yet).
7. For strict live mode, feature construction must anchor market data on latest available trading day on/before `asof_date`.

## 7.1 Clarified Strong-Constraint Semantics (confirmed)

Canonical example:

- Request date (`asof_date`): `2026-06-13`
- Latest available trade date: `2026-06-12`
- Selected report type: `Q1`
- Selected financial end date preference: `2026-03-31` (optional preference, must still satisfy asof-availability)

Required feature construction behavior:

1. Trading and fundamental features are taken from latest available day on/before `asof_date` (example: `2026-06-12`).
2. Financial features are taken from latest available report-period under selected report type as of request time (for example latest available `Q1`).
3. If caller gives a future/unavailable `financial_end_date`, service resolves to latest available period under selected report type, instead of force-using future period.
4. If no report-period is available under selected report type as of request-time constraints, return `LIVE_FEATURE_UNAVAILABLE`.

Additional clarification:

- If user selects `Q3` at a time when `2026-Q3` is not yet available, service must not anchor to `2026-Q3`; it must use the latest available `Q3` period at that time.

## 8. Validation Plan

1. Upstream unit test: strict mode rejects non-live feature path.
2. Upstream integration test: strict mode success when live_db available.
3. BE integration test: compare endpoint propagates strict rejection metadata.
4. UI smoke: left card shows realtime-compliant result or explicit rejection hint.

## 9. Open Questions

1. `asof_date` is calendar request date; upstream resolves and uses nearest available trading date on/before `asof_date`.
2. Report-type selection uses asof-available latest period under that report type (not forced future period).
3. For `FUSION`, strict live means disallow `fusion` source entirely or permit if underlying features are live?
