@echo off
chcp 65001 >nul
title Assi Bridge - установка
cd /d "%~dp0"

echo == Assi Bridge ==
echo Папка: %CD%
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo Не нашёл PowerShell. Установи Windows PowerShell и запусти снова.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-assi.ps1" -Autostart
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
  echo Установка завершилась с ошибкой %RC%. Смотри сообщения выше.
) else (
  echo Готово. Сервер запущен, ярлык автозапуска создан.
  echo Дальше: открой http://127.0.0.1:8787/local и подключи телефон.
)
echo.
pause
