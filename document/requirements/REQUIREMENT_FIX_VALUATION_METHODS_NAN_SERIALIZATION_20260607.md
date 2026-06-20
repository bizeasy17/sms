# Requirement: Fix NaN Serialization in valuation/methods (UAT)

## Background
`GET /api/stocks/{ts_code}/valuation/methods/` may return HTTP 500 when response payload contains `NaN` or `Inf`, observed in:
- `data_by_variant -> list row -> corporate_action_impact -> latest_dividend_event -> stock_distribution_ratio`

## Goal
- Prevent JSON serialization failure (`ValueError: Out of range float values are not JSON compliant: nan`).
- Keep existing valuation logic unchanged; only sanitize response payload values.

## Ownership
- Service owner: `smartinvestor_be` (`api/views.py`).

## Scope
- In scope:
  - Add payload sanitizer for `NaN/Inf` to `None` before `Response(...)` in `get_stock_valuation_methods`.
- Out of scope:
  - Changing valuation formulas or corporate action calculation logic.

## Acceptance Criteria
1. The endpoint no longer returns 500 for the reported request.
2. `stock_distribution_ratio` and similar invalid floats serialize as `null`.
3. Existing valid numeric fields remain unchanged.

## Validation
- Re-run the reported request:
  - `/api/stocks/301080.SZ/valuation/methods/?freq=D&valuation_band_pct=0.1`
- Expected: status 200 and JSON serializable payload.
