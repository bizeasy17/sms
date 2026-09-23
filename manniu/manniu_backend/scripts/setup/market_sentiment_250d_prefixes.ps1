param(
    [int]$Days = 365,
    [string]$EngineVersion = 'sentiment_v1',
    [int]$ChunkSize = 300
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$PythonExe = 'C:\Users\HANJ29\Development\web\UAT\.venv\Scripts\python.exe'

if (-not (Test-Path $PythonExe)) {
    throw "UAT virtual environment Python was not found: $PythonExe"
}

Set-Location $ProjectRoot

# Use the last completed calendar day so an in-progress EOD cannot enter the run.
$EndDate = (Get-Date).Date.AddDays(-1)
$StartDate = $EndDate.AddDays( - ($Days - 1))
$StartText = $StartDate.ToString('yyyyMMdd')
$EndText = $EndDate.ToString('yyyyMMdd')

$codeQuery = "from market_data.models import Security; print(','.join(code for code in Security.objects.filter(asset_type='STOCK', list_status__in=['L', '']).values_list('ts_code', flat=True) if code.startswith(('00', '30', '60', '68'))))"
$codeOutput = & $PythonExe manage.py shell -c $codeQuery --verbosity 0
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to load stock codes from the security master.'
}

$tsCodes = @($codeOutput -split ',' | Where-Object { $_ -match '^(00|30|60|68)' } | Sort-Object -Unique)
if ($tsCodes.Count -eq 0) {
    throw 'No 00/30/60/68 stock codes were found.'
}

Write-Host "Refreshing stock sentiment: $StartText..$EndText, codes=$($tsCodes.Count), engine=$EngineVersion"
for ($offset = 0; $offset -lt $tsCodes.Count; $offset += $ChunkSize) {
    $last = [Math]::Min($offset + $ChunkSize - 1, $tsCodes.Count - 1)
    $chunk = @($tsCodes[$offset..$last])
    $chunkText = $chunk -join ','
    Write-Host "Refreshing stock batch: $($offset + 1)-$($last + 1)/$($tsCodes.Count)"
    & $PythonExe manage.py refresh_market_sentiment --scope STOCK --start-date $StartText --end-date $EndText --ts-codes $chunkText --engine-version $EngineVersion
    if ($LASTEXITCODE -ne 0) {
        throw "Stock sentiment refresh failed for code chunk $($offset + 1)-$($last + 1)."
    }
}

Write-Host "Refreshing market sentiment: $StartText..$EndText, engine=$EngineVersion"
& $PythonExe manage.py refresh_market_sentiment --scope MARKET --start-date $StartText --end-date $EndText --engine-version $EngineVersion
if ($LASTEXITCODE -ne 0) {
    throw 'Market sentiment refresh failed.'
}

Write-Host 'Market sentiment refresh completed.'