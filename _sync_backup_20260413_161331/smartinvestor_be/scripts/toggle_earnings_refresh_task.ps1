param(
    [string]$TaskName = "\BASF\ML\UAT\Valuation Earnings Refresh",
    [string]$BatchPath = "C:\Users\HANJ29\Development\web\UAT\smartinvestor_be\earnings_refresh.bat",
    [string]$StartTime = "22:00",
    [datetime]$AsOfDate = (Get-Date),
    [switch]$CreateIfMissing,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

# Disclosure windows (inclusive) in MM-dd format.
$windowPairs = @(
    @{ Start = "01-15"; End = "03-10" }, # earnings express
    @{ Start = "03-01"; End = "05-05" }, # annual report
    @{ Start = "04-01"; End = "05-10" }, # Q1 report
    @{ Start = "07-15"; End = "09-05" }, # H1 report
    @{ Start = "10-10"; End = "11-05" }  # Q3 report
)

function Get-WindowDate {
    param(
        [int]$Year,
        [string]$MonthDay
    )
    return [datetime]::ParseExact(
        "$Year-$MonthDay",
        "yyyy-MM-dd",
        [System.Globalization.CultureInfo]::InvariantCulture
    )
}

function Test-InDisclosureWindow {
    param([datetime]$Date)

    $dateOnly = $Date.Date
    $year = $dateOnly.Year

    foreach ($w in $windowPairs) {
        $startDate = Get-WindowDate -Year $year -MonthDay $w.Start
        $endDate = Get-WindowDate -Year $year -MonthDay $w.End

        if ($dateOnly -ge $startDate -and $dateOnly -le $endDate) {
            return $true
        }
    }

    return $false
}

function Test-TaskExists {
    param([string]$Name)

    cmd /c "schtasks /Query /TN `"$Name`" >nul 2>nul"
    return ($LASTEXITCODE -eq 0)
}

function New-Task {
    param(
        [string]$Name,
        [string]$Batch,
        [string]$StartAt,
        [switch]$DryRun
    )

    $taskRun = "C:\Windows\System32\cmd.exe /c $Batch"
    $cmd = "schtasks /Create /TN `"$Name`" /TR `"$taskRun`" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $StartAt /F"

    if ($DryRun) {
        Write-Host "[WHATIF] $cmd"
        return
    }

    Invoke-Expression $cmd
}

function Set-TaskEnabledState {
    param(
        [string]$Name,
        [bool]$Enable,
        [switch]$DryRun
    )

    $action = if ($Enable) { "/ENABLE" } else { "/DISABLE" }
    $cmd = "schtasks /Change /TN `"$Name`" $action"

    if ($DryRun) {
        Write-Host "[WHATIF] $cmd"
        return
    }

    Invoke-Expression $cmd
}

$inWindow = Test-InDisclosureWindow -Date $AsOfDate
Write-Host "[INFO] as_of_date=$($AsOfDate.ToString('yyyy-MM-dd')), in_disclosure_window=$inWindow"

$taskExists = Test-TaskExists -Name $TaskName
if (-not $taskExists) {
    if ($CreateIfMissing) {
        Write-Host "[INFO] task not found, creating: $TaskName"
        New-Task -Name $TaskName -Batch $BatchPath -StartAt $StartTime -DryRun:$WhatIf
        $taskExists = $true
    } else {
        Write-Host "[WARN] task not found: $TaskName"
        Write-Host "[WARN] rerun with -CreateIfMissing to auto-create"
        exit 1
    }
}

if ($taskExists) {
    if ($inWindow) {
        Write-Host "[INFO] enable task for disclosure window"
        Set-TaskEnabledState -Name $TaskName -Enable $true -DryRun:$WhatIf
    } else {
        Write-Host "[INFO] disable task outside disclosure window"
        Set-TaskEnabledState -Name $TaskName -Enable $false -DryRun:$WhatIf
    }
}

Write-Host "[INFO] done"
