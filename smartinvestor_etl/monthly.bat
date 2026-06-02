@echo off
setlocal DisableDelayedExpansion
echo Hello, Trading ^& Fundamental Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd /d "C:\Users\HANJ29\Development\web\UAT\smartinvestor_etl"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

echo [INFO] Using Python: %PYTHON_CMD%

"%PYTHON_CMD%" manage.py resample --freq=ME --dtype=TRADING
echo Hello, Funda dataset resample Completed!

"%PYTHON_CMD%" manage.py resample --freq=ME --dtype=FUNDA
echo Hello, Funda dataset resample Completed!

"%PYTHON_CMD%" manage.py fetchcorp
echo Hello, Fetching corp info Completed!

echo Hello, Monthly Job Chain Completed!
exit /b %ERRORLEVEL%