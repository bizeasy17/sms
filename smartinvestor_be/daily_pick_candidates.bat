@echo off
setlocal enableextensions enabledelayedexpansion

REM Auto-generate candidate file names by date + strategy version
set "STRATEGY_VERSION=baseline_v20260319"
set "SCOPE=688"
set "RISK_PROFILE=medium"
set "VALUATION_BAND_PCT=0.1"
set "RISK_LOOKBACK_DAYS=20"
set "TOP_N=50"
set "VENV_PYTHON=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"
set "VALUATION_TABLE_PREFIX=valuation"

if not exist "output" mkdir "output"
if not exist "output\logs" mkdir "output\logs"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "RUN_DATE=%%i"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"

set "OUTPUT_CSV=output\pick_%SCOPE%_%RUN_DATE%_%STRATEGY_VERSION%.csv"
set "LOG_FILE=output\logs\pick_%SCOPE%_%RUN_DATE%_%STRATEGY_VERSION%.log"

echo [INFO] start pickbuycandidates, run_date=%RUN_DATE%, strategy=%STRATEGY_VERSION%

"%PYTHON_CMD%" manage.py pickbuycandidates ^
  --scope %SCOPE% ^
  --valuation-band-pct %VALUATION_BAND_PCT% ^
  --risk-profile %RISK_PROFILE% ^
  --risk-lookback-days %RISK_LOOKBACK_DAYS% ^
  --top %TOP_N% ^
  --output-csv "%OUTPUT_CSV%" > "%LOG_FILE%" 2>&1

if errorlevel 1 (
  echo [ERROR] pickbuycandidates failed, check log: %LOG_FILE%
  exit /b 1
)

echo [INFO] done. log: %LOG_FILE%
if exist "%OUTPUT_CSV%" (
  echo [INFO] csv : %OUTPUT_CSV%
) else (
  echo [WARN] no csv generated: candidate count may be 0, check log
)

endlocal
