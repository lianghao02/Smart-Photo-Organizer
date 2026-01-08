@echo off
:: 切換至批次檔所在的目錄
cd /d "%~dp0"

echo [系統提示] 正在啟動照片整理助手 (Debug模式)...

:: 暫時改回直接執行 python，這樣如果有錯誤會顯示在視窗上
python photo_organizer.py

echo.
echo [系統提示] 程式已結束。如果有錯誤訊息請截圖。
pause  
