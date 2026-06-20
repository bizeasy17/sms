# Requirement: Traditional Valuation Card Gap/Anchor Empty After Manual Refresh (2026-06-13)

## Background
After manually running traditional valuation refresh triggered by market regime switch, user observed the traditional valuation panel cards showing:
- gap: -%
- anchor: -%
for both left/right cards.

## Current Investigation Findings
1. Endpoint used by FE:
- GET /api/stocks/<ts_code>/valuation/methods/?earnings_report_type=Q1

2. Verified sample (000001.SZ) is healthy now:
- current_price present
- rows_count > 0
- summary.composite_valuation_gap_pct / summary.composite_valuation_anchor_gap_pct present
- summary.conservative_valuation_gap_pct / summary.conservative_valuation_anchor_gap_pct present

3. Symptom can occur when summary lacks valuation prices:
- card gap/anchor are derived from summary.composite_valuation_price and summary.conservative_valuation_price
- if these are null, UI shows -%

4. Most likely trigger window:
- during/after partial refresh, selected report bucket may temporarily produce no effective valuation_price rows for the active variant in API assembly path
- then summary values become null, causing both cards to show -%

## Scope
- Service owner: smartinvestor_be (traditional valuation API assembly)
- UI service: smartinvestor_fe (display only; no business logic change required unless fallback label update is needed)

## Proposed Minimal Fix
1. Add API-side defensive fallback in get_stock_valuation_methods path:
- when computed summary for active variant has null composite+conservative prices,
- fallback to nearest non-null variant summary OR nearest non-null method prices (same report scope),
- keep current report filter semantics unchanged.

2. Add lightweight diagnostic metadata in response:
- summary_fallback_applied: true/false
- summary_fallback_reason: enum text

3. Keep FE unchanged for behavior; optional tooltip text if fallback applied.

## Acceptance Criteria
1. For affected symbols, traditional card left/right no longer show both gap/anchor as -% when valid valuation rows exist in same report scope.
2. Existing healthy symbols (e.g. 000001.SZ) remain unchanged in output values.
3. Response includes fallback metadata only when fallback path is used.

## Validation Plan
1. API checks:
- GET /api/stocks/<affected_ts_code>/valuation/methods/?earnings_report_type=Q1
- verify summary fields are non-null and fallback metadata expected

2. Regression checks:
- GET /api/stocks/000001.SZ/valuation/methods/?earnings_report_type=Q1
- values should remain consistent with baseline

## Notes
- This requirement is prepared before code change as requested by workspace workflow.
- Please confirm this requirement to proceed with implementation.
