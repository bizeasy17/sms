@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\web\UAT\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\log\daily"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TIMESTAMP=%%i"
set "LOG_FILE=%LOG_DIR%\daily_%RUN_TIMESTAMP%.log"

set "CORE_INDICES=000001.SH,399001.SZ,000300.SH,000016.SH,000905.SH,399005.SZ,399006.SZ"

if not exist "%PYTHON_EXE%" (
    call :log ERROR: UAT virtual environment Python was not found.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || (
    call :log ERROR: Could not change directory to %PROJECT_ROOT%.
    exit /b 1
)
call :log Daily market-data synchronization started.
call :log Log file: %LOG_FILE%

call :sync security-master by-code || goto :failure
call :sync index-master by-code || goto :failure
call :sync company-profile by-code || goto :failure
call :sync stock-bars by-date || goto :failure
call :sync stock-fundamentals by-date || goto :failure
call :sync stock-cost by-date || goto :failure
call :sync_indices index-bars || goto :failure
call :sync_indices index-fundamentals || goto :failure
call :sync sw-industry-daily by-date || goto :failure
call :detect_regime_events || goto :failure
call :sync_financials || goto :failure

popd
call :log Daily market-data synchronization completed.
exit /b 0

:sync
call :log Synchronizing %~1...
"%PYTHON_EXE%" manage.py sync_market_data --dataset %~1 --mode daily --scope all --strategy %~2 >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log ERROR: %~1 synchronization failed. See %LOG_FILE%
    exit /b 1
)
call :log %~1 synchronization completed.
exit /b 0

:sync_indices
call :log Synchronizing %~1 for core indices...
"%PYTHON_EXE%" manage.py sync_market_data --dataset %~1 --mode daily --scope ts-code --ts-codes "%CORE_INDICES%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log ERROR: %~1 synchronization failed. See %LOG_FILE%
    exit /b 1
)
call :log %~1 synchronization completed.
exit /b 0

:sync_financials
call :log Synchronizing financial data for disclosures due today...
"%PYTHON_EXE%" manage.py sync_financials --mode daily --scope actual-date >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log ERROR: financial synchronization failed. See %LOG_FILE%
    exit /b 1
)
call :log Financial synchronization completed.
exit /b 0

:detect_regime_events
call :log Detecting market and security regime events...
"%PYTHON_EXE%" manage.py detect_regime_events --scope all >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log ERROR: regime event detection failed. See %LOG_FILE%
    exit /b 1
)
call :log Regime event detection completed.
exit /b 0

:failure
call :log Daily market-data synchronization failed. See %LOG_FILE%
popd
exit /b 1

:log
echo %*
>> "%LOG_FILE%" echo %*
exit /b 0