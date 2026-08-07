## 📌 持久化經驗與 Bug 坑洞

- Windows Shell 欄位索引 `3` 是檔案修改日期，不可當成媒體拍攝日期，否則複製或下載後會歸到錯誤年份。
- 影片優先採用 QuickTime `com.apple.quicktime.creationdate`，其次才採用一般 `creation_time`。
- 截圖與監視器畫面採可解釋分數制；達 7 分移至 `_Excluded/Screenshots`，低於門檻維持年月歸檔。
- 日期不可採「第一個讀到就使用」；必須收集候選日期、依可信度決策，並隔離高可信年份衝突。
- 程式產生的日期檔名不可回頭作為日期證據；低於 50 分的日期必須隔離複查。
- 已配對的 Google Takeout Sidecar JSON 必須跟隨媒體的 Copy／Move／重新命名結果；孤立 JSON 不自動處理。

## 📦 外部依賴追蹤

| 來源專案 | 引用路徑 | Commit Hash | 擷取日期 | 本地改動說明 |
|---|---|---|---|---|
| FFmpeg | `ffprobe` 命令列介面 | 未複製原始碼 | 2026-08-06 | 僅呼叫 JSON 後設資料輸出，不納入外部程式碼 |

## ⚡️ 上游衝突紀錄

<!-- 記錄與 upstream 合併時發生的衝突與解決策略 -->

## 🔖 GitHub 借鏡清單

- [FFmpeg／ffprobe](https://github.com/FFmpeg/FFmpeg)：以唯讀方式擷取影片容器與串流層級的日期標籤。

## 📅 學習歷史

- 2026-08-06：建立媒體拍攝日期可信度優先序，禁止以修改日期冒充拍攝日期。
- 2026-08-06：將截圖辨識改為 7 分門檻，並在日誌記錄各項加扣分原因。
- 2026-08-07：新增日期可信度模型、`_Review/DateConflict` 隔離與 `date_audit.csv` 稽核報告。
- 2026-08-07：排除程式產生的日期檔名，並新增 `_Review/LowConfidenceDate`。
- 2026-08-07：新增可關閉、預設啟用的 Sidecar JSON 一併處理功能。
