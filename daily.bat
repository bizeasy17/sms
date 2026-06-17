@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
if not defined ENABLE_PARALLEL_REFRESH set "ENABLE_PARALLEL_REFRESH=1"
if not defined LOW_FREQ_TRADITIONAL_FULL_REFRESH_MONTHDAY set "LOW_FREQ_TRADITIONAL_FULL_REFRESH_MONTHDAY=1"

set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).Day"') do set "CUR_DAY=%%i"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMM"') do set "CUR_MONTH_KEY=%%i"
set "LOG_FILE=%LOG_DIR%\daily_%RUN_STAMP%.log"
set "TRADITIONAL_FULL_MARK_FILE=%LOG_DIR%\traditional_full_refresh_last_month.txt"
set "LAST_TRADITIONAL_FULL_MONTH="
if exist "%TRADITIONAL_FULL_MARK_FILE%" (
  for /f "usebackq delims=" %%i in ("%TRADITIONAL_FULL_MARK_FILE%") do if not defined LAST_TRADITIONAL_FULL_MONTH set "LAST_TRADITIONAL_FULL_MONTH=%%i"
)

set "TRADITIONAL_CANDIDATE_POLICY=disclosure-only"
set "SHOULD_TRADITIONAL_FULL_REFRESH=0"
if %CUR_DAY% GEQ %LOW_FREQ_TRADITIONAL_FULL_REFRESH_MONTHDAY% (
  if /I not "%LAST_TRADITIONAL_FULL_MONTH%"=="%CUR_MONTH_KEY%" (
    set "SHOULD_TRADITIONAL_FULL_REFRESH=1"
    set "TRADITIONAL_CANDIDATE_POLICY=all"
  )
)
set "TRADITIONAL_REFRESH_CMD=set CANDIDATE_POLICY=%TRADITIONAL_CANDIDATE_POLICY% && call %UAT_ROOT%\smartinvestor_be\earnings_refresh.bat"

echo [INFO] daily pipeline start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] uat_root=%UAT_ROOT% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] current_day=%CUR_DAY% >> "%LOG_FILE%"
echo [INFO] current_month_key=%CUR_MONTH_KEY% >> "%LOG_FILE%"
echo [INFO] low_freq_traditional_full_refresh_monthday=%LOW_FREQ_TRADITIONAL_FULL_REFRESH_MONTHDAY% >> "%LOG_FILE%"
echo [INFO] traditional_full_mark_file=%TRADITIONAL_FULL_MARK_FILE% >> "%LOG_FILE%"
echo [INFO] last_traditional_full_month=%LAST_TRADITIONAL_FULL_MONTH% >> "%LOG_FILE%"
echo [INFO] should_traditional_full_refresh=%SHOULD_TRADITIONAL_FULL_REFRESH% >> "%LOG_FILE%"
echo [INFO] traditional_candidate_policy=%TRADITIONAL_CANDIDATE_POLICY% >> "%LOG_FILE%"

call :run_step "ETL daily trading download" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=TRADING"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL daily fundamental download" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=FUNDAMENTAL"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "ETL daily CYQ download" "%UAT_ROOT%\smartinvestor_etl" "%PYTHON_CMD% manage.py download --freq=D --dtype=CYQ"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "Earnings sync market local delta" "%UAT_ROOT%\tushare_earnings_service" "%PYTHON_CMD% manage.py sync_market_local --mode delta --freq D --retention-years 3"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "Earnings sync index dailybasic local" "%UAT_ROOT%\tushare_earnings_service" "%PYTHON_CMD% manage.py sync_index_dailybasic_local --lookback-years 8"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE daily trading pull" "%UAT_ROOT%\smartinvestor_be" "call %UAT_ROOT%\smartinvestor_be\daily_pull_data.bat"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE sw params refresh daily pre-traditional" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py syncswvaluation --params-only --sample-size 3 --history-years 3,5,10 --history-quantile 0.5 --history-min-samples 120 --request-interval 0.45"
if errorlevel 1 exit /b %ERRORLEVEL%
if "%ENABLE_PARALLEL_REFRESH%"=="1" (
  call :run_parallel_steps ^
    "Earnings daily financial maintenance + periodic report refresh" "%UAT_ROOT%\tushare_earnings_service" "call %UAT_ROOT%\tushare_earnings_service\daily_financial_periodic_refresh.bat" ^
    "BE traditional valuation prefill daily" "%UAT_ROOT%\smartinvestor_be" "%TRADITIONAL_REFRESH_CMD%"
  if errorlevel 1 exit /b %ERRORLEVEL%
) else (
  call :run_step "Earnings daily financial maintenance + periodic report refresh" "%UAT_ROOT%\tushare_earnings_service" "call %UAT_ROOT%\tushare_earnings_service\daily_financial_periodic_refresh.bat"
  if errorlevel 1 exit /b %ERRORLEVEL%
  call :run_step "BE traditional valuation prefill daily" "%UAT_ROOT%\smartinvestor_be" "%TRADITIONAL_REFRESH_CMD%"
  if errorlevel 1 exit /b %ERRORLEVEL%
)
if "%SHOULD_TRADITIONAL_FULL_REFRESH%"=="1" (
  > "%TRADITIONAL_FULL_MARK_FILE%" echo %CUR_MONTH_KEY%
  echo [INFO] traditional monthly full refresh mark updated month=%CUR_MONTH_KEY% >> "%LOG_FILE%"
)
call :run_step "BE sw rotation run daily evaluation" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py refresh_sw_rotation_run_evaluation_daily --windows 5,20,60 --limit 200"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE THS moneyflow daily sync" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py sync_ths_moneyflow_daily --lookback-days 7"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE stock moneyflow daily sync" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py sync_stock_moneyflow_ths_daily --lookback-days 7"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE stock moneyflow feature latest" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py build_stock_moneyflow_features --latest"
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE valuation risk prefill daily" "%UAT_ROOT%\smartinvestor_be" "%PYTHON_CMD% manage.py prefillvaluationrisk --market CN"
if errorlevel 1 exit /b %ERRORLEVEL%
@REM call :run_step "BE daily prediction" "%UAT_ROOT%\smartinvestor_be" "call %UAT_ROOT%\smartinvestor_be\daily_funda_prediction.bat"

