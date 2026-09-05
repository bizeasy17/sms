@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
set "PYTHONIOENCODING=utf-8"

for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddYears(-5).ToString('yyyyMMdd')"') do set "ETL_START_DATE=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddYears(-3).ToString('yyyy-MM-dd')"') do set "BE_DAILY_START_DATE=%%i"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"

set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\rebuild_market_history_etl_to_be_%RUN_STAMP%.log"

if /I "%~1"=="--dry-run" goto :dry_run

echo [INFO] market history rebuild start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] etl daily range=%ETL_START_DATE% through today >> "%LOG_FILE%"
echo [INFO] backend daily start=%BE_DAILY_START_DATE% through ETL latest >> "%LOG_FILE%"

call :run_step "ETL company setup" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py setup"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL 5-year daily trading" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=TRADING --start_date=%ETL_START_DATE%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL 5-year daily fundamental" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=FUNDAMENTAL --start_date=%ETL_START_DATE%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL 5-year daily CYQ" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=CYQ --start_date=%ETL_START_DATE%"
if errorlevel 1 exit /b %ERRORLEVEL%

call :run_step "ETL weekly trading resample" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py resample --freq=W-FRI --dtype=TRADING"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL weekly fundamental resample" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py resample --freq=W-FRI --dtype=FUNDA"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL weekly cost resample" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py resample --freq=W-FRI --dtype=COST"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL monthly trading resample" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py resample --freq=ME --dtype=TRADING"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL monthly fundamental resample" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py resample --freq=ME --dtype=FUNDA"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL monthly cost resample" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py resample --freq=ME --dtype=COST"
if errorlevel 1 exit /b %ERRORLEVEL%

call :run_step "BE company setup" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py setup"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE 3-year per-stock daily trading" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py pulldata --freq=D --dtype=trading --date-from=%BE_DAILY_START_DATE%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE 3-year per-stock daily fundamental" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py pulldata --freq=D --dtype=fundamental --date-from=%BE_DAILY_START_DATE%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE 3-year per-stock daily cost" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py pulldata --freq=D --dtype=cost --date-from=%BE_DAILY_START_DATE%"
if errorlevel 1 exit /b %ERRORLEVEL%

for %%F in (W M) do (
  for %%D in (trading fundamental cost) do (
    call :run_step "BE %%F full-history %%D" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py pulldata --freq=%%F --dtype=%%D --batch=True"
    if errorlevel 1 exit /b !ERRORLEVEL!
  )
)

echo [INFO] market history rebuild completed at %DATE% %TIME% >> "%LOG_FILE%"
echo market history rebuild completed. log=%LOG_FILE%
exit /b 0

:dry_run
echo [DRY-RUN] ETL daily start=%ETL_START_DATE%
echo [DRY-RUN] Backend daily start=%BE_DAILY_START_DATE%
echo [DRY-RUN] Would run ETL D Trading, Fundamental, CYQ; resample W/M Trading, Fundamental, Cost; then run Backend D per-stock and W/M full-history pulls.
exit /b 0

:run_step
set "STEP_NAME=%~1"
set "STEP_DIR=%~2"
set "STEP_CMD=%~3"
echo [STEP] %STEP_NAME%
echo [STEP] %STEP_NAME% >> "%LOG_FILE%"
if not exist "%STEP_DIR%" (
  echo [ERROR] %STEP_NAME% missing dir: %STEP_DIR% >> "%LOG_FILE%"
  exit /b 1
)
pushd "%STEP_DIR%"
call %STEP_CMD% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" (
  echo [ERROR] %STEP_NAME% failed code=!ERR! at %DATE% %TIME% >> "%LOG_FILE%"
  echo market history rebuild failed at step: %STEP_NAME%. see %LOG_FILE%
  exit /b !ERR!
)
goto :eof