@echo off
setlocal EnableExtensions EnableDelayedExpansion

if /I "%DEBUG_TRACE%"=="1" echo on

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

set "START_DATE=%~1"
if "%START_DATE%"=="" set "START_DATE=2024-01-01"
set "END_DATE=%~2"
if "%END_DATE%"=="" set "END_DATE=2025-12-31"
set "SCOPE=%~3"
if "%SCOPE%"=="" set "SCOPE=ALL"
set "DEFAULT_METHODS=sw_history,pe,pb,ps,peg,fcff_dcf,ddm"
set "METHODS="
set "CADENCE_DAYS=30"
set "ENABLE_FULL_REFRESH=%BACKFILL_ENABLE_FULL_REFRESH%"
if "%ENABLE_FULL_REFRESH%"=="" set "ENABLE_FULL_REFRESH=0"
set "TEMPLATE_REFRESH_MONTHS=%BACKFILL_TEMPLATE_REFRESH_MONTHS%"
if "%TEMPLATE_REFRESH_MONTHS%"=="" set "TEMPLATE_REFRESH_MONTHS=05,09,11"

set "ARG_IDX=0"
set "PARSE_STAGE=methods"
for %%A in (%*) do (
  set /a ARG_IDX+=1
  if !ARG_IDX! GEQ 4 (
    set "TOK=%%~A"
    if /I "!PARSE_STAGE!"=="methods" (
      echo !TOK!| findstr /R "^[0-9][0-9]*$" >nul 2>&1
      if not errorlevel 1 (
        set "CADENCE_DAYS=!TOK!"
      ) else (
        if not defined METHODS (
          set "METHODS=!TOK!"
        ) else (
          set "METHODS=!METHODS!,!TOK!"
        )
      )
    )
  )
)

if not defined METHODS set "METHODS=%DEFAULT_METHODS%"

echo %CADENCE_DAYS%| findstr /R "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 (
  echo [WARN] invalid cadence_days=%CADENCE_DAYS%, fallback to 30
  set "CADENCE_DAYS=30"
)

if /I not "%ENABLE_FULL_REFRESH%"=="0" if /I not "%ENABLE_FULL_REFRESH%"=="1" (
  echo [WARN] invalid BACKFILL_ENABLE_FULL_REFRESH=%ENABLE_FULL_REFRESH%, fallback to 0
  set "ENABLE_FULL_REFRESH=0"
)

if not exist logs mkdir logs
set "LOG_FILE=logs\backfill_traditional_history_event_driven_2023_2024.log"
set "CHECKPOINT_FILE=logs\backfill_traditional_history_event_driven_2023_2024.checkpoint"
set "EVENT_DATES_FILE=%BASE_DIR%logs\event_dates_traditional_2023_2024.txt"
set "EVENT_REASONS_FILE=%BASE_DIR%logs\event_dates_traditional_2023_2024_reasons.csv"
set "FULL_REFRESH_DATES_FILE=%BASE_DIR%logs\event_dates_traditional_full_refresh_2023_2024.txt"
set "FINANCIAL_CODES_DIR=%BASE_DIR%logs\event_codes_traditional_2023_2024"
set "TEMPLATE_REFRESH_MARKET=CN"

set "RESUME_FROM="
if exist "%CHECKPOINT_FILE%" (
  set /p RESUME_FROM=<"%CHECKPOINT_FILE%"
)

echo [INFO] traditional event-driven backfill start %DATE% %TIME%>>"%LOG_FILE%"
echo [INFO] start_date=%START_DATE% end_date=%END_DATE% scope=%SCOPE% methods=%METHODS% cadence_days=%CADENCE_DAYS% enable_full_refresh=%ENABLE_FULL_REFRESH% template_refresh_months=%TEMPLATE_REFRESH_MONTHS% resume_from=%RESUME_FROM%>>"%LOG_FILE%"

"%PYTHON_CMD%" "tushare_earnings_service\manage.py" export_backfill_event_dates --start-date %START_DATE% --end-date %END_DATE% --scope %SCOPE% --output-file %EVENT_DATES_FILE% --reasons-file %EVENT_REASONS_FILE% --financial-apis disclosure_date,express_vip,income,fina_indicator_vip --financial-date-codes-dir %FINANCIAL_CODES_DIR% --cadence-days %CADENCE_DAYS% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] export_backfill_event_dates failed code=%ERR%>>"%LOG_FILE%"
  echo traditional event-driven backfill failed. see %LOG_FILE%
  exit /b %ERR%
)

> "%FULL_REFRESH_DATES_FILE%" type nul
if "%ENABLE_FULL_REFRESH%"=="1" (
  if exist "%EVENT_REASONS_FILE%" (
    for /f "usebackq skip=1 tokens=1,* delims=," %%A in ("%EVENT_REASONS_FILE%") do (
      set "DAY_DATE=%%A"
      set "DAY_REASONS=%%B"
      set "HAS_CADENCE=!DAY_REASONS:cadence:=!"
      set "HAS_REGIME=!DAY_REASONS:regime:=!"
      if not "!HAS_CADENCE!"=="!DAY_REASONS!" (
        >> "%FULL_REFRESH_DATES_FILE%" echo !DAY_DATE!
      ) else if not "!HAS_REGIME!"=="!DAY_REASONS!" (
        >> "%FULL_REFRESH_DATES_FILE%" echo !DAY_DATE!
      )
    )
  )
) else (
  echo [INFO] full refresh disabled by config, only financial event-driven partial refresh will run>>"%LOG_FILE%"
)

