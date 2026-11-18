# Второй экземпляр моста — для друга (порт 8788, свой токен, свой чат).
# Запуск: powershell -ExecutionPolicy Bypass -File start-friend.ps1

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$env:ASSI_INSTANCE = 'friend'
$env:ASSI_PORT = '8788'
$env:ASSI_OPENCODE_PORT = '8791'
$env:ASSI_PUBLIC_URL = 'https://friend.assi.pro'

$busy = $false
try { $busy = (Test-NetConnection -ComputerName 127.0.0.1 -Port 8788 -WarningAction SilentlyContinue).TcpTestSucceeded } catch { }

if (-not $busy) {
    Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList '-u', 'app.py' -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput "$root\friend.run.log" -RedirectStandardError "$root\friend.err.log"
}

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        if ((Invoke-WebRequest 'http://127.0.0.1:8788/api/ping' -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break }
    } catch { }
}

if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath "$env:USERPROFILE\.local\bin\cloudflared.exe" `
        -ArgumentList '--config', "$env:USERPROFILE\.cloudflared\config.yml", 'tunnel', '--no-autoupdate', 'run' `
        -WindowStyle Hidden -RedirectStandardError "$env:USERPROFILE\.cloudflared\run.err.log" -RedirectStandardOutput "$env:USERPROFILE\.cloudflared\run.out.log"
}
