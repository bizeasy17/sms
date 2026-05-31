@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo [INFO] stopping UAT service windows

call :kill_window "UAT ETL 5000"
call :kill_window "UAT BE 5001"
call :kill_window "UAT Earnings 5002"
call :kill_window "UAT FE Vite"

echo [INFO] applying port-based fallback for Django services
call :kill_port 5000
call :kill_port 5001
call :kill_port 5002

echo [INFO] stop sequence completed.
exit /b 0

:kill_window
set "WINDOW_TITLE=%~1"
echo [INFO] closing window %WINDOW_TITLE%
taskkill /FI "WINDOWTITLE eq %WINDOW_TITLE%" /T /F >nul 2>&1
if errorlevel 1 (
  echo [WARN] window not found or already closed: %WINDOW_TITLE%
) else (
  echo [INFO] window closed: %WINDOW_TITLE%
)
goto :eof

:kill_port
set "TARGET_PORT=%~1"
set "FOUND_PID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%TARGET_PORT%" ^| findstr "LISTENING"') do (
  set "FOUND_PID=%%p"
  goto :kill_pid
)

echo [WARN] no listening process found on port %TARGET_PORT%
goto :eof

:kill_pid
echo [INFO] killing pid !FOUND_PID! on port %TARGET_PORT%
taskkill /PID !FOUND_PID! /T /F >nul 2>&1
if errorlevel 1 (
  echo [WARN] failed to kill pid !FOUND_PID! on port %TARGET_PORT%
) else (
  echo [INFO] killed pid !FOUND_PID! on port %TARGET_PORT%
)
goto :eof