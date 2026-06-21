# REQUIREMENT: Predictive Event Backfill Skip No-Rows Failures (2026-06-21)

## Background
During event-driven predictive backfill, some dates may contain symbols that return `No rows for ts_code=...`.
Current script treats `ok=0 fail=1` as fatal and exits, blocking long-running backfills.

## Owner
- Service/Script: `UAT/backfill_predictive_history_event_driven_2024_2025.bat`

## Goal
- For per-date runs that fail only because of `No rows for ts_code`, auto-skip the date and continue the batch.

## Scope
- Update failure handling in `:process_date` of the event-driven predictive backfill script.
- Keep all non-no-rows failures as fatal (existing behavior).

## Acceptance Criteria
1. When a date fails and command output contains both:
   - `No rows for ts_code=`
   - `all predictions failed (ok=0, fail=1)`
   the script writes a `[SKIP]` entry, updates checkpoint to current date, and continues.
2. For other non-zero exits, script still writes `[ERROR]` and exits with non-zero code.
3. Existing parameters, logging, and checkpoint semantics remain compatible.

## Validation
- One-day run reproducing no-rows case should not abort whole script.
- One-day run with a real unexpected error should still fail fast.
