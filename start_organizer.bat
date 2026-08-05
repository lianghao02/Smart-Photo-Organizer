@echo off
chcp 65001 > nul
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] 找不到 Python 環境，請確認已安裝 Python 並勾選 Add to PATH。
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [INFO] 正在建立虛擬環境與安裝必要套件...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    if exist "requirements.txt" (
        pip install --no-pip-version-check -q -r requirements.txt
    )
) else (
    call .venv\Scripts\activate.bat
)

:: 使用 pythonw 啟動 (無 CMD 主視窗) 並即刻結束批次檔
start "" pythonw main.py
exit

