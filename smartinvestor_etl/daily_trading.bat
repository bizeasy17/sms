@echo off
echo Hello, Trading Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_etl\"

@REM python manage.py fetchcorp
@REM echo Hello, Fetching corp info Completed!

python manage.py download --freq=D --dtype=TRADING
REM --resume="300145.SZ"
echo Hello, Trading dataset download Completed!