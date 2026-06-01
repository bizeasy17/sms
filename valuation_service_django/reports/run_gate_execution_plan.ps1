param(
    [string]$PlanCsv = "c:\Users\HANJ29\Development\code\sms\valuation_service_django\reports\valuation_migration_gate_execution_plan_20260322.csv",
    [string]$ProjectRoot = "c:\Users\HANJ29\Development\code\sms\valuation_service_django",
    [string]$OnlyPhase = "",
    [string]$OnlyGate = "",
    [string]$OnlyStatus = "TODO",
    [switch]$DryRun,
    [switch]$ContinueOnError
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Section($text) {
    Write-Host ""
    Write-Host "========== $text =========="
}

function Ensure-ParentDir($path) {
    $parent = Split-Path -Path $path -Parent
    if (-not (Test-Path -Path $parent)) {
        New-Item -Path $parent -ItemType Directory -Force | Out-Null
    }
}

if (-not (Test-Path -Path $PlanCsv)) {
    throw "Plan CSV not found: $PlanCsv"
}

Write-Section "Load Plan"
$rows = Import-Csv -Path $PlanCsv
if (-not $rows) {
    throw "Plan CSV is empty: $PlanCsv"
}

# Filter: auto steps only
$steps = $rows | Where-Object { $_.step_type -eq "auto" }

if ($OnlyPhase) {
    $steps = $steps | Where-Object { $_.phase -eq $OnlyPhase }
}
if ($OnlyGate) {
    $steps = $steps | Where-Object { $_.gate_id -eq $OnlyGate }
}
if ($OnlyStatus) {
    $steps = $steps | Where-Object { $_.status -eq $OnlyStatus }
}

$steps = $steps | Sort-Object { [int]$_.exec_step }

if (-not $steps) {
    Write-Host "No matching auto steps to execute."
    exit 0
}

Write-Host ("Total auto steps to run: {0}" -f $steps.Count)
Write-Host ("DryRun: {0}" -f [bool]$DryRun)
Write-Host ("ContinueOnError: {0}" -f [bool]$ContinueOnError)

$summary = [System.Collections.Generic.List[object]]::new()

foreach ($step in $steps) {
    $execStep = [int]$step.exec_step
    $name = $step.step_name
    $gate = $step.gate_id
    $phase = $step.phase
    $cmd = [string]$step.run_command
    $evidenceRelative = [string]$step.evidence_output
    $evidencePath = Join-Path $ProjectRoot $evidenceRelative

    Write-Section ("Step {0} | {1} | {2} | {3}" -f $execStep, $phase, $gate, $name)
    Write-Host "Command: $cmd"
    Write-Host "Evidence: $evidencePath"

    Ensure-ParentDir -path $evidencePath

    if ($DryRun) {
        "[DRY RUN] $cmd" | Out-File -FilePath $evidencePath -Encoding UTF8
        $summary.Add([pscustomobject]@{
            exec_step = $execStep
            gate_id = $gate
            phase = $phase
            step_name = $name
            result = "DRY_RUN"
            evidence_output = $evidencePath
        }) | Out-Null
        continue
    }

    $start = Get-Date
    $exitCode = 0
    $result = "PASS"

    try {
        # Use a child powershell process to preserve command semantics from CSV.
        $output = & powershell -NoProfile -ExecutionPolicy Bypass -Command $cmd 2>&1
        $exitCode = $LASTEXITCODE

        "[START] $start" | Out-File -FilePath $evidencePath -Encoding UTF8
        "[COMMAND] $cmd" | Out-File -FilePath $evidencePath -Append -Encoding UTF8
        "[OUTPUT]" | Out-File -FilePath $evidencePath -Append -Encoding UTF8
        $output | Out-File -FilePath $evidencePath -Append -Encoding UTF8
        "[EXIT_CODE] $exitCode" | Out-File -FilePath $evidencePath -Append -Encoding UTF8

        if ($exitCode -ne 0) {
            $result = "FAIL"
        }
    }
    catch {
        $result = "ERROR"
        "[START] $start" | Out-File -FilePath $evidencePath -Encoding UTF8
        "[COMMAND] $cmd" | Out-File -FilePath $evidencePath -Append -Encoding UTF8
        "[ERROR] $($_.Exception.Message)" | Out-File -FilePath $evidencePath -Append -Encoding UTF8
        "[EXIT_CODE] 1" | Out-File -FilePath $evidencePath -Append -Encoding UTF8
        $exitCode = 1
    }

    $summary.Add([pscustomobject]@{
        exec_step = $execStep
        gate_id = $gate
        phase = $phase
        step_name = $name
        result = $result
        exit_code = $exitCode
        evidence_output = $evidencePath
    }) | Out-Null

    Write-Host ("Result: {0} (exit={1})" -f $result, $exitCode)

    if (($result -ne "PASS") -and (-not $ContinueOnError)) {
        Write-Host "Execution stopped on first failure. Use -ContinueOnError to keep running."
        break
    }
}

Write-Section "Summary"
$summary | Format-Table -AutoSize

$summaryPath = Join-Path $ProjectRoot "reports\exec_logs\execution_summary_20260322.csv"
$summary | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8
Write-Host "Summary CSV: $summaryPath"
