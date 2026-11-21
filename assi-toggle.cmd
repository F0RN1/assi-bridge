@echo off
cd /d "C:\Users\Forni\assi-stack\bridge"
powershell -NoProfile -ExecutionPolicy Bypass -File "assi.ps1" toggle
timeout /t 2 >nul
