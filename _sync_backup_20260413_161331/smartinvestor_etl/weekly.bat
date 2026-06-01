@echo off
echo Hello, Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_etl\"

python manage.py resample --freq=W-FRI --dtype=TRADING
echo Hello, Trading dataset resample Completed!

python manage.py resample --freq=W-FRI --dtype=FUNDA
echo Hello, Funda dataset resample Completed!