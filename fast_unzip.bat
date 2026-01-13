@echo off
setlocal EnableDelayedExpansion

title Google Takeout - WinRAR Batch Unzip Tool

echo ========================================================
echo   Google Takeout - WinRAR Batch Unzip Tool
echo ========================================================
echo.

:: 1. Find WinRAR
set "RAR_EXE="
if exist "%ProgramFiles%\WinRAR\WinRAR.exe" set "RAR_EXE=%ProgramFiles%\WinRAR\WinRAR.exe"
if exist "%ProgramFiles(x86)%\WinRAR\WinRAR.exe" set "RAR_EXE=%ProgramFiles(x86)%\WinRAR\WinRAR.exe"

if defined RAR_EXE goto :FOUND_RAR

echo [ERROR] WinRAR.exe not found!
echo Please check default paths:
echo  - "%ProgramFiles%\WinRAR\WinRAR.exe"
echo  - "%ProgramFiles(x86)%\WinRAR\WinRAR.exe"
pause
exit /b

:FOUND_RAR
echo [System] WinRAR found: "!RAR_EXE!"
echo.

:: 2. Source Directory
set "SRC_DIR="
if "%~1" neq "" (
    set "SRC_DIR=%~1"
) else (
    set /p "SRC_DIR=Please enter SOURCE folder (drag & drop): "
)

:: Strip quotes
set "SRC_DIR=!SRC_DIR:"=!"

if "!SRC_DIR!"=="" (
    echo [ERROR] No input path.
    pause
    exit /b
)

if not exist "!SRC_DIR!" (
    echo [ERROR] Path not found: !SRC_DIR!
    pause
    exit /b
)

echo.
echo [Source]: !SRC_DIR!
echo.

:: 3. Destination Directory
set "DST_DIR="
echo Tip: Use a different drive (e.g. SSD) for max speed!
set /p "DST_DIR=Please enter DESTINATION folder (drag & drop): "
set "DST_DIR=!DST_DIR:"=!"

if "!DST_DIR!"=="" (
    echo [ERROR] Destination path is empty.
    pause
    exit /b
)

if not exist "!DST_DIR!" mkdir "!DST_DIR!"

echo.
echo ========================================================
echo  Ready to extract...
echo  Source: !SRC_DIR!
echo  Dest  : !DST_DIR!
echo ========================================================
echo.
pause

:: 4. Start Extraction
echo.
echo Change Directory to Source...
pushd "!SRC_DIR!"
if errorlevel 1 (
    echo [ERROR] Failed to access source directory.
    pause
    exit /b
)

echo Invoking WinRAR on *.zip files...
echo.

:: Loop relative files
for %%F in (*.zip) do (
    echo [Processing] %%F ...
    
    :: Executing WinRAR
    "!RAR_EXE!" x -ibck -y "%%F" "!DST_DIR!\"
)

popd
echo.
echo [DONE] All tasks finished. Please check: !DST_DIR!
echo.
pause
