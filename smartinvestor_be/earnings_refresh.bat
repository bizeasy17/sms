@echo off
setlocal enableextensions enabledelayedexpansion

set "VENV_PYTHON=C:\Users\HANJ29\Development\code\JIUCAI_DEV\.venv\Scripts\python.exe"
set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"
set "VALUATION_TABLE_PREFIX=valuation"

if not exist "output" mkdir "output"
if not exist "output\logs" mkdir "output\logs"

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%i"
set "MASTER_LOG=output\logs\earnings_refresh_%RUN_STAMP%.log"
set "CANDIDATE_FILE=output\logs\earnings_refresh_%RUN_STAMP%_candidates.txt"
set "PYTHON_CMD=python"
if exist "%VENV_PYTHON%" set "PYTHON_CMD=%VENV_PYTHON%"
if not defined CANDIDATE_POLICY set "CANDIDATE_POLICY=disclosure-only"
set "REFRESH_POLICY=disclosure"
if /I "%CANDIDATE_POLICY%"=="all" set "REFRESH_POLICY=all"
if /I "%REFRESH_POLICY%"=="all" (
	set "DEFAULT_REFRESH_REASON=regime_switch_manual"
) else (
	set "DEFAULT_REFRESH_REASON=disclosure_refresh"
)
if not defined REFRESH_REASON set "REFRESH_REASON=%DEFAULT_REFRESH_REASON%"
for /f "delims=" %%i in ('powershell -NoProfile -Command "$v='%REFRESH_REASON%'; if ([string]::IsNullOrWhiteSpace($v)) { $v='refresh' }; ($v -replace '[^0-9A-Za-z._-]', '_')"') do set "REFRESH_REASON_SAFE=%%i"
if not defined REFRESH_REASON_SAFE set "REFRESH_REASON_SAFE=refresh"
set "REFRESH_RUN_ID=valsnap_%REFRESH_REASON_SAFE%_%RUN_STAMP%"
set "COMMON_ARGS=--methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --profit-buckets both --request-interval 0.2 --refresh-policy "%REFRESH_POLICY%" --refresh-run-id "%REFRESH_RUN_ID%" --business-match-topn 3"
if defined PREFILL_EXTRA_ARGS set "COMMON_ARGS=%COMMON_ARGS% %PREFILL_EXTRA_ARGS%"
set "CANDIDATE_ARGS=--methods sw_history,pe,pb,ps,peg,fcff_dcf,ddm,scarcity_overlay --express-max-age-days 180 --candidate-policy %CANDIDATE_POLICY% --output-file %CANDIDATE_FILE%"
if defined CANDIDATE_EXTRA_ARGS set "CANDIDATE_ARGS=%CANDIDATE_ARGS% %CANDIDATE_EXTRA_ARGS%"
set "FAILURES=0"

call :log INFO "start earnings refresh base_dir=%BASE_DIR% python=%PYTHON_CMD% candidate_policy=%CANDIDATE_POLICY% refresh_policy=%REFRESH_POLICY% refresh_reason_safe=%REFRESH_REASON_SAFE% refresh_run_id=%REFRESH_RUN_ID%"
if /I "%REFRESH_POLICY%"=="all" goto :run_full_scopes

call :build_candidates
if not "%FAILURES%"=="0" (
	call :log ERROR "earnings refresh aborted while building candidates failures=%FAILURES%"
	exit /b 1
)
for %%z in ("%CANDIDATE_FILE%") do set "CANDIDATE_SIZE=%%~zz"
if "%CANDIDATE_SIZE%"=="0" (
	call :log INFO "no disclosure candidates found candidate_file=%CANDIDATE_FILE%"
	exit /b 0
)
call :log_candidate_prefix_counts
call :maybe_run_scope 60
call :maybe_run_scope 68
call :maybe_run_scope 00
call :maybe_run_scope 30
call :maybe_run_scope 8

if not "%FAILURES%"=="0" (
	call :log ERROR "earnings refresh completed with failures=%FAILURES%"
	exit /b 1
)

call :log INFO "earnings refresh completed successfully"
exit /b 0

:run_full_scopes
call :log INFO "full refresh mode enabled, skip candidate export"
call :run_scope_full 60
call :run_scope_full 68
call :run_scope_full 00
call :run_scope_full 30
call :run_scope_full 8

