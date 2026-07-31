@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ===================================================
echo Smart Photo Organizer - Launching
echo ===================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [INFO] Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [INFO] Checking required packages...
if exist "requirements.txt" goto INSTALL_REQ
goto START_APP

:INSTALL_REQ
pip install -r requirements.txt

:START_APP
echo.
echo ===================================================
echo [OK] Starting application...
echo ===================================================
echo.

python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with code: %errorlevel%
    pause
)

