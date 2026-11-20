# Запуск иконки в трее (отправка файлов на телефон)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $py)) { $py = Join-Path $root '.venv\Scripts\python.exe' }

$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*phone_tray.py*' }
if ($running) { Write-Host "трей уже запущен"; exit }

Start-Process -FilePath $py -ArgumentList (Join-Path $root 'phone_tray.py') -WorkingDirectory $root
Write-Host "иконка в трее: правый клик - Отправить файл на телефон"
