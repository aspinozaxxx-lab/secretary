param(
    [string]$DeployPath = "E:\Projects\secretary-exe",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Dist = Join-Path $Root "dist\SecretaryBot"

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build.ps1")
}

if (-not (Test-Path $Dist)) {
    throw "Build output not found: $Dist"
}

New-Item -ItemType Directory -Force -Path $DeployPath | Out-Null

$RuntimeFiles = @("config.yaml", "context.md", "state.json")
$RuntimeDirs = @("logs", "chat_archive")

foreach ($File in $RuntimeFiles) {
    $Path = Join-Path $DeployPath $File
    if (Test-Path $Path) {
        Write-Host "Preserving runtime file: $File"
    }
}
foreach ($Dir in $RuntimeDirs) {
    $Path = Join-Path $DeployPath $Dir
    if (Test-Path $Path) {
        Write-Host "Preserving runtime directory: $Dir"
    }
}

$AppExe = Join-Path $DeployPath "SecretaryBot.exe"
if (Test-Path $AppExe) {
    Remove-Item -LiteralPath $AppExe -Force
}

$Internal = Join-Path $DeployPath "_internal"
if (Test-Path $Internal) {
    Remove-Item -LiteralPath $Internal -Recurse -Force
}

robocopy $Dist $DeployPath /E /XF config.yaml context.md state.json /XD logs chat_archive | Out-Null
$Code = $LASTEXITCODE
if ($Code -gt 7) {
    throw "robocopy failed with exit code $Code"
}

Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination (Join-Path $DeployPath "README.md") -Force
Copy-Item -LiteralPath (Join-Path $Root "config.example.yaml") -Destination (Join-Path $DeployPath "config.example.yaml") -Force
Copy-Item -LiteralPath (Join-Path $Root "context.example.md") -Destination (Join-Path $DeployPath "context.example.md") -Force

$Config = Join-Path $DeployPath "config.yaml"
if (-not (Test-Path $Config)) {
    Copy-Item -LiteralPath (Join-Path $Root "config.example.yaml") -Destination $Config
    Write-Host "Created config.yaml from config.example.yaml"
} else {
    Write-Host "Kept existing config.yaml"
}

$Context = Join-Path $DeployPath "context.md"
if (-not (Test-Path $Context)) {
    Copy-Item -LiteralPath (Join-Path $Root "context.example.md") -Destination $Context
    Write-Host "Created context.md from context.example.md"
} else {
    Write-Host "Kept existing context.md"
}

New-Item -ItemType Directory -Force -Path (Join-Path $DeployPath "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DeployPath "chat_archive") | Out-Null
Write-Host "Runtime state.json, logs and chat_archive were not copied from build output"

Write-Host "Deployed to $DeployPath"
