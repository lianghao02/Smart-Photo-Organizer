# Smart-Photo-Organizer v3.0 實作計畫

## 命名說明

目前 Git 歷史中的「Takeout Phase 1～4.8」是既有 ZIP 匯入引擎的開發階段；本文件的「v3.0 Phase 1～10」是新的人工審核產品流程，兩者不可混用。

## Phase 0：凍結既有 Takeout 基線（已完成）

Final Commit：`d182f99`，完整測試 41/41 通過。

先修正既有 Phase 5 驗收阻斷，再開始 v3.0：

- 初始化 `WebBridge._stop_event`。
- 統一媒體副檔名來源，讓 ZIP 掃描支援既有 RAW 格式。
- 修正中斷續傳測試的 Job／Member 狀態設定。
- 執行既有 34 項測試與 Phase 5 新測試。
- 通過後建立可辨識的基線 commit／tag。

## v3.0 Phase 1：來源索引與 SidecarMatcher

- 保留既有 ZIP 唯讀、安全掃描與單檔 `.part` 解壓。
- 抽出共用 `SidecarMatcher`。
- 建立一般資料夾與 Takeout ZIP 的統一來源索引介面。
- 不全量解壓 Takeout；採按需分析與 `_ReviewCache`。

## v3.0 Phase 2：MediaGroup 與 Live Photo

- 建立 MediaGroup SQLite Schema 與 API。
- 配對 HEIC／JPG + MOV Live Photo。
- 先記錄未知配對，不在此階段自動搬移。

## v3.0 Phase 3：Review Workspace 骨架

- 建立 `_Review/01`～`06`、`99` 與 `_ReviewCache`。
- 建立 ReviewEntry 與 `.lnk` 建立／解析流程。
- 建立捷徑路徑驗證、群組去重與 DRY_RUN。

## v3.0 Phase 4：既有分類改為捷徑

- 完全重複、模糊與 7 分截圖只建立 ReviewEntry／捷徑。
- 禁止這些分類直接搬移媒體。
- JSON 不建立捷徑，但保留在 MediaGroup。

## v3.0 Phase 5：待刪除隔離

- 解析 `_Review/99_待刪除` 中已登記捷徑。
- 依 group_id 去重並整組搬至 `_Quarantine/待刪除`。
- 提供預覽、交易紀錄與崩潰恢復。
- 不提供永久刪除。

## v3.0 Phase 6：短影片與 Live Photo 排除

- 讀取影片長度，建立小於或等於 5 秒候選。
- 在分類前排除 `LIVE_PHOTO_VIDEO`。

## v3.0 Phase 7：相似照片

- 依時間窗口、媒體類型與尺寸先分桶。
- 對候選計算 pHash／dHash 並形成相似群組。
- 大型媒體庫不得使用全庫 O(n²) 比較。

## v3.0 Phase 8：日期異常

- 將日期衝突與低可信度結果改為 `_Review/06_日期異常`。
- 保留 `date_audit.csv` 或等價稽核輸出。

## v3.0 Phase 9：MediaGroup 日期歸檔

- 人工審核後，完整 MediaGroup 一次歸檔。
- 使用唯一命名、零覆寫、雜湊驗證與續傳狀態。

## v3.0 Phase 10：移除雲端專用邏輯與整理 UI

- 移除 OneDrive／Google Drive placeholder 防下載程式碼與 UI。
- 保留 Windows Shell 的 `.lnk` 建立／解析及必要 metadata fallback。
- UI 改為來源選擇、開始分析、開啟審核、處理待刪除、開啟隔離區、依日期整理。

## 階段門檻

每一 Phase 必須符合：

- 驗收條件與相關自動測試通過。
- 沒有資料遺失或覆寫 Blocking 問題。
- 可從中斷狀態安全重試。
- Codex 完成一次獨立複查。
- 使用者確認後才進入下一 Phase。
