@echo off
echo Hello, Earnings Window Valuation Refresh Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\code\sms\valuation_service_django"

set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

echo Running disclosure-window incremental refresh for valuation snapshots (prefix batched)...
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope 60 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope 68 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope 00 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope 30 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope 8 --methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2 --refresh-policy disclosure

echo Hello, Earnings Window Valuation Refresh Completed!