' 智慧照片整理助手 - 靜默啟動器
' 正常執行：無任何視窗彈出
' 啟動失敗：顯示錯誤訊息框供偵錯

Dim oShell, oFSO, sDir, sScript, sLog, oExec, errMsg

Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

sDir    = oFSO.GetParentFolderName(WScript.ScriptFullName)
sScript = sDir & "\main.py"
sLog    = sDir & "\_launch_err.log"

' 刪除舊日誌
If oFSO.FileExists(sLog) Then oFSO.DeleteFile sLog

' 以隱藏視窗執行 Python（0 = 隱藏, True = 等待完成）
Dim exitCode
exitCode = oShell.Run("cmd /c python """ & sScript & """ 2>""" & sLog & """", 0, True)

' 若發生錯誤，彈出訊息框
If exitCode <> 0 Then
    errMsg = "❌ 程式啟動失敗（錯誤碼: " & exitCode & "）" & Chr(13) & Chr(10) & Chr(13) & Chr(10)
    If oFSO.FileExists(sLog) Then
        Dim oFile : Set oFile = oFSO.OpenTextFile(sLog, 1)
        If Not oFile.AtEndOfStream Then
            errMsg = errMsg & "錯誤詳情：" & Chr(13) & Chr(10) & oFile.ReadAll()
        End If
        oFile.Close
        oFSO.DeleteFile sLog
    End If
    errMsg = errMsg & Chr(13) & Chr(10) & "💡 請確認：pip install Pillow pillow-heif"
    MsgBox errMsg, vbCritical, "智慧照片整理助手"
Else
    If oFSO.FileExists(sLog) Then oFSO.DeleteFile sLog
End If
