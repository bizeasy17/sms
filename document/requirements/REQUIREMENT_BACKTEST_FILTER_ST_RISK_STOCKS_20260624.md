# REQUIREMENT: Backtest Filter ST/*ST Risk Stocks (UAT)

## 1. Background

User requires both traditional valuation backtest and predictive valuation backtest to exclude ST risk stocks (including names marked as ST or *ST) from candidate universe and trade execution.

## 2. Scope

- Workspace: UAT
- Service chain:
  - smartinvestor_be traditional backtest engine
  - smartinvestor_be predictive backtest gateway universe builder
- Frontend/API contract:
  - No request/response field changes required.
  - Behavior-only change: ST/*ST stocks are excluded by default.

## 3. Functional Requirements

### 3.1 Traditional Backtest (Signal + Account)

- In both traditional modes:
  - traditional_value_exit
  - traditional_value_exit_account
- Exclude ST risk stocks from buy candidate stage.
- ST risk recognition rule (name-based):
  - stock name starts with `ST`
  - stock name starts with `*ST`
  - stock name starts with `S*ST`
  - stock name starts with `SST`
- Existing open positions logic unchanged; filter applies to new entries.

### 3.2 Predictive Backtest

- In predictive market universe construction, exclude ST risk stocks before sending `ts_codes` to predictive service.
- Keep existing `.BJ` exclusion unchanged and stack with ST exclusion.

## 4. Non-Functional Constraints

- Minimal patch only; no unrelated refactor.
- Preserve current API payload shapes.
- Keep deterministic behavior for same inputs.

## 5. Verification Plan

### 5.1 Backend Static Checks

- smartinvestor_be: `manage.py check`
- tushare_earnings_service: `manage.py check` (regression safety for predictive chain)

### 5.2 Functional Smoke Checks

- Traditional run: verify buy candidate/trade outputs do not contain ST/*ST names.
- Predictive run payload preparation: verify effective `ts_codes` excludes ST/*ST and `.BJ`.

### 5.3 Build Check

- Frontend build not required for behavior-only backend change; run only if touched.

## 6. Impacted Files (Planned)

- `smartinvestor_be/backtest/services.py`
- `smartinvestor_be/backtest/views.py`

## 7. Risks and Rollback

- Risk: Name-based rule depends on `Corporation.name` quality.
- Rollback: revert patch in the two impacted files.

## 8. Acceptance Criteria

- Both traditional and predictive backtest flows do not buy/include ST/*ST risk stocks.
- Existing non-ST universe remains unchanged except already-existing filters.
- `manage.py check` passes for touched services.
