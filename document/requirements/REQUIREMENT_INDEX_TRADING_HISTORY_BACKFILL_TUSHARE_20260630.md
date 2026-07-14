# Requirement: Index Trading History Backfill From Tushare (UAT)

## Background
- `datastore.StockTradingHistory` currently lacks major index daily records (for example `399300.SZ`, `000001.SH`).
- Market index simplified valuation endpoint falls back to relative mode when index close is unavailable.

## Goal
- Backfill **all available index daily history** from Tushare into `datastore_stocktradinghistory`.
- Keep operation idempotent and safe for reruns.
- Make simplified index traditional valuation use local index trading history close as primary source.

## Scope
- Add a Django management command under `smartinvestor_be/datastore/management/commands/`.
- Pull index universe from `pro.index_basic` (or user-specified `--index-codes`).
- Pull daily bars from `pro.index_daily` with paged fetch for long history.
- Write to `StockTradingHistory` with `freq='D'`.

## Data Contract Impact
- Existing API shape kept; response may include `current_index_price_mode=trading_history|index_daily|relative_base_100` and `note` for source explainability.
- No schema changes.
- Data-only enrichment in existing `datastore_stocktradinghistory` table.

## Write Rules
- Unique key respected: `(trade_date, ts_code, freq)`.
- Insert with conflict-ignore to support repeated runs.
- Do not delete historical rows.

## Validation
- Command output includes:
  - index count
  - fetched rows
  - inserted rows
  - per-index failures
- DB verification samples:
  - `000001.SH`, `399001.SZ`, `000300.SH`, `399300.SZ` row counts and latest trade date.

## Rollback
- If rollback is required, remove inserted rows by `ts_code` + date range via SQL script (not automated in this change).
