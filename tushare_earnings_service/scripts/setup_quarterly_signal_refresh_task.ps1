param(
    [string]$TaskName = "\BASF\ML\UAT\Earnings Signal Quarterly Refresh",
    [string]$BatchPath = "C:\Users\HANJ29\Development\web\UAT\tushare_earnings_service\quarterly_signal_refresh.bat",
    [string]$StartTime = "21:30"
)

if (!(Test-Path $BatchPath)) {
    throw "Batch file not found: $BatchPath"
}

$taskCmd = "C:\Windows\System32\cmd.exe /c `"$BatchPath`""
& schtasks /Create /TN "$TaskName" /TR "$taskCmd" /SC MONTHLY /MO 3 /D 1 /ST "$StartTime" /F
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create scheduled task: $TaskName"
}

Write-Output "Scheduled task created: $TaskName"
Write-Output "Run command: schtasks /Run /TN \"$TaskName\""