@echo off
setlocal
chcp 65001 > nul
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "VENV_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"

if not exist "%VENV_PYTHON%" (
    echo [錯誤] 找不到可用的虛擬環境。
    echo 請先依 requirements.txt 重新建立 .venv。
    pause
    exit /b 1
)

"%VENV_PYTHON%" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 現有 .venv 已失效，可能仍引用搬遷前的路徑。
    echo 請依 DEVELOPMENT_ENVIRONMENT.md 的流程安全重建。
    pause
    exit /b 1
)

if not exist "%VENV_PYTHONW%" (
    echo [錯誤] 虛擬環境缺少 pythonw.exe。
    pause
    exit /b 1
)

rem 使用虛擬環境內的 pythonw 啟動，避免依賴 PATH 或目前磁碟機。
start "" "%VENV_PYTHONW%" "%~dp0main.py"
exit

