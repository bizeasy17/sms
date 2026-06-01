@echo off
setlocal EnableDelayedExpansion

REM Usage:
REM   full_signal_snapshot_refresh.bat [scope] [sleep_ms] [strict] [offset] [limit]
REM Example:
REM   full_signal_snapshot_refresh.bat ALL 50 0
REM   full_signal_snapshot_refresh.bat 60,00,30,68 100 1
REM   full_signal_snapshot_refresh.bat ALL 0 0 1000 500

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD=%BASE_DIR%..\.venv\Scripts\python.exe"
if exist "%PYTHON_CMD%" (
    "%PYTHON_CMD%" -c "import django" >nul 2>&1
    if errorlevel 1 set "PYTHON_CMD="
)
if not defined PYTHON_CMD if exist "C:\Users\HANJ29\Development\vdev1\Scripts\python.exe" set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not defined PYTHON_CMD set "PYTHON_CMD=python"

set "SCOPE=%~1"
if "%SCOPE%"=="" set "SCOPE=ALL"

set "SLEEP_MS=%~2"
if "%SLEEP_MS%"=="" set "SLEEP_MS=50"

set "STRICT=%~3"
if "%STRICT%"=="" set "STRICT=0"
set "STRICT_ARG="
if "%STRICT%"=="1" set "STRICT_ARG=--strict"

set "OFFSET=%~4"
set "LIMIT=%~5"
set "OFFSET_ARG="
set "LIMIT_ARG="
if not "%OFFSET%"=="" set "OFFSET_ARG=--offset %OFFSET%"
if not "%LIMIT%"=="" set "LIMIT_ARG=--limit %LIMIT%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "BATCH_KEY=full_%RUN_STAMP%"

if not exist logs mkdir logs
set "LOG_FILE=logs\full_signal_snapshot_refresh_%RUN_STAMP%.log"

echo [INFO] start full signal snapshot refresh at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] scope=%SCOPE% sleep_ms=%SLEEP_MS% strict=%STRICT% offset=%OFFSET% limit=%LIMIT% batch_key=%BATCH_KEY% >> "%LOG_FILE%"

set "CMD=%PYTHON_CMD% manage.py refresh_signal_snapshot --scope %SCOPE% --sleep-ms %SLEEP_MS% --batch-key %BATCH_KEY% %OFFSET_ARG% %LIMIT_ARG% %STRICT_ARG%"

echo [INFO] command=%CMD% >> "%LOG_FILE%"
echo [INFO] command=%CMD%
powershell -NoProfile -ExecutionPolicy Bypass -Command "$cmd='\"%PYTHON_CMD%\" manage.py refresh_signal_snapshot --scope \"%SCOPE%\" --sleep-ms %SLEEP_MS% --batch-key \"%BATCH_KEY%\" %OFFSET_ARG% %LIMIT_ARG% %STRICT_ARG%'; cmd /c \"$cmd 2>&1\" | Tee-Object -FilePath '%LOG_FILE%' -Append; exit $LASTEXITCODE"   
set "ERR=%ERRORLEVEL%"

if not "%ERR%"=="0" (
    echo [ERROR] full signal snapshot refresh failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
    echo full signal snapshot refresh failed. see %LOG_FILE%
    exit /b %ERR%
)

echo [INFO] full signal snapshot refresh completed at %DATE% %TIME% >> "%LOG_FILE%"
echo full signal snapshot refresh completed. log=%LOG_FILE%
exit /b 0
