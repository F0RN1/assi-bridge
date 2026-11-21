# Assi: включить / выключить сервер одной командой.
#   .\assi.ps1 on        — поднять мост, туннель и иконку в трее
#   .\assi.ps1 off       — остановить всё
#   .\assi.ps1 toggle    — переключить (кнопка на рабочем столе)
#   .\assi.ps1 status    — что сейчас запущено
param(
    [Parameter(Position = 0)]
    [ValidateSet('on', 'off', 'toggle', 'status')]
    [string]$Action = 'toggle'
)

$ErrorActionPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
$cf = Join-Path $env:USERPROFILE '.local\bin\cloudflared.exe'
$cfCfg = Join-Path $env:USERPROFILE '.cloudflared\config.yml'
$port = 8787

function Ping-Bridge {
    try { (Invoke-WebRequest "http://127.0.0.1:$port/api/ping" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { $false }
}

function Get-Activity {
    $bridges = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*app.py*' })
    $tray = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*phone_tray.py*' })
    $tunnel = @(Get-Process cloudflared -ErrorAction SilentlyContinue)
    [pscustomobject]@{
        Bridge = [bool]$bridges.Length -and (Ping-Bridge)
        Tunnel = [bool]$tunnel.Length
        Tray   = [bool]$tray.Length
    }
}

function Start-All {
    if (-not (Test-Path $py)) { Write-Host "нет окружения: запусти install-assi.ps1" -ForegroundColor Red; return }

    if (-not (Get-NetTCPConnection -LocalPort $port -State Listen)) {
        Write-Host "поднимаю мост…"
        Start-Process -FilePath $py -ArgumentList '-u', 'app.py' -WorkingDirectory $root -WindowStyle Hidden `
            -RedirectStandardOutput "$root\bridge.run.log" -RedirectStandardError "$root\bridge.err.log"
    }
    for ($i = 0; $i -lt 60; $i++) {
        if (Ping-Bridge) { break }
        Start-Sleep -Milliseconds 700
    }

    if (Test-Path $cf) {
        if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
            Write-Host "поднимаю туннель…"
            Start-Process -FilePath $cf -ArgumentList '--config', $cfCfg, 'tunnel', '--no-autoupdate', 'run' `
                -WindowStyle Hidden -RedirectStandardError "$env:USERPROFILE\.cloudflared\run.err.log" `
                -RedirectStandardOutput "$env:USERPROFILE\.cloudflared\run.out.log"
        }
    }

    $tray = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*phone_tray.py*' }
    if (-not $tray) {
        $pyw = Join-Path $root '.venv\Scripts\pythonw.exe'
        if (Test-Path $pyw) { Start-Process -FilePath $pyw -ArgumentList (Join-Path $root 'phone_tray.py') -WorkingDirectory $root }
    }

    $a = Get-Activity
    Write-Host ("сервер: {0} | туннель: {1} | трей: {2}" -f `
        $(if ($a.Bridge) { 'работает' } else { 'не отвечает' }), `
        $(if ($a.Tunnel) { 'есть' } else { 'нет' }), `
        $(if ($a.Tray) { 'есть' } else { 'нет' }))
}

function Stop-All {
    Write-Host "останавливаю…"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*phone_tray.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 2
    Write-Host "сервер остановлен"
}

switch ($Action) {
    'on' { Start-All }
    'off' { Stop-All }
    'toggle' { if ((Get-Activity).Bridge) { Stop-All } else { Start-All } }
    'status' {
        $a = Get-Activity
        Write-Host ("мост: {0} | туннель: {1} | трей: {2}" -f `
            $(if ($a.Bridge) { 'работает' } else { 'стоит' }), `
            $(if ($a.Tunnel) { 'есть' } else { 'нет' }), `
            $(if ($a.Tray) { 'есть' } else { 'нет' }))
    }
}
