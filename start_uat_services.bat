@echo off
setlocal EnableExtensions

set "UAT_ROOT=%~dp0"
if "%UAT_ROOT:~-1%"=="\" set "UAT_ROOT=%UAT_ROOT:~0,-1%"

set "NPM_CMD=npm"
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm not found in PATH.
  exit /b 1
)

echo [INFO] launching ETL on 5000
start "UAT ETL 5000" cmd /k call "%UAT_ROOT%\smartinvestor_etl\run_django.bat"

echo [INFO] launching BE on 5001
start "UAT BE 5001" cmd /k call "%UAT_ROOT%\smartinvestor_be\run_django.bat"

echo [INFO] launching Earnings Service on 5002
start "UAT Earnings 5002" cmd /k call "%UAT_ROOT%\tushare_earnings_service\run_django.bat"

echo [INFO] launching FE via Vite
start "UAT FE Vite" /d "%UAT_ROOT%\smartinvestor_fe" cmd /k %NPM_CMD% run dev -- --host 0.0.0.0

echo [INFO] all launch commands submitted.
exit /b 0