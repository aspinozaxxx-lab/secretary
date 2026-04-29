param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if (-not $SkipInstall) {
    py -3.11 -m pip install -r requirements.txt
}

py -3.11 -m PyInstaller --noconfirm --clean SecretaryBot.spec

$Exe = Join-Path $Root "dist\SecretaryBot\SecretaryBot.exe"
if (-not (Test-Path $Exe)) {
    throw "SecretaryBot.exe was not created: $Exe"
}

Write-Host "Built $Exe"
