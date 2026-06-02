@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "LOG_FILE=%LOG_DIR%\weekly_%RUN_STAMP%.log"

echo [INFO] weekly pipeline start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] uat_root=%UAT_ROOT% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"

call :run_step "ETL weekly trading resample" :step_etl_weekly_trading
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL weekly funda resample" :step_etl_weekly_funda
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE weekly trading pull" :step_be_weekly_trading
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE weekly fundamental pull" :step_be_weekly_fundamental
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE weekly valuation due runner" :step_be_weekly_valuation_due_runner
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE weekly undervalued export" :step_be_weekly_undervalued_export
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE weekly fund holdings sync" :step_be_weekly_fund_holdings
if errorlevel 1 exit /b %ERRORLEVEL%

echo [INFO] weekly pipeline completed at %DATE% %TIME% >> "%LOG_FILE%"
echo weekly pipeline completed. log=%LOG_FILE%
exit /b 0

:run_step
set "STEP_NAME=%~1"
set "STEP_LABEL=%~2"
echo [STEP] %STEP_NAME%
echo [STEP] %STEP_NAME% >> "%LOG_FILE%"
call %STEP_LABEL% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] %STEP_NAME% failed code=!ERR! at %DATE% %TIME% >> "%LOG_FILE%"
  echo weekly pipeline failed at step: %STEP_NAME%. see %LOG_FILE%
  exit /b !ERR!
)
goto :eof

:step_etl_weekly_trading
cd /d "%UAT_ROOT%\smartinvestor_etl"
"%PYTHON_CMD%" manage.py resample --freq=W-FRI --dtype=TRADING
exit /b %ERRORLEVEL%

:step_etl_weekly_funda
cd /d "%UAT_ROOT%\smartinvestor_etl"
"%PYTHON_CMD%" manage.py resample --freq=W-FRI --dtype=FUNDA
exit /b %ERRORLEVEL%

:step_be_weekly_trading
cd /d "%UAT_ROOT%\smartinvestor_be"
"%PYTHON_CMD%" manage.py pulldata --freq=W --batch=True --dtype=trading
exit /b %ERRORLEVEL%

:step_be_weekly_fundamental
cd /d "%UAT_ROOT%\smartinvestor_be"
"%PYTHON_CMD%" manage.py pulldata --freq=W --batch=True --dtype=fundamental
exit /b %ERRORLEVEL%

:step_be_weekly_fund_holdings
cd /d "%UAT_ROOT%\smartinvestor_be"
"%PYTHON_CMD%" manage.py syncfundholdings --refresh-basic --market O --recent-days 550 --incremental-from-local
exit /b %ERRORLEVEL%

:step_be_weekly_valuation_due_runner
cd /d "%UAT_ROOT%\smartinvestor_be"
call "%UAT_ROOT%\smartinvestor_be\daily_valuation_due_runner.bat"
exit /b %ERRORLEVEL%

:step_be_weekly_undervalued_export
cd /d "%UAT_ROOT%\smartinvestor_be"
call "%UAT_ROOT%\smartinvestor_be\weekly_undervalued_friday.bat"
exit /b %ERRORLEVEL%
