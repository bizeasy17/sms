@echo off
setlocal

REM Run from this script directory (should contain manage.py)
cd /d "%~dp0"
set "VALUATION_TABLE_PREFIX=valuation"

echo [1/3] H1 batch: trade-date=2025-08-29
python.exe manage.py prefillvaluationsnapshot --trade-date 2025-08-29 --scope 60,00,30,68 --freq D --refresh-policy all --business-match-topn 3 
if errorlevel 1 goto :failed

echo.
echo [2/3] Q3 batch: trade-date=2025-10-31
python.exe manage.py prefillvaluationsnapshot --trade-date 2025-10-31 --scope 60,00,30,68 --freq D --refresh-policy all --business-match-topn 3 
if errorlevel 1 goto :failed

echo.
echo [3/3] FY(2025 annual) batch: trade-date=2026-04-30
python.exe manage.py prefillvaluationsnapshot --trade-date 2026-04-30 --scope 60,00,30,68 --freq D --refresh-policy all --business-match-topn 3 
if errorlevel 1 goto :failed

echo.
echo All refresh batches completed successfully.
goto :end

:failed
echo.
echo Batch stopped due to error. Exit code: %errorlevel%

:end
endlocal
