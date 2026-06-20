# REQUIREMENT: Weekly Pipeline Add Traditional Valuation Risk Refresh (2026-06-19)

## 1. Background

Weekly undervalued export currently filters by traditional risk level, but weekly pipeline does not explicitly refresh valuation risk snapshots before export.

## 2. Objective

Add a valuation risk refresh step into weekly pipeline before weekly undervalued export.

## 3. Service Ownership

- Owner: `web/UAT` pipeline script (`weekly.bat`)
- Backend command: `smartinvestor_be/manage.py prefillvaluationrisk --market CN`

## 4. Functional Change

1. Insert step in `weekly.bat`:
   - Step name: `BE weekly valuation risk prefill`
   - Command: `python manage.py prefillvaluationrisk --market CN`
2. Execution order:
   - After `BE weekly valuation due runner`
   - Before `BE weekly undervalued export`

## 5. Validation Plan

1. Run one manual traditional valuation refresh (`earnings_refresh.bat`) in UAT.
2. Verify weekly script contains new risk step.
3. (Optional next run) verify weekly export no longer sees risk coverage collapse.

## 6. Acceptance Criteria

- Weekly pipeline script includes risk prefill step in correct order.
- Manual traditional valuation refresh command runs successfully.
