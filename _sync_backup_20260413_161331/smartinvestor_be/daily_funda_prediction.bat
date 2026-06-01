@echo off
echo Hello, Trading Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\web\UAT\smartinvestor_be\"

python manage.py pulldata --freq=D --dtype=fundamental --batch=True
REM --resume="300145.SZ"
echo Hello, Pull Fundamental dataset Completed!

python manage.py predict --freq=D
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