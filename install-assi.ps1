# Установка в один запуск — оставлено для старых инструкций.
# Вся работа внутри setup.ps1: окружение, имя, токен, туннель, запуск.
param(
    [switch]$Autostart,
    [string]$Name = ''
)
& (Join-Path $PSScriptRoot 'setup.ps1') -Autostart:$Autostart -Name $Name
