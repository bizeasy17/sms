param(
    [string]$BaseUrl = "http://127.0.0.1:9200",
    [switch]$ShowAnswer,
    [string]$OutputFile = "output/alias_regression_answers.txt"
)

$ErrorActionPreference = "Stop"

function Convert-BodyToObject {
    param(
        [string]$Uri,
        [string]$Body
    )

    $resp = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $Uri -ContentType "application/json" -Body $Body
    $ms = New-Object System.IO.MemoryStream
    $resp.RawContentStream.CopyTo($ms)
    $text = [System.Text.Encoding]::UTF8.GetString($ms.ToArray())
    return ($text | ConvertFrom-Json)
}

$cases = @(
    @{ label = "zhaohang"; msg = "\u7ed9\u6211\u62db\u884c\u7684\u4f30\u503c" },
    @{ label = "maotai"; msg = "\u7ed9\u6211\u8305\u53f0\u7684\u4f30\u503c" },
    @{ label = "pingan"; msg = "\u7ed9\u6211\u5e73\u5b89\u7684\u4f30\u503c" },
    @{ label = "wanke"; msg = "\u7ed9\u6211\u4e07\u79d1\u7684\u4f30\u503c" },
    @{ label = "zhonglian"; msg = "\u7ed9\u6211\u4e2d\u8054\u7684\u4f30\u503c" }
)

$uri = "$BaseUrl/api/openclaw/valuation/chat/"
$results = @()

$outputLines = @()
if ($ShowAnswer) {
    $outputDir = Split-Path -Parent $OutputFile
    if ($outputDir -and -not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
}

foreach ($c in $cases) {
    $body = '{"message":"' + $c.msg + '"}'
    try {
        $obj = Convert-BodyToObject -Uri $uri -Body $body
        $answer = [string]($obj.answer)
        $answerHead = if ($answer) { ($answer -split "`n")[0] } else { "" }

        $results += [PSCustomObject]@{
            case_label = $c.label
            resolved = [string]$obj.resolved_ts_code
            need_clarification = [bool]$obj.need_clarification
            answer_head = $answerHead
        }

        if ($ShowAnswer) {
            "`n===== " + $c.label + " ====="
            $answer
            $outputLines += "===== " + $c.label + " ====="
            $outputLines += $answer
            $outputLines += ""
        }
    }
    catch {
        $results += [PSCustomObject]@{
            case_label = $c.label
            resolved = ""
            need_clarification = $false
            answer_head = "ERROR: " + $_.Exception.Message
        }
    }
}

$results | Format-Table -AutoSize

if ($ShowAnswer) {
    $outputLines | Set-Content -Path $OutputFile -Encoding utf8
    "Saved answers to: " + $OutputFile
}
