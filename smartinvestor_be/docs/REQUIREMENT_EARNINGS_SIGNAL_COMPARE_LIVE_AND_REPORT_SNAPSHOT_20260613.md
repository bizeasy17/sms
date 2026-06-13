# Requirement: Earnings Signal Compare - Realtime Latest vs Selected-Report Latest Snapshot

- Date: 2026-06-13
- Environment: UAT (logic to be validated in DEV-first when synced)
- Status: Confirmed and implemented

## 1. Background

Current predictive valuation compare flow can mix realtime inference and snapshot retrieval in ways that do not match business intent for the two cards.

Business requires strict split:

- Left card (`latest_view`): request-time realtime predict view for selected report period.
- Right card (`report_anchor_view`): selected report-type latest available snapshot only (no realtime inference).

## 2. Service Ownership (to confirm)

- API owner: `smartinvestor_be` (`api/views.py`, endpoint: `get_earnings_signal_compare`)
- Upstream data/inference provider: earnings forecast service (`/api/forecast/signal/` and `/api/forecast/predict/`)
- Frontend render owner: `smartinvestor_fe`

## 3. Required Business Rules

### Rule A: Left card latest_view

- Scope: applies to selected report period and snapshot/fusion views (`Q1`, `H1`, `Q3`, `FY`, `FUSION`).
- Anchor intent: request current date (example: `2026-06-13`) with latest available trading/fundamental context.
- Data source strategy:
  1. Always use realtime predict path.
  2. Lock financial input to selected report-period financial data (`financial_end_date` from selected period snapshot when available).
  3. If realtime predict temporarily fails, fallback to selected report-period snapshot as degraded backup.

### Rule B: Right card report_anchor_view

- Scope: all report periods plus fusion/snapshot display paths (`Q1`, `H1`, `Q3`, `FY`, `FUSION`).
- Must represent the latest available persisted snapshot under selected report type.
- No realtime inference allowed.
- Source can be latest table or history table, but only persisted snapshot records are allowed.
- For `FUSION`, use latest available persisted fusion snapshot; no realtime predict fallback.

## 4. API Contract Impact

Existing response keys stay unchanged:

- `data.latest_view`
- `data.report_anchor_view`
- `data.compare_summary`
- `data.compare_meta`

Add/extend metadata under `compare_meta`:

- `request_date`: request-time date (`YYYY-MM-DD`)
- `latest_policy`: `realtime_predict_with_selected_financial_period`
- `report_policy`: `snapshot_only_selected_report_type_latest`
- `latest_source_used`: `snapshot|predict|default`
- `latest_snapshot_staleness_days`: integer or null

No breaking contract change for frontend consumers.

## 5. Implementation Plan

1. Update compare endpoint orchestration in `get_earnings_signal_compare`.
2. For latest view: always run predict using request-time market/fundamental context and selected report-period financial data.
3. For right-card view: force snapshot-only path for selected report type latest value; disallow predict fallback.
4. Keep degrade behavior and cache behavior compatible.
5. Return compare metadata for source transparency.

## 6. Acceptance Criteria

- Left card always uses realtime predict with request-time context.
- Left card binds selected report-period financial input when available.
- Right card never triggers realtime predict and returns selected report-type latest persisted snapshot semantics.
- Behavior applies consistently to `Q1/H1/Q3/FY/FUSION` and snapshot display paths.
- Existing frontend can consume response without breaking changes.

## 7. Validation Plan

1. Django shell: call `get_earnings_signal_compare` for at least one symbol and each report type.
2. Verify `compare_meta.latest_source_used` matches threshold scenario.
3. Verify `report_anchor_view` source path remains snapshot-only.
4. Live API smoke on running service endpoint.

## 8. Progress

- Implemented in `api/views.py` compare endpoint orchestration.
- Added latest snapshot staleness threshold policy (default 30 days, configurable by `EARNINGS_LATEST_SNAPSHOT_STALE_DAYS`).
- Enforced report-anchor snapshot-only policy, including fusion path.
- Added compare metadata for source transparency (`request_date`, `latest_source_used`, `latest_snapshot_staleness_days`, policy fields).
- Completed deterministic Django-shell monkeypatch smoke tests:
  - fresh snapshot => latest source `snapshot`
  - stale snapshot => latest source `predict`
  - report anchor call path remains snapshot-only in both `H1` and `FUSION` scenarios
