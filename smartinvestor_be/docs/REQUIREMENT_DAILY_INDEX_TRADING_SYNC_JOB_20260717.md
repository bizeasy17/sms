# REQUIREMENT: Daily Index Trading History Sync Job (UAT)

Date: 2026-07-17
Owner Service: smartinvestor_be

## Goal
Provide a daily-updated index trading history command and wire it into the UAT daily job pipeline.

## Scope
- Reuse and enhance command: `manage.py sync_index_trading_history`
- Add incremental mode suitable for daily execution.
- Add one step in UAT top-level `daily.bat`.

## DB/API Fields Confirmation
- Target model/table: `datastore.StockTradingHistory` / `datastore_stocktradinghistory`
- Index price field for downstream comparison: `close`
- Existing endpoint contract remains unchanged for requests.

## Command Contract
- `--mode {delta,full}` (default `delta`)
- `--delta-overlap-days` for safe overlap refresh in delta mode
- Keep `--start-date/--end-date` for backfill/full scenarios

## Scheduling Contract
- Add a new daily step in `UAT/daily.bat` after BE daily trading pull.
- Use delta mode with overlap to capture late corrections.

## Acceptance
1. Daily job can execute index trading sync without manual parameters.
2. Command in delta mode fetches only needed date window per index code.
3. New rows are written into `datastore_stocktradinghistory` for configured index list.

---

## UAT Hotfix 2026-07-23

### Background
- UAT `daily.bat` step `BE daily index trading sync` became abnormally slow.
- Root cause: a large subset of CSI index `ts_code` values now exceed 10 chars (for example `931833CNY120.CSI`), while `datastore.StockTradingHistory.ts_code` is `varchar(10)`.
- Existing command attempted to write those rows one by one, generating repeated `value too long for type character varying(10)` failures and extending runtime significantly.

### DB/API Fields Confirmation
- Target table/model remains `datastore_stocktradinghistory` / `datastore.StockTradingHistory`.
- Existing DB field constraint remains unchanged in this hotfix: `ts_code max_length=10`.
- No API request/response contract changes.

### Hotfix Scope
- In `manage.py sync_index_trading_history`, pre-filter overlong index codes (`len(ts_code) > 10`) before fetch/save.
- Keep processing compatible codes only, and print skip summary + sample codes for observability.

### Hotfix Acceptance
1. Daily index sync no longer spends most time on repeated overlong-code insert failures.
2. Command summary includes skipped overlong code count.
3. Existing downstream API behavior remains unchanged.
