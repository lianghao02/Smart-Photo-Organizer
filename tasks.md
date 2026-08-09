# Current Task：v3.0 Phase 3 — Review Workspace 骨架

## 前置基線

- Phase 2 Codex 簽收 Commit：`5f33fa1`
- Phase 2 簽收測試：全專案 71 項中 70 通過、1 項因 Windows Symlink 權限明確略過
- Phase 0～2 已凍結；除修復 Phase 3 造成的 Regression 外，不得改變既有 Takeout、SidecarMatcher 或 MediaGroup 契約。

## 目標

建立 `_Review`、`_ReviewCache`、SQLite `ReviewEntry` 與 Windows `.lnk` 安全建立／解析骨架。
Phase 3 只提供審核工作區與權威登記，不執行重複、模糊、截圖等分類，也不搬移、刪除或改名任何來源媒體。

## 必要功能

1. 建立固定資料夾：
   - `_Review/01_重複照片`
   - `_Review/02_相似照片`
   - `_Review/03_模糊照片`
   - `_Review/04_螢幕截圖`
   - `_Review/05_短影片`
   - `_Review/06_日期異常`
   - `_Review/99_待刪除`
   - `_ReviewCache`
2. 新增 `review_workspace.py`：
   - ReviewEntry 資料模型。
   - 捷徑零覆寫建立、冪等重跑與安全解析。
   - `.lnk` 只能指向允許的本機來源媒體或 `_ReviewCache`。
   - JSON 不得單獨建立捷徑。
   - ZIP 群組只規劃 `_ReviewCache/<job_id>/<group_id>`，不得提前全量解壓。
3. 擴充 SQLite：
   - `review_entries` 資料表、索引及外鍵。
   - 提供建立、取得、列舉與狀態更新 API。
   - 同一 Job／MediaGroup／分類只保留一筆權威紀錄。
4. DRY_RUN 只回傳預測結果，不建立資料夾、捷徑或 SQLite ReviewEntry。
5. 使用者把已登記捷徑移至 `99_待刪除` 後，仍可依檔名內 ReviewEntry ID、SQLite 與目標路徑完成驗證。

## 安全限制

- SQLite 是唯一權威狀態；捷徑內容不可單獨視為可信。
- 不覆寫既有 `.lnk`；既有捷徑若指向不同目標須標記錯誤。
- 不接受 `_Review` 以外的捷徑，也不接受允許根目錄以外的目標。
- 本階段不處理 `99_待刪除`、不建立 Quarantine，也不修改 UI。

## 驗收結果

- [x] `review_workspace.py` 與 SQLite ReviewEntry API 已完成。
- [x] 固定 Review 目錄骨架與 ReviewCache 路徑已完成。
- [x] 中文檔名、同群組多分類、冪等重跑、零覆寫與竄改攔截測試通過。
- [x] JSON／外部路徑拒絕測試通過。
- [x] `99_待刪除` 捷徑重新驗證測試通過。
- [x] DRY_RUN 與 ZIP 快取不提前建立測試通過。
- [x] Windows `WScript.Shell` 真實 `.lnk` 中文路徑建立與解析整合驗證通過。
- [x] Phase 3 測試 9/9 通過。
- [x] 全專案 80 項測試中 79 通過、1 項因 Windows Symlink 權限明確略過；語法載入與 `git diff --check` 通過。
- [x] Codex 自我複查完成，待建立 Phase 3 簽收 Commit。
