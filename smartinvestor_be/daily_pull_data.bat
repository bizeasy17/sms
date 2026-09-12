@echo off
echo Hello, Pull Fundamental Cost Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd /d "C:\Users\HANJ29\Development\web\UAT\smartinvestor_be"
set "PYTHON_CMD=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

echo [INFO] Using Python: %PYTHON_CMD%

"%PYTHON_CMD%" manage.py fetchcorp
echo Hello, Fetching corp info Completed!

"%PYTHON_CMD%" manage.py pulldata --freq=D --dtype=trading --batch=True
REM --resume="300145.SZ"
echo Hello, Pull Trading dataset Completed!

"%PYTHON_CMD%" manage.py pulldata --freq=D --dtype=fundamental --batch=True
REM --resume="300145.SZ"
echo Hello, Pull Fundamental dataset Completed!

"%PYTHON_CMD%" manage.py pulldata --freq=D --dtype=cost --batch=True
REM --resume="300145.SZ"
echo Hello, Pull Cost dataset Completed!

if errorlevel 1 (
	echo [ERROR] Predict failed.
	exit /b 1
)
echo Hello, Predict dataset Completed!

REM Disabled: daily pull only imports ETL data; do not run candidate picking.
REM if exist "daily_pick_candidates.bat" (
REM 	call daily_pick_candidates.bat
REM 	if errorlevel 1 (
REM 		echo [ERROR] Daily pick candidates failed.
REM 		exit /b 1
REM 	)
REM 	echo Hello, Daily Pick Candidates Completed!
REM ) else (
REM 	echo [WARN] daily_pick_candidates.bat not found, skip candidate picking.
REM )


@REM python manage.py combinedata --freq=D
REM --resume="300145.SZ"
echo Hello, Combine dataset disabled!

@REM python manage.py extractfeat --freq=D --distance=20 --feattyp=all
echo Hello, extract feature disabled!

@REM python .\manage.py predict --freq=D --startwith=3 --model_surfix=pkl --v=1.2 --model_name=RF
@REM python .\manage.py predict --freq=D --startwith=688 --model_surfix=pkl --v=1.2 --model_name=RF

@REM python .\manage.py predict --freq=D --startwith=3 --model_surfix=pkl --v=1.2 --model_name=XGB
@REM python .\manage.py predict --freq=D --startwith=688 --model_surfix=pkl --v=1.2 --model_name=XGB
@REM python .\manage.py predict --freq=D --startwith=60 --model_surfix=pkl --v=1.2 --model_name=XGB
@REM python .\manage.py predict --freq=D --startwith=0 --model_surfix=pkl --v=1.2 --model_name=RF
@REM python .\manage.py predict --freq=D --startwith=60 --model_surfix=pkl --v=1.2 --model_name=RF
echo Hello, Predict dataset v1.2 Completed!

@REM python manage.py predict --freq=D --model_surfix=model --v=1.1 --model_name=XGB
echo Hello, Predict dataset v1.1  Completed!


