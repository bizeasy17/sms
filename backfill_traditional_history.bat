@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

set "START_DATE=%~1"
if "%START_DATE%"=="" set "START_DATE=2024-01-01"
set "END_DATE=%~2"
if "%END_DATE%"=="" set "END_DATE=2025-12-31"
set "SCOPE=%~3"
if "%SCOPE%"=="" set "SCOPE=ALL"
set "METHODS=%~4"
if "%METHODS%"=="" set "METHODS=sw_history,pe,pb,ps,peg,fcff_dcf,ddm"

if not exist logs mkdir logs
set "LOG_FILE=logs\backfill_traditional_history.log"
set "CHECKPOINT_FILE=logs\backfill_traditional_history.checkpoint"
set "RESUME_FROM="
if exist "%CHECKPOINT_FILE%" (
  set /p RESUME_FROM=<"%CHECKPOINT_FILE%"
)

echo [INFO] traditional history backfill start %DATE% %TIME%>>"%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR%>>"%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD%>>"%LOG_FILE%"
echo [INFO] start_date=%START_DATE% end_date=%END_DATE% scope=%SCOPE% methods=%METHODS% resume_from=%RESUME_FROM%>>"%LOG_FILE%"

for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "$start=[datetime]::ParseExact('%START_DATE%','yyyy-MM-dd',$null); $end=[datetime]::ParseExact('%END_DATE%','yyyy-MM-dd',$null); for($d=$start;$d -le $end;$d=$d.AddDays(1)){ $d.ToString('yyyy-MM-dd') }"`) do (
  call :process_date %%D
  if errorlevel 1 goto :FAILED
)

echo [INFO] traditional history backfill completed %DATE% %TIME%>>"%LOG_FILE%"
echo traditional history backfill completed. log=%LOG_FILE%
exit /b 0

:process_date
set "CUR_DATE=%~1"
if defined RESUME_FROM (
  if "%CUR_DATE%" LEQ "%RESUME_FROM%" (
    echo [SKIP] %CUR_DATE% already completed>>"%LOG_FILE%"
    exit /b 0
  )
)

echo [STEP] trade_date=%CUR_DATE%>>"%LOG_FILE%"
"%PYTHON_CMD%" "smartinvestor_be\manage.py" prefillvaluationsnapshot --trade-date %CUR_DATE% --scope %SCOPE% --freq D --refresh-policy all --price-anchor-mode market_now --profit-buckets both --backfill-history-only --methods %METHODS% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] trade_date=%CUR_DATE% failed code=%ERR%>>"%LOG_FILE%"
  exit /b %ERR%
)
> "%CHECKPOINT_FILE%" echo %CUR_DATE%
echo [OK] trade_date=%CUR_DATE%>>"%LOG_FILE%"
exit /b 0

:FAILED
set "ERR=%ERRORLEVEL%"
echo [ERROR] traditional history backfill failed code=%ERR%>>"%LOG_FILE%"
echo traditional history backfill failed. see %LOG_FILE%
exit /b %ERR%
