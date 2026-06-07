# Requirement: Persist Variant-Level Valuation Summary on Refresh (UAT)

## 1. Background
Current valuation selection paths compute variant-level summary at request time in multiple API flows, which adds repeated CPU work for batch list/result pages.
Refresh pipeline already produces `summary_by_variant`, but it is not persisted as a first-class query target.

## 2. Goal
Persist variant-level summary during valuation refresh, so selection/list APIs can read precomputed summary directly.

## 3. Scope
- Service owner: `smartinvestor_be` (to be confirmed by user before code changes).
- Environment order: implement and validate in DEV first, then sync to UAT.
- This phase implements **latest snapshot summary persistence only** (no history table in first iteration).

## 4. Proposed Data Contract (Latest)
A new latest summary model/table keyed by:
- `ts_code`
- `market`
- `valuation_variant`
- `latest_trade_date`
- optional alignment keys: `profit_report_type`, `profit_report_end_date` (if needed by existing query paths)

Suggested fields:
- `composite_valuation_price` (float)
- `conservative_valuation_price` (float)
- `undervalue_score` (float/int)
- `buy_candidate` (bool)
- `buy_candidate_reason` (text)
- `valuation_valid_methods` (json)
- `valuation_under_methods` (json)
- `buy_candidate_rule_version` (string)
- `updated_at` (datetime)

## 5. Write Path
During valuation refresh:
1. Build per-variant `summary_by_variant` using existing summary logic.
2. Bulk upsert latest summary rows in the same refresh transaction boundary where reasonable.
3. Keep source-of-truth logic unchanged by reusing existing summary function.

## 6. Read Path (Phase 1)
- Switch batch-oriented valuation selection/list queries to read latest summary table first.
- Keep fallback to runtime summary computation for safety if summary row missing.

## 7. Non-Functional Requirements
- Keep API contract backward-compatible.
- Keep runtime behavior consistent with current summary rule version.
- Include migration and index for key query dimensions.

## 8. Validation Plan
- Unit tests for summary upsert and retrieval.
- API regression check: before/after response parity for summary fields.
- Performance spot check: compare list endpoint response time (same input, before vs after).

## 9. Risks
- Rule version drift if summary logic changes without backfill.
- Missing summary rows for edge cases (must fallback to runtime compute).
- Added write cost in refresh pipeline.

## 10. Rollback
- Feature flag or guarded read path: disable persisted-summary read and revert to runtime computation.
- Keep schema in place if rollback is read-path-only.

## 11. Acceptance Criteria
- Refresh writes variant-level latest summary rows successfully.
- Batch selection/list endpoints can read persisted summary without behavior regression.
- Tests pass and verification commands/results are reported.
