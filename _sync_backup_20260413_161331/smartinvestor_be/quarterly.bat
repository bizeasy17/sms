@echo off
echo Hello, Quarterly Valuation Config Update Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\web\UAT\smartinvestor_be\"

python manage.py updatevaluationconfigs --market CN --tasks keyword_rules_refresh
echo Hello, Keyword Rules Refresh Completed!
