# REQUIREMENT: Market Index Valuation Price Source Close Only (UAT)

Date: 2026-07-17
Owner Service: smartinvestor_be
Endpoint: GET /api/market-index/valuation-simple/

## Background
Header market index valuation summary currently compares implied valuation prices with a current index price that may come from `close_qfq` in `datastore_stocktradinghistory`. For index codes (e.g. `000001.SH`), adjusted close is not the desired comparison baseline for this business scenario.

## Problem
- Price source mismatch: valuation factors (`INDEX_DAILYBASIC`) can be up to date while current index price is stale or from adjusted-field preference.
- User-visible gap percent can be misleading when baseline is not the standard index close.

## Scope
Only `get_market_index_simple_valuation` in smartinvestor_be.

## Contract Changes
Backward compatible additive/behavioral adjustment:
1. Current index price selection for market index valuation should use `close` only when reading from `datastore_stocktradinghistory`.
2. Response adds explicit source metadata fields:
   - `current_index_price_field`
   - `current_index_price_source_table`

No request parameter changes.

## DB/API Fields Confirmation
- Trading source table/model: `datastore_stocktradinghistory` (`StockTradingHistory`)
- Valuation factor table: `earnings_mkt_index_dailybasic`
- Existing summary fields kept as-is.

## Acceptance Criteria
1. For `index_code=000001.SH`, gap percentage is computed against close-based current price.
2. Response explicitly states the field/table used for current price.
3. Existing consumers remain compatible (no removed fields).

## Risk
Low. Logic is localized to one endpoint and preserves old response fields.

## Rollback
Revert modified branch in `get_market_index_simple_valuation` to prior close_qfq-first behavior.
