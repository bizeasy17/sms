# Requirement: Predictive Backtest Persist Full Replay Params (UAT)

## Background
Current predictive backtest history records do not persist all replay filters/inputs. As a result, history replay can only restore partial information.

Target behavior should align with traditional backtest history: all effective replay parameters must be persisted and recoverable from run history/detail APIs.

## Problem Statement
For predictive backtest runs, persisted `params` may miss parts of the actual execution inputs (especially optional filter fields and `batch_key_map` details), causing:
1. Run-history dialog cannot fully display all conditions.
2. Replay from history cannot recover full original filtering context.

## Scope
- Primary owner service: `UAT/tushare_earnings_service` (predictive backtest persistence)
- Pass-through compatibility check: `UAT/smartinvestor_be` proxy endpoints
- FE display compatibility (read-only of new/complete params): `UAT/smartinvestor_fe`

## Functional Requirements
1. Persist full effective replay parameters for predictive runs
- On run creation (`/api/forecast/backtest/run/`), persist complete effective params used by engine, not only minimal subset.
- Must include all supported filters and execution controls accepted by predictive backtest payload normalization.
- Must include predictive batch mapping payload:
  - `batch_key_map` full object per report type.

2. Stable detail/list response contract
- `GET /api/forecast/backtest/runs/` rows include full `params` object for each run.
- `GET /api/forecast/backtest/runs/{id}/` returns `params` equal to persisted full params.
- Existing fields remain backward compatible.

3. Replay consistency
- Replaying a run from history with returned params should reconstruct same parameter intent as original run.
- If legacy runs have incomplete params, keep compatibility fallback and mark as partial only for old data.

## API Contract Impact
- Additive/compatibility-safe enhancement only.
- No endpoint path changes.
- Response body extends completeness of `params` but does not remove old keys.

## Technical Plan (Minimal)
1. In predictive service `earnings_forecast/views.py`:
- ensure normalization builds a full canonical params dict (`effective_params`).
- persist `effective_params` into `EarningsBacktestRun.params`.
- ensure `batch_key_map` is copied/preserved as complete object.

2. In list/detail serializers for predictive runs:
- always return persisted `params`.
- avoid rebuilding with defaults that can mask missing persisted keys unless explicitly needed for legacy fallback.

3. In BE proxy (`smartinvestor_be/backtest/views.py`):
- keep transparent proxy behavior (no key dropping).

## Validation
1. Execute predictive backtest with non-default filters and full batch mapping.
2. Check DB row `EarningsBacktestRun.params` contains all sent/effective keys, including `batch_key_map`.
3. Verify:
- `/api/forecast/backtest/runs/?limit=1&offset=0` first row `params` complete.
- `/api/forecast/backtest/runs/{id}/` `params` complete and consistent.
4. Open FE history and confirm parameter text can display all replay conditions.

## Out Of Scope
- Backfilling all historical rows by migration job (can be a separate task).
- Changing predictive strategy math/logic.
