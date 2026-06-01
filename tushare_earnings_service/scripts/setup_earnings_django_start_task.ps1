param(
	[string]$TaskName = "UAT_Earnings_Django_Service",
	[string]$RunBatPath = "C:\Users\HANJ29\Development\web\UAT\tushare_earnings_service\run_django.bat"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RunBatPath)) {
	throw "run_django.bat not found: $RunBatPath"
}

$currentUser = "$env:USERDOMAIN\$env:USERNAME"
$taskRun = "cmd /c `"$RunBatPath`""

Write-Host "[INFO] create/update task: $TaskName"
Write-Host "[INFO] user: $currentUser"
Write-Host "[INFO] command: $taskRun"

schtasks /Create /TN $TaskName /SC ONLOGON /TR $taskRun /RU $currentUser /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) {
	throw "failed to create task '$TaskName'. exit_code=$LASTEXITCODE"
}

Write-Host "[INFO] query task: $TaskName"
schtasks /Query /TN $TaskName /FO LIST /V | Out-Host
if ($LASTEXITCODE -ne 0) {
	throw "task '$TaskName' query failed. exit_code=$LASTEXITCODE"
}

Write-Host "[DONE] task ready. It will start earnings django service at user logon."
