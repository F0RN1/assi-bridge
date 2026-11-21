@echo off
cd /d "C:\Users\Forni\assi-stack\bridge"
powershell -NoProfile -ExecutionPolicy Bypass -File "assi.ps1" toggle
ping -n 3 127.0.0.1 >nul
