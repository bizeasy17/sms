@echo off
setlocal enableextensions enabledelayedexpansion

set "VENV_PYTHON=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"
set "VALUATION_TABLE_PREFIX=valuation"

if not exist "output" mkdir "output"
if not exist "output\logs" mkdir "output\logs"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "RUN_DATE=%%i"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"

set "TRADING_LOG=output\logs\weekly_trading_%RUN_DATE%.log"
set "FUNDAMENTAL_LOG=output\logs\weekly_fundamental_%RUN_DATE%.log"
set "MASTER_LOG=output\logs\weekly_pipeline_%RUN_STAMP%.log"

call :log INFO "start weekly pipeline run_date=%RUN_DATE% python=%PYTHON_CMD%"

"%PYTHON_CMD%" manage.py pulldata --freq=W --batch=True --dtype=trading > "%TRADING_LOG%" 2>&1
if errorlevel 1 (
	call :log ERROR "weekly trading pull failed log=%TRADING_LOG%"
	exit /b 1
)
call :log INFO "weekly trading pull completed log=%TRADING_LOG%"

"%PYTHON_CMD%" manage.py pulldata --freq=W --batch=True --dtype=fundamental > "%FUNDAMENTAL_LOG%" 2>&1
if errorlevel 1 (
	call :log ERROR "weekly fundamental pull failed log=%FUNDAMENTAL_LOG%"
	exit /b 1
)
call :log INFO "weekly fundamental pull completed log=%FUNDAMENTAL_LOG%"

call :log INFO "trigger weekly undervalued export script"
call "%BASE_DIR%weekly_undervalued_friday.bat"
if errorlevel 1 (
	call :log ERROR "weekly undervalued export failed check output\\logs\\weekly_undervalued_*.log"
	exit /b 1
)
call :log INFO "weekly undervalued export completed"

@REM "%PYTHON_CMD%" manage.py predict --freq=W
@REM call :log INFO "weekly predict completed"

call :log INFO "weekly pipeline completed successfully"
endlocal
goto :eof

:log
set "LEVEL=%~1"
set "MESSAGE=%~2"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm:ss\""') do set "NOW=%%i"
echo [!NOW!] [!LEVEL!] !MESSAGE!
>> "%MASTER_LOG%" echo [!NOW!] [!LEVEL!] !MESSAGE!
goto :eof