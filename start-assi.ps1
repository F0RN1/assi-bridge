# Поднимает мост и туннель. Запускается планировщиком при входе в систему.
$ErrorActionPreference = 'SilentlyContinue'
$root = 'C:\Users\Forni\tools\mobile-bridge'
$cf = 'C:\Users\Forni\.local\bin\cloudflared.exe'
$cfCfg = 'C:\Users\Forni\.cloudflared\config.yml'

# 1. Мост (сам поднимет opencode serve на 8790)
$busy = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if (-not $busy) {
    Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
        -ArgumentList '-u', 'app.py' -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput "$root\bridge.run.log" -RedirectStandardError "$root\bridge.err.log"
}

# 2. Ждём, пока мост ответит (максимум 60 секунд)
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest 'http://127.0.0.1:8787/api/ping' -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
    catch { Start-Sleep -Seconds 1 }
}

# 3. Туннель assi.assi.pro
if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
    Remove-Item 'C:\Users\Forni\.cloudflared\run.err.log' -Force
    Start-Process -FilePath $cf -ArgumentList '--config', $cfCfg, 'tunnel', '--no-autoupdate', 'run' `
        -WindowStyle Hidden -RedirectStandardError 'C:\Users\Forni\.cloudflared\run.err.log' `
        -RedirectStandardOutput 'C:\Users\Forni\.cloudflared\run.out.log'
}
