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
        "--report-type", "Q1",
        "--base-config", "configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold.yaml",
        "--baseline-model", "uat_20260719_q1_p1_f3_grayzone_threshold",
        "--parameter", "label.cls_gray_zone.abs_min",
        "--values", "0.06", "0.07", "0.08", "0.09",
        "--top-pct", "0.08",
        "--name", "q1_gray_zone",
        "--python", $Python,
        "--run-tag", $RunTag
    )

    Invoke-Sweep -Arguments @(
        "--report-type", "H1",
        "--base-config", "configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2_uat_ocf_fix_f3_grayzone_threshold.yaml",
        "--baseline-config", "configs/default.h1_opt_exp_r1_cls_a_oos2024_fy2_uat_ocf_fix.yaml",
        "--baseline-model", "uat_20260718_h1_ocf_fix",
        "--parameter", "label.cls_gray_zone.abs_min",
        "--values", "0.04", "0.06", "0.08", "0.10",
        "--top-pct", "0.10",
        "--name", "h1_gray_zone",
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
