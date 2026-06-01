@echo off
setlocal

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD=%BASE_DIR%..\.venv\Scripts\python.exe"
if exist "%PYTHON_CMD%" (
    "%PYTHON_CMD%" -c "import django" >nul 2>&1
    if errorlevel 1 set "PYTHON_CMD="
)
if not defined PYTHON_CMD if exist "C:\Users\HANJ29\Development\vdev1\Scripts\python.exe" set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not defined PYTHON_CMD set "PYTHON_CMD=python"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
if not exist logs mkdir logs
set "LOG_FILE=logs\quarterly_signal_refresh_%RUN_STAMP%.log"

echo [INFO] quarterly signal refresh job disabled at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] refresh_signal_snapshot execution removed; use daily_financial_periodic_refresh.bat periodic window logic instead >> "%LOG_FILE%"

echo quarterly signal refresh job disabled. log=%LOG_FILE%
exit /b 0