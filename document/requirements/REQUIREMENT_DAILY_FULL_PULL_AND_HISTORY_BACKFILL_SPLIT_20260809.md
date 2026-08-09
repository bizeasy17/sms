# REQUIREMENT: Split Daily Full Pull and History Backfill (UAT)

Date: 2026-08-09
Owner: smartinvestor_etl job orchestration (`daily.bat` and a new backfill batch)

## Goal
Separate two workloads:
1. Daily normal run: fetch current day full-market data by explicit `trade_date`.
2. Historical repair: run a dedicated looping backfill job for missing history.

## Changes
- Update `daily.bat` to pass `--trade_date=<today>` for:
  - `download --dtype=TRADING`
  - `download --dtype=FUNDAMENTAL`
  - `download --dtype=CYQ`
- Add a new batch job `backfill_missing_history.bat`:
  - Keeps per-symbol loop mode.
  - Runs trading/fundamental/cyq backfill from local latest+1 to today.

## Contract Impact
- No API request/response contract changes.
- No DB schema changes.
- Only ETL scheduling and command invocation strategy changes.

## Validation
- Daily run log should show explicit `trade_date` mode for the three ETL downloads.
- Backfill run log should show per-symbol range logs and progress.
