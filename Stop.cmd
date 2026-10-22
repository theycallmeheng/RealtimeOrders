@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\services.ps1" stop
pause
