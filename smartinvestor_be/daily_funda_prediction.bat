@echo off
echo Hello, Pull Fundamental Cost Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_be\"

python manage.py pulldata --freq=D --dtype=fundamental --batch=True
REM --resume="300145.SZ"
echo Hello, Pull Fundamental dataset Completed!

python manage.py pulldata --freq=D --dtype=cost --batch=True
REM --resume="300145.SZ"
echo Hello, Pull Cost dataset Completed!

if errorlevel 1 (
	echo [ERROR] Predict failed.
	exit /b 1
)
echo Hello, Predict dataset Completed!

if exist "daily_pick_candidates.bat" (
	call daily_pick_candidates.bat
	if errorlevel 1 (
		echo [ERROR] Daily pick candidates failed.
		exit /b 1
	)
	echo Hello, Daily Pick Candidates Completed!
) else (
	echo [WARN] daily_pick_candidates.bat not found, skip candidate picking.
)


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


