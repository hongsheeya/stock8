param(
    [string]$RuntimeRoot = "C:\stock8-runtime2\app",
    [int]$Port = 3002,
    [int]$RestartDelaySeconds = 10
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$wizPath = Join-Path $projectRoot ".venv\Scripts\wiz.exe"
$runtimeLogRoot = Join-Path $projectRoot "data\runtime-logs"
$serverLog = Join-Path $runtimeLogRoot "stock8-paper"
$supervisorLog = Join-Path $runtimeLogRoot "supervisor.log"
$frontendBuilder = Join-Path $PSScriptRoot "rebuild-stock8-frontend.ps1"
$projectSourceRoot = Join-Path $projectRoot "src"
$buildStamp = Join-Path $projectRoot "bundle\.stock8-build-stamp"

if (-not (Test-Path -LiteralPath $wizPath)) {
    throw "WIZ executable was not found: $wizPath"
}

if (-not (Test-Path -LiteralPath $RuntimeRoot)) {
    throw "WIZ runtime was not found: $RuntimeRoot"
}

New-Item -ItemType Directory -Path $runtimeLogRoot -Force | Out-Null

function Write-SupervisorLog([string]$Message) {
    Add-Content -LiteralPath $supervisorLog -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}

function Test-ProjectRebuildRequired {
    if (-not (Test-Path -LiteralPath $buildStamp)) { return $true }
    $bundleTime = (Get-Item -LiteralPath $buildStamp).LastWriteTimeUtc
    $newer = Get-ChildItem -LiteralPath $projectSourceRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".py", ".ts", ".scss", ".pug", ".html", ".json") -and $_.LastWriteTimeUtc -gt $bundleTime } |
        Select-Object -First 1
    return $null -ne $newer
}

# This local supervisor is deliberately locked to the KIS PAPER database.
$env:TRADING_MODE = "PAPER"
$env:STOCK8_PAPER_DB_PATH = "project/main/data/paper/trading.db"
$env:STOCK8_LIVE_DB_PATH = "project/main/data/live/trading.db"
$env:STOCK8_LIVE_ORIGIN = "http://127.0.0.1:3001"
$env:STOCK8_PAPER_ORIGIN = "http://127.0.0.1:$Port"
$env:STOCK8_DAYTRADE_HARD_LOCK = "false"
# Keep every PAPER feature available, but submit broker orders only during the
# actual exchange session. Continuous mode is useful for UI research, not for
# an unattended market-open run because KIS rejects off-hours paper orders.
$env:STOCK8_PAPER_CONTINUOUS = "false"
$env:WIZ_DB_MAX_CONCURRENCY = "4"
$env:TZ = "Asia/Seoul"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
# curl-cffi (used by yfinance) cannot reliably open a CA bundle from this
# project's Korean Windows path. Keep the bundle under the ASCII runtime root
# so live minute bars do not silently fall back during trigger evaluation.
$env:CURL_CA_BUNDLE = "C:\stock8-runtime2\certs\cacert.pem"
$env:REQUESTS_CA_BUNDLE = "C:\stock8-runtime2\certs\cacert.pem"
$env:PORT = [string]$Port

Write-SupervisorLog "Supervisor started in PAPER mode."

while ($true) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Start-Sleep -Seconds 15
        continue
    }

    if ((Test-Path -LiteralPath $frontendBuilder) -and (Test-ProjectRebuildRequired)) {
        Write-SupervisorLog "Project source is newer than runtime bundle; rebuilding frontend and backend before server start."
        try {
            & $frontendBuilder -RuntimeRoot $RuntimeRoot | ForEach-Object { Write-SupervisorLog $_ }
        }
        catch {
            Write-SupervisorLog ("Project rebuild failed: " + $_.Exception.Message)
        }
    }

    Write-SupervisorLog "Starting WIZ server."
    Push-Location $RuntimeRoot
    try {
        & $wizPath run "--host=127.0.0.1" "--port=$Port" "--log=$serverLog"
        Write-SupervisorLog "WIZ server process exited with code $LASTEXITCODE."
    }
    catch {
        Write-SupervisorLog ("WIZ server failed: " + $_.Exception.Message)
    }
    finally {
        Pop-Location
    }

    Start-Sleep -Seconds $RestartDelaySeconds
}
