@echo off
chcp 65001 >nul
title Assi - сервер
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0assi.ps1" toggle
ping -n 3 127.0.0.1 >nul
