@echo off
echo Hello, Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_etl\"

python manage.py download --freq=D --dtype=TRADING
REM --resume="300145.SZ"
echo Hello, Trading dataset download Completed!