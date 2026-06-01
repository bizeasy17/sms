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
if not defined SIGNAL_SNAPSHOT_ANCHOR_MODE set "SIGNAL_SNAPSHOT_ANCHOR_MODE=ann"
if not defined ENABLE_REGIME_TRIGGER_FULL_REFRESH set "ENABLE_REGIME_TRIGGER_FULL_REFRESH=1"
if not defined LOW_FREQ_FULL_REFRESH_MONTHDAY set "LOW_FREQ_FULL_REFRESH_MONTHDAY=1"
if not defined FULL_REFRESH_SCOPE set "FULL_REFRESH_SCOPE=60,00,30,68"
if not defined FULL_REFRESH_SLEEP_MS set "FULL_REFRESH_SLEEP_MS=50"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "CHANGED_SINCE=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).Month"') do set "CUR_MONTH=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).Day"') do set "CUR_DAY=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).Year"') do set "CUR_YEAR=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddYears(-1).Year"') do set "PREV_YEAR=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd')"') do set "ANN_END_DATE=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).AddDays(-%DISCLOSURE_LOOKBACK_DAYS%).ToString('yyyyMMdd')"') do set "ANN_START_DATE=%%i"

set "TARGET_REPORTS=LATEST"
set "TARGET_TAG=LATEST_DAILY"
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
set "REGIME_STATE_FILE=logs\market_regime_last.txt"
set "CURRENT_MARKET_REGIME="
set "PREVIOUS_MARKET_REGIME="
set "SHOULD_FULL_REFRESH=0"
set "FULL_REFRESH_REASON=none"

echo [INFO] start daily financial periodic refresh at %DATE% %TIME% > "%LOG_FILE%"
echo [INFO] base_dir=%BASE_DIR% >> "%LOG_FILE%"
echo [INFO] python=%PYTHON_CMD% >> "%LOG_FILE%"
echo [INFO] current_month=%CUR_MONTH% >> "%LOG_FILE%"
echo [INFO] current_day=%CUR_DAY% >> "%LOG_FILE%"
echo [INFO] target_reports=%TARGET_REPORTS% >> "%LOG_FILE%"
echo [INFO] target_tag=%TARGET_TAG% >> "%LOG_FILE%"
echo [INFO] audit_end_dates=%AUDIT_END_DATES% >> "%LOG_FILE%"
echo [INFO] disclosure_lookback_days=%DISCLOSURE_LOOKBACK_DAYS% >> "%LOG_FILE%"
echo [INFO] remote_dividend_lookback_days=%REMOTE_DIVIDEND_LOOKBACK_DAYS% >> "%LOG_FILE%"
echo [INFO] remote_financial_ann_lookback_days=%REMOTE_FINANCIAL_ANN_LOOKBACK_DAYS% >> "%LOG_FILE%"
echo [INFO] remote_financial_ann_apis=%REMOTE_FINANCIAL_ANN_APIS% >> "%LOG_FILE%"
echo [INFO] signal_snapshot_anchor_mode=%SIGNAL_SNAPSHOT_ANCHOR_MODE% >> "%LOG_FILE%"
echo [INFO] enable_regime_trigger_full_refresh=%ENABLE_REGIME_TRIGGER_FULL_REFRESH% >> "%LOG_FILE%"
echo [INFO] low_freq_full_refresh_monthday=%LOW_FREQ_FULL_REFRESH_MONTHDAY% >> "%LOG_FILE%"
echo [INFO] full_refresh_scope=%FULL_REFRESH_SCOPE% >> "%LOG_FILE%"
echo [INFO] full_refresh_sleep_ms=%FULL_REFRESH_SLEEP_MS% >> "%LOG_FILE%"
echo [INFO] ann_date_range=%ANN_START_DATE%~%ANN_END_DATE% >> "%LOG_FILE%"
echo [INFO] changed_since_anchor=%CHANGED_SINCE% >> "%LOG_FILE%"
echo [INFO] changed_codes_file=%CHANGED_CODES_FILE% >> "%LOG_FILE%"

if "%ENABLE_REGIME_TRIGGER_FULL_REFRESH%"=="1" (
  call :capture_market_regime
  if errorlevel 1 (
    echo [WARN] detect_market_regime failed, continue without regime trigger >> "%LOG_FILE%"
  ) else (
    echo [INFO] current_market_regime=%CURRENT_MARKET_REGIME% >> "%LOG_FILE%"
    if exist "%REGIME_STATE_FILE%" (
      for /f "usebackq delims=" %%i in ("%REGIME_STATE_FILE%") do (
        if not defined PREVIOUS_MARKET_REGIME set "PREVIOUS_MARKET_REGIME=%%i"
      )
    )
    if defined PREVIOUS_MARKET_REGIME (
      echo [INFO] previous_market_regime=%PREVIOUS_MARKET_REGIME% >> "%LOG_FILE%"
      if /I not "%CURRENT_MARKET_REGIME%"=="%PREVIOUS_MARKET_REGIME%" (
        set "SHOULD_FULL_REFRESH=1"
        set "FULL_REFRESH_REASON=regime_switch_%PREVIOUS_MARKET_REGIME%_to_%CURRENT_MARKET_REGIME%"
        echo [INFO] full refresh scheduled by regime switch >> "%LOG_FILE%"
      )
    ) else (
      echo [INFO] previous_market_regime not found, initialize state only >> "%LOG_FILE%"
    )
    > "%REGIME_STATE_FILE%" echo %CURRENT_MARKET_REGIME%
  )
) else (
  echo [INFO] regime-triggered full refresh disabled >> "%LOG_FILE%"
)

