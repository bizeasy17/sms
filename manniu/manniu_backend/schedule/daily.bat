@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo ERROR: ASI_DEV virtual environment Python was not found.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1

call :sync security-master || goto :failure
call :sync index-master || goto :failure
call :sync company-profile || goto :failure
call :sync stock-bars || goto :failure
call :sync stock-fundamentals || goto :failure
call :sync stock-cost || goto :failure
call :sync index-bars || goto :failure
call :sync index-fundamentals || goto :failure

popd
echo Daily market-data synchronization completed.
exit /b 0

:sync
echo Synchronizing %~1...
"%PYTHON_EXE%" manage.py sync_market_data --dataset %~1 --mode daily --scope all
if errorlevel 1 (
    echo ERROR: %~1 synchronization failed.
    exit /b 1
)
exit /b 0

:failure
popd
exit /b 1