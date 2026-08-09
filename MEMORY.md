## 📌 持久化經驗與 Bug 坑洞

- Windows Shell 欄位索引 `3` 是檔案修改日期，不可當成媒體拍攝日期，否則複製或下載後會歸到錯誤年份。
- 影片優先採用 QuickTime `com.apple.quicktime.creationdate`，其次才採用一般 `creation_time`。
- 截圖與監視器畫面採可解釋分數制；達 7 分移至 `_Excluded/Screenshots`，低於門檻維持年月歸檔。
- 日期不可採「第一個讀到就使用」；必須收集候選日期、依可信度決策，並隔離高可信年份衝突。
- 程式產生的日期檔名不可回頭作為日期證據；低於 50 分的日期必須隔離複查。
- 已配對的 Google Takeout Sidecar JSON 必須跟隨媒體的 Copy／Move／重新命名結果；孤立 JSON 不自動處理。
- 既有 Takeout Phase 1～4.8 與 v3.0 Phase 1～10 是兩套不同階段名稱，文件與提交訊息必須註明所屬版本。
- Windows `.lnk` 無法直接指向 ZIP 內部成員；Takeout 審核流程須將命中分類的 MediaGroup 按需實體化至 `_ReviewCache`。
- `.lnk` 只供人工瀏覽，SQLite 才是 ReviewEntry、MediaGroup 與 Quarantine 狀態的權威來源。
- Live Photo MOV 必須在短影片分類前完成群組配對，避免被誤列為待刪短影片。
- `_Review/01`～`06` 只建立捷徑；只有 `_Review/99_待刪除` 可以觸發完整 MediaGroup 搬至 `_Quarantine/待刪除`。
- MediaGroup 媒體配對必須限制在相同來源類型、相同 ZIP 指紋、相同邏輯目錄與完全相同 stem；不可跨 ZIP 或移除 `(1)` 編號後猜測配對。
- Live Photo 僅接受 HEIC/JPEG + MOV/MP4，RAW 配對僅接受 RAW + JPEG；同 stem 並不足以證明兩個檔案屬於同組。
- MediaGroup SQLite 寫入必須冪等，重跑同一群組時不得累積重複的 `media_group_members`。
- Review 捷徑採 `ReviewEntry ID__可讀檔名.lnk`；使用者移至 `99_待刪除` 後仍以 ID 回查 SQLite，不信任捷徑檔名或目標本身。
- ZIP 審核快取必須固定在 `_ReviewCache/<job_id>/<group_id>`，呼叫端不得自訂任意 cache 路徑。
- 完全重複必須比較整個 MediaGroup 的所有非 JSON 媒體；Live Photo／RAW 成員未完整實體化時禁止降級成只比較主照片。
- Takeout 截圖評分與捷徑顯示必須沿用原始檔名，不可使用 UUID 或 `.part` 快取名稱作為證據。
- Quarantine 跨磁碟搬移採「整組先複製驗證、全部成功後才移除來源」；不可逐檔直接 move，否則中斷會拆散 MediaGroup。
- Quarantine 續傳不能依賴捷徑目標仍存在；來源可能已在前次交易部分移除，必須以 SQLite action/item 與已驗證目的檔恢復。
- 短影片分類必須先讀取 MediaGroup 的 `LIVE_PHOTO_VIDEO` 角色再決定是否呼叫 ffprobe；不得只靠 MOV 檔名或影片秒數排除。

## 📦 外部依賴追蹤

| 來源專案 | 引用路徑 | Commit Hash | 擷取日期 | 本地改動說明 |
|---|---|---|---|---|
| FFmpeg | `ffprobe` 命令列介面 | 未複製原始碼 | 2026-08-06 | 僅呼叫 JSON 後設資料輸出，不納入外部程式碼 |
| GooglePhotosTakeoutHelper | 無 | 未複製原始碼 | 2026-08-09 | 僅借鏡 Takeout 命名、JSON 與日期處理概念 |
| google-photos-exif | 無 | 未複製原始碼 | 2026-08-09 | 僅借鏡 Sidecar 檔名 edge cases |
| Lap | 無 | 未複製原始碼 | 2026-08-09 | 僅借鏡 MediaGroup 與 Live Photo 配對概念；GPL-3.0 程式碼不得直接移植 |

## ⚡️ 上游衝突紀錄

<!-- 記錄與 upstream 合併時發生的衝突與解決策略 -->

## 🔖 GitHub 借鏡清單

- [FFmpeg／ffprobe](https://github.com/FFmpeg/FFmpeg)：以唯讀方式擷取影片容器與串流層級的日期標籤。
- [GooglePhotosTakeoutHelper](https://github.com/TheLastGimbus/GooglePhotosTakeoutHelper)：借鏡 Takeout JSON 與日期規則，不採用其全量解壓／搬移架構。
- [google-photos-exif](https://github.com/mattwilson1024/google-photos-exif)：借鏡 SidecarMatcher 命名變體，不作為主架構。
- [Lap](https://github.com/julyx10/lap)：借鏡 Live Photo 與成組媒體概念；僅參考設計，不直接複製 GPL-3.0 程式碼。

## 📅 學習歷史

- 2026-08-06：建立媒體拍攝日期可信度優先序，禁止以修改日期冒充拍攝日期。
- 2026-08-06：將截圖辨識改為 7 分門檻，並在日誌記錄各項加扣分原因。
- 2026-08-07：新增日期可信度模型、`_Review/DateConflict` 隔離與 `date_audit.csv` 稽核報告。
- 2026-08-07：排除程式產生的日期檔名，並新增 `_Review/LowConfidenceDate`。
- 2026-08-07：新增可關閉、預設啟用的 Sidecar JSON 一併處理功能。
- 2026-08-09：確立 v3.0 採人工審核優先、MediaGroup 原子處理、捷徑 Review 與 Quarantine 流程。
- 2026-08-09：決定先完成 Phase 0 Takeout 基線驗收，再進入 v3.0 Phase 1；UI 最終整理延至 Phase 10。
- 2026-08-09：完成 v3.0 Phase 2 Codex 獨立複查；收斂 Live Photo／RAW 配對範圍，補上跨 ZIP、跨任務與 SQLite 冪等防護。
- 2026-08-09：完成 v3.0 Phase 3 Review Workspace 骨架；確立 SQLite 權威 ReviewEntry、零覆寫捷徑與允許根目錄驗證。
- 2026-08-09：完成 v3.0 Phase 4 審核分類器；重複、模糊與截圖只建立 ReviewEntry／捷徑，不再作為 v3 流程的直接搬移指令。
- 2026-08-09：完成 v3.0 Phase 5 Quarantine 兩階段交易；支援跨磁碟、群組原子性、SHA-256 驗證與中斷續傳。
- 2026-08-09：完成 v3.0 Phase 6 短影片分類；5 秒門檻採精確浮點比較，Live Photo 影片在 ffprobe 前排除。
- 2026-08-09：完成 v3.0 Phase 7 相似照片分析；先依拍攝時間、方向與長寬比分桶，再以 dHash 分段索引限制比較量，完全重複不重複列入相似分類。
- 2026-08-09：完成 v3.0 Phase 8 日期異常審核；日期衝突、缺失與低可信度只建立審核捷徑，並以 UTF-8 BOM 原子更新 `date_audit.csv`。
- 2026-08-09：完成 v3.0 Phase 9 MediaGroup 日期歸檔；整組先複製驗證再移除來源，碰撞時採共同後綴並保留 Sidecar／Live Photo 關係。
