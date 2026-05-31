@echo off
setlocal enableextensions enabledelayedexpansion

set "SCOPE=688"
set "BASE_PROFIT_GROWTH=12"
set "BULL_PROFIT_GROWTH=20"
set "BEAR_PROFIT_GROWTH=4"
set "BULL_MULTIPLE_PREMIUM=10"
set "BEAR_MULTIPLE_DISCOUNT=10"
set "TOP_N=50"
set "VENV_PYTHON=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"
set "VALUATION_TABLE_PREFIX=valuation"

if not exist "output" mkdir "output"
if not exist "output\logs" mkdir "output\logs"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "RUN_DATE=%%i"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"

set "OUTPUT_CSV=output\annual_outlook_%SCOPE%_%RUN_DATE%.csv"
set "LOG_FILE=output\logs\annual_outlook_%SCOPE%_%RUN_DATE%.log"

echo [INFO] start annual outlook, run_date=%RUN_DATE%, scope=%SCOPE%
"%PYTHON_CMD%" manage.py annualoutlook ^
  --scope %SCOPE% ^
  --base-profit-growth-pct %BASE_PROFIT_GROWTH% ^
  --bull-profit-growth-pct %BULL_PROFIT_GROWTH% ^
  --bear-profit-growth-pct %BEAR_PROFIT_GROWTH% ^
  --bull-multiple-premium-pct %BULL_MULTIPLE_PREMIUM% ^
  --bear-multiple-discount-pct %BEAR_MULTIPLE_DISCOUNT% ^
  --top %TOP_N% ^
  --output-csv "%OUTPUT_CSV%" > "%LOG_FILE%" 2>&1

if errorlevel 1 (
  echo [ERROR] annualoutlook failed, check log: %LOG_FILE%
  exit /b 1
)

echo [INFO] done. log: %LOG_FILE%
if exist "%OUTPUT_CSV%" (
  echo [INFO] csv : %OUTPUT_CSV%
) else (
  echo [WARN] no csv generated: check log
)

endlocal
