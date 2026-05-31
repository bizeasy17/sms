param(
    [string]$TaskName = "\BASF\ML\Valuation\UAT Service Stopper",
    [string]$BatchPath = "C:\Users\HANJ29\Development\web\UAT\stop_uat_services.bat",
    [string]$StartDate = "01/01/2099",
    [string]$StartTime = "00:00",
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $BatchPath)) {
    throw "Batch file not found: $BatchPath"
}

$taskCmd = 'C:\Windows\System32\cmd.exe /c ""' + $BatchPath + '""'
$cmd = "schtasks /Create /TN `"$TaskName`" /TR `"$taskCmd`" /SC ONCE /SD $StartDate /ST $StartTime /F"

if ($WhatIf) {
    Write-Host "[WHATIF] $cmd"
    exit 0
}

Invoke-Expression $cmd
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create scheduled task: $TaskName"
}

Write-Output "Scheduled task created: $TaskName"
Write-Output "Manual run: schtasks /Run /TN \"$TaskName\""