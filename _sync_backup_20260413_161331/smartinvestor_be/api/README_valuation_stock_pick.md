# Valuation Stock Picking API

## Endpoint

`GET /api/stock-pick-valuation/{trade_date}/{scope}/{model}/{model_version}/{top_bottom}/{freq}/{period}/{params}/{from_index}/{to_index}/`

This endpoint is dedicated for valuation-based picking page and is isolated from the legacy picking UI endpoint.

## Path Params

- `trade_date`: e.g. `2026-03-20`
- `scope`: `WATCHLIST` / `60` / `0` / `3` / `688` / `SCOPE:NONE` equivalent path value used by frontend
- `model`: `xgb` / `rf` / `cat`
- `model_version`: e.g. `1.2`
- `top_bottom`: `B` / `T` / `B,T`
- `freq`: `D` / `W` / `M`
- `period`: integer, e.g. `60`
- `params`: legacy combined filter string, e.g. `ALL` or `STAT:TVOL|FEAT:IS_BULLISH_AND_DIVERGENT`
- `from_index`: pagination start index
- `to_index`: pagination end index

## Query Params

- `valuation_method`: `pe` / `pb` / `ps` / `peg` / `fcff_dcf` / `ddm`
- `valuation_status`: `under` / `fair` / `over`
- `valuation_band_pct`: e.g. `0.1`
- `valuation_pick_strategy`: `baseline` / `best_score` / `median` / `min` / `max` / `first`
- `buy_candidate_only`: `1` to return only buy candidates
- `valuation_business_topn`: optional business-match candidate count

## Dedicated Endpoint Defaults

If query params are not provided, this endpoint still forces valuation flow with defaults:

- `valuation_method=pe`
- `valuation_band_pct=0.1`
- `valuation_pick_strategy` uses backend setting `LIVE_VALUATION_PICK_STRATEGY`
- valuation calculation is always enabled

## Response Notes

`data[]` includes normal picking fields plus valuation-specific fields:

- `valuation_method`
- `valuation_price`
- `valuation_market_cap`
- `valuation_status`
- `valuation_gap_pct`
- `valuation_source`
- `valuation_candidate_count`
- `valuation_pick_strategy`
- `buy_candidate`
- `undervalue_score`
- `composite_valuation_price`
- `conservative_valuation_price`

Response also contains `valuation_filter` and `meta` sections for frontend diagnostics.
