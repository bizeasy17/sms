@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"

set "CORE_INDICES=000001.SH,399001.SZ,399006.SZ,000688.SH,000300.SH,000905.SH,000852.SH,000016.SH"

if not exist "%PYTHON_EXE%" (
    echo ERROR: ASI_DEV virtual environment Python was not found.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1

call :sync security-master by-code || goto :failure
call :sync index-master by-code || goto :failure
call :sync company-profile by-code || goto :failure
call :sync stock-bars by-date || goto :failure
call :sync stock-fundamentals by-date || goto :failure
call :sync stock-cost by-date || goto :failure
call :sync_indices index-bars || goto :failure
call :sync_indices index-fundamentals || goto :failure

popd
echo Daily market-data synchronization completed.
exit /b 0

:sync
echo Synchronizing %~1...
"%PYTHON_EXE%" manage.py sync_market_data --dataset %~1 --mode daily --scope all --strategy %~2
if errorlevel 1 (
    echo ERROR: %~1 synchronization failed.
    exit /b 1
)
exit /b 0

:sync_indices
echo Synchronizing %~1 for core indices...
"%PYTHON_EXE%" manage.py sync_market_data --dataset %~1 --mode daily --scope ts-code --ts-codes "%CORE_INDICES%"
if errorlevel 1 (
    echo ERROR: %~1 synchronization failed.
    exit /b 1
)
exit /b 0

:failure
popd
exit /b 1