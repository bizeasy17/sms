param(
    [string]$BaseUrl = "http://127.0.0.1:9100",
    [switch]$WithFeishu
)

$ErrorActionPreference = "Stop"

function Test-Case {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    try {
        & $Action
        Write-Host "[PASS] $Name" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "[FAIL] $Name :: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

$results = @()

$results += Test-Case -Name "Health endpoint" -Action {
    $resp = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health"
    if ($resp.status -ne "ok") {
        throw "expected status=ok, actual=$($resp.status)"
    }
}

$results += Test-Case -Name "NL question with ts_code in message" -Action {
    $payload = @{
        message = "600036.SH now valuation advice"
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/openclaw/valuation/chat" -ContentType "application/json" -Body $payload

    if (-not $resp.skill) { throw "missing skill" }
    if (-not $resp.answer) { throw "missing answer" }
    if (-not $resp.valuation) { throw "missing valuation" }
}

$results += Test-Case -Name "NL question with explicit ts_code field" -Action {
    $payload = @{
        message = "please advise"
        ts_code = "600036.SH"
        freq = "D"
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/openclaw/valuation/chat" -ContentType "application/json" -Body $payload

    if (-not $resp.answer) { throw "missing answer" }
}

$results += Test-Case -Name "Band parsing strict(5%)" -Action {
    $payload = @{
        message = "600036.SH strict mode"
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/openclaw/valuation/chat" -ContentType "application/json" -Body $payload
    $band = [double]$resp.valuation.valuation_band_pct
    if ([Math]::Abs($band - 0.05) -gt 0.0001) {
        throw "expected 0.05, actual=$band"
    }
}

$results += Test-Case -Name "Band parsing explicit 15%" -Action {
    $payload = @{
        message = "600036.SH 15%"
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/openclaw/valuation/chat" -ContentType "application/json" -Body $payload
    $band = [double]$resp.valuation.valuation_band_pct
    if ([Math]::Abs($band - 0.15) -gt 0.0001) {
        throw "expected 0.15, actual=$band"
    }
}

if ($WithFeishu) {
    $results += Test-Case -Name "Feishu forwarding" -Action {
        $payload = @{
            message = "600036.SH send to feishu"
            forward_to_feishu = $true
        } | ConvertTo-Json

        $resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/openclaw/valuation/chat" -ContentType "application/json" -Body $payload
        if ($resp.feishu_forwarded -ne $true) {
            throw "feishu_forwarded is false, error=$($resp.feishu_error)"
        }
    }
}
else {
    Write-Host "[SKIP] Feishu forwarding test (use -WithFeishu to enable)" -ForegroundColor Yellow
}

$passCount = ($results | Where-Object { $_ -eq $true }).Count
$failCount = ($results | Where-Object { $_ -eq $false }).Count

Write-Host ""
Write-Host "Summary: pass=$passCount fail=$failCount" -ForegroundColor Cyan

if ($failCount -gt 0) {
    exit 1
}

exit 0
