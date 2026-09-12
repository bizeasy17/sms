@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\log\market_data"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TIMESTAMP=%%i"
set "LOG_FILE=%LOG_DIR%\market_data_init_%RUN_TIMESTAMP%.log"

set "CORE_INDICES=000001.SH,399001.SZ,000300.SH,000016.SH,000905.SH,399005.SZ,399006.SZ"

if not exist "%PYTHON_EXE%" (
    call :log ERROR: ASI_DEV virtual environment Python was not found.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
call :log Market-data initialization started.
call :log Log file: %LOG_FILE%

call :sync security-master || goto :failure
call :sync index-master || goto :failure
call :sync company-profile || goto :failure
call :sync stock-bars || goto :failure
call :sync stock-fundamentals || goto :failure
call :sync stock-cost || goto :failure
call :sync_indices index-bars || goto :failure
call :sync_indices index-fundamentals || goto :failure

popd
call :log Initial market-data synchronization completed.
exit /b 0

:sync
call :log Initializing %~1 with the default five-year history window...
"%PYTHON_EXE%" manage.py sync_market_data --dataset %~1 --mode backfill --scope all >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log ERROR: %~1 initialization failed. See %LOG_FILE%
    exit /b 1
)
call :log %~1 initialization completed.
exit /b 0

:sync_indices
call :log Initializing %~1 for core indices [%CORE_INDICES%] with the default five-year history window...
"%PYTHON_EXE%" manage.py sync_market_data --dataset %~1 --mode backfill --scope ts-code --ts-codes "%CORE_INDICES%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log ERROR: %~1 initialization failed. See %LOG_FILE%
    exit /b 1
)
call :log %~1 initialization completed.
exit /b 0

:failure
call :log Market-data initialization failed. See %LOG_FILE%
popd
exit /b 1

:log
echo %*
>> "%LOG_FILE%" echo %*
exit /b 0