for /f "usebackq delims=" %%D in ("%EVENT_DATES_FILE%") do (
  call :process_date %%D
  if errorlevel 1 goto :FAILED
)

echo [INFO] traditional event-driven backfill completed %DATE% %TIME%>>"%LOG_FILE%"
echo traditional event-driven backfill completed. log=%LOG_FILE%
exit /b 0

:process_date
set "CUR_DATE=%~1"
if defined RESUME_FROM (
  if "%CUR_DATE%" LEQ "%RESUME_FROM%" (
    echo [SKIP] %CUR_DATE% already completed>>"%LOG_FILE%"
    exit /b 0
  )
)

echo [STEP] trade_date=%CUR_DATE%>>"%LOG_FILE%"

findstr /x /c:"%CUR_DATE%" "%FULL_REFRESH_DATES_FILE%" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
  echo [MODE] full_refresh_by_cadence_or_regime date=%CUR_DATE%>>"%LOG_FILE%"
  set "CUR_MONTH=%CUR_DATE:~5,2%"
  set "ALLOW_TEMPLATE_REFRESH=0"
  if /I "%TEMPLATE_REFRESH_MONTHS%"=="ALL" (
    set "ALLOW_TEMPLATE_REFRESH=1"
  ) else (
    set "MONTHS_PAD=,%TEMPLATE_REFRESH_MONTHS%,"
    set "TARGET_MONTH=,!CUR_MONTH!,"
    if /I not "!MONTHS_PAD:%TARGET_MONTH%=!"=="!MONTHS_PAD!" (
      set "ALLOW_TEMPLATE_REFRESH=1"
    )
  )
  if "!ALLOW_TEMPLATE_REFRESH!"=="1" (
    if not defined TEMPLATE_REFRESH_DONE_MONTHS set "TEMPLATE_REFRESH_DONE_MONTHS="
    set "DONE_PAD=,!TEMPLATE_REFRESH_DONE_MONTHS!,"
    if /I "!DONE_PAD:%TARGET_MONTH%=!"=="!DONE_PAD!" (
      echo [STEP] update_templates_if_due market=%TEMPLATE_REFRESH_MARKET% date=%CUR_DATE% month=!CUR_MONTH! months=%TEMPLATE_REFRESH_MONTHS%>>"%LOG_FILE%"
      "%PYTHON_CMD%" "smartinvestor_be\manage.py" updatevaluationconfigs --market %TEMPLATE_REFRESH_MARKET% --run-due >> "%LOG_FILE%" 2>&1
      set "ERR=%ERRORLEVEL%"
      if not "!ERR!"=="0" (
        echo [ERROR] update_templates_if_due failed date=%CUR_DATE% code=!ERR!>>"%LOG_FILE%"
        exit /b !ERR!
      )
      if defined TEMPLATE_REFRESH_DONE_MONTHS (
        set "TEMPLATE_REFRESH_DONE_MONTHS=!TEMPLATE_REFRESH_DONE_MONTHS!,!CUR_MONTH!"
      ) else (
        set "TEMPLATE_REFRESH_DONE_MONTHS=!CUR_MONTH!"
      )
    ) else (
      echo [SKIP] update_templates_if_due already_done_in_run date=%CUR_DATE% month=!CUR_MONTH!>>"%LOG_FILE%"
    )
  ) else (
    echo [SKIP] update_templates_if_due month_gate date=%CUR_DATE% month=!CUR_MONTH! months=%TEMPLATE_REFRESH_MONTHS%>>"%LOG_FILE%"
  )
  "%PYTHON_CMD%" "smartinvestor_be\manage.py" prefillvaluationsnapshot --trade-date %CUR_DATE% --scope %SCOPE% --freq D --refresh-policy all --price-anchor-mode market_now --profit-buckets both --backfill-history-only --methods %METHODS% >> "%LOG_FILE%" 2>&1
) else (
  set "DAY_CODES_FILE=%FINANCIAL_CODES_DIR%\%CUR_DATE%.txt"
  if exist "!DAY_CODES_FILE!" (
    for %%z in ("!DAY_CODES_FILE!") do set "DAY_CODES_SIZE=%%~zz"
    if "!DAY_CODES_SIZE!"=="0" (
      echo [SKIP] trade_date=%CUR_DATE% no financial event codes>>"%LOG_FILE%"
      exit /b 0
    )
    echo [MODE] partial_refresh_by_financial_events date=%CUR_DATE% file=!DAY_CODES_FILE!>>"%LOG_FILE%"
    "%PYTHON_CMD%" "smartinvestor_be\manage.py" prefillvaluationsnapshot --trade-date %CUR_DATE% --scope %SCOPE% --codes-file "!DAY_CODES_FILE!" --freq D --refresh-policy all --price-anchor-mode market_now --profit-buckets both --backfill-history-only --methods %METHODS% >> "%LOG_FILE%" 2>&1
  ) else (
    echo [SKIP] trade_date=%CUR_DATE% no financial event codes file>>"%LOG_FILE%"
    exit /b 0
  )
)
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] trade_date=%CUR_DATE% failed code=%ERR%>>"%LOG_FILE%"
  exit /b %ERR%
)
> "%CHECKPOINT_FILE%" echo %CUR_DATE%
echo [OK] trade_date=%CUR_DATE%>>"%LOG_FILE%"
exit /b 0

:FAILED
set "ERR=%ERRORLEVEL%"
echo [ERROR] traditional event-driven backfill failed code=%ERR%>>"%LOG_FILE%"
echo traditional event-driven backfill failed. see %LOG_FILE%
exit /b %ERR%
