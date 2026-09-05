@echo off
setlocal EnableExtensions
set "DJANGO_SETTINGS_MODULE="
set "ROOT=%~dp0"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
set "START_DATE=%~1"
set "END_DATE=%~2"
set "SCOPE=%~3"
set "MAX_MISSING_CODES=%~4"
if "%~3"=="60" if "%~5"=="30" if "%~6"=="68" if not "%~7"=="" (
	set "SCOPE=60,00,30,68"
	set "MAX_MISSING_CODES=%~7"
)
if "%START_DATE%"=="" for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddYears(-1).ToString('yyyy-MM-dd')"') do set "START_DATE=%%i"
if "%END_DATE%"=="" for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "END_DATE=%%i"
if "%SCOPE%"=="" set "SCOPE=60,00,30,68"
if /I "%SCOPE%"=="ALL" set "SCOPE=60,00,30,68"
set "NORMALIZED_SCOPE="
for %%S in (%SCOPE:,= %) do (
	if "%%S"=="60" call :append_scope 60
	if "%%S"=="00" call :append_scope 00
	if "%%S"=="30" call :append_scope 30
	if "%%S"=="68" call :append_scope 68
)
if "%NORMALIZED_SCOPE%"=="" set "NORMALIZED_SCOPE=60,00,30,68"
set "SCOPE=%NORMALIZED_SCOPE%"
if "%MAX_MISSING_CODES%"=="" set "MAX_MISSING_CODES=20"
if not exist "%ROOT%logs" mkdir "%ROOT%logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "EARNINGS_REPORT=%ROOT%logs\earnings_history_precheck_%STAMP%.json"
set "BE_REPORT=%ROOT%logs\be_history_precheck_%STAMP%.json"

pushd "%ROOT%tushare_earnings_service"
"%PYTHON_CMD%" manage.py check_history_backfill_prerequisites --start-date %START_DATE% --end-date %END_DATE% --scope %SCOPE% --max-missing-codes %MAX_MISSING_CODES% --report-file "%EARNINGS_REPORT%"
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" exit /b %ERR%

pushd "%ROOT%smartinvestor_be"
"%PYTHON_CMD%" manage.py check_history_backfill_prerequisites --start-date %START_DATE% --end-date %END_DATE% --scope %SCOPE% --max-missing-codes %MAX_MISSING_CODES% --report-file "%BE_REPORT%"
set "ERR=%ERRORLEVEL%"
popd
exit /b %ERR%

:append_scope
if "%NORMALIZED_SCOPE%"=="" (
	set "NORMALIZED_SCOPE=%~1"
) else (
	set "NORMALIZED_SCOPE=%NORMALIZED_SCOPE%,%~1"
)
exit /b 0