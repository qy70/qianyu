@echo off
chcp 65001 >nul
"%~dp0千鱼安装助手.exe" --dependencies-only
if errorlevel 1 pause