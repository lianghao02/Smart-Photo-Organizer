# Current Task：v3.0 Phase 4 — 重複、模糊與截圖審核分類

## 前置基線

- Phase 3 簽收 Commit：`3eaeec4`
- Phase 3 簽收測試：全專案 80 項中 79 通過、1 項因 Windows Symlink 權限明確略過
- v3.0 新流程與既有 v2.9 直接整理流程並存；Phase 10 完成替代 UI 前，不移除舊功能。

## 目標

建立 v3.0 人工審核分類器，沿用既有完全重複、Laplacian 模糊與 7 分截圖概念，但分類結果只能建立 SQLite ReviewEntry 與 `_Review/01`、`03`、`04` 捷徑。

## 必要功能

1. 完全重複：
   - 採 MediaGroup 容量 → partial SHA-256 → full SHA-256 三階段。
   - 只有完整內容相同才標記，部分雜湊碰撞不得誤判。
   - Live Photo／RAW 群組必須比較所有非 JSON 媒體，不能只比較主照片。
   - 決定性選出一組保留，其餘登記至 `01_重複照片`。
2. 模糊照片：
   - 沿用 OpenCV Laplacian，預設門檻 100。
   - OpenCV／NumPy 為選用依賴；未安裝時明確警告但不阻斷其他分類。
   - 命中只登記至 `03_模糊照片`，不得建立 `_Blurry` 或搬移媒體。
3. 截圖／監視器畫面：
   - 沿用 `MediaMetadataExtractor.calculate_screenshot_score()` 可解釋 7 分制。
   - 必須保留並使用 Takeout 原始檔名，不可使用不具語意的快取檔名評分。
   - 命中只登記至 `04_螢幕截圖`，不得移至 `_Excluded/Screenshots`。
4. 同一 MediaGroup 可同時出現在多個分類；實體媒體保持單一、不重複處理。
5. 雜湊前後核對容量與修改時間；分析期間被外部修改的檔案不得沿用舊結果。
6. JSON 不參與媒體重複雜湊，也不建立捷徑；Live Photo 影片必須保留在群組簽章中。

## 不在本階段

- `99_待刪除` 與 Quarantine 搬移。
- 短影片、相似照片、日期異常與最終日期歸檔。
- UI 切換與舊流程移除。

## 驗收結果

- [x] 新增 `review_classifier.py`，沒有修改來源媒體的檔案操作。
- [x] 完整重複三階段與 partial collision 防誤判測試通過。
- [x] Live Photo 完整群組比較測試通過。
- [x] 7 分截圖、原始檔名證據與來源內容不變測試通過。
- [x] 模糊候選只建立 ReviewEntry／捷徑測試通過。
- [x] 同群組多分類與選用 OpenCV 降級測試通過。
- [x] 分析期間媒體變更攔截測試通過。
- [x] ZIP Live Photo／RAW 群組成員未完整實體化時禁止降級判定。
- [x] Phase 4 新增測試 10/10 通過。
- [x] 全專案 90 項測試中 89 通過、1 項因 Windows Symlink 權限明確略過；語法載入與 `git diff --check` 通過。
- [x] Codex 自我複查完成，待建立 Phase 4 簽收 Commit。
