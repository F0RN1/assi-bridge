@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "setup.ps1" -Autostart
echo.
echo Готово. Это окно можно закрыть.
ping -n 4 127.0.0.1 >nul
