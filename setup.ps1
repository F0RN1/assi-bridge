# Assi: установка и первая настройка в одном запуске.
#
# Что делает:
#   1. ставит Python 3.12, если его нет;
#   2. создаёт .venv и ставит зависимости;
#   3. спрашивает имя сервера (2–8 символов: латиница и цифры);
#   4. генерирует токен и порт, поднимает мост и туннель;
#   5. печатает «код подключения» для телефона и копирует его в буфер.
#
# Запуск:  powershell -ExecutionPolicy Bypass -File setup.ps1
#          powershell -ExecutionPolicy Bypass -File setup.ps1 -Autostart -Name mypc

param(
    [switch]$Autostart,
    [string]$Name = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$state = Join-Path $root 'bridge.json'

function Say($msg) { Write-Host $msg }
function Fail($msg) { Write-Host "ошибка: $msg" -ForegroundColor Red; exit 1 }

Say "== Assi: установка =="
Say "папка: $root"

# --- Python ---------------------------------------------------------------
$pyCmd = $null
foreach ($cand in @(@('py', '-3.12'), @('python', ''), @('python3', ''))) {
    $exe = Get-Command $cand[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $args = @($cand[1..($cand.Length - 1)] | Where-Object { $_ })
    $ver = & $cand[0] @args -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($ver -and [version]$ver -ge [version]'3.10') { $pyCmd = $cand; break }
}
if (-not $pyCmd) {
    Say "Python не найден — ставлю Python 3.12…"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "нет winget. Поставь Python 3.12 с https://www.python.org/downloads/ (галочка 'Add python.exe to PATH') и запусти setup.ps1 снова"
    }
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $pyCmd = @('py', '-3.12')
}
$pyExe = $pyCmd[0]
$pyArgs = @($pyCmd[1..($pyCmd.Length - 1)] | Where-Object { $_ })
Say "Python: $pyExe $pyArgs"

# --- окружение ------------------------------------------------------------
$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    Say "создаю .venv…"
    & $pyExe @pyArgs -m venv (Join-Path $root '.venv')
    if (-not (Test-Path $vpy)) { Fail "не получилось создать .venv" }
}
Say "ставлю зависимости (один раз, пара минут)…"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r (Join-Path $root 'requirements.txt') --quiet
& $vpy -m pip install -r (Join-Path $root 'requirements-tray.txt') --quiet
if ($LASTEXITCODE -ne 0) { Fail "зависимости не поставились" }

# --- cloudflared ----------------------------------------------------------
$cf = Join-Path $env:USERPROFILE '.local\bin\cloudflared.exe'
if (-not (Test-Path $cf)) { $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source }
if (-not $cf) {
    Say ""
    Say "Для доступа с телефона через интернет нужен cloudflared (бесплатно, без аккаунта)."
    $ans = Read-Host "Поставить cloudflared сейчас? [Y/n]"
    if ($ans -notmatch '^[nN]') {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install -e --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements
            $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
        }
        if (-not $cf) { Say "не вышло автоматически — скачай вручную: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" }
    }
}

# --- настройка ------------------------------------------------------------
$cfg = $null
if (Test-Path $state) { $cfg = Get-Content $state -Raw | ConvertFrom-Json }

if (-not $cfg -or -not $cfg.token) {
    if (-not $Name) {
        do {
            $Name = (Read-Host "Имя сервера (2–8 символов, латиница и цифры)").Trim().ToLower()
            if ($Name -notmatch '^[a-z0-9]{2,8}$') {
                Say "не подходит: только a-z и 0-9, длина 2–8. Например: mypc, home1" -ForegroundColor Yellow
                $Name = ''
            }
        } while (-not $Name)
    } elseif ($Name -notmatch '^[a-z0-9]{2,8}$') {
        Fail "имя должно быть 2–8 символов: a-z и 0-9"
    }

    # свободный порт: 8787, иначе первый свободный выше
    $port = 8787
    while (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { $port++ }

    $token = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    $cfg = [pscustomobject]@{
        token      = $token
        port       = $port
        name       = $Name
        instance   = 'assi'
        public_url = ''
        created    = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    }
    [IO.File]::WriteAllText($state, ($cfg | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding $false))
    Say "имя: $Name · порт: $port"
} else {
    Say "настройка уже есть: имя $($cfg.name), порт $($cfg.port)"
}

# --- автозапуск -----------------------------------------------------------
if ($Autostart) {
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup 'Assi Bridge.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = 'powershell.exe'
    $s.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\start-assi.ps1`""
    $s.WorkingDirectory = $root
    $s.WindowStyle = 7
    $s.Description = 'Assi: сервер для телефона'
    $s.Save()
    Say "автозапуск при входе: включён"
}

# --- запуск ---------------------------------------------------------------
& (Join-Path $root 'assi.ps1') on
Start-Sleep 3

$cfg = Get-Content $state -Raw | ConvertFrom-Json
$url = ($cfg.public_url -replace '/$', '')
if (-not $url) {
    $lan = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1).IPAddress
    if ($lan) { $url = "http://${lan}:$($cfg.port)" }
}
$code = if ($url) { "$url/?token=$($cfg.token)" } else { "http://127.0.0.1:$($cfg.port)/?token=$($cfg.token)" }

$code | Set-Clipboard -ErrorAction SilentlyContinue
$code | Out-File (Join-Path $root 'connect.txt') -Encoding UTF8

Say ""
Say "=============================================="
Say " готово. Код подключения (скопирован):"
Say ""
Say " $code"
Say ""
Say " В приложении на телефоне вставь его в поле"
Say " «код подключения» — всё, можно пользоваться."
Say "=============================================="
Say ""

Start-Process "http://127.0.0.1:$($cfg.port)/local"
