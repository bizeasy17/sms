param(
    [string]$BaseUrl = "http://127.0.0.1:9200",
    [string]$Token = "demo-u001-token",
    [string]$WatchlistName = "OpenClaw Regression List",
    [string]$OutputFile = "output/openclaw_product_regression.json"
)

$ErrorActionPreference = "Stop"

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Uri,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )

    if ($Body -ne $null) {
        $jsonBody = $Body | ConvertTo-Json -Depth 10 -Compress
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers -ContentType "application/json" -Body $jsonBody
    }

    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers
}

$headers = @{
    Authorization = "Bearer $Token"
    "X-Request-Id" = ("reg-" + [Guid]::NewGuid().ToString("N"))
}

$result = [ordered]@{
    request_id = $headers["X-Request-Id"]
    watchlist = @{}
    batch = @{}
    report = @{}
    alerts = @{}
}

$watchlistsUri = "$BaseUrl/api/openclaw/watchlists/"
$batchUri = "$BaseUrl/api/openclaw/valuation/batch/"
$alertsRulesUri = "$BaseUrl/api/openclaw/alerts/rules/"
$alertsEvaluateUri = "$BaseUrl/api/openclaw/alerts/evaluate/"

# 1) upsert watchlist
$watchlistResp = Invoke-Json -Method Post -Uri $watchlistsUri -Body @{ name = $WatchlistName; is_default = $true } -Headers $headers
$watchlistId = [int]$watchlistResp.watchlist.id
$result.watchlist.id = $watchlistId
$result.watchlist.name = [string]$watchlistResp.watchlist.name
$result.watchlist.created = [bool]$watchlistResp.created

# 2) add items
$itemsUri = "$BaseUrl/api/openclaw/watchlists/$watchlistId/items/"
$null = Invoke-Json -Method Post -Uri $itemsUri -Body @{ ts_code = "600036.SH"; note = "bank" } -Headers $headers
$null = Invoke-Json -Method Post -Uri $itemsUri -Body @{ ts_code = "600519.SH"; note = "liquor" } -Headers $headers
$null = Invoke-Json -Method Post -Uri $itemsUri -Body @{ ts_code = "000001.SZ"; note = "bank" } -Headers $headers

# 3) list watchlists for validation
$watchlistListResp = Invoke-Json -Method Get -Uri $watchlistsUri -Headers $headers
$targetList = @($watchlistListResp.watchlists | Where-Object { [int]$_.id -eq $watchlistId })
$result.watchlist.item_count = if ($targetList.Count -gt 0) { @($targetList[0].items).Count } else { 0 }

# 4) batch compare
$batchResp = Invoke-Json -Method Post -Uri $batchUri -Body @{ ts_codes = @("600036.SH", "600519.SH", "000001.SZ"); freq = "D" } -Headers $headers
$result.batch.count = @($batchResp.results).Count
$result.batch.ts_codes = @($batchResp.results | ForEach-Object { $_.ts_code })

# 5) daily report (no feishu forwarding)
$reportUri = "$BaseUrl/api/openclaw/watchlists/$watchlistId/daily-report/"
$reportResp = Invoke-Json -Method Post -Uri $reportUri -Body @{ forward_to_feishu = $false } -Headers $headers
$result.report.rows = @($reportResp.rows).Count
$result.report.feishu_forwarded = [bool]$reportResp.feishu_forwarded

# 6) upsert alert rules
$null = Invoke-Json -Method Post -Uri $alertsRulesUri -Body @{ ts_code = "600036.SH"; discount_threshold_pct = 5; method_dispersion_threshold_pct = 20; change_threshold_pct = 3; enabled = $true } -Headers $headers
$null = Invoke-Json -Method Post -Uri $alertsRulesUri -Body @{ ts_code = "600519.SH"; discount_threshold_pct = 5; method_dispersion_threshold_pct = 20; change_threshold_pct = 3; enabled = $true } -Headers $headers

$rulesResp = Invoke-Json -Method Get -Uri $alertsRulesUri -Headers $headers
$result.alerts.rule_count = @($rulesResp.rules).Count

# 7) evaluate alerts
$evalResp = Invoke-Json -Method Post -Uri $alertsEvaluateUri -Body @{ freq = "D" } -Headers $headers
$result.alerts.triggered_count = [int]$evalResp.count
$result.alerts.triggered_ts_codes = @($evalResp.alerts | ForEach-Object { $_.ts_code })

$outputDir = Split-Path -Parent $OutputFile
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

($result | ConvertTo-Json -Depth 8) | Set-Content -Path $OutputFile -Encoding utf8
Write-Host "OpenClaw product regression finished."
Write-Host "Request-Id: $($result.request_id)"
Write-Host "WatchlistId: $watchlistId"
Write-Host "Saved report: $OutputFile"
