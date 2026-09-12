@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\log\financials"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TIMESTAMP=%%i"
set "LOG_FILE=%LOG_DIR%\financial_data_init_%RUN_TIMESTAMP%.log"

if not exist "%PYTHON_EXE%" (
    call :log ERROR: ASI_DEV virtual environment Python was not found.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
call :log Financial data initialization started.
call :log Log file: %LOG_FILE%

call :sync disclosure_date || goto :failure
call :sync income_vip || goto :failure
call :sync balancesheet_vip || goto :failure
call :sync cashflow_vip || goto :failure
call :sync fina_indicator_vip || goto :failure
call :sync forecast_vip || goto :failure
call :sync express_vip || goto :failure
call :sync dividend || goto :failure
call :sync fina_audit || goto :failure
call :sync fina_mainbz_vip || goto :failure

popd
call :log Initial financial data synchronization completed.
exit /b 0

:sync
call :log Initializing %~1 with the default five-year history window...
"%PYTHON_EXE%" manage.py sync_financials --mode backfill --scope all --endpoints %~1 >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log ERROR: %~1 initialization failed. See %LOG_FILE%
    exit /b 1
)
call :log %~1 initialization completed.
exit /b 0

:failure
call :log Financial data initialization failed. See %LOG_FILE%
popd
exit /b 1

:log
echo %*
