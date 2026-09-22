@echo off
setlocal EnableExtensions

set "SCRIPTS_ROOT=%~dp0"
set "BACKEND_ROOT=%SCRIPTS_ROOT%.."
set "FRONTEND_ROOT=%SCRIPTS_ROOT%..\..\manniu_frontend"
set "PYTHON_CMD=C:\Users\HANJ29\Development\web\UAT\.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found in PATH.
    exit /b 1
)

if not exist "%BACKEND_ROOT%\manage.py" (
    echo [ERROR] Django manage.py was not found at "%BACKEND_ROOT%\manage.py".
    exit /b 1
)

if not exist "%FRONTEND_ROOT%\package.json" (
    echo [ERROR] Frontend package.json was not found at "%FRONTEND_ROOT%\package.json".
    exit /b 1
)

echo [INFO] launching Manniu backend on 8010
start "Manniu Backend 8010" /d "%BACKEND_ROOT%" cmd /k call "%PYTHON_CMD%" manage.py runserver 0.0.0.0:8010

echo [INFO] launching Manniu frontend on 5174
start "Manniu Frontend 5174" /d "%FRONTEND_ROOT%" cmd /k "set VITE_BACKEND_ORIGIN=http://127.0.0.1:8010&& npm run dev -- --host 0.0.0.0 --port 5174"

echo [INFO] all Manniu launch commands submitted.
exit /b 0