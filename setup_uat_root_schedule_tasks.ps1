param(
    [string]$TaskRoot = "\BASF\ML\Valuation",
    [string]$DailyTaskName = "UAT Daily Pipeline",
    [string]$WeeklyTaskName = "UAT Weekly Pipeline",
    [string]$MonthlyTaskName = "UAT Monthly Pipeline",
    [string]$QuarterlyTaskName = "UAT Quarterly Pipeline",
    [string]$DailyBatchPath = "C:\Users\HANJ29\Development\web\UAT\daily.bat",
    [string]$WeeklyBatchPath = "C:\Users\HANJ29\Development\web\UAT\weekly.bat",
    [string]$MonthlyBatchPath = "C:\Users\HANJ29\Development\web\UAT\monthly.bat",
    [string]$QuarterlyBatchPath = "C:\Users\HANJ29\Development\web\UAT\quarterly.bat",
    [string]$DailyStartTime = "21:30",
    [string]$WeeklyStartTime = "21:30",
    [string]$MonthlyStartTime = "21:30",
    [string]$QuarterlyStartTime = "21:30",
    [string]$WeeklyDays = "FRI",
    [int]$MonthlyDay = 1,
    [int]$QuarterlyMonthInterval = 3,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Join-TaskName {
    param(
        [string]$Root,
        [string]$Name
    )
    $rootNorm = ($Root -replace "/", "\").Trim().Trim("\")
    return "\$rootNorm\$Name"
}

function Ensure-PathExists {
    param([string]$Path)
    if (!(Test-Path $Path)) {
        throw "Batch file not found: $Path"
    }
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
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Command"
    }
}

function Upsert-DailyTask {
    param(
        [string]$TaskName,
        [string]$BatchPath,
        [string]$StartAt,
        [switch]$DryRun
    )
    $taskRun = 'C:\Windows\System32\cmd.exe /c ""' + $BatchPath + '""'
    $cmd = "schtasks /Create /TN `"$TaskName`" /TR `"$taskRun`" /SC DAILY /ST $StartAt /F"
    Run-Command -Command $cmd -DryRun:$DryRun
}

function Upsert-WeeklyTask {
    param(
        [string]$TaskName,
        [string]$BatchPath,
        [string]$StartAt,
        [string]$Days,
        [switch]$DryRun
    )
    $taskRun = 'C:\Windows\System32\cmd.exe /c ""' + $BatchPath + '""'
    $cmd = "schtasks /Create /TN `"$TaskName`" /TR `"$taskRun`" /SC WEEKLY /D $Days /ST $StartAt /F"
    Run-Command -Command $cmd -DryRun:$DryRun
}

function Upsert-MonthlyTask {
    param(
        [string]$TaskName,
        [string]$BatchPath,
        [string]$StartAt,
        [int]$Day,
        [switch]$DryRun
    )
    $taskRun = 'C:\Windows\System32\cmd.exe /c ""' + $BatchPath + '""'
    $cmd = "schtasks /Create /TN `"$TaskName`" /TR `"$taskRun`" /SC MONTHLY /D $Day /ST $StartAt /F"
    Run-Command -Command $cmd -DryRun:$DryRun
}

function Upsert-QuarterlyTask {
    param(
        [string]$TaskName,
        [string]$BatchPath,
        [string]$StartAt,
        [int]$MonthInterval,
        [int]$Day,
        [switch]$DryRun
    )
    $taskRun = 'C:\Windows\System32\cmd.exe /c ""' + $BatchPath + '""'
    $cmd = "schtasks /Create /TN `"$TaskName`" /TR `"$taskRun`" /SC MONTHLY /MO $MonthInterval /D $Day /ST $StartAt /F"
    Run-Command -Command $cmd -DryRun:$DryRun
}

Ensure-PathExists -Path $DailyBatchPath
Ensure-PathExists -Path $WeeklyBatchPath
Ensure-PathExists -Path $MonthlyBatchPath
Ensure-PathExists -Path $QuarterlyBatchPath

$dailyTask = Join-TaskName -Root $TaskRoot -Name $DailyTaskName
$weeklyTask = Join-TaskName -Root $TaskRoot -Name $WeeklyTaskName
$monthlyTask = Join-TaskName -Root $TaskRoot -Name $MonthlyTaskName
$quarterlyTask = Join-TaskName -Root $TaskRoot -Name $QuarterlyTaskName

Write-Host "[INFO] upsert daily task: $dailyTask"
Upsert-DailyTask -TaskName $dailyTask -BatchPath $DailyBatchPath -StartAt $DailyStartTime -DryRun:$WhatIf

Write-Host "[INFO] upsert weekly task: $weeklyTask"
Upsert-WeeklyTask -TaskName $weeklyTask -BatchPath $WeeklyBatchPath -StartAt $WeeklyStartTime -Days $WeeklyDays -DryRun:$WhatIf

Write-Host "[INFO] upsert monthly task: $monthlyTask"
Upsert-MonthlyTask -TaskName $monthlyTask -BatchPath $MonthlyBatchPath -StartAt $MonthlyStartTime -Day $MonthlyDay -DryRun:$WhatIf

Write-Host "[INFO] upsert quarterly task: $quarterlyTask"
Upsert-QuarterlyTask -TaskName $quarterlyTask -BatchPath $QuarterlyBatchPath -StartAt $QuarterlyStartTime -MonthInterval $QuarterlyMonthInterval -Day $MonthlyDay -DryRun:$WhatIf

Write-Host "[INFO] done"