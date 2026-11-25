# Assi: сервер одной командой.
#   .\assi.ps1 on       — поднять мост, туннель и иконку в трее
#   .\assi.ps1 off      — остановить всё
#   .\assi.ps1 toggle   — переключить (кнопка на рабочем столе)
#   .\assi.ps1 pause    — выключить мост, оставив «спящий» порт для телефона
#   .\assi.ps1 resume   — поднять мост обратно (после pause)
#   .\assi.ps1 status   — что сейчас запущено
param(
    [Parameter(Position = 0)]
    [ValidateSet('on', 'off', 'toggle', 'pause', 'resume', 'restart', 'status')]
    [string]$Action = 'toggle'
)

$ErrorActionPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
$pyw = Join-Path $root '.venv\Scripts\pythonw.exe'
$state = Join-Path $root 'bridge.json'
$cfCfg = Join-Path $env:USERPROFILE '.cloudflared\config.yml'
$cf = Join-Path $env:USERPROFILE '.local\bin\cloudflared.exe'
if (-not (Test-Path $cf)) { $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source }
$tunnelLog = Join-Path $root 'tunnel.log'

$port = 8787
$stateObj = $null
if (Test-Path $state) {
    $stateObj = Get-Content $state -Raw | ConvertFrom-Json
    if ($stateObj.port) { $port = [int]$stateObj.port }
}

function Ping-Bridge {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$port/api/ping" -UseBasicParsing -TimeoutSec 2
        return ($r.Content -like '*"ok":true*' -or $r.Content -like '*"ok": true*')
    } catch { return $false }
}

function Gate-Running {
    $p = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*wake_gate.py*' })
    return [bool]$p.Length
}

function Bridge-Running {
    $p = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*app.py*' -and $_.CommandLine -notlike '*wake_gate*' })
    return [bool]$p.Length
}

function Get-Activity {
    [pscustomobject]@{
        Bridge = (Bridge-Running) -and (Ping-Bridge)
        Gate   = Gate-Running
        Tunnel = [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
        Tray   = [bool](Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -like '*phone_tray.py*' })
    }
}

function Save-StateUrl([string]$url) {
    if (-not (Test-Path $state)) { return }
    $j = Get-Content $state -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($j.public_url -ne $url) {
        $j | Add-Member -Force public_url $url
        [IO.File]::WriteAllText($state, ($j | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding $false))
        # connect.txt тоже обновляем: иначе на телефон вставляют адрес, который уже умер
        $tok = $j.token
        if ($tok) {
            $code = ($url.TrimEnd('/')) + '/?token=' + $tok
            $txt = Join-Path $root 'connect.txt'
            [IO.File]::WriteAllText($txt, $code + "`r`n", (New-Object System.Text.UTF8Encoding $true))
        }
    }
}

