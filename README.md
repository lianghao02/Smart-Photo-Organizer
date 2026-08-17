# 智慧照片整理助手 Smart-Photo-Organizer v3.1.0

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v3.1.0-blue.svg)](CHANGELOG.md)

本工具採「先分析、人工審核、最後處理」流程。分析階段只建立索引、SQLite 狀態、報表與 Windows 捷徑，不搬移、刪除或重新命名來源媒體；Google Takeout ZIP 保持唯讀。

## v3.1.0 更新重點

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
