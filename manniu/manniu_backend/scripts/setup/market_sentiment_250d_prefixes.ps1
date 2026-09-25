param(
    [int]$Days = 365,
    [string]$StartDate = '',
    [string]$EndDate = '',
    [string]$EngineVersion = 'sentiment_v1',
    [ValidateSet('BOTH', 'STOCK', 'MARKET')]
    [string]$Scope = 'BOTH',
    [int]$ChunkSize = 300,
    [int]$StartBatch = 1
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$PythonExe = 'C:\Users\HANJ29\Development\web\UAT\.venv\Scripts\python.exe'

if (-not (Test-Path $PythonExe)) {
    throw "UAT virtual environment Python was not found: $PythonExe"
}

Set-Location $ProjectRoot

if ($Days -lt 1) {
    throw 'Days must be greater than 0.'
}
if ($ChunkSize -lt 1) {
    throw 'ChunkSize must be greater than 0.'
}
if ($StartBatch -lt 1) {
    throw 'StartBatch must be at least 1.'
}

if ([bool]$StartDate -ne [bool]$EndDate) {
    throw 'StartDate and EndDate must be provided together.'
}

if ($StartDate -and $EndDate) {
    $dateFormats = [string[]]@('yyyyMMdd', 'yyyy-MM-dd')
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $dateStyles = [Globalization.DateTimeStyles]::None
    $ResolvedStartDate = [datetime]::MinValue
    $ResolvedEndDate = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($StartDate, $dateFormats, $culture, $dateStyles, [ref]$ResolvedStartDate)) {
        throw 'StartDate must use YYYYMMDD or YYYY-MM-DD.'
    }
    if (-not [datetime]::TryParseExact($EndDate, $dateFormats, $culture, $dateStyles, [ref]$ResolvedEndDate)) {
        throw 'EndDate must use YYYYMMDD or YYYY-MM-DD.'
    }
    if ($ResolvedStartDate -gt $ResolvedEndDate) {
        throw 'StartDate cannot be after EndDate.'
    }
}
else {
    # Use the last completed calendar day so an in-progress EOD cannot enter the run.
    $ResolvedEndDate = (Get-Date).Date.AddDays(-1)
    $ResolvedStartDate = $ResolvedEndDate.AddDays( - ($Days - 1))
}

$StartText = $ResolvedStartDate.ToString('yyyyMMdd')
$EndText = $ResolvedEndDate.ToString('yyyyMMdd')

$tsCodes = @()
if ($Scope -in @('BOTH', 'STOCK')) {
    $codeQuery = "from market_data.models import Security; print(','.join(code for code in Security.objects.filter(asset_type='STOCK', list_status__in=['L', '']).values_list('ts_code', flat=True) if code.startswith(('00', '30', '60', '68'))))"
    $codeOutput = & $PythonExe manage.py shell -c $codeQuery --verbosity 0
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to load stock codes from the security master.'
    }

    $tsCodes = @($codeOutput -split ',' | Where-Object { $_ -match '^(00|30|60|68)' } | Sort-Object -Unique)
    if ($tsCodes.Count -eq 0) {
        throw 'No 00/30/60/68 stock codes were found.'
    }

    $batchCount = [Math]::Ceiling($tsCodes.Count / [double]$ChunkSize)
    if ($StartBatch -gt $batchCount) {
        throw "StartBatch must be between 1 and $batchCount."
    }
}
else {
    $batchCount = 0
}

if ($Scope -in @('BOTH', 'STOCK')) {
    Write-Host "Refreshing stock sentiment: $StartText..$EndText, codes=$($tsCodes.Count), batches=$batchCount, start_batch=$StartBatch, engine=$EngineVersion"
    for ($offset = 0; $offset -lt $tsCodes.Count; $offset += $ChunkSize) {
        $batchNumber = [int]($offset / $ChunkSize) + 1
        if ($batchNumber -lt $StartBatch) {
            continue
        }
        $last = [Math]::Min($offset + $ChunkSize - 1, $tsCodes.Count - 1)
        $chunk = @($tsCodes[$offset..$last])
        $chunkText = $chunk -join ','
        Write-Host "Refreshing stock batch $batchNumber/${batchCount}: $($offset + 1)-$($last + 1)/$($tsCodes.Count)"
        & $PythonExe manage.py refresh_market_sentiment --scope STOCK --start-date $StartText --end-date $EndText --ts-codes $chunkText --engine-version $EngineVersion
        if ($LASTEXITCODE -ne 0) {
            throw "Stock sentiment refresh failed for code chunk $($offset + 1)-$($last + 1)."
        }
    }
}

if ($Scope -in @('BOTH', 'MARKET')) {
    Write-Host "Refreshing market sentiment: $StartText..$EndText, engine=$EngineVersion"
    & $PythonExe manage.py refresh_market_sentiment --scope MARKET --start-date $StartText --end-date $EndText --engine-version $EngineVersion
    if ($LASTEXITCODE -ne 0) {
        throw 'Market sentiment refresh failed.'
    }
}

Write-Host "Market sentiment refresh completed: scope=$Scope dates=$StartText..$EndText engine=$EngineVersion"