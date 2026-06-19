# REQUIREMENT: Backtest History Archive Retention 14 Days (2026-06-19)

## 1. Background

Backtest history dialog loading is slow when historical records accumulate over time.
Current backend history aggregation loads active runs plus archive runs/files in one request path.

## 2. Objective

Keep working-set history to recent 14 days and archive older records/files.
Default history API response should prioritize active working set and skip archive scanning unless explicitly requested.

## 3. Service Ownership

- Owner service: `web/UAT/smartinvestor_be` (`backtest` app)
- Touch points:
  - Backtest history API in `backtest/views.py`
  - New archive command in `backtest/management/commands/`

## 4. Functional Changes

1. Add management command to archive old backtest runs:
   - Command name: `archivebacktestruns`
   - Default retention: 14 days
   - Candidate rule: `updated_at < now - retention_days`
   - Scope: `traditional_value_exit` and `traditional_value_exit_account`
2. Archive outputs:
   - Export archived DB rows to `output/archive/db_backtest_runs_cleanup_<timestamp>/traditional_backtest_runs.json`
   - Move run result JSON files to `output/archive/backtests/<strategy_name>/`
3. Working set cleanup:
   - Remove archived records from active DB after successful export/move bookkeeping.
4. API behavior for history loading:
   - Add query param `include_archive` (default `0`)
   - When `include_archive=0`, skip archive file/JSON scan for faster dialog load.
   - When `include_archive=1`, keep existing archive-inclusive behavior.

## 5. Non-Goals

1. No UI layout changes.
2. No changes to backtest scoring logic.
3. No deletion of archive data.

## 6. Validation Plan

1. Run archive command in dry-run mode and verify candidate counts.
2. Run command in apply mode and verify:
   - Archive JSON file created.
   - Archived run files moved to archive folder.
   - Active DB count reduced for older than 14 days.
3. Verify API:
   - `GET /backtest/traditional/runs/?kind=manual` returns active only by default.
   - `GET /backtest/traditional/runs/?kind=manual&include_archive=1` includes archive rows.

## 7. Acceptance Criteria

1. Backtest history API default load path avoids archive scan.
2. Archive command can relocate old runs/files and export metadata safely.
3. Recent 14-day runs remain in working set.
4. Archive data remains retrievable with `include_archive=1`.
