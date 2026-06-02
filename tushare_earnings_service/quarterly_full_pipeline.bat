@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=C:\Users\HANJ29\Development\web\UAT"
set "ETL_DIR=%UAT_ROOT%\smartinvestor_etl"
set "EARNINGS_DIR=%UAT_ROOT%\tushare_earnings_service"

set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\quarterly_full_pipeline_%RUN_STAMP%.log"

echo [INFO] quarterly full pipeline start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] etl_dir=%ETL_DIR% >> "%LOG_FILE%"
echo [INFO] earnings_dir=%EARNINGS_DIR% >> "%LOG_FILE%"
echo [INFO] quarterly full pipeline start at %DATE% %TIME%
echo [INFO] log=%LOG_FILE%

if not exist "%ETL_DIR%\manage.py" (
  echo [ERROR] ETL manage.py not found: %ETL_DIR%\manage.py >> "%LOG_FILE%"
  echo [ERROR] ETL manage.py not found: %ETL_DIR%\manage.py
  exit /b 1
)
if not exist "%EARNINGS_DIR%\manage.py" (
  echo [ERROR] Earnings manage.py not found: %EARNINGS_DIR%\manage.py >> "%LOG_FILE%"
  echo [ERROR] Earnings manage.py not found: %EARNINGS_DIR%\manage.py
  exit /b 1
)

echo [STEP] resample trading (ME)
echo [STEP] resample trading (ME) >> "%LOG_FILE%"
pushd "%ETL_DIR%"
"%PYTHON_CMD%" manage.py resample --freq=ME --dtype=TRADING --force true >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

echo [STEP] resample funda (ME)
echo [STEP] resample funda (ME) >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py resample --freq=ME --dtype=FUNDA --force true >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

echo [STEP] fetchcorp
echo [STEP] fetchcorp >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py fetchcorp >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED
popd

pushd "%EARNINGS_DIR%"
echo [INFO] sync_market_local removed from quarterly pipeline; handled by daily job >> "%LOG_FILE%"

echo [STEP] monthly_financial_maintenance
echo [STEP] monthly_financial_maintenance >> "%LOG_FILE%"
"%PYTHON_CMD%" manage.py monthly_financial_maintenance --scope 60,00,30,68 --latest-only >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :FAILED

echo [INFO] refresh_signal_snapshot removed from quarterly pipeline; handled by daily periodic window job >> "%LOG_FILE%"

popd

echo [INFO] quarterly full pipeline completed at %DATE% %TIME% >> "%LOG_FILE%"
echo quarterly full pipeline completed. log=%LOG_FILE%
exit /b 0

:FAILED
set "ERR=%ERRORLEVEL%"
popd
echo [ERROR] quarterly full pipeline failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
echo quarterly full pipeline failed. see %LOG_FILE%
exit /b %ERR%