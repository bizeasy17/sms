# REQUIREMENT: Daily Job Missed-Week Backfill (UAT)

Date: 2026-08-09
Owner: smartinvestor_etl (download command), orchestrated by UAT `daily.bat`

## Problem
When daily jobs did not run for a work week and are executed on Sunday, trading/fundamental ETL downloads did not backfill missing days from the last successful date.

## Expected
For `manage.py download --freq=D --dtype=TRADING|FUNDAMENTAL` without explicit date range:
- Start from each symbol's next date after its latest stored `trade_date`.
- End at today.
- Backfill all missing days in between.

## Scope
- `smartinvestor_etl/stockdata/management/commands/download.py`
- `smartinvestor_etl/utils/data_utils.py` (trading/fundamental fetch functions)

## Non-goals
- No API contract change.
- No scheduler/topology changes.

## Validation
- Run ETL daily trading/fundamental download in UAT without date args.
- Confirm logs show range fetch (not single trade_date only).
- Confirm missed-week dates are inserted from last local date forward.
