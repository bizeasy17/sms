# Requirement: Fix Predictive Backtest History List Pagination and Missing Fields (UAT)

## Background
In Backtest Execute "Run History" dialog under predictive source:
1. Many columns are blank in manual/favorites list (total_return_pct, max_drawdown_pct, start_date, end_date, starting_capital, ending_capital, params, avg_holding_days, sharpe/sortino/calmar, profit_factor, expectancy_pct).
2. Pagination is incorrect: UI shows only first 20 rows repeatedly; total count is incorrect; favorites count can be much larger than visible rows.

## Root Cause
1. Predictive service list endpoint `GET /api/forecast/backtest/runs/` currently:
   - does not accept/use `offset`
   - returns `count` (page size) but not `total`
   - always returns `qs[:limit]` from first page
2. Predictive list rows do not include enough fields (`params`, derived summary metrics) for FE columns.
3. FE history loader expects backend paging with `limit+offset` and total-style metadata; for predictive source this expectation is not met.

## Scope
- Backend (required):
  - `UAT/tushare_earnings_service/earnings_forecast/views.py`
  - `UAT/smartinvestor_be/backtest/views.py` (pass-through query update if needed)
- Frontend (minimal optional compatibility):
  - `UAT/smartinvestor_fe/src/views/BacktestExecuteView.vue`

## Functional Requirements
1. Predictive runs list endpoint supports paging correctly:
   - inputs: `limit`, `offset`, optional `batch_key`
   - returns: `data`, `count`, `total`, `limit`, `offset`
2. Predictive runs list rows include fields needed by run-history table:
   - top-level: `id`, `run_key`, `batch_key`, `status`, `created_at`, `updated_at`
   - `params` (full normalized params for display)
   - `summary` enriched with:
     - `trade_count`, `avg_return_pct`, `median_return_pct`, `win_rate_pct`
     - `total_return_pct`, `max_drawdown_pct`, `avg_holding_days`
     - `sharpe_ratio`, `sortino_ratio`, `calmar_ratio`, `profit_factor`, `expectancy_pct`
     - `starting_capital`, `ending_capital`
   - start/end date should be available via row-level fields or params fallback (prefer both)
3. Favorites tab can iterate through pages and aggregate favorite run ids across full result set.

## Compatibility
- Keep endpoint path and existing fields backward compatible.
- Additive response enhancement only.

## Validation
1. API smoke checks:
   - `/api/forecast/backtest/runs/?limit=20&offset=0`
   - `/api/forecast/backtest/runs/?limit=20&offset=20`
   - ensure returned ids differ across pages and `total` is stable.
2. FE run-history dialog under predictive source:
   - manual tab total > 20 can page beyond first page.
   - previously blank columns now populated for rows with available stats.
   - favorites tab can display more than first-page rows when favorite ids exceed 20.

## Out of Scope
- Recomputing historical runs that never stored sufficient metrics in result payload.
- Changing metric definitions.
