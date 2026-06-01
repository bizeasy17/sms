@echo off
echo Hello, Trading Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\web\UAT\smartinvestor_be\"

python manage.py pulldata --freq=D --dtype=trading --batch=True
REM --resume="300145.SZ"
echo Hello, Pull Trading dataset Completed!