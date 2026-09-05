@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "DJANGO_SETTINGS_MODULE="
set "PYTHONIOENCODING=utf-8"

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

if not defined PYTHON_CMD set "PYTHON_CMD=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

set "START_DATE=%~1"
if "%START_DATE%"=="" set "START_DATE=2024-01-01"
set "END_DATE=%~2"
if "%END_DATE%"=="" set "END_DATE=2025-12-31"
set "SCOPE=%~3"
if "%SCOPE%"=="" set "SCOPE=ALL"
set "PLAN_FILE=%~4"
set "PLAN_MODE=0"
if not "%PLAN_FILE%"=="" if exist "%PLAN_FILE%" set "PLAN_MODE=1"

if "%PLAN_MODE%"=="1" (
  set "REPORT_TYPES="
  set "STORE_MODE=%~5"
  if "%STORE_MODE%"=="" set "STORE_MODE=history"
  set "ENABLE_REGIME_SWITCH=%~6"
  if "%ENABLE_REGIME_SWITCH%"=="" set "ENABLE_REGIME_SWITCH=1"
) else (
  set "REPORT_TYPES=%~4"
  if "%REPORT_TYPES%"=="" set "REPORT_TYPES=LATEST"
  set "STORE_MODE=%~5"
  if "%STORE_MODE%"=="" set "STORE_MODE=history"
  set "ENABLE_REGIME_SWITCH=%~6"
  if "%ENABLE_REGIME_SWITCH%"=="" set "ENABLE_REGIME_SWITCH=1"
  set "ARG7=%~7"

  rem Rebuild scope when PowerShell splits comma-separated stock list into extra args.
  set "IDX=4"
  :collect_scope_tokens
  call set "CUR=%%%IDX%%"
  if "%CUR%"=="" goto scope_collect_done
    echo %CUR%| findstr /R /I "^[0-9][0-9][0-9][0-9][0-9][0-9]\.[A-Z][A-Z]$" >nul 2>&1
  if errorlevel 1 goto scope_collect_done
  if /I not "%SCOPE%"=="ALL" set "SCOPE=%SCOPE%,%CUR%"
  set /a IDX+=1
  goto collect_scope_tokens

  :scope_collect_done
  if not "%IDX%"=="4" (
    call set "REPORT_TYPES=%%%IDX%%"
    if "%REPORT_TYPES%"=="" set "REPORT_TYPES=LATEST"
    set /a IDX+=1
    call set "STORE_MODE=%%%IDX%%"
    if "%STORE_MODE%"=="" set "STORE_MODE=history"
    set /a IDX+=1
    call set "ENABLE_REGIME_SWITCH=%%%IDX%%"
    if "%ENABLE_REGIME_SWITCH%"=="" set "ENABLE_REGIME_SWITCH=1"
    set /a IDX+=1
    call set "ARG7=%%%IDX%%"
  )

  rem PowerShell can split LATEST,FUSION into two positional args (LATEST FUSION).
  rem Auto-rejoin and shift params so users don't need to remember quoting rules.
  if /I "%REPORT_TYPES%"=="LATEST" if /I "%STORE_MODE%"=="FUSION" (
    if /I "%ENABLE_REGIME_SWITCH%"=="history" (
      set "REPORT_TYPES=LATEST,FUSION"
      set "STORE_MODE=history"
      if not "%ARG7%"=="" set "ENABLE_REGIME_SWITCH=%ARG7%"
    )
  )
)

if /I not "%STORE_MODE%"=="latest" if /I not "%STORE_MODE%"=="history" if /I not "%STORE_MODE%"=="both" (
  echo [WARN] invalid store_mode=%STORE_MODE%, fallback to history
  set "STORE_MODE=history"
)

if /I not "%ENABLE_REGIME_SWITCH%"=="0" if /I not "%ENABLE_REGIME_SWITCH%"=="1" (
  echo [WARN] invalid enable_regime_switch=%ENABLE_REGIME_SWITCH%, fallback to 1
  set "ENABLE_REGIME_SWITCH=1"
)

