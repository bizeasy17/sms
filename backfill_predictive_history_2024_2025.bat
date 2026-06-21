@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

if not defined PYTHON_CMD set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

set "START_DATE=%~1"
if "%START_DATE%"=="" set "START_DATE=2024-01-01"
set "END_DATE=%~2"
if "%END_DATE%"=="" set "END_DATE=2025-12-31"
set "SCOPE=%~3"
if "%SCOPE%"=="" set "SCOPE=ALL"
set "REPORT_TYPES=%~4"
if "%REPORT_TYPES%"=="" set "REPORT_TYPES=LATEST,FUSION"
set "STORE_MODE=%~5"
if "%STORE_MODE%"=="" set "STORE_MODE=both"

if not exist logs mkdir logs
set "LOG_FILE=logs\backfill_predictive_history_2024_2025.log"
set "CHECKPOINT_FILE=logs\backfill_predictive_history_2024_2025.checkpoint"
set "RESUME_FROM="
if exist "%CHECKPOINT_FILE%" (
  set /p RESUME_FROM=<"%CHECKPOINT_FILE%"
)

echo [INFO] predictive history backfill start %DATE% %TIME%>>"%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR%>>"%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD%>>"%LOG_FILE%"
echo [INFO] start_date=%START_DATE% end_date=%END_DATE% scope=%SCOPE% report_types=%REPORT_TYPES% store_mode=%STORE_MODE% resume_from=%RESUME_FROM%>>"%LOG_FILE%"

for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "$start=[datetime]::ParseExact('%START_DATE%','yyyy-MM-dd',$null); $end=[datetime]::ParseExact('%END_DATE%','yyyy-MM-dd',$null); for($d=$start;$d -le $end;$d=$d.AddDays(1)){ $d.ToString('yyyy-MM-dd') }"`) do (
  call :process_date %%D
  if errorlevel 1 goto :FAILED
)

echo [INFO] predictive history backfill completed %DATE% %TIME%>>"%LOG_FILE%"
echo predictive history backfill completed. log=%LOG_FILE%
exit /b 0

:process_date
set "CUR_DATE=%~1"
if defined RESUME_FROM (
  if "%CUR_DATE%" LEQ "%RESUME_FROM%" (
    echo [SKIP] %CUR_DATE% already completed>>"%LOG_FILE%"
    exit /b 0
  )
)

echo [STEP] asof_date=%CUR_DATE%>>"%LOG_FILE%"
"%PYTHON_CMD%" "tushare_earnings_service\manage.py" refresh_signal_snapshot --full-refresh --scope %SCOPE% --asof-date %CUR_DATE% --store-mode %STORE_MODE% --report-types %REPORT_TYPES% --serving-slot production --anchor-mode ann --batch-key backfill_pred_%CUR_DATE% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] asof_date=%CUR_DATE% failed code=%ERR%>>"%LOG_FILE%"
  exit /b %ERR%
)
> "%CHECKPOINT_FILE%" echo %CUR_DATE%
echo [OK] asof_date=%CUR_DATE%>>"%LOG_FILE%"
exit /b 0

:FAILED
set "ERR=%ERRORLEVEL%"
echo [ERROR] predictive history backfill failed code=%ERR%>>"%LOG_FILE%"
echo predictive history backfill failed. see %LOG_FILE%
exit /b %ERR%
