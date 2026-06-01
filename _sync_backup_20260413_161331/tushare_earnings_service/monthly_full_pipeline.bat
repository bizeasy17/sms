@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=C:\Users\HANJ29\Development\web\UAT"
set "ETL_DIR=%UAT_ROOT%\smartinvestor_etl"
set "EARNINGS_DIR=%UAT_ROOT%\tushare_earnings_service"

set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddMonths(-1).ToString('yyyy-MM-01')"') do set "SYNC_START_MONTHLY=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddYears(-3).ToString('yyyy-MM-dd')"') do set "SYNC_START_FIRST=%%i"
set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\monthly_full_pipeline_%RUN_STAMP%.log"
set "INIT_MARKER=%UAT_ROOT%\tushare_earnings_service\outputs\.market_sync_initialized"

set "SYNC_START=%SYNC_START_MONTHLY%"
if not exist "%INIT_MARKER%" (
  set "SYNC_START=%SYNC_START_FIRST%"
)

echo [INFO] monthly full pipeline start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] etl_dir=%ETL_DIR% >> "%LOG_FILE%"
echo [INFO] earnings_dir=%EARNINGS_DIR% >> "%LOG_FILE%"
echo [INFO] sync_start=%SYNC_START% monthly_start=%SYNC_START_MONTHLY% first_start=%SYNC_START_FIRST% retention_years=3 >> "%LOG_FILE%"
if exist "%INIT_MARKER%" (
  echo [INFO] init_marker=%INIT_MARKER% exists=true >> "%LOG_FILE%"
) else (
  echo [INFO] init_marker=%INIT_MARKER% exists=false >> "%LOG_FILE%"
)

if not exist "%ETL_DIR%\manage.py" (
  echo [ERROR] ETL manage.py not found: %ETL_DIR%\manage.py >> "%LOG_FILE%"
  exit /b 1
)
if not exist "%EARNINGS_DIR%\manage.py" (
  echo [ERROR] Earnings manage.py not found: %EARNINGS_DIR%\manage.py >> "%LOG_FILE%"
  exit /b 1
)

echo [STEP] resample trading (ME) >> "%LOG_FILE%"
pushd "%ETL_DIR%"
"%PYTHON_CMD%" manage.py resample --freq=ME --dtype=TRADING --force true >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

echo [STEP] resample funda (ME) >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py resample --freq=ME --dtype=FUNDA --force true >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

echo [STEP] fetchcorp >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py fetchcorp >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED
popd

pushd "%EARNINGS_DIR%"
echo [STEP] sync_market_local >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py sync_market_local --start-date %SYNC_START% --retention-years 3 >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

echo [STEP] monthly_financial_maintenance >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py monthly_financial_maintenance --scope 60,00,30,68 --latest-only >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

echo [STEP] refresh_signal_snapshot >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py refresh_signal_snapshot --scope 60,00,30,68 --store-mode both --serving-slot production --batch-key monthly_%RUN_STAMP% >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

if not exist "%INIT_MARKER%" (
  echo initialized > "%INIT_MARKER%"
)
popd

echo [INFO] monthly full pipeline completed at %DATE% %TIME% >> "%LOG_FILE%"
echo monthly full pipeline completed. log=%LOG_FILE%
exit /b 0

:FAILED
set "ERR=%ERRORLEVEL%"
popd
echo [ERROR] monthly full pipeline failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
echo monthly full pipeline failed. see %LOG_FILE%
exit /b %ERR%
