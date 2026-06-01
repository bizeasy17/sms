@echo off
setlocal enableextensions enabledelayedexpansion
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM Full deployment script for standalone valuation service.
REM Usage:
REM   deploy_standalone_valuation_full.bat [TARGET_DIR] [SMOKE_TSCODE]
REM Example:
REM   deploy_standalone_valuation_full.bat "C:\Users\HANJ29\Development\code\sms\valuation_service_django" 688818.SH

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "DEFAULT_TARGET=C:\Users\HANJ29\Development\code\sms\valuation_service_django"
set "TARGET_DIR=%~1"
if "%TARGET_DIR%"=="" set "TARGET_DIR=%DEFAULT_TARGET%"

set "SMOKE_TSCODE=%~2"
if "%SMOKE_TSCODE%"=="" set "SMOKE_TSCODE=688818.SH"

set "VENV_PYTHON=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"

if not exist "%BASE_DIR%manage.py" (
  echo [ERROR] manage.py not found in source root: %BASE_DIR%
  exit /b 1
)

if /i "%PYTHON_CMD%"=="python" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    exit /b 1
  )
) else (
  if not exist "%PYTHON_CMD%" (
    echo [ERROR] Python executable missing: %PYTHON_CMD%
    exit /b 1
  )
)

if not exist "%BASE_DIR%output" mkdir "%BASE_DIR%output"
if not exist "%BASE_DIR%output\logs" mkdir "%BASE_DIR%output\logs"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TS=%%i"
set "LOG_FILE=%BASE_DIR%output\logs\standalone_full_deploy_%RUN_TS%.log"
set "SMOKE_LOG=%BASE_DIR%output\logs\standalone_full_deploy_smoke_%RUN_TS%.log"
set "BACKUP_DIR=%TARGET_DIR%\backup\standalone_full_deploy_%RUN_TS%"

call :log "[INFO] source=%BASE_DIR%"
call :log "[INFO] target=%TARGET_DIR%"
call :log "[INFO] python=%PYTHON_CMD%"
call :log "[INFO] smoke_tscode=%SMOKE_TSCODE%"

if not exist "%TARGET_DIR%" (
  call :log "[INFO] target directory missing, creating..."
  mkdir "%TARGET_DIR%" >> "%LOG_FILE%" 2>&1
)

call :log "[INFO] creating backup at %BACKUP_DIR%"
mkdir "%BACKUP_DIR%" >> "%LOG_FILE%" 2>&1

if exist "%TARGET_DIR%\manage.py" (
  call :safe_robocopy "%TARGET_DIR%\valuation_api" "%BACKUP_DIR%\valuation_api" /E
  call :safe_robocopy "%TARGET_DIR%\valuation_service" "%BACKUP_DIR%\valuation_service" /E
  call :safe_robocopy "%TARGET_DIR%\static" "%BACKUP_DIR%\static" /E
  call :safe_robocopy "%TARGET_DIR%\docs" "%BACKUP_DIR%\docs" /E
  if exist "%TARGET_DIR%\manage.py" copy /Y "%TARGET_DIR%\manage.py" "%BACKUP_DIR%\manage.py" >> "%LOG_FILE%" 2>&1
  if exist "%TARGET_DIR%\requirements.txt" copy /Y "%TARGET_DIR%\requirements.txt" "%BACKUP_DIR%\requirements.txt" >> "%LOG_FILE%" 2>&1
  if exist "%TARGET_DIR%\README.md" copy /Y "%TARGET_DIR%\README.md" "%BACKUP_DIR%\README.md" >> "%LOG_FILE%" 2>&1
)

call :log "[INFO] syncing source files to target"
call :safe_robocopy "%BASE_DIR%valuation_api" "%TARGET_DIR%\valuation_api" /E
call :safe_robocopy "%BASE_DIR%valuation_service" "%TARGET_DIR%\valuation_service" /E
call :safe_robocopy "%BASE_DIR%static" "%TARGET_DIR%\static" /E
call :safe_robocopy "%BASE_DIR%docs" "%TARGET_DIR%\docs" /E

copy /Y "%BASE_DIR%manage.py" "%TARGET_DIR%\manage.py" >> "%LOG_FILE%" 2>&1
copy /Y "%BASE_DIR%requirements.txt" "%TARGET_DIR%\requirements.txt" >> "%LOG_FILE%" 2>&1
if exist "%BASE_DIR%README.md" copy /Y "%BASE_DIR%README.md" "%TARGET_DIR%\README.md" >> "%LOG_FILE%" 2>&1

for %%f in (biweekly.bat daily_express_vip_sync.bat daily_valuation_due_runner.bat earnings_refresh.bat monthly.bat quarterly.bat) do (
  if exist "%BASE_DIR%%%f" copy /Y "%BASE_DIR%%%f" "%TARGET_DIR%\%%f" >> "%LOG_FILE%" 2>&1
)

call :log "[INFO] compile validation on target"
pushd "%TARGET_DIR%"
"%PYTHON_CMD%" -m compileall valuation_api\management\commands\estmktv.py valuation_api\scarcity_auto_engine.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  popd
  call :log "[ERROR] compile validation failed"
  exit /b 1
)

call :log "[INFO] running database migrations on target"
"%PYTHON_CMD%" manage.py migrate --noinput >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  popd
  call :log "[ERROR] migrate failed"
  exit /b 1
)

call :log "[INFO] smoke validation: manage.py estmktv --scarcity-profile auto --show-source"
"%PYTHON_CMD%" manage.py estmktv --tscode %SMOKE_TSCODE% --scarcity-profile auto --show-source > "%SMOKE_LOG%" 2>&1
if errorlevel 1 (
  popd
  call :log "[ERROR] smoke command failed, see %SMOKE_LOG%"
  exit /b 1
)

findstr /i "scarcity_profile_effective scarcity_profile_auto_reason" "%SMOKE_LOG%" >nul
if errorlevel 1 (
  popd
  call :log "[ERROR] smoke output missing scarcity markers, see %SMOKE_LOG%"
  exit /b 1
)

popd

call :log "[INFO] deploy completed successfully"
call :log "[INFO] backup=%BACKUP_DIR%"
call :log "[INFO] smoke_log=%SMOKE_LOG%"
exit /b 0

:safe_robocopy
set "SRC=%~1"
set "DST=%~2"
set "OPT=%~3"
if not exist "%SRC%" (
  call :log "[WARN] skip missing path: %SRC%"
  goto :eof
)
mkdir "%DST%" >> "%LOG_FILE%" 2>&1
robocopy "%SRC%" "%DST%" %OPT% /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >> "%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  call :log "[ERROR] robocopy failed (%RC%): %SRC% -> %DST%"
  exit /b 1
)
goto :eof

:log
echo %~1
echo %~1>> "%LOG_FILE%"
goto :eof
