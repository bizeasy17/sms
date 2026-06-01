@echo off
echo Hello, Biweekly Valuation Config Update Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_be\"
set "VALUATION_TABLE_PREFIX=valuation"

python manage.py updatevaluationconfigs --market CN --tasks sw_mapping_sync
echo Hello, SW Mapping Sync Completed!
