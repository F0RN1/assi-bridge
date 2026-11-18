# Assi Bridge — установка на Windows в один запуск
#
# Что делает:
#   1. проверяет Python 3.12 (если нет — ставит через winget);
#   2. создаёт окружение .venv и ставит зависимости;
#   3. проверяет наличие OpenCode (без него мосту не с кем говорить);
#   4. по флагу -Autostart кладёт ярлык в «Автозагрузку»;
#   5. запускает мост и открывает страницу с адресом и токеном.
#
# Запуск:  powershell -ExecutionPolicy Bypass -File install-assi.ps1
#          powershell -ExecutionPolicy Bypass -File install-assi.ps1 -Autostart

param(
    [switch]$Autostart
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say($msg) { Write-Host $msg }
function Fail($msg) { Write-Host "ОШИБКА: $msg" -ForegroundColor Red; exit 1 }

Say "== Assi Bridge: установка =="
Say "папка: $root"

# --- 1. Python -------------------------------------------------------------
$py = $null
foreach ($cand in @('py -3.12', 'python', 'python3')) {
    $parts = $cand.Split(' ')
    $exe = Get-Command $parts[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $ver = & $parts[0] $parts[1..($parts.Length - 1)] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($ver -and [version]$ver -ge [version]'3.10') { $py = $cand; break }
}
if (-not $py) {
    Say "Python не найден — пробую поставить Python 3.12 через winget…"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "нет winget. Поставь Python 3.12 вручную: https://www.python.org/downloads/ (галочка 'Add python.exe to PATH')"
    }
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $py = 'py -3.12'
}
Say "Python: $py"

# --- 2. Окружение и зависимости -------------------------------------------
if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
    Say "создаю окружение .venv…"
    $parts = $py.Split(' ')
    & $parts[0] $parts[1..($parts.Length - 1)] -m venv "$root\.venv"
}
$vpy = "$root\.venv\Scripts\python.exe"
Say "ставлю зависимости (первый раз долго — качается распознавание речи)…"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r "$root\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) { Fail "не удалось поставить зависимости" }

# --- 3. OpenCode ----------------------------------------------------------
if (Get-Command opencode -ErrorAction SilentlyContinue) {
    Say "OpenCode найден"
} else {
    Say "! OpenCode не найден в PATH. Мост работает только вместе с ним:" -ForegroundColor Yellow
    Say "  поставь https://opencode.ai, залогинься в свою модель и запусти хотя бы раз."
}

# --- 4. Автозагрузка ------------------------------------------------------
if ($Autostart) {
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup 'Assi Bridge.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = 'powershell.exe'
    $s.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\start-assi.ps1`""
    $s.WorkingDirectory = $root
    $s.WindowStyle = 7
    $s.Description = 'Асси: мост и туннель'
    $s.Save()
    Say "ярлык автозапуска создан: $lnk"
}

# --- 5. Запуск ------------------------------------------------------------
Say "запускаю мост…"
Start-Process -FilePath $vpy -ArgumentList '-u', 'app.py' -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput "$root\bridge.run.log" -RedirectStandardError "$root\bridge.err.log"

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest 'http://127.0.0.1:8787/api/ping' -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { break }
    } catch { }
}

Say ""
Say "Готово. Открываю страницу с адресом и токеном…"
Start-Process 'http://127.0.0.1:8787/local'
Say "Дальше: установи приложение на телефон и введи адрес сервера и токен со страницы."
Say "Если телефон должен ходить из интернета — нужен свой домен + туннель cloudflared."
