@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\log\predictive_valuation"
set "MODE=%~1"
set "START_DATE=%~2"
set "END_DATE=%~3"
set "SCOPE=%~4"
set "TS_CODES=%~5"
set "LIMIT=%~6"

if "%MODE%"=="" set "MODE=refresh"
if "%SCOPE%"=="" set "SCOPE=all"
if /I "%MODE%"=="history" set "MODE=backfill"
if "%LIMIT%"=="" if /I "%MODE%"=="backfill" set "LIMIT=0"
if "%LIMIT%"=="" set "LIMIT=500"

if not exist "%PYTHON_EXE%" (
    echo ERROR: ASI_DEV virtual environment Python was not found.
    exit /b 1
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TIMESTAMP=%%i"
set "LOG_FILE=%LOG_DIR%\predictive_valuation_%MODE%_%RUN_TIMESTAMP%.log"

pushd "%PROJECT_ROOT%" || exit /b 1
set "DJANGO_SETTINGS_MODULE=config.settings"
call :log Predictive valuation %MODE% started.

"%PYTHON_EXE%" manage.py predictive_valuation validate >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure

if /I "%MODE%"=="backfill" (
    call :backfill_features || goto :failure
    call :backfill_valuations || goto :failure
    goto :success
)
if /I "%MODE%"=="refresh" (
    "%PYTHON_EXE%" manage.py predictive_valuation detect-events --limit %LIMIT% >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto :failure
    "%PYTHON_EXE%" manage.py predictive_valuation consume-events --limit %LIMIT% >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto :failure
    goto :success
)

call :log ERROR: MODE must be backfill, history, or refresh.
goto :failure

:backfill_features
set "DATE_ARGS="
if not "%START_DATE%"=="" set "DATE_ARGS=--start-date %START_DATE%"
if not "%END_DATE%"=="" set "DATE_ARGS=%DATE_ARGS% --end-date %END_DATE%"
set "SCOPE_ARGS=--scope %SCOPE%"
if /I "%SCOPE%"=="ts-code" set "SCOPE_ARGS=%SCOPE_ARGS% --ts-codes %TS_CODES%"
"%PYTHON_EXE%" manage.py predictive_valuation backfill-features %SCOPE_ARGS% %DATE_ARGS% --limit %LIMIT% >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:backfill_valuations
set "DATE_ARGS="
if not "%START_DATE%"=="" set "DATE_ARGS=--start-date %START_DATE%"
if not "%END_DATE%"=="" set "DATE_ARGS=%DATE_ARGS% --end-date %END_DATE%"
set "SCOPE_ARGS=--scope %SCOPE%"
if /I "%SCOPE%"=="ts-code" set "SCOPE_ARGS=%SCOPE_ARGS% --ts-codes %TS_CODES%"
"%PYTHON_EXE%" manage.py predictive_valuation backfill-valuations %SCOPE_ARGS% %DATE_ARGS% --limit %LIMIT% >> "%LOG_FILE%" 2>&1
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