if not exist logs mkdir logs
set "RUN_TAG=%BACKFILL_RUN_TAG%"
if defined RUN_TAG set "RUN_TAG=_%RUN_TAG%"
if defined RUN_TAG set "RUN_TAG=%RUN_TAG: =%"
set "LOG_FILE=logs\backfill_predictive_history_event_driven%RUN_TAG%.log"
set "CHECKPOINT_FILE=logs\backfill_predictive_history_event_driven%RUN_TAG%.checkpoint"
set "EVENT_DATES_FILE=logs\event_dates_predictive%RUN_TAG%.txt"
set "EVENT_REASONS_FILE=logs\event_dates_predictive_reasons%RUN_TAG%.csv"
set "FULL_REFRESH_DATES_FILE=logs\event_dates_predictive_full_refresh%RUN_TAG%.txt"
set "FINANCIAL_CODES_DIR=logs\event_codes_predictive%RUN_TAG%"

set "RESUME_FROM="
if exist "%CHECKPOINT_FILE%" (
  set /p RESUME_FROM=<"%CHECKPOINT_FILE%"
)

set "REGIME_FLAG="
if "%ENABLE_REGIME_SWITCH%"=="1" set "REGIME_FLAG=--enable-regime-switch"

if "%PLAN_MODE%"=="1" goto :run_plan

echo [INFO] predictive event-driven backfill start %DATE% %TIME%>>"%LOG_FILE%"
echo [INFO] start_date=%START_DATE% end_date=%END_DATE% scope=%SCOPE% report_types=%REPORT_TYPES% store_mode=%STORE_MODE% enable_regime_switch=%ENABLE_REGIME_SWITCH% resume_from=%RESUME_FROM%>>"%LOG_FILE%"
echo [INFO] final_parsed_args start_date=%START_DATE% end_date=%END_DATE% scope=%SCOPE% report_types=%REPORT_TYPES% store_mode=%STORE_MODE% enable_regime_switch=%ENABLE_REGIME_SWITCH% >>"%LOG_FILE%"

if /I not "%BACKFILL_SKIP_PRECHECK%"=="1" (
  set "PRECHECK_REPORT=%BASE_DIR%logs\predictive_history_precheck%RUN_TAG%.json"
  "%PYTHON_CMD%" "tushare_earnings_service\manage.py" check_history_backfill_prerequisites --start-date %START_DATE% --end-date %END_DATE% --scope %SCOPE% --report-file "!PRECHECK_REPORT!" >> "%LOG_FILE%" 2>&1
  set "ERR=!ERRORLEVEL!"
  if not "!ERR!"=="0" (
    echo [ERROR] predictive precheck failed code=!ERR! report=!PRECHECK_REPORT!>>"%LOG_FILE%"
    exit /b !ERR!
  )
)

"%PYTHON_CMD%" "tushare_earnings_service\manage.py" export_backfill_event_dates --start-date %START_DATE% --end-date %END_DATE% --scope %SCOPE% --output-file %EVENT_DATES_FILE% --reasons-file %EVENT_REASONS_FILE% --financial-apis disclosure_date,express_vip,income,fina_indicator_vip --financial-date-codes-dir %FINANCIAL_CODES_DIR% --full-refresh-dates-file %FULL_REFRESH_DATES_FILE% %REGIME_FLAG% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] export_backfill_event_dates failed code=%ERR%>>"%LOG_FILE%"
  echo predictive event-driven backfill failed. see %LOG_FILE%
  exit /b %ERR%
)

for /f "usebackq delims=" %%D in ("%EVENT_DATES_FILE%") do (
  call :process_date %%D
  if errorlevel 1 goto :FAILED
)

echo [INFO] predictive event-driven backfill completed %DATE% %TIME%>>"%LOG_FILE%"
echo predictive event-driven backfill completed. log=%LOG_FILE%
exit /b 0

:run_plan
if not exist logs mkdir logs
set "PLAN_LOG=logs\backfill_predictive_history_event_driven_plan.log"

