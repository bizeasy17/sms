# Requirement: Fix weekly undervalued export argparse percent help bug (UAT)

## Background
Running UAT weekly pipeline fails at step `BE weekly undervalued export`.
The command `manage.py exportweeklyundervalued` throws:
`ValueError: badly formed help string`

Root cause from stack trace:
- `prediction/management/commands/exportweeklyundervalued.py`
- argparse help string contains `%` in Chinese text `收益率(%)`
- argparse treats `%` as formatter token and requires escaping as `%%`.

## Goal
- Make `exportweeklyundervalued` parse arguments successfully.
- Ensure weekly pipeline no longer fails at weekly undervalued export due to this issue.

## Scope
- In scope: fix help string escaping in command arguments.
- Out of scope: strategy logic changes, scoring/filtering behavior changes.

## Acceptance Criteria
1. `manage.py exportweeklyundervalued --strategy-style balanced` runs without argparse help-string exception.
2. Re-running `weekly.bat` passes the `BE weekly undervalued export` step.

## Validation
- Command-level check:
  - `python manage.py exportweeklyundervalued --strategy-style balanced`
- Pipeline-level check:
  - rerun `UAT/weekly.bat` and confirm no failure on weekly undervalued export.