if "%SHOULD_FULL_REFRESH%"=="0" (
  if "%CUR_DAY%"=="%LOW_FREQ_FULL_REFRESH_MONTHDAY%" (
    set "SHOULD_FULL_REFRESH=1"
    set "FULL_REFRESH_REASON=monthly_%LOW_FREQ_FULL_REFRESH_MONTHDAY%"
    echo [INFO] monthly full refresh day matched >> "%LOG_FILE%"
  )
)

call :run_step "sync_disclosure_by_ann_date" "%PYTHON_CMD% manage.py sync_disclosure_by_ann_date --start-date %ANN_START_DATE% --end-date %ANN_END_DATE% --scope 60,00,30,68"
if errorlevel 1 goto :FAILED

call :run_step "export_updated_financial_codes" "%PYTHON_CMD% manage.py export_updated_financial_codes --changed-since %CHANGED_SINCE% --scope 60,00,30,68 --apis disclosure_date --include-remote-dividend-events --remote-dividend-lookback-days %REMOTE_DIVIDEND_LOOKBACK_DAYS% --include-remote-financial-ann-events --remote-financial-ann-apis %REMOTE_FINANCIAL_ANN_APIS% --remote-financial-lookback-days %REMOTE_FINANCIAL_ANN_LOOKBACK_DAYS% --output-file %CHANGED_CODES_FILE%"
if errorlevel 1 goto :FAILED

for %%z in ("%CHANGED_CODES_FILE%") do set "CHANGED_CODES_SIZE=%%~zz"
if "%CHANGED_CODES_SIZE%"=="0" (
  set "CHANGED_CODES_COUNT=0"
  echo [INFO] no updated disclosure stocks found since %CHANGED_SINCE%, skip changed-code sync/build/refresh >> "%LOG_FILE%"
) else (
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

  call :run_step "refresh_signal_snapshot_%TARGET_TAG%_fusion_changed_codes" "%PYTHON_CMD% manage.py refresh_signal_snapshot --tscodes-file %CHANGED_CODES_FILE% --report-types %TARGET_REPORTS%,FUSION --store-mode both --serving-slot production --anchor-mode %SIGNAL_SNAPSHOT_ANCHOR_MODE% --batch-key daily_%TARGET_TAG%_fusion_%RUN_STAMP%"
  if errorlevel 1 goto :FAILED
)

if "%SHOULD_FULL_REFRESH%"=="1" (
  call :run_step "refresh_signal_snapshot_full_%FULL_REFRESH_REASON%" "%PYTHON_CMD% manage.py refresh_signal_snapshot --scope %FULL_REFRESH_SCOPE% --full-refresh --report-types LATEST,FUSION --store-mode both --serving-slot production --anchor-mode %SIGNAL_SNAPSHOT_ANCHOR_MODE% --sleep-ms %FULL_REFRESH_SLEEP_MS% --batch-key full_%FULL_REFRESH_REASON%_%RUN_STAMP%"
  if errorlevel 1 goto :FAILED
) else (
  echo [INFO] skip full refresh (no regime switch and not monthly fallback day) >> "%LOG_FILE%"
)

echo [INFO] daily financial periodic refresh completed at %DATE% %TIME% >> "%LOG_FILE%"
echo daily financial periodic refresh completed. log=%LOG_FILE%
exit /b 0

:capture_market_regime
set "CURRENT_MARKET_REGIME="
set "REGIME_PROBE_FILE=logs\market_regime_probe_%RUN_STAMP%.txt"
"%PYTHON_CMD%" manage.py detect_market_regime --value-only > "%REGIME_PROBE_FILE%" 2>> "%LOG_FILE%"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" exit /b %ERR%

for /f "usebackq delims=" %%i in ("%REGIME_PROBE_FILE%") do (
  if not defined CURRENT_MARKET_REGIME set "CURRENT_MARKET_REGIME=%%i"
)
if not defined CURRENT_MARKET_REGIME exit /b 1
set "CURRENT_MARKET_REGIME=%CURRENT_MARKET_REGIME: =%"
exit /b 0

:run_step
set "STEP_NAME=%~1"
set "STEP_CMD=%~2"
echo [STEP] %STEP_NAME%
echo [STEP] %STEP_NAME% >> "%LOG_FILE%"
%STEP_CMD% >> "%LOG_FILE%" 2>&1
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
