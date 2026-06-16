@echo off
echo Hello, Trading Fundamental Resample Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd /d "C:\Users\HANJ29\Development\web\UAT\smartinvestor_be"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
set "VALUATION_TABLE_PREFIX=valuation"

echo [INFO] Using Python: %PYTHON_CMD%

"%PYTHON_CMD%" manage.py pulldata --freq=M --batch=True --dtype=trading
REM --resume="300145.SZ"

"%PYTHON_CMD%" manage.py pulldata --freq=M --batch=True --dtype=fundamental

echo Hello, Pull Trading Fundamental dataset Completed!

"%PYTHON_CMD%" manage.py syncswvaluation --params-only --sample-size 3 --history-years 3,5,10 --history-quantile 0.5 --history-min-samples 120 --request-interval 0.45
if errorlevel 1 (
	echo [ERROR] syncswvaluation params refresh failed.
	exit /b 1
)
echo Hello, SW valuation params refresh Completed!

"%PYTHON_CMD%" manage.py syncvaluationremotecache --market CN --request-interval 0.4 --history-years 3,5,10 --history-quantile 0.5 --history-min-samples 120
if errorlevel 1 (
	echo [ERROR] syncvaluationremotecache failed.
	exit /b 1
)
echo Hello, Valuation Remote Cache Sync Completed!

"%PYTHON_CMD%" manage.py refresh_ths_industry_snapshot --strict
if errorlevel 1 (
	echo [ERROR] refresh_ths_industry_snapshot failed.
	exit /b 1
)
echo Hello, THS industry snapshot (member_count) refresh Completed!

"%PYTHON_CMD%" manage.py refresh_ths_moneyflow_score_monthly --top-n 20 --lookback-days 30 --ths-index-type N
if errorlevel 1 (
	echo [ERROR] refresh_ths_moneyflow_score_monthly failed.
	exit /b 1
)
echo Hello, THS moneyflow score monthly refresh Completed!

@REM python manage.py predict --freq=M
@REM echo Hello, Predict dataset Completed!

echo Hello, Monthly Job Chain Completed!
