@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD="
if exist "C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe" set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not defined PYTHON_CMD set "PYTHON_CMD=%BASE_DIR%..\.venv\Scripts\python.exe"
if exist "%PYTHON_CMD%" (
    "%PYTHON_CMD%" -c "import django" >nul 2>&1
    if errorlevel 1 set "PYTHON_CMD="
)
if not defined PYTHON_CMD set "PYTHON_CMD=python"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
if not exist logs mkdir logs
set "LOG_FILE=logs\monthly_signal_full_refresh_%RUN_STAMP%.log"
set "BATCH_KEY=monthly_full_%RUN_STAMP%"

echo [INFO] monthly signal full refresh start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] batch_key=%BATCH_KEY% >> "%LOG_FILE%"

echo [STEP] monthly_financial_maintenance >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py monthly_financial_maintenance --scope 60,00,30,68 --latest-only >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo [ERROR] monthly_financial_maintenance failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
    echo monthly signal full refresh failed. see %LOG_FILE%
    exit /b %ERR%
)

echo [STEP] refresh_signal_snapshot --full-refresh >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py refresh_signal_snapshot --scope 60,00,30,68 --full-refresh --report-types LATEST --store-mode both --serving-slot production --sleep-ms 50 --batch-key %BATCH_KEY% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo [ERROR] refresh_signal_snapshot full failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
    echo monthly signal full refresh failed. see %LOG_FILE%
    exit /b %ERR%
)

echo [INFO] monthly signal full refresh completed at %DATE% %TIME% >> "%LOG_FILE%"
echo monthly signal full refresh completed. log=%LOG_FILE%
exit /b 0
