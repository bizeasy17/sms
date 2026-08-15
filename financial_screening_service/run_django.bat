@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
set "FINANCIAL_DB_NAME=smartinvestor_earnings_uat"
set "FINANCIAL_DB_HOST=127.0.0.1"
set "FINANCIAL_DB_PORT=5432"
set "FINANCIAL_DB_USER=postgres"
set "FINANCIAL_DB_PASSWORD=postgres"
"%PYTHON_CMD%" manage.py runserver 5003