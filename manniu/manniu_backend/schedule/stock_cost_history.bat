@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\code\ASI_DEV\.venv\Scripts\python.exe"
set "ACTION=%~1"
set "START_DATE=%~2"
set "END_DATE=%~3"

if "%ACTION%"=="" set "ACTION=check"
if /i not "%ACTION%"=="check" if /i not "%ACTION%"=="backfill" goto :usage

if not exist "%PYTHON_EXE%" (
    echo ERROR: ASI_DEV virtual environment Python was not found.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1

if /i "%ACTION%"=="check" (
    if "%START_DATE%"=="" (
        "%PYTHON_EXE%" manage.py repair_stock_cost_history
    ) else if "%END_DATE%"=="" (
        "%PYTHON_EXE%" manage.py repair_stock_cost_history --start-date "%START_DATE%"
    ) else (
        "%PYTHON_EXE%" manage.py repair_stock_cost_history --start-date "%START_DATE%" --end-date "%END_DATE%"
    )
) else (
    if "%START_DATE%"=="" (
        "%PYTHON_EXE%" manage.py repair_stock_cost_history --execute --batch-size 50
    ) else if "%END_DATE%"=="" (
        "%PYTHON_EXE%" manage.py repair_stock_cost_history --execute --batch-size 50 --start-date "%START_DATE%"
    ) else (
        "%PYTHON_EXE%" manage.py repair_stock_cost_history --execute --batch-size 50 --start-date "%START_DATE%" --end-date "%END_DATE%"
    )
)
set "EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %EXIT_CODE%

:usage
echo Usage: %~nx0 [check^|backfill] [start-date] [end-date]
echo Example: %~nx0 check
echo Example: %~nx0 backfill 20210908 20260908
exit /b 2