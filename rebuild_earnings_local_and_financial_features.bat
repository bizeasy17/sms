@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"
set "EARNINGS_DIR=%UAT_ROOT%\tushare_earnings_service"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
set "PYTHONIOENCODING=utf-8"
set "DRY_RUN=0"
set "FINANCIAL_ONLY=0"
if /I "%~1"=="--financial-only" (
  set "FINANCIAL_ONLY=1"
  shift
)
if /I "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
)

set "MARKET_START_DATE=%~1"
if "%MARKET_START_DATE%"=="" (
  for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddYears(-5).ToString('yyyy-MM-dd')"') do set "MARKET_START_DATE=%%i"
)
set "MARKET_END_DATE=%~2"
if "%MARKET_END_DATE%"=="" (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "MARKET_END_DATE=%%i"
)
for /f %%i in ('powershell -NoProfile -Command "([datetime]::Parse('%MARKET_START_DATE%')).ToString('yyyyMMdd')"') do set "FINANCIAL_START_DATE=%%i"
for /f %%i in ('powershell -NoProfile -Command "([datetime]::Parse('%MARKET_END_DATE%')).ToString('yyyyMMdd')"') do set "FINANCIAL_END_DATE=%%i"
set "SCOPE=%~3"
set /a SCOPE_ARG_INDEX=4
:collect_scope_tokens
call set "SCOPE_TOKEN=%%%SCOPE_ARG_INDEX%%"
if "%SCOPE_TOKEN%"=="" goto scope_tokens_done
if /I "%SCOPE_TOKEN%"=="--dry-run" goto scope_tokens_done
echo %SCOPE_TOKEN%| findstr /R "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 goto scope_tokens_done
if "%SCOPE%"=="" (
  set "SCOPE=%SCOPE_TOKEN%"
) else (
  set "SCOPE=%SCOPE%,%SCOPE_TOKEN%"
)
set /a SCOPE_ARG_INDEX+=1
goto collect_scope_tokens

:scope_tokens_done
if "%SCOPE%"=="" set "SCOPE=60,00,30,68"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\rebuild_earnings_local_and_financial_features_%RUN_STAMP%.log"

if "%DRY_RUN%"=="1" goto :dry_run
if /I "%~4"=="--dry-run" goto :dry_run

if not exist "%EARNINGS_DIR%\manage.py" (
  echo [ERROR] Earnings manage.py not found: %EARNINGS_DIR%\manage.py
  exit /b 1
)

echo [INFO] earnings local mirror and financial feature rebuild start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] market date range=%MARKET_START_DATE% through %MARKET_END_DATE% >> "%LOG_FILE%"
echo [INFO] financial date range=%FINANCIAL_START_DATE% through %FINANCIAL_END_DATE% scope=%SCOPE% >> "%LOG_FILE%"

if "%FINANCIAL_ONLY%"=="0" (
  call :run_step "Earnings local daily market mirror" "%PYTHON_CMD% manage.py sync_market_local --mode range --start-date=%MARKET_START_DATE% --end-date=%MARKET_END_DATE% --freq D"
  if errorlevel 1 exit /b !ERRORLEVEL!
  call :run_step "Earnings local index dailybasic mirror" "%PYTHON_CMD% manage.py sync_index_dailybasic_local --start-date=%MARKET_START_DATE% --end-date=%MARKET_END_DATE%"
  if errorlevel 1 exit /b !ERRORLEVEL!
) else (
  echo [INFO] skip local market mirrors: financial-only mode >> "%LOG_FILE%"
)
call :run_step "Earnings financial endpoint history" "%PYTHON_CMD% manage.py sync_financials_direct --scope %SCOPE% --apis income,balancesheet_vip,cashflow_vip,forecast_vip,express_vip,dividend,fina_indicator_vip,fina_audit,fina_mainbz_vip --start-date=%FINANCIAL_START_DATE% --end-date=%FINANCIAL_END_DATE%"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "Earnings financial feature panel rebuild" "%PYTHON_CMD% manage.py build_financial_feature_panel"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "Earnings financial feature snapshot rebuild" "%PYTHON_CMD% manage.py build_financial_feature_snapshot"
if errorlevel 1 exit /b %ERRORLEVEL%

echo [INFO] earnings local mirror and financial feature rebuild completed at %DATE% %TIME% >> "%LOG_FILE%"
echo earnings local mirror and financial feature rebuild completed. log=%LOG_FILE%
exit /b 0

:dry_run
echo [DRY-RUN] market date range=%MARKET_START_DATE% through %MARKET_END_DATE%
echo [DRY-RUN] financial date range=%FINANCIAL_START_DATE% through %FINANCIAL_END_DATE% scope=%SCOPE%
if "%FINANCIAL_ONLY%"=="1" (
  echo [DRY-RUN] Would skip local market mirrors and run sync_financials_direct, build_financial_feature_panel, and build_financial_feature_snapshot.
) else (
  echo [DRY-RUN] Would run sync_market_local range D, sync_index_dailybasic_local, sync_financials_direct, build_financial_feature_panel, and build_financial_feature_snapshot.
)
exit /b 0

:run_step
set "STEP_NAME=%~1"
set "STEP_CMD=%~2"
echo [STEP] %STEP_NAME%
echo [STEP] %STEP_NAME% >> "%LOG_FILE%"
pushd "%EARNINGS_DIR%"
call %STEP_CMD% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" (
  echo [ERROR] %STEP_NAME% failed code=!ERR! at %DATE% %TIME% >> "%LOG_FILE%"
  echo earnings rebuild failed at step: %STEP_NAME%. see %LOG_FILE%
  exit /b !ERR!
)
goto :eof