echo [INFO] daily pipeline completed at %DATE% %TIME% >> "%LOG_FILE%"
echo daily pipeline completed. log=%LOG_FILE%
exit /b 0

:run_step
set "STEP_NAME=%~1"
set "STEP_DIR=%~2"
set "STEP_CMD=%~3"
echo [STEP] %STEP_NAME%
echo [STEP] %STEP_NAME% >> "%LOG_FILE%"
if not exist "%STEP_DIR%" (
  echo [ERROR] %STEP_NAME% missing dir: %STEP_DIR% >> "%LOG_FILE%"
  echo daily pipeline failed at step: %STEP_NAME%. missing dir %STEP_DIR%. see %LOG_FILE%
  exit /b 1
)
pushd "%STEP_DIR%"
call %STEP_CMD% >> "%LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" (
  echo [ERROR] %STEP_NAME% failed code=!ERR! at %DATE% %TIME% >> "%LOG_FILE%"
  echo daily pipeline failed at step: %STEP_NAME%. see %LOG_FILE%
  exit /b !ERR!
)
goto :eof

:run_parallel_steps
set "STEP1_NAME=%~1"
set "STEP1_DIR=%~2"
set "STEP1_CMD=%~3"
set "STEP2_NAME=%~4"
set "STEP2_DIR=%~5"
set "STEP2_CMD=%~6"

if not exist "%STEP1_DIR%" (
  echo [ERROR] %STEP1_NAME% missing dir: %STEP1_DIR% >> "%LOG_FILE%"
  echo daily pipeline failed at step: %STEP1_NAME%. missing dir %STEP1_DIR%. see %LOG_FILE%
  exit /b 1
)
if not exist "%STEP2_DIR%" (
  echo [ERROR] %STEP2_NAME% missing dir: %STEP2_DIR% >> "%LOG_FILE%"
  echo daily pipeline failed at step: %STEP2_NAME%. missing dir %STEP2_DIR%. see %LOG_FILE%
  exit /b 1
)

set "PAR_STEP1_DIR=%STEP1_DIR%"
set "PAR_STEP1_CMD=%STEP1_CMD%"
set "PAR_STEP2_DIR=%STEP2_DIR%"
set "PAR_STEP2_CMD=%STEP2_CMD%"
set "PAR_STEP1_LOG=%LOG_DIR%\parallel_%RUN_STAMP%_step1.log"
set "PAR_STEP2_LOG=%LOG_DIR%\parallel_%RUN_STAMP%_step2.log"

echo [STEP] parallel start: %STEP1_NAME% ^| %STEP2_NAME%
echo [STEP] parallel start: %STEP1_NAME% ^| %STEP2_NAME% >> "%LOG_FILE%"
echo [INFO] parallel log for %STEP1_NAME%: %PAR_STEP1_LOG% >> "%LOG_FILE%"
echo [INFO] parallel log for %STEP2_NAME%: %PAR_STEP2_LOG% >> "%LOG_FILE%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $cmd1 = 'cd /d \"' + $env:PAR_STEP1_DIR + '\" && ' + $env:PAR_STEP1_CMD + ' >> \"' + $env:PAR_STEP1_LOG + '\" 2>&1'; $cmd2 = 'cd /d \"' + $env:PAR_STEP2_DIR + '\" && ' + $env:PAR_STEP2_CMD + ' >> \"' + $env:PAR_STEP2_LOG + '\" 2>&1'; $p1 = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd1 -PassThru; $p2 = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd2 -PassThru; $p1.WaitForExit(); $p2.WaitForExit(); if ($p1.ExitCode -ne 0 -or $p2.ExitCode -ne 0) { Write-Host ('parallel step failed: step1=' + $p1.ExitCode + ', step2=' + $p2.ExitCode); exit 1 }"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] parallel steps failed at %DATE% %TIME% >> "%LOG_FILE%"
  echo [ERROR] check logs: %PAR_STEP1_LOG% ; %PAR_STEP2_LOG% >> "%LOG_FILE%"
  echo daily pipeline failed at parallel steps. see %LOG_FILE%
  exit /b %ERR%
)

echo [STEP] parallel completed: %STEP1_NAME% ^| %STEP2_NAME% >> "%LOG_FILE%"
goto :eof
