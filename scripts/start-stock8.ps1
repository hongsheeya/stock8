# Existing Windows startup task calls this launcher. Account supervisors retain
# separate environment variables and databases; starting a server is not consent.
$ErrorActionPreference = 'Stop'
$stock8Children = @()
foreach ($stock8Name in @('start-stock8-live.ps1', 'start-stock8-paper.ps1')) {
    $stock8Script = Join-Path $PSScriptRoot $stock8Name
    $stock8Children += Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
        '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $stock8Script + '"'))
}
$stock8Children | Wait-Process
