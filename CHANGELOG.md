# 變更紀錄

本專案依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 維護，版本號遵循語意化版本。

## [Unreleased]

## 🏆 v3.0.0 里程碑：人工審核歸檔

### 重大更新摘要

v3.0 將本機資料夾與 Google Takeout ZIP 統一成「唯讀分析、人工審核、隔離或日期歸檔」工作流程，媒體、JSON Sidecar、Live Photo 與 RAW/JPEG 配對檔以 MediaGroup 整組處理。

舊版分類結果會直接決定實體搬移，Takeout 也缺少可供人工挑選的完整流程。本版以 SQLite 權威狀態、Windows 捷徑、按需 ZIP 快取、兩階段搬移與 SHA-256 驗證收斂資料風險；程式不提供永久刪除，原始 Takeout ZIP 永遠唯讀。

## ✨ 重點更新特色

🔍 **統一來源與 SidecarMatcher（跨 ZIP 配對與歧義防護）**：

- 一般資料夾及多個 Takeout ZIP 使用同一來源模型，支援常見 JSON、重複編號及 Supplemental Metadata 變體。
- 同一 JSON 在任務內最多指派一次；同優先序多候選標記歧義，不任意選取。

📦 **MediaGroup 整組處理（Live Photo／RAW／JSON 不拆散）**：

- HEIC／JPG + MOV Live Photo、RAW + JPEG 與 Google JSON 建立決定性群組。
- Quarantine 與日期歸檔均驗證完整成員，缺少任何檔案即停止整組操作。

🗂️ **人工審核工作區（01～06 與 99_待刪除）**：

- 重複、相似、模糊、7 分制截圖、5 秒短影片與日期異常只建立 `.lnk` 捷徑。
- 只有移入 `99_待刪除` 的已登記捷徑可在確認後觸發隔離；同一群組多個捷徑只處理一次。

🛡️ **兩階段 Quarantine 與日期歸檔（零覆寫、可續傳）**：

- 先完整複製、`fsync`、核對容量與 SHA-256，再移除來源；碰撞時整組使用共同穩定後綴。
- 日期衝突、低可信度及待刪除群組不自動歸檔；中斷後依 SQLite 交易狀態續傳。

⚡ **大型 Takeout 按需處理（低峰值暫存）**：

- ZIP 先執行路徑、Symlink、加密、壓縮比及成員總量安全檢查。
- 一次只解壓目前 MediaGroup；未命中審核的快取立即清理，命中項目才保留於 `_ReviewCache`。

🖥️ **v3.0 非技術操作介面（安全流程明確化）**：

- 介面依序提供來源選擇、開始分析、開啟審核、處理待刪除、開啟隔離區與依日期整理。
- 移除 OneDrive／Google Drive placeholder 防下載控制項；分析中鎖定搬移操作，正式處理前一律顯示預覽摘要。

🧪 **完整回歸驗證（137 項測試）**：

- 136 項通過；1 項 Symlink 測試因目前 Windows 權限不足而明確略過；0 失敗。
- 另完成 1280px 桌面與 390px 行動寬度瀏覽器互動、響應式及主控台錯誤驗證。

## [2.9.0]

### 新增

- 照片／影片日期候選與可信度決策。
- 7 分制螢幕截圖與監視器畫面辨識。
- Google Takeout ZIP 唯讀掃描、單檔串流解壓、SQLite 續傳與 Sidecar 配對基礎。
