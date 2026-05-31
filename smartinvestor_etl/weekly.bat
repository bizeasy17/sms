@echo off
echo Hello, Trading Fundamental Resample Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\web\UAT\smartinvestor_etl\"

python manage.py resample --freq=W-FRI --dtype=TRADING
echo Hello, Trading dataset resample Completed!

python manage.py resample --freq=W-FRI --dtype=FUNDA
echo Hello, Funda dataset resample Completed!