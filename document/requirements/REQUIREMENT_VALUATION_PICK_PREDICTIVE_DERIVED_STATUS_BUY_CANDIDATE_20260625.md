# Requirement: Predictive Stock Picking Derived Status/Buy Candidate (Path A)

## Background
In valuation stock picking predictive mode, existing filters `valuation_status` and `buy_candidate_only` are currently evaluated by traditional valuation-side fields before predictive filtering. This causes mismatch with predictive snapshot cards.

## Ownership
- Implementing service: `smartinvestor_be` (aggregator layer)
- No schema changes in `tushare_earnings_service` snapshot tables

## Scope
- Endpoint: `GET /api/stock-pick-valuation/{trade_date}/{scope}/`
- File: `smartinvestor_be/api/views.py`
- Mode affected: `picking_mode=predictive` only

## Functional Changes
1. Add predictive-derived fields using existing predictive snapshot/enrichment payload:
   - `predictive_valuation_status`: derived from `target_return_pct` and valuation band.
   - `predictive_buy_candidate`: derived from predictive action/score/risk/target return.
2. In predictive mode, switch filtering semantics:
   - `valuation_status` filter should apply to `predictive_valuation_status`.
   - `buy_candidate_only` filter should apply to `predictive_buy_candidate`.
3. In predictive mode result rows, switch displayed/returned semantic fields:
   - `valuation_status` should reflect predictive-derived status.
   - `buy_candidate` should reflect predictive-derived buy candidate.
   - Keep legacy valuation-side values in separate compatibility fields.

## Rules (Default Thresholds)
- Predictive valuation status (band aligned with `valuation_band_pct`, default 0.1):
  - `under`: `target_return_pct >= +10%`
  - `fair`: `-10% < target_return_pct < +10%`
  - `over`: `target_return_pct <= -10%`
  - missing `target_return_pct`: `unknown`
- Predictive buy candidate:
  - `action == BUY`
  - `signal_score >= 85`
  - `risk_level in {LOW, MEDIUM}`
  - `target_return_pct >= 10`

## Compatibility
- Traditional mode behavior remains unchanged.
- Request params remain unchanged (`valuation_status`, `buy_candidate_only`).
- Existing clients continue working; semantics switch only when `picking_mode=predictive`.

## Validation
1. `manage.py check` in `smartinvestor_be` passes.
2. Predictive pick smoke for scope `68`:
   - Baseline strict query reproduces deterministic result count.
   - Relaxing `valuation_status`/`buy_candidate_only` affects results according to predictive-derived fields.
3. Spot-check symbol `688111.SH`:
   - Should be evaluated by predictive-derived `valuation_status`/`buy_candidate` in predictive mode.

## Out of Scope
- DB migrations in earnings snapshot models.
- Frontend UI redesign (optional label refinement excluded in this minimal patch).
