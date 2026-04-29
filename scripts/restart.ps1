param(
    [string]$DeployPath = "E:\Projects\secretary-exe"
)

$ErrorActionPreference = "Stop"
$Exe = Join-Path $DeployPath "SecretaryBot.exe"

if (-not (Test-Path $Exe)) {
    throw "SecretaryBot.exe not found: $Exe"
}

$TargetRoot = (Resolve-Path $DeployPath).Path
$Processes = Get-Process -Name "SecretaryBot" -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and (Split-Path $_.Path -Parent).StartsWith($TargetRoot, [System.StringComparison]::OrdinalIgnoreCase)
}

foreach ($Process in $Processes) {
    Write-Host "Stopping SecretaryBot.exe pid=$($Process.Id)"
    $null = $Process.CloseMainWindow()
}

Start-Sleep -Seconds 5

foreach ($Process in $Processes) {
    $Fresh = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
    if ($Fresh) {
        Write-Host "Killing SecretaryBot.exe pid=$($Fresh.Id)"
        Stop-Process -Id $Fresh.Id -Force
    }
}

Start-Process -FilePath $Exe -WorkingDirectory $DeployPath
Write-Host "Started $Exe"
