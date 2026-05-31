@echo off
setlocal EnableExtensions

set "START_DATE=%~1"
if "%START_DATE%"=="" set "START_DATE=2023-01-01"
set "END_DATE=%~2"
if "%END_DATE%"=="" set "END_DATE=2024-12-31"

set "BASE_DIR=%~dp0smartinvestor_be"
set "PY=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%BASE_DIR%\manage.py" (
  echo [ERROR] manage.py not found: "%BASE_DIR%\manage.py"
  exit /b 1
)

cd /d "%BASE_DIR%"
set "START_DATE=%START_DATE%"
set "END_DATE=%END_DATE%"

echo [INFO] Fill missing report_type, range=%START_DATE%..%END_DATE%
"%PY%" manage.py shell -i python -c "exec(open(r'scripts/fill_missing_report_type_crossdb.py', encoding='utf-8').read())"
set "RC=%ERRORLEVEL%"
echo [INFO] exit_code=%RC%
exit /b %RC%
