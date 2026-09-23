@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\web\UAT\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\log\predictive_valuation"
set "MODE=%~1"
set "START_DATE=%~2"
set "END_DATE=%~3"
set "SCOPE=%~4"
set "TS_CODES=%~5"
set "LIMIT=%~6"
set "REPORT_TYPES=%~7"
set "ANCHOR_MODE=%~8"
set "HISTORY_YEARS=%~9"

rem PowerShell may pass comma-separated report types as separate batch arguments.
if /I "%~9"=="FY" if /I "%~8"=="Q3" goto :split_report_args
goto :after_split_report_args

:split_report_args
set "TS_CODES="
set "LIMIT=%~5"
set "REPORT_TYPES=%~6,%~7,%~8,%~9"
shift
shift
shift
shift
shift
shift
shift
shift
shift
set "ANCHOR_MODE=%~1"
set "HISTORY_YEARS=%~2"

:after_split_report_args

if "%MODE%"=="" set "MODE=refresh"
if "%SCOPE%"=="" set "SCOPE=all"
if /I "%MODE%"=="history" set "MODE=backfill"
set "START_DATE=%START_DATE:-=%"
set "END_DATE=%END_DATE:-=%"
if "%LIMIT%"=="" if /I "%MODE%"=="backfill" set "LIMIT=0"
if "%LIMIT%"=="" set "LIMIT=500"
if "%REPORT_TYPES%"=="" set "REPORT_TYPES=Q1,H1,Q3,FY"
if "%ANCHOR_MODE%"=="" set "ANCHOR_MODE=live_latest"
if "%HISTORY_YEARS%"=="" set "HISTORY_YEARS=5"

rem Accept the previous positional order: report_types, limit, anchor_mode, history_years.
if "%REPORT_TYPES%"=="0" (
    set "TMP=!REPORT_TYPES!"
    set "REPORT_TYPES=!LIMIT!"
    set "LIMIT=!TMP!"
)

rem PowerShell can omit an empty quoted argument when invoking a .bat file.
rem Recover the current order when the empty ts_codes argument shifts later values left.
if /I not "%SCOPE%"=="ts-code" if not "%LIMIT:,=%"=="%LIMIT%" if /I "%REPORT_TYPES%"=="ann" (
    set "TMP_TS_CODES=!TS_CODES!"
    set "TMP_LIMIT=!LIMIT!"
    set "TMP_REPORT_TYPES=!REPORT_TYPES!"
    set "TMP_ANCHOR_MODE=!ANCHOR_MODE!"
    set "TS_CODES="
    set "LIMIT=!TMP_TS_CODES!"
    set "REPORT_TYPES=!TMP_LIMIT!"
    set "ANCHOR_MODE=!TMP_REPORT_TYPES!"
    set "HISTORY_YEARS=!TMP_ANCHOR_MODE!"
)

if not exist "%PYTHON_EXE%" (
    echo ERROR: UAT virtual environment Python was not found.
    exit /b 1
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TIMESTAMP=%%i"
set "LOG_FILE=%LOG_DIR%\predictive_valuation_%MODE%_%RUN_TIMESTAMP%.log"

pushd "%PROJECT_ROOT%" || exit /b 1
set "DJANGO_SETTINGS_MODULE=config.settings"
call :log Predictive valuation %MODE% started.
call :log "Resolved batch parameters: mode=%MODE%; scope=%SCOPE%; ts_codes=%TS_CODES%; start_date=%START_DATE%; end_date=%END_DATE%; report_types=%REPORT_TYPES%; anchor_mode=%ANCHOR_MODE%; limit=%LIMIT%; history_years=%HISTORY_YEARS%"

"%PYTHON_EXE%" manage.py predictive_valuation validate >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure

if /I "%MODE%"=="backfill" goto :backfill
if /I "%MODE%"=="refresh" goto :refresh

call :log ERROR: MODE must be backfill, history, or refresh.
goto :failure

:backfill
call :backfill_features
if errorlevel 1 goto :failure
call :backfill_valuations
if errorlevel 1 goto :failure
goto :success

:refresh
"%PYTHON_EXE%" manage.py predictive_valuation detect-events --limit %LIMIT% >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure
"%PYTHON_EXE%" manage.py predictive_valuation consume-events --limit %LIMIT% >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure
goto :success

:backfill_features
set "DATE_ARGS="
set "HISTORY_ARGS=--history-years !HISTORY_YEARS!"
if not "!START_DATE!"=="" set "DATE_ARGS=--start-date !START_DATE!"
if not "!END_DATE!"=="" set "DATE_ARGS=!DATE_ARGS! --end-date !END_DATE!"
if not "!START_DATE!"=="" set "HISTORY_ARGS="
set "SCOPE_ARGS=--scope !SCOPE!"
if /I "!SCOPE!"=="ts-code" set "SCOPE_ARGS=!SCOPE_ARGS! --ts-codes "!TS_CODES!""
"!PYTHON_EXE!" manage.py predictive_valuation backfill-features !SCOPE_ARGS! !DATE_ARGS! !HISTORY_ARGS! --limit !LIMIT! >> "!LOG_FILE!" 2>&1
exit /b %ERRORLEVEL%

:backfill_valuations
set "DATE_ARGS="
set "HISTORY_ARGS=--history-years !HISTORY_YEARS!"
if not "!START_DATE!"=="" set "DATE_ARGS=--start-date !START_DATE!"
if not "!END_DATE!"=="" set "DATE_ARGS=!DATE_ARGS! --end-date !END_DATE!"
if not "!START_DATE!"=="" set "HISTORY_ARGS="
set "SCOPE_ARGS=--scope !SCOPE!"
if /I "!SCOPE!"=="ts-code" set "SCOPE_ARGS=!SCOPE_ARGS! --ts-codes "!TS_CODES!""
"!PYTHON_EXE!" manage.py predictive_valuation backfill-valuations !SCOPE_ARGS! !DATE_ARGS! --report-types "!REPORT_TYPES!" --anchor-mode "!ANCHOR_MODE!" !HISTORY_ARGS! --limit !LIMIT! >> "!LOG_FILE!" 2>&1
exit /b %ERRORLEVEL%

:success
popd
call :log Predictive valuation %MODE% completed. Log: %LOG_FILE%
exit /b 0

:failure
set "EXIT_CODE=%ERRORLEVEL%"
popd
call :log ERROR: Predictive valuation %MODE% failed. Log: %LOG_FILE%
exit /b %EXIT_CODE%

:log
echo %*
echo %* >> "%LOG_FILE%"