set "TAIL_ARGS="
set /a IDX=5
:collect_plan_tail_args
call set "CUR=%%%IDX%%"
if "%CUR%"=="" goto plan_tail_done
set "TAIL_ARGS=%TAIL_ARGS% %CUR%"
set /a IDX+=1
goto collect_plan_tail_args

:plan_tail_done
set /a PLAN_TOTAL=0
set /a PLAN_OK=0
set /a PLAN_FAIL=0
echo [INFO] plan mode start %DATE% %TIME% file=%PLAN_FILE% start_date=%START_DATE% end_date=%END_DATE% scope=%SCOPE% tail_args=%TAIL_ARGS%>>"%PLAN_LOG%"

for /f "usebackq tokens=1,2 delims=," %%A in (`powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $lines=Get-Content -LiteralPath '%PLAN_FILE%'; foreach($line in $lines){ $raw=$line.Trim(); if(-not $raw){ continue }; if($raw.StartsWith('#')){ continue }; foreach($seg in ($raw -split ',')){ $s=$seg.Trim(); if(-not $s){ continue }; $parts=$s -split '\|',2; if($parts.Count -lt 2){ continue }; $year=$parts[0].Trim(); $reports=$parts[1].Trim().ToUpper(); if(-not $year -or -not $reports){ continue }; if($reports -eq 'ALL'){ $reports='LATEST,FUSION' }; Write-Output ($year + ',' + $reports) } }"`) do (
  call :run_plan_task %%~A %%~B
)

echo [INFO] plan mode done total=!PLAN_TOTAL! ok=!PLAN_OK! fail=!PLAN_FAIL! %DATE% %TIME%>>"%PLAN_LOG%"
if not "!PLAN_FAIL!"=="0" (
  echo predictive event-driven backfill plan failed partially. see %PLAN_LOG%
  exit /b 1
)
echo predictive event-driven backfill plan completed. log=%PLAN_LOG%
exit /b 0

:run_plan_task
set "TASK_YEAR=%~1"
set "TASK_REPORT_TYPES=%~2"

echo %TASK_YEAR%| findstr /R "^[0-9][0-9][0-9][0-9]$" >nul 2>&1
if errorlevel 1 (
  echo [WARN] skip invalid plan year=%TASK_YEAR%>>"%PLAN_LOG%"
  exit /b 0
)
if "%TASK_REPORT_TYPES%"=="" (
  echo [WARN] skip empty report_types for year=%TASK_YEAR%>>"%PLAN_LOG%"
  exit /b 0
)

set "TASK_START=%TASK_YEAR%-01-01"
set "TASK_END=%TASK_YEAR%-12-31"
if "%START_DATE%" GTR "%TASK_START%" set "TASK_START=%START_DATE%"
if "%END_DATE%" LSS "%TASK_END%" set "TASK_END=%END_DATE%"
if "%TASK_START%" GTR "%TASK_END%" (
  echo [SKIP] out-of-range year=%TASK_YEAR% start=%TASK_START% end=%TASK_END%>>"%PLAN_LOG%"
  exit /b 0
)

set /a PLAN_TOTAL+=1
set "BACKFILL_RUN_TAG=plan_%TASK_YEAR%"
echo [TASK] start idx=!PLAN_TOTAL! year=%TASK_YEAR% report_types=%TASK_REPORT_TYPES% start=%TASK_START% end=%TASK_END% run_tag=!BACKFILL_RUN_TAG!>>"%PLAN_LOG%"
call "%~f0" "%TASK_START%" "%TASK_END%" "%SCOPE%" "%TASK_REPORT_TYPES%"%TAIL_ARGS%
set "TASK_ERR=!ERRORLEVEL!"
if not "%TASK_ERR%"=="0" (
  set /a PLAN_FAIL+=1
  echo [TASK] fail idx=!PLAN_TOTAL! year=%TASK_YEAR% report_types=%TASK_REPORT_TYPES% code=%TASK_ERR%>>"%PLAN_LOG%"
) else (
  set /a PLAN_OK+=1
  echo [TASK] ok idx=!PLAN_TOTAL! year=%TASK_YEAR% report_types=%TASK_REPORT_TYPES%>>"%PLAN_LOG%"
)
exit /b 0

