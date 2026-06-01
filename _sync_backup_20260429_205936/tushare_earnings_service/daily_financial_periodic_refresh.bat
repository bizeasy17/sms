@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

set "PYTHON_CMD=C:\Users\HANJ29\Development\vdev1\Scripts\python.exe"
if not exist "%PYTHON_CMD%" set "PYTHON_CMD=python"
if not defined DISCLOSURE_LOOKBACK_DAYS set "DISCLOSURE_LOOKBACK_DAYS=2"
if not defined REMOTE_DIVIDEND_LOOKBACK_DAYS set "REMOTE_DIVIDEND_LOOKBACK_DAYS=%DISCLOSURE_LOOKBACK_DAYS%"
if not defined REMOTE_FINANCIAL_ANN_LOOKBACK_DAYS set "REMOTE_FINANCIAL_ANN_LOOKBACK_DAYS=%DISCLOSURE_LOOKBACK_DAYS%"
if not defined REMOTE_FINANCIAL_ANN_APIS set "REMOTE_FINANCIAL_ANN_APIS=fina_indicator_vip"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "CHANGED_SINCE=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).Month"') do set "CUR_MONTH=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).Year"') do set "CUR_YEAR=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddYears(-1).Year"') do set "PREV_YEAR=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd')"') do set "ANN_END_DATE=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddDays(-%DISCLOSURE_LOOKBACK_DAYS%).ToString('yyyyMMdd')"') do set "ANN_START_DATE=%%i"

set "TARGET_REPORTS="
set "TARGET_TAG="
set "AUDIT_END_DATES="
if "%CUR_MONTH%"=="3" set "TARGET_REPORTS=Q1,FY"
if "%CUR_MONTH%"=="3" set "TARGET_TAG=Q1_FY"
if "%CUR_MONTH%"=="4" set "TARGET_REPORTS=Q1,FY"
if "%CUR_MONTH%"=="4" set "TARGET_TAG=Q1_FY"
if "%CUR_MONTH%"=="7" set "TARGET_REPORTS=H1"
if "%CUR_MONTH%"=="7" set "TARGET_TAG=H1"
if "%CUR_MONTH%"=="8" set "TARGET_REPORTS=H1"
if "%CUR_MONTH%"=="8" set "TARGET_TAG=H1"
if "%CUR_MONTH%"=="10" set "TARGET_REPORTS=Q3"
if "%CUR_MONTH%"=="10" set "TARGET_TAG=Q3"
if "%CUR_MONTH%"=="11" set "TARGET_REPORTS=Q3"
if "%CUR_MONTH%"=="11" set "TARGET_TAG=Q3"

if "%TARGET_TAG%"=="Q1_FY" set "AUDIT_END_DATES=%CUR_YEAR%0331,%PREV_YEAR%1231"
if "%TARGET_TAG%"=="H1" set "AUDIT_END_DATES=%CUR_YEAR%0630"
if "%TARGET_TAG%"=="Q3" set "AUDIT_END_DATES=%CUR_YEAR%0930"

if not exist logs mkdir logs
set "LOG_FILE=logs\daily_financial_periodic_refresh_%RUN_STAMP%.log"
set "CHANGED_CODES_FILE=logs\daily_financial_changed_codes_%RUN_STAMP%.txt"

echo [INFO] start daily financial periodic refresh at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] current_month=%CUR_MONTH% >> "%LOG_FILE%"
echo [INFO] target_reports=%TARGET_REPORTS% >> "%LOG_FILE%"
echo [INFO] target_tag=%TARGET_TAG% >> "%LOG_FILE%"
echo [INFO] audit_end_dates=%AUDIT_END_DATES% >> "%LOG_FILE%"
echo [INFO] disclosure_lookback_days=%DISCLOSURE_LOOKBACK_DAYS% >> "%LOG_FILE%"
echo [INFO] remote_dividend_lookback_days=%REMOTE_DIVIDEND_LOOKBACK_DAYS% >> "%LOG_FILE%"
echo [INFO] remote_financial_ann_lookback_days=%REMOTE_FINANCIAL_ANN_LOOKBACK_DAYS% >> "%LOG_FILE%"
echo [INFO] remote_financial_ann_apis=%REMOTE_FINANCIAL_ANN_APIS% >> "%LOG_FILE%"
echo [INFO] ann_date_range=%ANN_START_DATE%~%ANN_END_DATE% >> "%LOG_FILE%"
echo [INFO] changed_since_anchor=%CHANGED_SINCE% >> "%LOG_FILE%"
echo [INFO] changed_codes_file=%CHANGED_CODES_FILE% >> "%LOG_FILE%"

