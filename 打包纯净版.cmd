@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0package.ps1"
pause
