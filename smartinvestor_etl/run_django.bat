@echo off
echo Hello, Start Django Server!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd /d "C:\Users\HANJ29\Development\web\UAT\smartinvestor_etl"
set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

"%PYTHON_CMD%" manage.py runserver 5000
echo Hello, Django Server is running!