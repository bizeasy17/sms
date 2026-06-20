# REQUIREMENT: Align Valuation Picking Buy-Candidate Gate With Backtest (2026-06-19)

## 1. Background

Current behavior differs between valuation picking and backtest:

- Both use shared `summarize_buy_candidate` core scoring logic.
- Backtest adds an extra hard gate before entry: `current_price <= conservative_valuation_price`.
- Valuation picking (`buy_candidate_only=1`) currently only checks `buy_candidate == true`, without enforcing the same hard gate.

This causes observable mismatch: some symbols appear as buy candidates in picking UI but are not eligible for backtest entry on the same day.

## 2. Objective

Adopt option 1 (full alignment):

- In valuation picking flow, align buy-candidate eligibility with backtest gate.
- Enforce hard condition: `current_price <= conservative_valuation_price` for buy-candidate inclusion.

## 3. Service Ownership

Owner service: `web/UAT/smartinvestor_be`.

Change surface:

- API path: valuation picking endpoint in `api/views.py`.
- No DB schema change.
- No frontend contract break expected (same response fields retained).

## 4. Functional Requirements

1. For valuation picking rows, compute an additional boolean gate:
   - `pass_backtest_candidate_gate = (current_price is not None) and (conservative_valuation_price is not None) and (current_price <= conservative_valuation_price)`.

2. When `buy_candidate_only=1`, row inclusion requires BOTH:
   - `buy_candidate == true`, and
   - `pass_backtest_candidate_gate == true`.

3. For consistency and explainability, expose alignment status in response payload (row-level), for example:
   - `buy_candidate_backtest_aligned` (boolean)
   - `buy_candidate_backtest_align_reason` (string, optional)

4. Keep existing valuation score and valuation status logic unchanged.

## 5. Non-Goals

- No changes to shared valuation scoring formula in `valuation_summary`.
- No changes to backtest strategy/risk/financial filter logic.
- No changes to predictive-only signal filters.

## 6. Compatibility & Risk

Expected impact:

- Number of rows returned under `buy_candidate_only=1` may decrease.
- Existing clients without `buy_candidate_only=1` should see no major sorting/filter break.

Risk mitigation:

- Keep legacy fields intact.
- Add alignment flags for auditability.

## 7. Validation Plan

1. Static check: ensure no syntax/runtime errors in `api/views.py`.
2. In-process API smoke test (RequestFactory):
   - Run valuation picking endpoint with `buy_candidate_only=1`.
   - Verify every returned row satisfies `current_price <= conservative_valuation_price`.
3. Spot-check with `buy_candidate_only=0`:
   - Confirm rows may include non-aligned candidates, but flags correctly reflect alignment status.
4. Regression sanity:
   - Existing `valuation_status`, `valuation_score`, and pagination behavior remain valid.

## 8. Rollback

Single-file rollback in `api/views.py` by removing hard-gate enforcement and alignment fields.

## 9. Acceptance Criteria

- Under `buy_candidate_only=1`, no row violates `current_price <= conservative_valuation_price`.
- Response includes clear row-level alignment marker(s).
- No new errors from static diagnostics for touched files.
