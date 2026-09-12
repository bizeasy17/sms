@echo off
setlocal

rem Refresh market-data business-text industry matches once per year.
cd /d "%~dp0.."
python manage.py traditional_valuation refresh-business-matches --business-match-topn 3

if errorlevel 1 (
	echo Annual business industry match refresh failed.
	exit /b 1
)

echo Annual business industry match refresh completed.
exit /b 0