if not defined TARGET_REPORTS (
  echo [INFO] skip monthly_financial_maintenance and refresh_signal_snapshot because month=%CUR_MONTH% is outside report windows >> "%LOG_FILE%"
  echo daily periodic refresh skipped for month=%CUR_MONTH%. log=%LOG_FILE%
  exit /b 0
)

call :run_step "sync_disclosure_by_ann_date" "%PYTHON_CMD% manage.py sync_disclosure_by_ann_date --start-date %ANN_START_DATE% --end-date %ANN_END_DATE% --scope 60,00,30,68"
if errorlevel 1 goto :FAILED

call :run_step "export_updated_financial_codes" "%PYTHON_CMD% manage.py export_updated_financial_codes --changed-since %CHANGED_SINCE% --scope 60,00,30,68 --apis disclosure_date --include-remote-dividend-events --remote-dividend-lookback-days %REMOTE_DIVIDEND_LOOKBACK_DAYS% --include-remote-financial-ann-events --remote-financial-ann-apis %REMOTE_FINANCIAL_ANN_APIS% --remote-financial-lookback-days %REMOTE_FINANCIAL_ANN_LOOKBACK_DAYS% --output-file %CHANGED_CODES_FILE%"
if errorlevel 1 goto :FAILED

for %%z in ("%CHANGED_CODES_FILE%") do set "CHANGED_CODES_SIZE=%%~zz"
if "%CHANGED_CODES_SIZE%"=="0" (
  echo [INFO] no updated disclosure stocks found since %CHANGED_SINCE%, skip sync/build/refresh >> "%LOG_FILE%"
  echo daily financial periodic refresh completed with zero updated stocks. log=%LOG_FILE%
  exit /b 0
)

for /f %%i in ('powershell -NoProfile -Command "(Get-Content '%CHANGED_CODES_FILE%' | Measure-Object).Count"') do set "CHANGED_CODES_COUNT=%%i"
echo [INFO] updated disclosure stocks count=%CHANGED_CODES_COUNT% >> "%LOG_FILE%"

call :run_step "sync_financials_for_changed_codes" "%PYTHON_CMD% manage.py sync_financials_direct --tscodes-file %CHANGED_CODES_FILE% --apis income,balancesheet_vip,cashflow_vip,forecast_vip,express_vip,dividend,fina_indicator_vip,fina_audit,fina_mainbz_vip --latest-only"
if errorlevel 1 goto :FAILED

if not "%AUDIT_END_DATES%"=="" (
  for %%E in (%AUDIT_END_DATES:,= %) do (
    call :run_step "audit_income_coverage_autofix_%%E" "%PYTHON_CMD% manage.py audit_income_coverage --end-date %%E --scope 60,00,30,68 --auto-fix --rebuild-features"
    if errorlevel 1 goto :FAILED
  )
)

call :run_step "build_financial_feature_panel_changed" "%PYTHON_CMD% manage.py build_financial_feature_panel --tscodes-file %CHANGED_CODES_FILE%"
if errorlevel 1 goto :FAILED

call :run_step "build_financial_feature_snapshot_changed" "%PYTHON_CMD% manage.py build_financial_feature_snapshot --tscodes-file %CHANGED_CODES_FILE%"
if errorlevel 1 goto :FAILED

call :run_step "refresh_signal_snapshot_%TARGET_TAG%_fusion_incremental" "%PYTHON_CMD% manage.py refresh_signal_snapshot --scope 60,00,30,68 --report-types %TARGET_REPORTS%,FUSION --store-mode both --serving-slot production --changed-since %CHANGED_SINCE% --changed-lookback-hours 0 --batch-key daily_%TARGET_TAG%_fusion_%RUN_STAMP%"
if errorlevel 1 goto :FAILED

echo [INFO] daily financial periodic refresh completed at %DATE% %TIME% >> "%LOG_FILE%"
echo daily financial periodic refresh completed. log=%LOG_FILE%
exit /b 0

:run_step
set "STEP_NAME=%~1"
set "STEP_CMD=%~2"
echo [STEP] %STEP_NAME%
echo [STEP] %STEP_NAME% >> "%LOG_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$cmd='%STEP_CMD%'; cmd /c $cmd 2>&1 | Tee-Object -FilePath '%LOG_FILE%' -Append; exit $LASTEXITCODE"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo [ERROR] %STEP_NAME% failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
  exit /b %ERR%
)
goto :eof

:FAILED
set "ERR=%ERRORLEVEL%"
echo [ERROR] daily financial periodic refresh failed code=%ERR% at %DATE% %TIME% >> "%LOG_FILE%"
echo daily financial periodic refresh failed. see %LOG_FILE%
exit /b %ERR%
