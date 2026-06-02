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
if not exist "output\weekly_undervalued" mkdir "output\weekly_undervalued"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "RUN_DATE=%%i"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"

set "MASTER_LOG=output\logs\weekly_undervalued_%RUN_STAMP%.log"
set "STYLE_LIST=balanced conservative aggressive"

call :log INFO "start weekly undervalued export run_date=%RUN_DATE% python=%PYTHON_CMD% config=output/weekly_undervalued/job_strategy_config.json"

for %%S in (%STYLE_LIST%) do (
  set "STYLE=%%S"
  set "TRADITIONAL_CSV=output\weekly_undervalued\traditional_undervalued_!STYLE!_%RUN_DATE%.csv"
  set "PREDICTIVE_CSV=output\weekly_undervalued\predictive_undervalued_!STYLE!_%RUN_DATE%.csv"
  call :log INFO "start weekly undervalued export style=!STYLE! run_date=%RUN_DATE% python=%PYTHON_CMD% config=output/weekly_undervalued/job_strategy_config.json"
  "%PYTHON_CMD%" manage.py exportweeklyundervalued ^
    --strategy-style !STYLE! ^
    --traditional-output "!TRADITIONAL_CSV!" ^
    --predictive-output "!PREDICTIVE_CSV!" >> "%MASTER_LOG%" 2>&1
  if errorlevel 1 (
    call :log ERROR "exportweeklyundervalued failed style=!STYLE! log=%MASTER_LOG%"
    exit /b 1
  )
  call :log INFO "weekly undervalued export completed style=!STYLE! traditional_csv=!TRADITIONAL_CSV! predictive_csv=!PREDICTIVE_CSV! log=%MASTER_LOG%"
)

endlocal
goto :eof

:log
set "LEVEL=%~1"
set "MESSAGE=%~2"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm:ss\""') do set "NOW=%%i"
echo [!NOW!] [!LEVEL!] !MESSAGE!
>> "%MASTER_LOG%" echo [!NOW!] [!LEVEL!] !MESSAGE!
goto :eof
