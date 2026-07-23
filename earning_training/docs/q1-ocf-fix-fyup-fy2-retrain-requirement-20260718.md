# Q1 OCF Fix Retrain Requirement (FY2 Holdout)

## Background
- Current Q1 retrain (`uat_20260718_q1_ocf_fix`) auto-fell back from `target_fy_up` to `target_valuation_up`.
- Root cause: with `fy_test_years=1`, Q1 test split has only single-class `target_fy_up` labels, so classifier target is not trainable/evaluable.

## Goal
- Keep Q1 classification target at `target_fy_up` for same-label comparability.
- Minimize config changes and rerun Q1 training + business replay metrics.

## Change Scope
- Config only, no Python code changes.
- New config file: `configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2.yaml`
  - `train.model_version`: `uat_20260718_q1_ocf_fix_fy2`
  - `train.fy_test_years`: `2`

## Contract and Data Impact
- API request/response fields: no changes.
- DB schema/table fields: no changes.
- Runtime behavior: Q1 training split selection changes for label availability, expected to keep `cls_target_col=target_fy_up`.

## Validation Plan
1. Train Q1 only with new config.
2. Verify output metrics file reports `cls_target_col=target_fy_up`.
3. Replay compare baseline vs new (same target) on top-decile return/hit-rate/max-drawdown.