function Start-Bridge {
    if (-not (Test-Path $py)) { Write-Host "нет окружения: запусти setup.ps1" -ForegroundColor Red; return }
    # даём «спящему порту» умереть: иначе мост не сядет на занятый порт
    for ($i = 0; $i -lt 24; $i++) {
        if (-not (Get-NetTCPConnection -LocalPort $port -State Listen)) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Bridge-Running)) {
        Write-Host "поднимаю мост…"
        Start-Process -FilePath $py -ArgumentList '-u', 'app.py' -WorkingDirectory $root -WindowStyle Hidden `
            -RedirectStandardOutput "$root\bridge.run.log" -RedirectStandardError "$root\bridge.err.log"
    }
    for ($i = 0; $i -lt 60; $i++) {
        if (Ping-Bridge) { break }
        Start-Sleep -Milliseconds 700
    }
}

function Start-Tunnel {
    if (-not $cf) {
        Write-Host "cloudflared не найден — сервер будет доступен только в своей сети" -ForegroundColor Yellow
        return
    }
    if (Get-Process cloudflared -ErrorAction SilentlyContinue) { return }

    if (Test-Path $cfCfg) {
        Write-Host "поднимаю туннель (свой домен)…"
        Start-Process -FilePath $cf -ArgumentList '--config', $cfCfg, 'tunnel', '--no-autoupdate', 'run' `
            -WindowStyle Hidden -RedirectStandardError "$env:USERPROFILE\.cloudflared\run.err.log" `
            -RedirectStandardOutput "$env:USERPROFILE\.cloudflared\run.out.log"
        return
    }

    # Постоянный адрес от регистратора: cloudflared поднимается по токену туннеля.
    if (Test-Path $state) {
        $st = Get-Content $state -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($st.tunnel_token) {
            Write-Host "поднимаю туннель (постоянный адрес)…"
            Start-Process -FilePath $cf -ArgumentList 'tunnel', '--no-autoupdate', 'run', '--token', $st.tunnel_token `
                -WindowStyle Hidden -RedirectStandardOutput "$root\tunnel.log" -RedirectStandardError "$root\tunnel.err.log"
            if ($st.public_url) { Write-Host "адрес: $($st.public_url)" }
            return
        }
    }

    # Быстрый туннель: адрес бесплатный и без аккаунта, но меняется при каждом запуске.
    Write-Host "поднимаю туннель…"
    Remove-Item $tunnelLog -Force
    Start-Process -FilePath $cf -ArgumentList 'tunnel', '--url', "http://127.0.0.1:$port", '--no-autoupdate' `
        -WindowStyle Hidden -RedirectStandardOutput $tunnelLog -RedirectStandardError "$root\tunnel.err.log"
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (-not (Test-Path $tunnelLog)) { continue }
        $m = Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches |
            Select-Object -First 1
        if ($m) {
            $url = $m.Matches[0].Value
            Save-StateUrl $url
            Write-Host "адрес: $url"
            return
        }
    }
    Write-Host "туннель не ответил — смотри tunnel.log" -ForegroundColor Yellow
}

function Start-Tray {
    if (-not (Test-Path $pyw)) { return }
    if (Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*phone_tray.py*' }) { return }
    Start-Process -FilePath $pyw -ArgumentList (Join-Path $root 'phone_tray.py') -WorkingDirectory $root
}

function Start-Gate {
    if (-not (Get-NetTCPConnection -LocalPort $port -State Listen)) {
        Start-Process -FilePath $py -ArgumentList '-u', 'wake_gate.py' -WorkingDirectory $root -WindowStyle Hidden `
            -RedirectStandardOutput "$root\gate.log" -RedirectStandardError "$root\gate.err.log"
        Start-Sleep 2
    }
}

function Start-All {
    Start-Bridge
    Start-Tunnel
    Start-Tray
    $a = Get-Activity
    Write-Host ("сервер: {0} | туннель: {1} | трей: {2}" -f `
        $(if ($a.Bridge) { 'работает' } else { 'не отвечает' }), `
        $(if ($a.Tunnel) { 'есть' } else { 'нет' }), `
        $(if ($a.Tray) { 'есть' } else { 'нет' }))
}

function Stop-Bridge {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*app.py*' -or $_.CommandLine -like '*wake_gate.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep 2
}

function Stop-All {
    Write-Host "останавливаю…"
    Stop-Bridge
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*phone_tray.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 1
    Write-Host "сервер остановлен"
}

function Pause-All {
    Write-Host "выключаю мост (порт остаётся для телефона)…"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep 2
    Start-Gate
    Write-Host "сервер выключен — включить можно с телефона"
}

function Restart-All {
    Write-Host "перезапускаю мост…"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*app.py*' -or $_.CommandLine -like '*wake_gate.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    for ($i = 0; $i -lt 24; $i++) {
        if (-not (Get-NetTCPConnection -LocalPort $port -State Listen)) { break }
        Start-Sleep -Milliseconds 500
    }
    Start-All
}

switch ($Action) {
    'on' { Start-All }
    'off' { Stop-All }
    'pause' { Pause-All }
    'restart' { Restart-All }
    'resume' {
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like '*wake_gate.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        for ($i = 0; $i -lt 24; $i++) {
            if (-not (Get-NetTCPConnection -LocalPort $port -State Listen)) { break }
            Start-Sleep -Milliseconds 500
        }
        Start-All
    }
    'toggle' { if ((Get-Activity).Bridge) { Stop-All } else { Start-All } }
    'status' {
        $a = Get-Activity
        Write-Host ("мост: {0} | спящий порт: {1} | туннель: {2} | трей: {3}" -f `
            $(if ($a.Bridge) { 'работает' } else { 'стоит' }), `
            $(if ($a.Gate) { 'да' } else { 'нет' }), `
            $(if ($a.Tunnel) { 'есть' } else { 'нет' }), `
            $(if ($a.Tray) { 'есть' } else { 'нет' }))
    }
}
