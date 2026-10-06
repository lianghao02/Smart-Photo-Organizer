@echo off
setlocal
cd /d "%~dp0."
set "PS_HOST=pwsh.exe"
where.exe pwsh.exe >nul 2>&1
if errorlevel 1 set "PS_HOST=powershell.exe"
"%PS_HOST%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_and_run.ps1" %*
if errorlevel 1 (
    pause
    exit /b 1
)
