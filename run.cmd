@echo off
chcp 65001 >nul
title Assi - сервер
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0assi.ps1" toggle
timeout /t 3 >nul
