# Current Task：v3.0 Phase 1 — 來源索引與 SidecarMatcher

## 前置基線

- Phase 0 Final Commit：`d182f99`
- 既有完整測試：41/41 通過
- Phase 0 已凍結；除修復 Phase 1 造成的 Regression 外，不得重寫既有 Takeout 解壓、續傳、日期、去重或歸檔流程。

## 目標

建立一般資料夾與 Google Takeout ZIP 共用的「唯讀來源索引」及「SidecarMatcher」。Phase 1 只負責辨識來源成員與建立媒體／JSON 配對結果，不解壓完整媒體、不搬移、不刪除、不改名，也不建立 MediaGroup。

## 必要新增模組

### 1. `source_index.py`

提供統一來源項目資料結構與兩種唯讀索引入口：

- `FolderSourceIndexer`：索引一般資料夾。
- `TakeoutSourceIndexer`：包裝既有 `TakeoutZipScanner` 與 ZIP 中央目錄結果。

每個來源項目至少包含：

- `source_key`：任務內穩定且唯一的識別值。
- `source_type`：`FOLDER` 或 `TAKEOUT_ZIP`。
- `logical_path`：統一使用 `/` 的邏輯相對路徑。
- `filename`、`extension`、`size`。
- `is_media`、`is_json`、`is_safe`、`reject_reason`。
- 一般資料夾：保留實體絕對路徑。
- ZIP：保留 archive path／fingerprint／member index／CRC，不解壓媒體。

來源索引規則：

- 使用 `media_types.py` 作為唯一副檔名來源。
- Windows 路徑比較不分大小寫，但輸出保留原始檔名與路徑。
- 支援中文、空白與 Unicode 檔名／資料夾。
- 一般資料夾不得跟隨 Symlink／Junction／Reparse Point。
- 略過專案管理目錄：`_Excluded`、`_Review`、`_ReviewCache`、`_Quarantine`、`_ImportTemp`。
- Google JSON 必須索引為 Sidecar 候選，不得視為垃圾檔。
- Takeout ZIP 必須保持唯讀，不得呼叫媒體解壓或建立正式目的檔。

### 2. `sidecar_matcher.py`

實作不依賴 SQLite、檔案搬移或 UI 的純配對器。輸入統一來源項目，輸出：

- 已配對媒體與 JSON。
- `match_quality` 與可稽核的配對原因。
- 未配對媒體。
- 未配對 JSON。
- 模糊／衝突候選；不得任意選一筆。

## Sidecar 配對規則與優先序

路徑正規化只供比較，不得改寫來源名稱。由高至低：

1. 同邏輯資料夾、完整媒體檔名：`photo.jpg` ↔ `photo.jpg.json`。
2. 同邏輯資料夾、Supplemental Metadata：
   - `photo.jpg.supplemental-metadata.json`
   - 已知截斷變體，如 `.supplemental-metada.json`。
3. 同邏輯資料夾、裸 stem：`photo.jpg` ↔ `photo.json`。
4. Google Takeout 重複編號變體：至少支援 `photo(1).jpg` ↔ `photo.jpg(1).json`，且不得搶走未編號原檔的 JSON。
5. 跨 ZIP、相同邏輯路徑配對。
6. 最後才允許跨資料夾的檔名回退；只有全任務內候選唯一時才能配對。

共同限制：

- 比較時不分副檔名大小寫。
- 一個 JSON 最多指派給一個媒體。
- 同一媒體若有多個同優先序候選，標記 `AMBIGUOUS`，不得依掃描順序任意選擇。
- `-edited`、`編輯` 等衍生檔不得在沒有明確唯一規則時偷用原檔 Sidecar；無法確定就保留為未配對／模糊候選。
- 結果順序必須固定，重跑同一來源應產生相同結果。
- 配對應以查詢表／索引完成，不得對全庫做 O(n²) 媒體 × JSON 比較。

## 既有流程整合

- `TakeoutIndexer.build_cross_zip_index()` 改為呼叫 `SidecarMatcher`，保留既有 `sidecar_links`、`match_quality`、狀態單向推進與盤點報告契約。
- `Processor._get_sidecar_pairs()` 保留為相容包裝，內部改用相同 `SidecarMatcher` 規則。
- Phase 1 不移除舊公開方法，不要求 UI 改呼叫新 API。
- 不得讓重新索引把 `VERIFIED`、`METADATA_PARSED`、`DESTINATION_RESERVED`、`COMPLETED` 或其他受保護狀態降級。
- 不得加入新的第三方套件。

## 測試要求

新增：

- `test_source_index.py`
- `test_sidecar_matcher.py`

至少覆蓋：

- [x] 一般資料夾唯讀索引、中文路徑及管理目錄排除。
- [x] 一般資料夾不跟隨 Symlink／Junction；無法在測試環境建立時須明確 skip。
- [x] Takeout ZIP 中央目錄索引不解壓媒體。
- [x] `photo.jpg.json` 精準配對。
- [x] `photo.json` 裸 stem 配對。
- [x] Supplemental Metadata 正常與截斷變體配對。
- [x] `photo(1).jpg` ↔ `photo.jpg(1).json` 編號變體配對。
- [x] 大小寫不同仍能配對，輸出保留原始名稱。
- [x] 跨 ZIP 相同邏輯路徑配對。
- [x] 單一 JSON 不會配給多個媒體。
- [x] 同優先序多候選輸出 `AMBIGUOUS`，結果不依輸入順序改變。
- [x] 跨資料夾檔名回退只有唯一候選時成功。
- [x] 一般資料夾與 ZIP 對等案例產生相同配對品質。
- [x] `TakeoutIndexer` 舊盤點數量、SQLite 關聯與狀態保護不 Regression。
- [x] `Processor._get_sidecar_pairs()` 的 Copy／Move／DRY_RUN 既有行為不 Regression。

## 不在本次範圍

- MediaGroup 或 Live Photo 配對（v3.0 Phase 2）。
- `_Review`、`_ReviewCache`、`.lnk` 或 Quarantine。
- 相似、模糊、截圖、短影片、日期異常分類。
- 媒體解壓快取與正式日期歸檔。
- UI 改版或移除雲端選項。
- 新增永久刪除功能。
- 修改 Phase 0 已凍結的安全刪除、雜湊、續傳或零覆寫契約。

## 驗收條件

- [x] `python -m py_compile` 可編譯所有產品與測試模組。
- [x] `python -c "import main, source_index, sidecar_matcher"` 成功。
- [x] Phase 0 既有 41 項測試全部通過。
- [x] Phase 1 新測試全部通過，且測試名稱與實際覆蓋行為一致。
- [x] `git diff --check` 無錯誤。
- [x] Git 差異只包含 Phase 1 必要模組、整合、測試與相關文件。
- [x] 無媒體被解壓、搬移、刪除或改名的 Phase 1 測試證據。
- [x] Antigravity 提交後由 Codex 執行一次獨立複查；小型測試／文件問題由 Codex 直接收尾，不再重複退回。

