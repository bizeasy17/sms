@echo off
echo Hello, Start Django Server!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\code\sms\smartinvestor_etl\"

python manage.py runserver 5000
echo Hello, Django Server is running!