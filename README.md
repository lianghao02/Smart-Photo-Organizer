# 智慧照片整理助手 Smart-Photo-Organizer v3.2.0

## 技術架構現況（2026-08-24）

本專案主力為 **Python 3.13／pywebview／Pillow／SQLite**，以既有測試保護 Google Takeout、MediaGroup 與審核流程。現階段不進行完整重寫；只有在效能量測確認瓶頸時，才評估以 Rust 抽換雜湊、索引或 ZIP 串流等單一核心。

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v3.2.0-blue.svg)](CHANGELOG.md)

本工具採「先分析、人工審核、最後處理」流程。分析階段只建立索引、SQLite 狀態、報表與 Windows 捷徑，不搬移、刪除或重新命名來源媒體；Google Takeout ZIP 保持唯讀。

## 下載、依賴與啟動

- **系統**：Windows 10/11，Python `>=3.13,<3.14`；版本範圍記錄於 `pyproject.toml`。
- **推薦啟動**：下載 ZIP、解壓後雙擊 `RUN.bat`。沒有 Python 時，腳本會建立專案內的 `python_embed` 並安裝依賴。
- **手動安裝**：`py -3.13 -m venv .venv`，啟用後執行 `python -m pip install -e .`，再執行 `python main.py`。
- **執行依賴**：pywebview、Pillow、pillow-heif、geopy、pystray；`requirements.txt` 供自癒環境，`pyproject.toml` 是套件與 Python 版本的正式來源。
- **功能**：索引本機照片及 Google Takeout ZIP、配對 sidecar、依日期／位置／媒體群組整理、相似度與人工審核工作區。
- **打包／移機**：保留完整專案與 `python_embed`；若要建立正式安裝套件，可在安裝 `build` 工具後執行 `python -m build`，輸出位於 `dist/`。
- **資料安全**：先以測試資料驗證，不要把輸出放進來源資料夾；大量處理前必須保留原始檔備份。

## v3.2.0 更新重點

- **標準 Python package 架構**：15 個核心模組集中於 `src/smart_photo_organizer/`，使用 package 相對匯入；規格文件與測試分別收納於 `docs/`、`tests/`。
- **高風險防禦強化**：
  - 影像解碼加入 `RuntimeError` 與 Pillow `DecompressionBombError` 例外攔截防禦，避免毀損/超大圖檔中斷分析。
  - SQLite 連線初始化配置 `PRAGMA busy_timeout = 30000;`，增強高併發與多工作階段存取下的鎖定忍受度。
  - 增強 Takeout ZIP 未標記 Bit 11 之 CP437 檔名自動轉碼修復機制，確保中文 Sidecar 完整配對。
- **測試套件全面通**：140 項單元測試完全跑通（139 Passed, 1 Skipped, 0 Failed）。

## 環境與啟動

- Windows 10 或更新版本
- Python 3.13
- 安裝相依套件：`python -m pip install -r requirements.txt`
- 開發模式安裝：`python -m pip install -e .`
- 啟動：`python main.py`

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
python -m unittest discover -s tests -v
```

測試數量會隨版本調整，以實際指令結果為準。詳細異動請參閱 [CHANGELOG.md](CHANGELOG.md)。
