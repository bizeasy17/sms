param(
    [string]$TaskRoot = "\BASF\ML\UAT",
    [string]$DailyTaskName = "Valuation Earnings Refresh",
    [string]$BackfillTaskName = "Valuation Earnings Refresh Backfill",
    [string]$DailyBatchPath = "C:\Users\HANJ29\Development\web\UAT\smartinvestor_be\earnings_refresh.bat",
    [string]$BackfillBatchPath = "C:\Users\HANJ29\Development\web\UAT\smartinvestor_be\earnings_refresh_backfill.bat",
    [string]$DailyStartTime = "22:00",
    [string]$BackfillStartTime = "23:30",
    [switch]$CreateBackfillTask,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Join-TaskName {
    param(
        [string]$Root,
        [string]$Name
    )
    $rootNorm = ($Root -replace "/", "\\").Trim().Trim("\\")
    return "\$rootNorm\$Name"
}

function Run-Command {
    param(
        [string]$Command,
        [switch]$DryRun
    )
    if ($DryRun) {
        Write-Host "[WHATIF] $Command"
        return
    }
    Invoke-Expression $Command
}

function Upsert-Task {
    param(
        [string]$TaskName,
        [string]$BatchPath,
        [string]$StartAt,
        [switch]$DryRun
    )

    $taskRun = 'C:\Windows\System32\cmd.exe /c ""' + $BatchPath + '""'
    $cmd = "schtasks /Create /TN `"$TaskName`" /TR `"$taskRun`" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $StartAt /F"
    Run-Command -Command $cmd -DryRun:$DryRun
}

function Set-TaskEnabledState {
    param(
        [string]$TaskName,
        [bool]$Enable,
        [switch]$DryRun
    )
    $action = if ($Enable) { "/ENABLE" } else { "/DISABLE" }
    $cmd = "schtasks /Change /TN `"$TaskName`" $action"
    Run-Command -Command $cmd -DryRun:$DryRun
}

$dailyTask = Join-TaskName -Root $TaskRoot -Name $DailyTaskName
$backfillTask = Join-TaskName -Root $TaskRoot -Name $BackfillTaskName

Write-Host "[INFO] upsert daily task: $dailyTask"
Upsert-Task -TaskName $dailyTask -BatchPath $DailyBatchPath -StartAt $DailyStartTime -DryRun:$WhatIf

Write-Host "[INFO] keep daily task enabled (toggle script controls seasonal enable/disable)"
Set-TaskEnabledState -TaskName $dailyTask -Enable $true -DryRun:$WhatIf

if ($CreateBackfillTask) {
    Write-Host "[INFO] upsert backfill task: $backfillTask"
    Upsert-Task -TaskName $backfillTask -BatchPath $BackfillBatchPath -StartAt $BackfillStartTime -DryRun:$WhatIf

    Write-Host "[INFO] disable backfill task by default"
    Set-TaskEnabledState -TaskName $backfillTask -Enable $false -DryRun:$WhatIf
}

Write-Host "[INFO] done"
