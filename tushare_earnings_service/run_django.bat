@echo off
echo Hello, Start Earnings Service Django Server!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd /d "C:\Users\HANJ29\Development\web\UAT\tushare_earnings_service"

set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

echo [INFO] Using Python: %PYTHON_CMD%

"%PYTHON_CMD%" manage.py runserver 5002
echo Hello, Earnings Service Django Server is running!
