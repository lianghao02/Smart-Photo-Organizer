@echo off
chcp 65001 > nul
cd /d "%~dp0"

set "ERRLOG=%TEMP%\spo_debug_%RANDOM%.log"

:: 嘗試以靜默模式執行（無 CMD 視窗）
pythonw main.py 2>"%ERRLOG%"
set /a EXITCODE=%errorlevel%

if %EXITCODE% NEQ 0 (
    echo.
    echo ======================================================
    echo     智慧照片整理助手 - 啟動錯誤偵錯
    echo ======================================================
    echo.
    if exist "%ERRLOG%" (
        for %%A in ("%ERRLOG%") do (
            if %%~zA GTR 0 (
                echo 錯誤訊息：
                echo.
                type "%ERRLOG%"
            ) else (
                echo 程式異常退出，錯誤碼: %EXITCODE%
            )
        )
    ) else (
        echo 程式異常退出，錯誤碼: %EXITCODE%
    )
    echo.
    echo ------------------------------------------------------
    echo  💡 常見問題排查：
    echo     1. pip install Pillow pillow-heif
    echo     2. 確認 Python 已加入 PATH 環境變數
    echo ------------------------------------------------------
    echo.
    if exist "%ERRLOG%" del "%ERRLOG%" 2>nul
    pause
) else (
    :: 成功 - 清理並自動關閉
    if exist "%ERRLOG%" del "%ERRLOG%" 2>nul
)
