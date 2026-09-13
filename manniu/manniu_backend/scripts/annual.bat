@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=C:\Users\HANJ29\Development\web\UAT\.venv\Scripts\python.exe"
set "RULES_FILE=%PROJECT_ROOT%\market_data\static\industry_config\industry_regime_rules_CN.json"

if not exist "%PYTHON_EXE%" (
	echo ERROR: UAT virtual environment Python was not found.
	exit /b 1
)

if not exist "%RULES_FILE%" (
	echo ERROR: Industry regime rules file was not found.
	exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1

call :sync_industry_mapping || goto :failure
call :refresh_business_matches || goto :failure

popd
echo Annual market-data refresh completed.
exit /b 0

:sync_industry_mapping
echo Publishing annual SW industry mapping and regime rules...
"%PYTHON_EXE%" manage.py sync_sw_industry_mapping --from-tushare --rules-file "%RULES_FILE%"
if errorlevel 1 (
	echo ERROR: SW industry mapping publication failed.
	exit /b 1
)
exit /b 0

:refresh_business_matches
echo Refreshing market-data business-text industry matches...
"%PYTHON_EXE%" manage.py traditional_valuation refresh-business-matches --business-match-topn 3

if errorlevel 1 (
	echo Annual business industry match refresh failed.
	exit /b 1
)
exit /b 0

:failure
popd
exit /b 1
