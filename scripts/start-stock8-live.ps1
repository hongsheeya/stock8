param(
    [string]$RuntimeRoot = "C:\stock8-runtime2\app",
    [int]$Port = 3001
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$wizPath = Join-Path $projectRoot ".venv\Scripts\wiz.exe"
$runtimeLogRoot = Join-Path $projectRoot "data\runtime-logs"
if (-not (Test-Path -LiteralPath $wizPath) -or -not (Test-Path -LiteralPath $RuntimeRoot)) {
    throw "Stock8 runtime is missing"
}
New-Item -ItemType Directory -Path $runtimeLogRoot -Force | Out-Null
$env:TRADING_MODE = "LIVE"
$env:STOCK8_LIVE_DB_PATH = "project/main/data/live/trading.db"
$env:STOCK8_PAPER_DB_PATH = "project/main/data/paper/trading.db"
$env:STOCK8_LIVE_ORIGIN = "http://127.0.0.1:$Port"
$env:STOCK8_PAPER_ORIGIN = "http://127.0.0.1:3002"
# Legacy environment unlock is not consent. New account/strategy policies
# default OFF and require a user-confirmed setting plus an unlocked symbol.
$env:STOCK8_LIVE_TRADING_UNLOCK = ""
$env:STOCK8_DAYTRADE_HARD_LOCK = "false"
$env:WIZ_DB_MAX_CONCURRENCY = "4"
$env:TZ = "Asia/Seoul"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:CURL_CA_BUNDLE = "C:\stock8-runtime2\certs\cacert.pem"
$env:REQUESTS_CA_BUNDLE = "C:\stock8-runtime2\certs\cacert.pem"
$env:PORT = [string]$Port
while ($true) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Start-Sleep -Seconds 15
        continue
    }
    Push-Location $RuntimeRoot
    try {
        & $wizPath run "--host=127.0.0.1" "--port=$Port" "--log=$(Join-Path $runtimeLogRoot 'stock8-live')"
    } finally { Pop-Location }
    Start-Sleep -Seconds 10
}
