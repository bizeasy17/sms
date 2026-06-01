@echo off
setlocal

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
if not exist logs mkdir logs
set "LOG_FILE=logs\quarterly_financial_maintenance_%RUN_STAMP%.log"

echo [INFO] start quarterly financial maintenance at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"

"%PYTHON_CMD%" manage.py monthly_financial_maintenance --scope 60,00,30,68 --latest-only >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"

if not "%ERR%"=="0" (
    echo [ERROR] quarterly financial maintenance failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
    echo quarterly financial maintenance failed. see %LOG_FILE%
    exit /b %ERR%
)

echo [INFO] quarterly financial maintenance completed at %DATE% %TIME% >> "%LOG_FILE%"
echo quarterly financial maintenance completed. log=%LOG_FILE%
exit /b 0