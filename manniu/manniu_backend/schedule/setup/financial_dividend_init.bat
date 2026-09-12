@echo off
setlocal

set "PROJECT_ROOT=%~dp0..\.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\log\financials"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TIMESTAMP=%%i"
set "LOG_FILE=%LOG_DIR%\financial_dividend_init_%RUN_TIMESTAMP%.log"

if not exist "%PYTHON_EXE%" (
    call :log ERROR: ASI_DEV virtual environment Python was not found.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
call :log Dividend financial data synchronization started.
call :log Log file: %LOG_FILE%
call :log Using quarterly mode without date filters so Tushare stk_div is queried by ts_code only.

"%PYTHON_EXE%" manage.py sync_financials --mode quarterly --scope all --endpoints dividend >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :failure

call :log Dividend financial data synchronization completed.
popd
exit /b 0

:failure
call :log ERROR: Dividend financial data synchronization failed. See %LOG_FILE%
popd
exit /b 1

:log
echo %*