:process_date
set "CUR_DATE=%~1"
if defined RESUME_FROM (
  if "%CUR_DATE%" LEQ "%RESUME_FROM%" (
    echo [SKIP] %CUR_DATE% already completed>>"%LOG_FILE%"
    exit /b 0
  )
)

echo [STEP] asof_date=%CUR_DATE%>>"%LOG_FILE%"
set "STEP_LOG=logs\_tmp_backfill_pred_event_%CUR_DATE%%RUN_TAG%.log"
if exist "%STEP_LOG%" del /q "%STEP_LOG%" >nul 2>&1

findstr /x /c:"%CUR_DATE%" "%FULL_REFRESH_DATES_FILE%" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
  echo [MODE] full_refresh_by_regime_switch date=%CUR_DATE%>>"%LOG_FILE%"
  "%PYTHON_CMD%" "tushare_earnings_service\manage.py" refresh_signal_snapshot --full-refresh --scope %SCOPE% --asof-date %CUR_DATE% --store-mode %STORE_MODE% --report-types %REPORT_TYPES% --serving-slot production --anchor-mode ann --batch-key backfill_pred_event_%CUR_DATE% >> "%STEP_LOG%" 2>&1
) else (
  set "DAY_CODES_FILE=%FINANCIAL_CODES_DIR%\%CUR_DATE%.txt"
  if exist "!DAY_CODES_FILE!" (
    for %%z in ("!DAY_CODES_FILE!") do set "DAY_CODES_SIZE=%%~zz"
    if "!DAY_CODES_SIZE!"=="0" (
      echo [SKIP] asof_date=%CUR_DATE% no financial event codes>>"%LOG_FILE%"
      exit /b 0
    )
    echo [MODE] partial_refresh_by_financial_events date=%CUR_DATE% file=!DAY_CODES_FILE!>>"%LOG_FILE%"
    "%PYTHON_CMD%" "tushare_earnings_service\manage.py" refresh_signal_snapshot --tscodes-file "!DAY_CODES_FILE!" --asof-date %CUR_DATE% --store-mode %STORE_MODE% --report-types %REPORT_TYPES% --serving-slot production --anchor-mode ann --batch-key backfill_pred_event_%CUR_DATE% >> "%STEP_LOG%" 2>&1
  ) else (
    echo [SKIP] asof_date=%CUR_DATE% no financial event codes file>>"%LOG_FILE%"
    exit /b 0
  )
)
set "ERR=%ERRORLEVEL%"
if exist "%STEP_LOG%" type "%STEP_LOG%" >> "%LOG_FILE%"
if not "%ERR%"=="0" (
  findstr /I /C:"No rows for ts_code=" "%STEP_LOG%" >nul 2>&1
  if "%ERRORLEVEL%"=="0" (
    findstr /I /C:"all predictions failed (ok=0, fail=1)" "%STEP_LOG%" >nul 2>&1
    if "%ERRORLEVEL%"=="0" (
      echo [SKIP] asof_date=%CUR_DATE% all candidates returned no rows>>"%LOG_FILE%"
      > "%CHECKPOINT_FILE%" echo %CUR_DATE%
      if exist "%STEP_LOG%" del /q "%STEP_LOG%" >nul 2>&1
      exit /b 0
    )
  )
  echo [ERROR] asof_date=%CUR_DATE% failed code=%ERR%>>"%LOG_FILE%"
  if exist "%STEP_LOG%" del /q "%STEP_LOG%" >nul 2>&1
  exit /b %ERR%
)
> "%CHECKPOINT_FILE%" echo %CUR_DATE%
echo [OK] asof_date=%CUR_DATE%>>"%LOG_FILE%"
if exist "%STEP_LOG%" del /q "%STEP_LOG%" >nul 2>&1
exit /b 0

:FAILED
set "ERR=%ERRORLEVEL%"
echo [ERROR] predictive event-driven backfill failed code=%ERR%>>"%LOG_FILE%"
echo predictive event-driven backfill failed. see %LOG_FILE%
exit /b %ERR%
