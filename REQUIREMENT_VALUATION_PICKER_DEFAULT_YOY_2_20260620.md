# REQUIREMENT: Valuation Picker Financial YoY Defaults = 2 (2026-06-20)

## Background
The valuation stock-picking page currently initializes:
- min_netprofit_yoy = null
- min_ebit_yoy = null

This causes the two fields to be empty on first load.

## Requirement
Set default value to 2 for both fields on page initialization:
- min_netprofit_yoy default = 2
- min_ebit_yoy default = 2

Apply this to both pages:
- Backtest execute page
- Valuation stock-picking page (financial filter panel)

## Scope
- Frontend only (smartinvestor_fe)
- Do not change backend filtering logic
- Do not change API contract

## Acceptance
1. First entering valuation picker page shows:
   - Net Profit YoY Min = 2
   - EBIT YoY Min = 2
2. Clicking run/preview without manual edits sends:
   - min_netprofit_yoy=2
   - min_ebit_yoy=2
3. Existing user override behavior remains unchanged.
4. On valuation stock-picking page, quick-strategy apply should keep default 2 when profile does not specify min_netprofit_yoy/min_ebit_yoy.

## File Impact (planned)
- smartinvestor_fe/src/views/BacktestExecuteView.vue
- smartinvestor_fe/src/components/ValuationStockPickingFilter.vue
