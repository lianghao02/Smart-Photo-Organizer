@echo off
chcp 65001 >nul
setlocal
title ⚡ 強力快速刪除工具 (Fast Delete Tool)
color 0C

:: ========================================================
:: 資深前端架構師的貼心小工具
:: 用途：解決 Windows 刪除大量檔案時的卡頓問題
:: 原理：使用 Robocopy 鏡像機制 (Sync with Empty)
:: ========================================================

echo.
echo ========================================================
echo        ⚡ 強力快速刪除工具 (Fast Delete Tool) ⚡
echo.
echo        [警告] 檔案刪除後 **無法從資源回收桶復原**！
echo        [警告] 請確認您選對了資料夾！
echo ========================================================
echo.

:: 1. 取得目標路徑 (支援拖曳或輸入)
set "target_dir=%~1"
if "%target_dir%"=="" (
    set /p "target_dir=>>> 請將要刪除的資料夾 [拖曳] 到此視窗，或貼上路徑並按下 Enter: "
)

:: 去除可能存在的引號
set "target_dir=%target_dir:"=%"

:: 2. 檢查路徑有效性
if "%target_dir%"=="" goto NoInput
if not exist "%target_dir%" goto NotFound
if not exist "%target_dir%\" goto NotFolder

:: 3. 二次確認 (Safety Check)
echo.
echo --------------------------------------------------------
echo [確認目標] 您即將 **永久消滅** 以下資料夾：
echo.
echo     %target_dir%
echo.
echo --------------------------------------------------------
echo.
set /p "confirm=>>> 請輸入 YES (不分大小寫) 以確認刪除，輸入其他內容取消: "

if /i not "%confirm%"=="YES" (
    echo.
    echo [X] 操作已取消，您的檔案很安全。
    goto End
)

:: 4. 執行快速刪除 (Robocopy Magic)
echo.
echo [1/3] 正在建立暫存空目錄...
set "empty_dir=%TEMP%\fast_delete_empty_%RANDOM%"
if not exist "%empty_dir%" md "%empty_dir%"

echo [2/3] 正在快速清空目標內容 (Robocopy Mirror Mode)...
REM /MIR: 鏡像目錄樹 (等同於 /E 加 /PURGE)
REM /NFL: 不記錄檔名 /NDL: 不記錄目錄名 /NJH: 不記錄工作標頭 /NJS: 不記錄工作摘要
REM /NC: 不記錄類別 /NS: 不記錄大小 /NP: 不顯示進度

robocopy "%empty_dir%" "%target_dir%" /MIR /NFL /NDL /NJH /NJS /NC /NS /NP >nul

echo [3/3] 正在移除殘留空資料夾...
rd /s /q "%target_dir%"
rd /s /q "%empty_dir%"

echo.
echo ========================================================
echo        ✅ 刪除完成 (Deletion Complete)
echo ========================================================
goto End

:NoInput
echo.
echo [!] 未輸入路徑。
goto End

:NotFound
echo.
echo [!] 找不到路徑: "%target_dir%"
goto End

:NotFolder
echo.
echo [!] 輸入的路徑似乎不是一個資料夾。為了安全起見，本工具只接受資料夾。
goto End

:End
echo.
pause
