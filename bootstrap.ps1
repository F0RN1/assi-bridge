# Assi Bridge bootstrap: downloads the repo and runs the installer.
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/F0RN1/assi-bridge/main/bootstrap.ps1 | iex"
param(
    [string]$Dest = (Join-Path $env:USERPROFILE 'assi-bridge'),
    [string]$Zip  = 'https://codeload.github.com/F0RN1/assi-bridge/zip/refs/heads/main'
)

$ErrorActionPreference = 'Stop'

Write-Host "Assi Bridge -> $Dest" -ForegroundColor Cyan
$tmp = Join-Path $env:TEMP ("assi-bridge-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + ".zip")
Write-Host "Downloading..."
Invoke-WebRequest -Uri $Zip -OutFile $tmp -UseBasicParsing

Write-Host "Unpacking..."
$work = Join-Path $env:TEMP ("assi-bridge-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
Expand-Archive -Path $tmp -DestinationPath $work -Force
$src = Get-ChildItem $work -Directory | Select-Object -First 1

if (Test-Path $Dest) {
    Write-Host "Updating existing install..."
    Get-ChildItem $src.FullName -Force | ForEach-Object {
        if ($_.Name -in @('.venv', 'bridge.json', 'shared')) { return }
        Copy-Item $_.FullName -Destination $Dest -Recurse -Force
    }
} else {
    Move-Item $src.FullName $Dest
}

Remove-Item $tmp -Force -ErrorAction SilentlyContinue
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Running installer..."
Start-Process -FilePath (Join-Path $Dest 'install.cmd') -WorkingDirectory $Dest -Wait
