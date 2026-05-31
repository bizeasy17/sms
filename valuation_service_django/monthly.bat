@echo off
echo Hello, Monthly Valuation Update Program!
cd /d "%~dp0"
set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

"%PYTHON_CMD%" manage.py updatevaluationconfigs --market CN --tasks sw_params_refresh,sw_params_refresh_reference
echo Hello, Valuation Params Refresh Completed!

"%PYTHON_CMD%" manage.py updatevaluationconfigs --market CN --tasks valuation_snapshot_prefill
echo Hello, Valuation Snapshot Prefill Completed!

echo Hello, Monthly Job Chain Completed!