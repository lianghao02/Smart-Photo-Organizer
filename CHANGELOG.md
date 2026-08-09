# 變更紀錄

本專案依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 維護，版本號遵循語意化版本。

## [Unreleased]

### 新增

- 建立 v3.0 統一來源索引、SidecarMatcher 與 MediaGroup／Live Photo 配對基礎。
- 建立 `_Review`／`_ReviewCache` 工作區、SQLite ReviewEntry 與 Windows 捷徑安全驗證骨架。
- 新增 MediaGroup 層級完全重複、Laplacian 模糊與 7 分制截圖人工審核分類器。
- 新增 `99_待刪除` 至 `_Quarantine/待刪除` 的 MediaGroup 兩階段驗證搬移與中斷續傳。
- 新增 5 秒內短影片人工審核分類，並在執行 ffprobe 前排除 Live Photo 配對影片。
- 新增以時間／尺寸分桶與 dHash 分段索引執行的相似照片人工審核分類。
- 新增 MediaGroup 日期衝突／低可信度人工審核與防公式注入的日期稽核報表。
- 新增 MediaGroup 兩階段日期歸檔、零覆寫命名與中斷續傳交易。

### 修正

- 防止不同 ZIP、不同檔名編號與不支援格式被誤組為 Live Photo 或 RAW 配對。
- MediaGroup 與 ReviewEntry 寫入改為冪等並補上跨任務主鍵與允許根目錄防護。

### 文件

- 建立 v3.0 產品規格、架構、實作計畫、目前任務與 UI／UX 規格。
- 建立 Antigravity／Codex 單一協作規則與階段停止條件。
- 明確區分既有 Takeout Phase 1～4.8 與新的 v3.0 Phase 1～10。

## [2.9.0]

### 新增

- 照片／影片日期候選與可信度決策。
- 7 分制螢幕截圖與監視器畫面辨識。
- Google Takeout ZIP 唯讀掃描、單檔串流解壓、SQLite 續傳與 Sidecar 配對基礎。
