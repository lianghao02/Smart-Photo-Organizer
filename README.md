# 智慧照片整理助手 Smart-Photo-Organizer v3.2.0

## 專案概念與開發原因

智慧照片整理助手先索引本機媒體與 Google Takeout，再提供日期、位置、相似度及媒體群組的人工審核流程。開發動機是大量照片常有中繼資料衝突、重複內容與多分卷配對問題，直接搬檔會讓錯誤難以追查。

設計將分析狀態與媒體處理分開，以 SQLite 保存索引及進度，先展示候選結果，再由使用者決定後續操作。它適合需要審核與相似度工作區的使用者；不能把日期推定或相似度當成確定事實。

**典型流程**：選擇來源與獨立輸出 → 分析 → 閱讀問題清單與報表 → 人工審核 → 確認後處理。

## 技術架構現況（2026-08-24）

本專案主力為 **Python 3.13／pywebview／Pillow／SQLite**，以既有測試保護 Google Takeout、MediaGroup 與審核流程。現階段不進行完整重寫；只有在效能量測確認瓶頸時，才評估以 Rust 抽換雜湊、索引或 ZIP 串流等單一核心。

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v3.2.0-blue.svg)](CHANGELOG.md)

本工具採「先分析、人工審核、最後處理」流程。分析階段只建立索引、SQLite 狀態、報表與 Windows 捷徑，不搬移、刪除或重新命名來源媒體；Google Takeout ZIP 保持唯讀。

## 下載、依賴與啟動

- **系統**：Windows 10/11，Python `>=3.13,<3.14`；版本範圍記錄於 `pyproject.toml`。
- **推薦啟動**：下載 ZIP、解壓後雙擊 `RUN.bat`。首次啟動會以完整 Python 3.13 建立專案 `.venv`；未安裝時顯示處置指引。
- **手動安裝**：先執行 `setup_and_run.ps1 -NoLaunch`；需要 editable 開發安裝時，再用 `.venv\Scripts\python.exe -m pip install --no-deps -e .`。
- **執行依賴**：pywebview、Pillow、pillow-heif、geopy、pystray、OpenCV、NumPy；`requirements.txt` 保存驗證版本，`pyproject.toml` 是套件與 Python 版本的正式來源。
- **功能**：索引本機照片及 Google Takeout ZIP、配對 sidecar、依日期／位置／媒體群組整理、相似度與人工審核工作區。
- **打包／移機**：開發環境於新路徑重建 `.venv`；舊 `python_embed` 不含 Tcl/Tk，不應宣稱能獨立啟動；若要建立正式安裝套件，可在專案環境安裝 `build` 工具後執行 `.venv\Scripts\python.exe -B -s -m build`，輸出位於 `dist/`。
- **資料安全**：先以測試資料驗證，不要把輸出放進來源資料夾；大量處理前必須保留原始檔備份。

## v3.2.0 更新重點

- **標準 Python package 架構**：15 個核心模組集中於 `src/smart_photo_organizer/`，使用 package 相對匯入；規格文件與測試分別收納於 `docs/`、`tests/`。
- **高風險防禦強化**：
  - 影像解碼加入 `RuntimeError` 與 Pillow `DecompressionBombError` 例外攔截防禦，避免毀損/超大圖檔中斷分析。
  - SQLite 連線初始化配置 `PRAGMA busy_timeout = 30000;`，增強高併發與多工作階段存取下的鎖定忍受度。
  - 增強 Takeout ZIP 未標記 Bit 11 之 CP437 檔名自動轉碼修復機制，確保中文 Sidecar 完整配對。
- **v3.2.0 當時測試紀錄**：140 項單元測試（139 Passed, 1 Skipped, 0 Failed）；目前數量與結果以實際執行為準，不代表 Shell／GUI 全流程已驗證。

## 環境與啟動

- Windows 10 或更新版本
- Python 3.13
- 安裝相依套件：`.venv\Scripts\python.exe -m pip install -r requirements.txt`
- 開發模式安裝：`.venv\Scripts\python.exe -m pip install --no-deps -e .`
- 啟動：`.venv\Scripts\python.exe -s main.py`

## 基本流程

