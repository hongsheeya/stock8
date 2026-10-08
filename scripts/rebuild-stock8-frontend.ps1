param(
    [string]$RuntimeRoot = "C:\stock8-runtime2\app"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$wizPath = Join-Path $projectRoot ".venv\Scripts\wiz.exe"
$distRoot = Join-Path $projectRoot "build\dist\build"
$buildSourceRoot = Join-Path $projectRoot "build\src"
$bundleRoot = Join-Path $projectRoot "bundle\www"
$bundleSourceRoot = Join-Path $projectRoot "bundle\src"
$buildStamp = Join-Path $projectRoot "bundle\.stock8-build-stamp"
$distMain = Join-Path $distRoot "main.js"
$bundleMain = Join-Path $bundleRoot "main.js"

if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Python was not found: $pythonPath" }
if (-not (Test-Path -LiteralPath $wizPath)) { throw "WIZ was not found: $wizPath" }
if (-not (Test-Path -LiteralPath $RuntimeRoot)) { throw "WIZ runtime was not found: $RuntimeRoot" }

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    $bundledNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    if (Test-Path -LiteralPath $bundledNode) {
        $env:PATH = "$(Split-Path -Parent $bundledNode);$env:PATH"
    }
    else {
        throw "Node.js was not found. Frontend bundle cannot be rebuilt."
    }
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$buildStarted = Get-Date

Push-Location $RuntimeRoot
$previousBuildOnly = $env:STOCK8_BUILD_ONLY
try {
    $env:STOCK8_BUILD_ONLY = "1"
    & $pythonPath $wizPath project build main
}
finally {
    $env:STOCK8_BUILD_ONLY = $previousBuildOnly
    Pop-Location
}

# WIZ can return exit code 0 even when its nested Node build failed. Validate
# the actual artifact instead of trusting only the process exit code.
if (-not (Test-Path -LiteralPath $distMain)) {
    throw "WIZ build did not create $distMain"
}
if (-not (Test-Path -LiteralPath $buildSourceRoot)) {
    throw "WIZ build did not create $buildSourceRoot"
}
$distInfo = Get-Item -LiteralPath $distMain
if ($distInfo.LastWriteTime -lt $buildStarted.AddSeconds(-2) -or $distInfo.Length -lt 100000) {
    throw "WIZ returned without producing a fresh frontend bundle."
}

New-Item -ItemType Directory -Path $bundleRoot -Force | Out-Null
Copy-Item -Path (Join-Path $distRoot "*") -Destination $bundleRoot -Recurse -Force

# WIZ serves Python APIs and models from bundle/src, not directly from src.
# Keeping only bundle/www fresh produces the misleading state where the UI is
# current but the worker continues to run yesterday's trading engine.
New-Item -ItemType Directory -Path $bundleSourceRoot -Force | Out-Null
Copy-Item -Path (Join-Path $buildSourceRoot "*") -Destination $bundleSourceRoot -Recurse -Force

$version = Get-Date -Format "yyyyMMdd-HHmmss"
$indexPath = Join-Path $bundleRoot "index.html"
$html = Get-Content -Raw -LiteralPath $indexPath
$html = [regex]::Replace($html, 'href="main\.css(?:\?v=[^"]*)?"', "href=`"main.css?v=$version`"")
$html = [regex]::Replace($html, 'src="vendor\.js(?:\?v=[^"]*)?"', "src=`"vendor.js?v=$version`"")
$html = [regex]::Replace($html, 'src="main\.js(?:\?v=[^"]*)?"', "src=`"main.js?v=$version`"")
$html = [regex]::Replace($html, 'data-version="[^"]*"', "data-version=`"$version`"")
Set-Content -LiteralPath $indexPath -Value $html -Encoding utf8NoBOM -NoNewline

if (-not (Test-Path -LiteralPath $bundleMain)) {
    throw "Frontend deploy did not create $bundleMain"
}

Set-Content -LiteralPath $buildStamp -Value $version -Encoding ascii -NoNewline

Write-Output "Frontend and backend bundles rebuilt and deployed: main.js?v=$version"
