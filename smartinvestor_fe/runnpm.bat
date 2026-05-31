@echo off
echo Hello, Run NPM Program!
PowerShell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process"
cd "C:\Users\HANJ29\Development\"
cd ".\web\UAT\smartinvestor_fe\"

npm run dev
echo Hello, NPM is running!