@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
if not defined ETL_MAX_BACKFILL_DAYS set "ETL_MAX_BACKFILL_DAYS=0"

set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "LOG_FILE=%LOG_DIR%\backfill_missing_history_%RUN_STAMP%.log"

echo [INFO] backfill pipeline start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] uat_root=%UAT_ROOT% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] etl_max_backfill_days=%ETL_MAX_BACKFILL_DAYS% >> "%LOG_FILE%"

call :run_step "ETL backfill trading download" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=TRADING --max_backfill_days=%ETL_MAX_BACKFILL_DAYS%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL backfill fundamental download" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=FUNDAMENTAL --max_backfill_days=%ETL_MAX_BACKFILL_DAYS%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL backfill CYQ download" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=CYQ --max_backfill_days=%ETL_MAX_BACKFILL_DAYS%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE backfill pull from ETL" "%UAT_ROOT%\smartinvestor_be" "call %UAT_ROOT%\smartinvestor_be\daily_pull_data.bat"
if errorlevel 1 exit /b %ERRORLEVEL%

echo [INFO] backfill pipeline completed at %DATE% %TIME% >> "%LOG_FILE%"
echo backfill pipeline completed. log=%LOG_FILE%
exit /b 0

:run_step
set "STEP_NAME=%~1"
set "STEP_DIR=%~2"
set "STEP_CMD=%~3"
echo [STEP] %STEP_NAME%
echo [STEP] %STEP_NAME% >> "%LOG_FILE%"
if not exist "%STEP_DIR%" (
  echo [ERROR] %STEP_NAME% missing dir: %STEP_DIR% >> "%LOG_FILE%"
  echo backfill pipeline failed at step: %STEP_NAME%. missing dir %STEP_DIR%. see %LOG_FILE%
  exit /b 1
)
pushd "%STEP_DIR%"
call %STEP_CMD% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" (
  echo [ERROR] %STEP_NAME% failed code=!ERR! at %DATE% %TIME% >> "%LOG_FILE%"
  echo backfill pipeline failed at step: %STEP_NAME%. see %LOG_FILE%
  exit /b !ERR!
)
goto :eof