1. 選擇本機照片資料夾或 Google Takeout ZIP。
2. 選擇與來源不重疊的輸出資料夾。
3. 執行分析並查看報表、相似照片及問題清單。
4. 人工確認後，再執行專案提供的後續處理功能。

## 資料安全

- 原始 ZIP 以唯讀方式開啟，不在壓縮檔內修改內容。
- 不應把輸出資料夾放在來源資料夾內，也不應把來源放在輸出內。
- 相似度、時間與位置推定皆可能誤判；大量處理前請先抽查並保留備份。
- 中斷後可利用狀態資料繼續分析，但仍應確認磁碟空間充足。

## 驗證

```powershell
.venv\Scripts\python.exe -B -s -m unittest discover -s tests -v
```

測試數量會隨版本調整，以實際指令結果為準。詳細異動請參閱 [CHANGELOG.md](CHANGELOG.md)。

## 開發環境與啟動（2026-10 環境修復）

- 使用完整 Python 3.13 建立專案 `.venv`；啟動器不依賴 `python` 與 `py` 的預設版本。
- 首次執行既有 BAT 入口，或 `pwsh -NoProfile -File setup_and_run.ps1 -NoLaunch`。需要網路取得 requirements.txt 的指定版本；無 Python 時提供安裝指引。
- 唯讀健檢：`pwsh -NoProfile -File setup_and_run.ps1 -CheckOnly`；不建立環境、不下載套件。
- 正常啟動使用 `.venv\Scripts\python.exe -B -s`。所有手動套件操作也必須使用此直譯器的 `-m pip`。
- 已就緒環境不反覆安裝；`-Force` 僅重新套用依賴，不刪除環境。版本不符或環境損壞時保留現場，不自動改用全域 Python。
- `.venv` 不可搬移。換路徑或重新 Clone 後須於最終路徑重新建立；全域 PATH 與全域套件不需調整。
- 開發 `.venv` 與現有 Release／Portable 成品分開維護，既有發布包保留。免安裝、Win10／11 與乾淨電腦相容性另依發布門檻驗證。

## 已知 Bug、限制與疑難排解

以下區分已確認問題、功能限制及待驗證項目；歷史修正不代表舊發行包已自動更新，也不代表本次文件更新重新完成所有功能測試。

| 狀態 | 情境 | 處理方式 |
|---|---|---|
| 已修復（無限等待，2026-10-06） | 原先 Shell 讀寫與初始化沒有期限，錯誤管道未消耗，重複 start 也可能留下子程序。 | 正式 WinShellReader 改用 STA 輔助程序與有期限的讀寫；單次回應預設最多等待 15 秒，失敗時回收舊程序及通道，下一次請求可重新啟動。會記錄失敗，不將逾時當成分析成功。 |
| 環境限制 | 舊 python_embed 缺少 Tcl/Tk，不能視為完整可啟動環境。 | 使用完整 Python 3.13 建立的專案 .venv 與既有 RUN.bat；不要搬移 .venv 或切到未驗證的 3.14。 |
| 判讀限制 | 日期、位置、Sidecar 或相似度可能不明確。 | 先人工確認，輸出與來源保持分離；分析不搬動來源不等於所有後續處理都是唯讀。 |

Takeout 檔名轉碼、影像解碼例外與 SQLite 等待處理的歷史修正見 [CHANGELOG.md](CHANGELOG.md)。逾時的現行交接見 [HANDOFF.md](HANDOFF.md)。既有單元測試通過不能用來宣稱所有 Shell／GUI 流程都已驗證。

本次完整回歸 148 項執行、147 通過、1 略過，包含 8 項 Shell 測試及正式 COM 後端的資料夾／ZIP 分析重跑。Windows Shell 仍可能因系統或第三方元件忙碌而失敗；本次修正避免無限等待，並保留原有失敗回報與資料保護。驗證範圍見 [修復報告](../00_Dev-Control-Center/docs/remaining-fixes/RESULTS.md)。

### 問題回報

請提供使用版本／啟動方式、作業系統與相關環境、重現步驟、預期及實際結果，以及去識別的錯誤訊息或最小樣本。先保留現場與來源資料；不要附真實案件、完整帳號、密碼、Token 或 API Key。版本修正以對應原始碼與發行包為準。
