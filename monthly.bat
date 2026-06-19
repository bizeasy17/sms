@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"
set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "LOG_FILE=%LOG_DIR%\monthly_%RUN_STAMP%.log"

echo [INFO] monthly pipeline start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] uat_root=%UAT_ROOT% >> "%LOG_FILE%"

call :run_step "ETL monthly resample" :step_etl_monthly_resample
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE monthly pull" :step_be_monthly_pull
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE traditional valuation monthly full refresh" :step_be_traditional_monthly_full
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE monthly traditional valuation risk prefill" :step_be_monthly_traditional_valuation_risk_prefill
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE monthly weekly undervalued export" :step_be_monthly_weekly_undervalued_export
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "Earnings predictive valuation monthly full refresh" :step_earnings_predictive_monthly_full
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE THS moneyflow monthly score" :step_be_ths_moneyflow_monthly_score
if errorlevel 1 exit /b %ERRORLEVEL%

echo [INFO] monthly pipeline completed at %DATE% %TIME% >> "%LOG_FILE%"
echo monthly pipeline completed. log=%LOG_FILE%
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
  echo monthly pipeline failed at step: %STEP_NAME%. see %LOG_FILE%
  exit /b !ERR!
)
goto :eof

:step_be_monthly_pull
call "%UAT_ROOT%\smartinvestor_be\monthly.bat"
exit /b %ERRORLEVEL%

:step_be_traditional_monthly_full
set "CANDIDATE_POLICY=all"
call "%UAT_ROOT%\smartinvestor_be\earnings_refresh.bat"
set "CANDIDATE_POLICY="
exit /b %ERRORLEVEL%

:step_be_monthly_traditional_valuation_risk_prefill
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
pushd "%UAT_ROOT%\smartinvestor_be"
"%PYTHON_CMD%" manage.py prefillvaluationrisk --market CN
set "ERR=%ERRORLEVEL%"
popd
exit /b %ERR%

:step_be_monthly_weekly_undervalued_export
call "%UAT_ROOT%\smartinvestor_be\weekly_undervalued_friday.bat"
exit /b %ERRORLEVEL%

:step_earnings_predictive_monthly_full
call "%UAT_ROOT%\tushare_earnings_service\monthly_signal_full_refresh.bat"
exit /b %ERRORLEVEL%

:step_etl_monthly_resample
call "%UAT_ROOT%\smartinvestor_etl\monthly.bat"
exit /b %ERRORLEVEL%

:step_be_ths_moneyflow_monthly_score
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
pushd "%UAT_ROOT%\smartinvestor_be"
"%PYTHON_CMD%" manage.py refresh_ths_moneyflow_score_monthly --top-n 20 --lookback-days 30 --ths-index-type N
set "ERR=%ERRORLEVEL%"
popd
exit /b %ERR%
