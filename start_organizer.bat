@echo off
setlocal
chcp 65001 > nul
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "VENV_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"

rem 優先使用專案虛擬環境；專案搬遷後若其 base Python 已被移除，
rem 改嘗試已指定的 Python 3.13，避免依賴 py 指向的其他版本。
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import webview, PIL" >nul 2>nul
    if not errorlevel 1 (
        if exist "%VENV_PYTHONW%" (
            start "" "%VENV_PYTHONW%" "%~dp0main.py"
        ) else (
            start "" "%VENV_PYTHON%" "%~dp0main.py"
        )
        exit /b 0
    )
)

set "FALLBACK_PYTHON=C:\Users\chia-hao\AppData\Local\Programs\Python\Python313\python.exe"
set "FALLBACK_READY="
if exist "%FALLBACK_PYTHON%" (
    "%FALLBACK_PYTHON%" -c "import webview, PIL" >nul 2>nul
    if not errorlevel 1 set "FALLBACK_READY=1"
)
if defined FALLBACK_READY (
    start "" "%FALLBACK_PYTHON%" "%~dp0main.py"
    exit /b 0
)

echo [錯誤] 找不到可用的 Python 3.13 執行環境，或必要套件尚未安裝。
echo 現有 .venv 可能仍引用搬遷前已移除的 Python；請以已安裝的 Python 3.13 重新建立 .venv，
echo 再執行 pip install -r requirements.txt。
pause
exit /b 1

