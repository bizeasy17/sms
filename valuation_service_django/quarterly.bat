@echo off
echo Hello, Quarterly Valuation Config Update Program!
cd /d "%~dp0"
set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
"%PYTHON_CMD%" manage.py updatevaluationconfigs --market CN --tasks keyword_rules_refresh

