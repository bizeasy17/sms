@echo off
setlocal enableextensions enabledelayedexpansion

set "VENV_PYTHON=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"
set "VALUATION_TABLE_PREFIX=valuation"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "output" mkdir "output"
if not exist "output\logs" mkdir "output\logs"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "RUN_DATE=%%i"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"

set "LOG_FILE=output\logs\valuation_due_runner_%RUN_DATE%.log"

echo [INFO] start valuation due runner, run_date=%RUN_DATE%
"%PYTHON_CMD%" manage.py updatevaluationconfigs --market CN --run-due > "%LOG_FILE%" 2>&1

if errorlevel 1 (
  echo [ERROR] valuation due runner failed, check log: %LOG_FILE%
  exit /b 1
)

echo [INFO] traditional valuation refresh runs disclosure-driven daily; monthly full fallback handled by UAT daily.bat

echo [INFO] done. log: %LOG_FILE%
endlocal