if not "%FAILURES%"=="0" (
	call :log ERROR "earnings refresh completed with failures=%FAILURES%"
	exit /b 1
)

call :log INFO "earnings refresh completed successfully"
exit /b 0

:build_candidates
call :log INFO "building disclosure candidates candidate_file=%CANDIDATE_FILE%"
"%PYTHON_CMD%" manage.py exportdisclosurecandidates %CANDIDATE_ARGS% > "%CANDIDATE_FILE%.log" 2>&1
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
	set /a FAILURES+=1
	call :log ERROR "candidate export failed exit_code=!RC! candidate_log=%CANDIDATE_FILE%.log"
	goto :eof
)
call :log INFO "candidate export completed candidate_file=%CANDIDATE_FILE% candidate_log=%CANDIDATE_FILE%.log"
goto :eof

:log_candidate_prefix_counts
for /f %%i in ('powershell -NoProfile -Command "(Get-Content '%CANDIDATE_FILE%' | Measure-Object).Count"') do set "CAND_ALL=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Content '%CANDIDATE_FILE%' | Where-Object { $_ -match '^60' } | Measure-Object).Count"') do set "CAND_60=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Content '%CANDIDATE_FILE%' | Where-Object { $_ -match '^68' } | Measure-Object).Count"') do set "CAND_68=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Content '%CANDIDATE_FILE%' | Where-Object { $_ -match '^00' } | Measure-Object).Count"') do set "CAND_00=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Content '%CANDIDATE_FILE%' | Where-Object { $_ -match '^30' } | Measure-Object).Count"') do set "CAND_30=%%i"
for /f %%i in ('powershell -NoProfile -Command "(Get-Content '%CANDIDATE_FILE%' | Where-Object { $_ -match '^8' } | Measure-Object).Count"') do set "CAND_8=%%i"
call :log INFO "candidate counts total=%CAND_ALL% 60=%CAND_60% 68=%CAND_68% 00=%CAND_00% 30=%CAND_30% 8=%CAND_8%"
goto :eof

:maybe_run_scope
set "SCOPE=%~1"
if not exist "%CANDIDATE_FILE%" (
	call :log INFO "scope=%SCOPE% skipped candidate file missing candidate_file=%CANDIDATE_FILE%"
	goto :eof
)
powershell -NoProfile -Command "if (Select-String -Path '%CANDIDATE_FILE%' -Pattern '^%SCOPE%' -Quiet) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
	call :run_scope %SCOPE%
	goto :eof
)
call :log INFO "scope=%SCOPE% skipped no candidates for prefix"
goto :eof

:run_scope
set "SCOPE=%~1"
set "SCOPE_LOG=output\logs\earnings_refresh_%RUN_STAMP%_scope_%SCOPE%.log"
call :log INFO "scope=%SCOPE% started scope_log=%SCOPE_LOG%"
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope %SCOPE% --codes-file "%CANDIDATE_FILE%" %COMMON_ARGS% > "%SCOPE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
	set /a FAILURES+=1
	call :log ERROR "scope=%SCOPE% failed exit_code=!RC! scope_log=%SCOPE_LOG%"
	goto :eof
)
call :log INFO "scope=%SCOPE% completed scope_log=%SCOPE_LOG%"
goto :eof

:run_scope_full
set "SCOPE=%~1"
set "SCOPE_LOG=output\logs\earnings_refresh_%RUN_STAMP%_scope_%SCOPE%.log"
call :log INFO "scope=%SCOPE% started scope_log=%SCOPE_LOG%"
"%PYTHON_CMD%" manage.py prefillvaluationsnapshot --scope %SCOPE% %COMMON_ARGS% > "%SCOPE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
	set /a FAILURES+=1
	call :log ERROR "scope=%SCOPE% failed exit_code=!RC! scope_log=%SCOPE_LOG%"
	goto :eof
)
call :log INFO "scope=%SCOPE% completed scope_log=%SCOPE_LOG%"
goto :eof

:log
set "LEVEL=%~1"
set "MESSAGE=%~2"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm:ss\""') do set "NOW=%%i"
echo [!NOW!] [!LEVEL!] !MESSAGE!
>> "%MASTER_LOG%" echo [!NOW!] [!LEVEL!] !MESSAGE!
goto :eof
