@echo off
echo Hello, Trading & Fundamental Download Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
call ".\vdev1\Scripts\activate"
cd ".\web\UAT\smartinvestor_be\"

python manage.py pulldata --freq=W --batch=True --dtype=trading
echo Hello, Pull Trading dataset Completed!

python manage.py pulldata --freq=W --batch=True --dtype=fundamental
REM --resume="300145.SZ"
echo Hello, Pull Fundamental dataset Completed!

python manage.py predict --freq=W
echo Hello, Predict dataset Completed!