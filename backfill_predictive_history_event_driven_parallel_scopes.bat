@echo off
setlocal EnableExtensions

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

set "START_DATE=%~1"
if "%START_DATE%"=="" set "START_DATE=2024-01-01"
set "END_DATE=%~2"
if "%END_DATE%"=="" set "END_DATE=2025-12-31"
set "REPORT_TYPES=%~3"
if "%REPORT_TYPES%"=="" set "REPORT_TYPES=LATEST"
set "STORE_MODE=%~4"
if "%STORE_MODE%"=="" set "STORE_MODE=history"
set "ENABLE_REGIME_SWITCH=%~5"
if "%ENABLE_REGIME_SWITCH%"=="" set "ENABLE_REGIME_SWITCH=1"

echo [INFO] launch predictive event-driven backfill in parallel scopes: 60,00,30,68
echo [INFO] start_date=%START_DATE% end_date=%END_DATE% report_types=%REPORT_TYPES% store_mode=%STORE_MODE% enable_regime_switch=%ENABLE_REGIME_SWITCH%

for %%S in (60 00 30 68) do (
  echo [INFO] start scope=%%S
  start "pred_backfill_%%S" cmd /c "cd /d %BASE_DIR% && set BACKFILL_RUN_TAG=scope_%%S && set PYTHON_CMD=%PYTHON_CMD% && call backfill_predictive_history_event_driven.bat %START_DATE% %END_DATE% %%S %REPORT_TYPES% %STORE_MODE% %ENABLE_REGIME_SWITCH%"
)

echo [INFO] all scope jobs launched.
echo [INFO] logs are separated by run tag under logs\, e.g. backfill_predictive_history_event_driven_scope_60.log
exit /b 0
