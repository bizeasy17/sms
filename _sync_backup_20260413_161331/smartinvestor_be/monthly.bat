@echo off
echo Hello, Trading Fundamental Resample Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_be\"
set "VALUATION_TABLE_PREFIX=valuation"

python manage.py pulldata --freq=M --batch=True --dtype=trading
REM --resume="300145.SZ"

python manage.py pulldata --freq=M --batch=True --dtype=fundamental

echo Hello, Pull Trading Fundamental dataset Completed!

python manage.py syncvaluationremotecache --market CN --request-interval 0.4 --history-years 3,5,10 --history-quantile 0.5 --history-min-samples 120
if errorlevel 1 (
	echo [ERROR] syncvaluationremotecache failed.
	exit /b 1
)
echo Hello, Valuation Remote Cache Sync Completed!

@REM python manage.py predict --freq=M
@REM echo Hello, Predict dataset Completed!

echo Hello, Monthly Job Chain Completed!
