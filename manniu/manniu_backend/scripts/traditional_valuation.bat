@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\web\UAT\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\log\traditional_valuation"
set "MODE=%~1"
set "START_DATE=%~2"
set "END_DATE=%~3"
set "SCOPE=%~4"
set "TS_CODES=%~5"
set "LIMIT=%~6"
set "REPORT_TYPES=%~7"
set "HISTORY_YEARS=%~8"

rem PowerShell may omit an empty quoted TS_CODES argument and shift later values left.
rem Recover the documented order when report types remain a single argument.
if /I not "%SCOPE%"=="ts-code" if /I "%LIMIT%"=="Q1" goto :recover_shifted_args
if /I not "%SCOPE%"=="ts-code" if /I "%LIMIT%"=="H1" goto :recover_shifted_args
if /I not "%SCOPE%"=="ts-code" if /I "%LIMIT%"=="Q3" goto :recover_shifted_args
if /I not "%SCOPE%"=="ts-code" if /I "%LIMIT%"=="FY" goto :recover_shifted_args
if /I not "%SCOPE%"=="ts-code" if not "%LIMIT:,=%"=="%LIMIT%" goto :recover_shifted_args
goto :after_recover_shifted_args

:recover_shifted_args
set "SHIFTED_LIMIT=%TS_CODES%"
set "TS_CODES="
set "HISTORY_YEARS=%REPORT_TYPES%"
set "REPORT_TYPES=%LIMIT%"
set "LIMIT=%SHIFTED_LIMIT%"
if "%LIMIT%"=="" set "LIMIT=0"

rem Also accept an unquoted Q1 H1 Q3 FY list after the omitted TS_CODES argument.
if /I "%~9"=="FY" if /I "%~8"=="Q3" goto :recover_unquoted_report_args
goto :after_recover_unquoted_report_args

:recover_unquoted_report_args
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
set "HISTORY_YEARS=%~1"

:after_recover_unquoted_report_args

:after_recover_shifted_args

if "%MODE%"=="" set "MODE=backfill"
if /I "%MODE%"=="history" set "MODE=backfill"
if "%SCOPE%"=="" set "SCOPE=all"
if "%LIMIT%"=="" if /I "%MODE%"=="backfill" set "LIMIT=0"
if "%LIMIT%"=="" set "LIMIT=500"
if "%REPORT_TYPES%"=="" set "REPORT_TYPES=Q1,H1,Q3,FY"
if "%HISTORY_YEARS%"=="" set "HISTORY_YEARS=5"

if not exist "%PYTHON_EXE%" (
    echo ERROR: UAT virtual environment Python was not found.
    exit /b 1
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TIMESTAMP=%%i"
set "LOG_FILE=%LOG_DIR%\traditional_valuation_%MODE%_%RUN_TIMESTAMP%.log"

pushd "%PROJECT_ROOT%" || exit /b 1
set "DJANGO_SETTINGS_MODULE=config.settings"
call :log Traditional valuation %MODE% started.
call :log "Resolved batch parameters: mode=%MODE%; scope=%SCOPE%; ts_codes=%TS_CODES%; start_date=%START_DATE%; end_date=%END_DATE%; report_types=%REPORT_TYPES%; limit=%LIMIT%; history_years=%HISTORY_YEARS%"

"%PYTHON_EXE%" manage.py traditional_valuation validate >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure

if /I "%MODE%"=="backfill" goto :backfill
if /I "%MODE%"=="refresh" goto :refresh
call :log ERROR: MODE must be backfill, history, or refresh.
goto :failure

:backfill
set "DATE_ARGS="
set "HISTORY_ARGS=--history-years %HISTORY_YEARS%"
if not "%START_DATE%"=="" set "DATE_ARGS=--start-date %START_DATE%"
if not "%END_DATE%"=="" set "DATE_ARGS=%DATE_ARGS% --end-date %END_DATE%"
if not "%START_DATE%"=="" set "HISTORY_ARGS="
set "SCOPE_ARGS=--scope %SCOPE%"
if /I "%SCOPE%"=="ts-code" set "SCOPE_ARGS=%SCOPE_ARGS% --ts-codes "%TS_CODES%""
"%PYTHON_EXE%" manage.py traditional_valuation backfill %SCOPE_ARGS% %DATE_ARGS% --report-types "%REPORT_TYPES%" %HISTORY_ARGS% --limit %LIMIT% --historical-disclosures >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure
goto :success

:refresh
"%PYTHON_EXE%" manage.py traditional_valuation detect-events --limit %LIMIT% >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure
"%PYTHON_EXE%" manage.py traditional_valuation consume-events --limit %LIMIT% >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure
goto :success

:success
popd
call :log Traditional valuation %MODE% completed. Log: %LOG_FILE%
exit /b 0

:failure
set "EXIT_CODE=%ERRORLEVEL%"
popd
call :log ERROR: Traditional valuation %MODE% failed. Log: %LOG_FILE%
exit /b %EXIT_CODE%

:log
echo %*
echo %* >> "%LOG_FILE%"