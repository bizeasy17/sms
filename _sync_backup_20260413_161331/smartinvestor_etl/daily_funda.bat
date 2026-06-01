@echo off
echo Hello, Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_etl\"

python manage.py download --dtype=FUNDAMENTAL --freq=D
REM  --resume="001221.SZ"
echo Hello, Funda dataset download Completed!