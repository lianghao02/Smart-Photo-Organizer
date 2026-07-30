@echo off
chcp 65001 > nul
cd /d "%~dp0"

:: 啟動 pythonw (無背景控制台視窗) 並立刻退出關閉 CMD
start "" pythonw main.py
exit
