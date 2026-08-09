# Current Task：v3.0 Phase 2 — MediaGroup 與 Live Photo 配對

## 前置基線

- Phase 1 Codex 簽收 Commit：`531a87f`
- Phase 1 既有測試：58 通過、1 項因 Windows 權限明確略過
- Phase 0 與 Phase 1 已凍結；除修復 Phase 2 造成的 Regression 外，不得修改既有 Takeout 或 SidecarMatcher 的核心解壓與優先序契約。

## 目標

實作 `media_group.py` 模組，定義不可拆分的 `MediaGroup` 資料模型，並在 SQLite 中管理 `media_groups` 與 `media_group_members` 狀態。
實作 Live Photo 配對 (HEIC/JPG + MOV) 與 RAW/JPEG 配對，將媒體、Sidecar JSON、Live Photo 影片與衍生檔綁定為單一 Group。
Phase 2 只在記憶體與 SQLite 建立 MediaGroup，不搬移、不刪除、不改名，也不建立捷徑。

## 必要新增模組

### `media_group.py`

1. **`MediaGroup` 與 `GroupMember` 資料結構**：
   - `group_id`：全任務唯一識別 Key (UUID 或 `mg_<hash>`)。
   - `primary_media`：主要相片或影片 `SourceItem`。
   - `source_type`：`FOLDER` 或 `TAKEOUT_ZIP`。
   - `members`：包含的所有成員 (主媒體、Sidecar JSON、Live Photo MOV 影片、RAW 配對檔等)。
   - `capture_date` / `date_source` / `date_confidence`。
   - `status`：`DISCOVERED`, `PAIRED`, `VALIDATED`, `CONFLICT`。

2. **Live Photo 與配對邏輯 (`LivePhotoPairer`)**：
   - 相同邏輯目錄/ZIP、相同檔案 stem：
     * 照片 (`.heic`, `.jpg`) + 影片 (`.mov`, `.mp4`) 綁定為 Live Photo MediaGroup。
     * Live Photo 中的 MOV 影片角色標記為 `LIVE_PHOTO_VIDEO`。
   - RAW + JPEG 配對 (同 stem 之 `.cr3`/`.dng` + `.jpg`)。
   - 結合 `SidecarMatcher` 輸出：將配對好的 Sidecar JSON 併入相同的 `MediaGroup`。

3. **SQLite 資料庫整合 (`import_state.py` 擴充)**：
   - 建立 `media_groups` 資料表：`group_id`, `job_id`, `primary_member_id`, `source_type`, `capture_date`, `confidence`, `status`, `created_at`。
   - 建立 `media_group_members` 資料表：`group_id`, `member_id`, `role` (`PRIMARY`, `GOOGLE_JSON`, `LIVE_PHOTO_VIDEO`, `RAW_PAIR`, `AUXILIARY`), `created_at`。
   - 提供 `create_media_group()`, `get_media_group()`, `list_media_groups()` 等讀寫介面。

## 測試要求

新增 `test_media_group.py`：
- [x] 同目錄 HEIC + MOV Live Photo 配對成功，群組包含 2 個媒體成員。
- [x] Live Photo 配對群組同時結合 `SidecarMatcher` 找到的 JSON。
- [x] RAW + JPEG 配對成功，主媒體為 RAW 或 JPEG，備用檔正確歸屬。
- [x] SQLite `media_groups` 與 `media_group_members` 寫入與查詢驗證。
- [x] 孤立相片/影片獨立為單成員 `MediaGroup`。
- [x] 唯讀驗證：無任何實體檔案被搬移、重命名或刪除。

## 不在本次範圍

- `_Review` 捷徑建立與 Workspace 骨架 (v3.0 Phase 3)。
- 完全重複/模糊/截圖捷徑分類 (v3.0 Phase 4)。
- 待刪除隔離與刪除 (v3.0 Phase 5)。
- 短影片長度過濾 (v3.0 Phase 6)。

## 驗收條件

- [x] `python -m py_compile` 可編譯所有產品與測試模組。
- [x] `python -c "import main, source_index, sidecar_matcher, media_group"` 成功。
- [x] Phase 1 既有 58 項測試全部通過，另有 1 項 Windows Symlink 權限測試明確略過。
- [x] Phase 2 新測試全部通過。
- [x] `git diff --check` 無錯誤。
- [x] Git 差異只包含 Phase 2 必要模組、整合與測試。

## Codex 獨立複查簽收

- [x] 修正不同 Takeout ZIP 同路徑、同 stem 媒體被誤組問題。
- [x] 僅允許 HEIC/JPEG + MOV/MP4 成為 Live Photo，RAW + JPEG 成為 RAW 配對。
- [x] 停止移除 `(1)` 等檔名編號，避免不同媒體互相誤配。
- [x] MediaGroup ID 納入 Job 範圍並採穩定雜湊，避免跨任務覆寫。
- [x] SQLite API 契合 `create_media_group()`、`get_media_group()`、`list_media_groups()`。
- [x] MediaGroup 成員寫入具備冪等性，舊版重複資料可安全遷移。
- [x] Phase 2 測試 12/12 通過；全專案 71 項測試中 70 通過、1 項因 Windows 權限明確略過。
- [x] `git diff --check` 無錯誤，且未建立任何 Phase 3 模組。
