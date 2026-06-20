# REQUIREMENT: Monthly Pipeline Add Traditional Risk Refresh + Weekly Undervalued Export (2026-06-19)

## 1. Background

Current monthly pipeline already performs traditional valuation monthly refresh, but does not explicitly run:

1. Traditional valuation risk refresh for current coverage.
2. Weekly undervalued export generation after monthly valuation refresh.

Because weekly undervalued export depends on both valuation snapshots and risk snapshots, running export without same-cycle risk refresh can produce very small or empty traditional results.

## 2. Objective

Integrate traditional valuation risk refresh and weekly undervalued export into monthly pipeline, leveraging the existing monthly valuation snapshot refresh.

## 3. Service Ownership

- Owner script: `web/UAT/monthly.bat`
- Backend command owner: `web/UAT/smartinvestor_be`

## 4. Scope

### In Scope

1. Update `web/UAT/monthly.bat` to add two BE steps.
2. Keep existing monthly steps and fail-fast behavior unchanged.

### Out of Scope

1. No changes to valuation/risk scoring logic.
2. No FE/API contract changes.
3. No ETL schema or model changes.

## 5. Change Plan (Exact Step Order)

Insert these two steps **after** `BE traditional valuation monthly full refresh` and **before** `Earnings predictive valuation monthly full refresh`:

1. `BE monthly traditional valuation risk prefill`
   - Command:
     - `python manage.py prefillvaluationrisk --market CN`
2. `BE monthly weekly undervalued export`
   - Command:
     - `call smartinvestor_be\weekly_undervalued_friday.bat`

Target sequence around changed region:

1. `BE traditional valuation monthly full refresh`
2. `BE monthly traditional valuation risk prefill` (new)
3. `BE monthly weekly undervalued export` (new)
4. `Earnings predictive valuation monthly full refresh`

## 6. Validation Plan

1. Run `monthly.bat` in UAT (or run new steps manually in same order for smoke check).
2. Verify log contains both new step names in expected order.
3. Verify weekly export output files are generated under:
   - `smartinvestor_be/output/weekly_undervalued/`
4. Verify monthly pipeline remains fail-fast when any new step fails.

## 7. Acceptance Criteria

1. `monthly.bat` includes both new steps in the specified order.
2. Monthly run triggers risk prefill before weekly undervalued export.
3. Weekly export artifacts are generated during monthly run.
4. Existing monthly behavior and error handling are preserved.
