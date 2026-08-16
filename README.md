# 智慧照片整理助手 Smart-Photo-Organizer v3.0.1

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v3.0.1-blue.svg)](CHANGELOG.md)

本工具採「先分析、人工審核、最後處理」流程。分析階段只建立索引、SQLite 狀態、報表與 Windows 捷徑，不搬移、刪除或重新命名來源媒體；Google Takeout ZIP 保持唯讀。

## v3.0.1 更新重點

- 修正 SQLite 連線在部分失敗路徑未關閉的問題。
- 拒絕來源與輸出目錄互相重疊，避免遞迴掃描或誤處理輸出資料。
- 強化 Takeout ZIP 檔名編碼、暫存清理與分析失敗處理。
- 補充媒體分組、管線與介面流程測試。

## 環境與啟動

- Windows 10 或更新版本
- Python 3.13
- 安裝相依套件：`python -m pip install -r requirements.txt`
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
python -m unittest discover -v
```

測試數量會隨版本調整，以實際指令結果為準。詳細異動請參閱 [CHANGELOG.md](CHANGELOG.md)。
