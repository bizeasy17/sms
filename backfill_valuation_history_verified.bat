@echo off
setlocal EnableExtensions EnableDelayedExpansion
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
call "%ROOT%precheck_valuation_history_backfill.bat" "%START_DATE%" "%END_DATE%" "%SCOPE%" "%MAX_MISSING_CODES%"
if errorlevel 1 exit /b %ERRORLEVEL%
set "BACKFILL_SKIP_PRECHECK=1"
set "BACKFILL_ENABLE_FULL_REFRESH=1"
call "%ROOT%backfill_traditional_history_event_driven.bat" "%START_DATE%" "%END_DATE%" "%SCOPE%"
if errorlevel 1 exit /b %ERRORLEVEL%
for %%S in (%SCOPE:,= %) do (
  call "%ROOT%backfill_predictive_history_event_driven.bat" "%START_DATE%" "%END_DATE%" %%S "LATEST,FUSION" history 1
  if errorlevel 1 exit /b !ERRORLEVEL!
)
exit /b 0

:append_scope
if "%NORMALIZED_SCOPE%"=="" (
  set "NORMALIZED_SCOPE=%~1"
) else (
  set "NORMALIZED_SCOPE=%NORMALIZED_SCOPE%,%~1"
)
exit /b 0