@echo off
setlocal enableextensions enabledelayedexpansion

set "VENV_PYTHON=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"
set "VALUATION_TABLE_PREFIX=valuation"

if not exist "output" mkdir "output"
if not exist "output\logs" mkdir "output\logs"

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"

set "MASTER_LOG=output\logs\valuation_full_refresh_weekly_%RUN_STAMP%.log"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"

set "COMMON_ARGS=--methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --profit-buckets both --request-interval 0.2 --refresh-policy all --business-match-topn 3 --enable-market-style --market-style-profile adaptive --price-anchor-mode market_now"
set "FAILURES=0"

call :log INFO "start valuation full refresh weekly python=%PYTHON_CMD%"

call :run_scope 60
call :run_scope 68
call :run_scope 00
call :run_scope 30
call :run_scope 8

if not "%FAILURES%"=="0" (
    call :log ERROR "valuation full refresh weekly completed with failures=%FAILURES%"
    exit /b 1
)

call :log INFO "valuation full refresh weekly completed successfully"
exit /b 0

:run_scope
set "SCOPE=%~1"
set "SCOPE_LOG=output\logs\valuation_full_refresh_weekly_%RUN_STAMP%_scope_%SCOPE%.log"
call :log INFO "scope=%SCOPE% started scope_log=%SCOPE_LOG%"
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope %SCOPE% %COMMON_ARGS% > "%SCOPE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
    set /a FAILURES+=1
    call :log ERROR "scope=%SCOPE% failed exit_code=!RC! scope_log=%SCOPE_LOG%"
    goto :eof
)
call :log INFO "scope=%SCOPE% completed scope_log=%SCOPE_LOG%"
goto :eof

:log
set "LEVEL=%~1"
set "MESSAGE=%~2"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm:ss\""') do set "NOW=%%i"
echo [!NOW!] [!LEVEL!] !MESSAGE!
>> "%MASTER_LOG%" echo [!NOW!] [!LEVEL!] !MESSAGE!
goto :eof
