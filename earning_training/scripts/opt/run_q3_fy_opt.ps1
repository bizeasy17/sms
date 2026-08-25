param(
    [string]$Python = "c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe",
    [string]$RunTag = (Get-Date -Format "yyyyMMdd_HHmmss"),
    [ValidateRange(1, 256)]
    [int]$LokyMaxCpuCount = 12,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$Runner = Join-Path $PSScriptRoot "run_parameter_sweep.py"
$PreviousLokyMaxCpuCount = $env:LOKY_MAX_CPU_COUNT
$env:LOKY_MAX_CPU_COUNT = $LokyMaxCpuCount.ToString()

function Invoke-Sweep {
    param([string[]]$Arguments)

    if ($DryRun) {
        $Arguments += "--dry-run"
    }
    & $Python $Runner @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Optimization sweep failed with exit code $LASTEXITCODE"
    }
}

Push-Location $ProjectRoot
try {
    Invoke-Sweep -Arguments @(
        "--report-type", "Q3",
        "--base-config", "configs/default.q3_opt_v2.yaml",
        "--baseline-config", "configs/default.fyq3_opt_v1.yaml",
        "--baseline-model", "dev_20260331_r3_15y",
        "--parameter", "train.sample_weight.time_decay.half_life_years",
        "--values", "3.0", "5.0", "7.0",
        "--top-pct", "0.10",
        "--name", "q3_time_decay",
        "--python", $Python,
        "--run-tag", $RunTag
    )

    Invoke-Sweep -Arguments @(
        "--report-type", "FY",
        "--base-config", "configs/default.fy_opt_v2.yaml",
        "--baseline-config", "configs/default.fyq3_opt_v1.yaml",
        "--baseline-model", "dev_20260331_r3_15y",
        "--parameter", "train.sample_weight.time_decay.half_life_years",
        "--values", "6.0", "8.0", "10.0",
        "--set", "label.exclude_fy_rows_for_training=false",
        "--top-pct", "0.10",
        "--name", "fy_time_decay",
        "--python", $Python,
        "--run-tag", $RunTag
    )
}
finally {
    Pop-Location
    if ($null -eq $PreviousLokyMaxCpuCount) {
        Remove-Item Env:LOKY_MAX_CPU_COUNT -ErrorAction SilentlyContinue
    }
    else {
        $env:LOKY_MAX_CPU_COUNT = $PreviousLokyMaxCpuCount
    }
}
