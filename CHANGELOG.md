# 版本變更紀錄

## [未發布] - 2026-08-24

### 文件

- 明列 Python 3.13／pywebview／Pillow／SQLite 為主力架構；Rust 僅保留為未來可量測效能瓶頸的局部核心選項，本次未進行語言遷移。

### 維護

- `RUN.bat` 優先使用 PowerShell 7；未安裝時自動退回 Windows PowerShell 5.1，維持既有可攜 Python 自癒啟動流程。

## [v3.2.0] - 2026-08-17

### 發布與環境

- 新增 Python 3.13 `RUN.bat` 自癒啟動與移機方式說明。
- 補齊 `requirements.txt`、`pyproject.toml`、可編輯安裝及套件建置的用途差異。
- 統一 README、套件中繼資料、後端與前端顯示版本，排除 3.0.1／3.1.0 混用。

## [v3.1.0] - 2026-08-16

### 架構重構

- **標準工業級套件結構**：全面導入 Python `src-layout`，將 15 個商業邏輯模組集中收納於 `src/`，技術與架構規格文件移至 `docs/`，單元測試收納於 `tests/`，根目錄僅保留核心進入點。
- **動態匯入相容機制**：`main.py` 與 `tests/` 均設置 `sys.path` 動態注入，確保直接啟動與 unittest 發現機制 100% 相容。

### 安全與例外防禦

- **影像解碼防禦**：`similarity.py` 影像解碼加入 `RuntimeError` 與 Pillow `DecompressionBombError` 攔截，防止毀損或超高像素圖檔導致分析中斷。
- **SQLite 鎖定超時保護**：`import_state.py` 加入 `PRAGMA busy_timeout = 30000;` 30 秒自動等待，強化 WAL 模式下併發存取穩定性。
- **Takeout 檔名轉碼增強**：`takeout_zip.py` 新增 `decode_member_name` 自動檢測並修正未標記 UTF-8 之 CP437 檔名，保障中文 Sidecar 匹配精準度。

### 測試與清理

- **全專案單元測試通過**：140 項測試全部跑通（139 Passed, 1 Skipped, 0 Failed）。
- **清理暫存殘留**：安全清理 `test_rename/` 臨時目錄與過往執行留下的 CSV/JSON 產出檔。

## [v3.0.1] - 2026-08-13

### 修正

- 確保 SQLite 連線在成功與失敗路徑都會關閉。
- 阻擋來源與輸出目錄重疊，避免遞迴掃描及資料風險。
- 改善 Takeout ZIP 成員檔名的 UTF-8／CP437 解碼。
- 修正分析失敗後未使用快取與暫存資源的清理。

### 測試與文件

- 增加媒體分組、v3 管線與介面流程的回歸測試。
- 重建 UTF-8 README 與 CHANGELOG，移除舊編碼亂碼及固定測試數字。

## [v3.0] - 2026-08-10

### 新增

- 建立唯讀分析、SQLite 狀態、人工審核與續傳流程。
- 支援 Google Takeout ZIP、照片分組與報表輸出。

## [v2.9.0] - 2026-08-04

### 變更

- 改善媒體中繼資料、相似度分析與桌面介面。
