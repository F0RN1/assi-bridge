# Убрать адрес <имя>.assi.pro у пользователя.
#   .\release.ps1 -Name slava -Invite nord-7k2q
#   .\release.ps1 -Name slava -AdminKey <ключ владельца>   (без кода приглашения)
# Без -Name спросит имя. Ключ владельца можно положить в переменную окружения
# ASSI_ADMIN_KEY — тогда флаг -AdminKey не нужен, а код приглашения не спрашивается.
param(
    [string]$Name = '',
    [string]$Invite = '',
    [string]$AdminKey = $env:ASSI_ADMIN_KEY
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Get-RegistrarUrl {
    $setup = Join-Path $root 'setup.ps1'
    if (Test-Path $setup) {
        $line = Select-String -Path $setup -Pattern '^\s*\$RegistrarUrl\s*=\s*''([^'']+)''' | Select-Object -First 1
        if ($line -and $line.Matches.Count) { return $line.Matches[0].Groups[1].Value.TrimEnd('/') }
    }
    return ''
}

$url = Get-RegistrarUrl
if (-not $url) { Write-Host "не нашёл `$RegistrarUrl в setup.ps1 — укажи адрес регистратора" -ForegroundColor Red; exit 1 }

if (-not $Name) { $Name = Read-Host 'имя пользователя (без .assi.pro)' }

$Name = $Name.Trim().ToLower()
$headers = @{}

if ($AdminKey) {
    $headers['X-Admin-Key'] = $AdminKey.Trim()
    $body = @{ name = $Name } | ConvertTo-Json -Compress
} else {
    if (-not $Invite) { $Invite = Read-Host 'пригласительный код' }
    $body = @{ name = $Name; invite = $Invite.Trim() } | ConvertTo-Json -Compress
}

try {
    $r = Invoke-RestMethod -Uri "$url/release" -Method Post -ContentType 'application/json; charset=utf-8' `
        -Headers $headers -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 45
    Write-Host ("готово: адрес {0}.assi.pro удалён (DNS, туннель, счётчик)" -f $r.released) -ForegroundColor Green
} catch {
    $msg = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        try { $msg = ($_.ErrorDetails.Message | ConvertFrom-Json).error } catch { $msg = $_.ErrorDetails.Message }
    }
    Write-Host "не вышло: $msg" -ForegroundColor Red
    exit 1
}
