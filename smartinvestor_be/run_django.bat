@echo off
echo Hello, Start Django Server!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd /d "C:\Users\HANJ29\Development\web\UAT\smartinvestor_be"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
set "VALUATION_TABLE_PREFIX=valuation"
set "FINANCIAL_SCREENING_SERVICE_BASE_URL=http://127.0.0.1:5003"

echo [INFO] Using Python: %PYTHON_CMD%

"%PYTHON_CMD%" manage.py runserver 5001
echo Hello, Django Server is running!