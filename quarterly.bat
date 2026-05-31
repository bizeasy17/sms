@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"
set "LOG_DIR=%UAT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "LOG_FILE=%LOG_DIR%\quarterly_%RUN_STAMP%.log"

echo [INFO] quarterly pipeline start at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] uat_root=%UAT_ROOT% >> "%LOG_FILE%"

call :run_step "Earnings quarterly full pipeline" :step_earnings_quarterly_full_pipeline
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE earnings refresh backfill" :step_be_earnings_refresh_backfill
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_step "BE annual outlook" :step_be_annual_outlook
if errorlevel 1 exit /b %ERRORLEVEL%

echo [INFO] quarterly pipeline completed at %DATE% %TIME% >> "%LOG_FILE%"
echo quarterly pipeline completed. log=%LOG_FILE%
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
  echo quarterly pipeline failed at step: %STEP_NAME%. see %LOG_FILE%
  exit /b !ERR!
)
goto :eof

:step_earnings_quarterly_full_pipeline
call "%UAT_ROOT%\tushare_earnings_service\quarterly_full_pipeline.bat"
exit /b %ERRORLEVEL%

:step_be_earnings_refresh_backfill
call "%UAT_ROOT%\smartinvestor_be\earnings_refresh_backfill.bat"
exit /b %ERRORLEVEL%

:step_be_annual_outlook
call "%UAT_ROOT%\smartinvestor_be\daily_annual_outlook.bat"
exit /b %ERRORLEVEL%
