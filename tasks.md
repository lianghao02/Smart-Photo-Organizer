# Current Task：v3.0 Phase 5 — `99_待刪除` 至 Quarantine

## 前置基線

- Phase 4 簽收 Commit：`ba7979b`
- Phase 4 簽收測試：全專案 90 項中 89 通過、1 項因 Windows Symlink 權限明確略過

## 目標

只接受 `_Review/99_待刪除` 中已登記且驗證成功的捷徑，依 `group_id` 去重後將完整 MediaGroup 移至 `_Quarantine/待刪除`。系統不提供永久刪除。

## 交易與安全契約

1. 預設 `DRY_RUN=True`，只列出群組、成員、容量與目的資料夾，不寫入交易或搬移檔案。
2. 捷徑必須同時通過：
   - 位於 `99_待刪除`。
   - 檔名含有效 ReviewEntry ID。
   - SQLite 有權威紀錄。
   - 解析目標與 SQLite 一致且位於允許根目錄。
3. 同一 MediaGroup 即使有多個分類捷徑，單次只能隔離一次。
4. 完整 MediaGroup 的媒體、Google JSON、Live Photo／RAW 配對檔缺一不可；缺少任一成員時整組停止。
5. 採兩階段跨磁碟安全搬移：
   - 第一階段：所有成員複製至 `.part`、flush／fsync、SHA-256 與容量驗證、零覆寫更名。
   - 第二階段：全部目的檔驗證成功後，才逐檔核對來源 SHA-256 並移除來源。
6. 中途失敗可依 SQLite `quarantine_actions`／`quarantine_items` 續傳；已驗證目的檔不得重複產生。
7. 磁碟空間不足、目的衝突、來源變更、Symlink／Reparse Point 或範圍外路徑一律停止，不移除來源。
8. Takeout ZIP 永遠唯讀；只移動 `_ReviewCache` 實體化群組，原始 ZIP 不修改、不改名、不刪除。
9. 完成後 MediaGroup 與所有 ReviewEntry 標記 `QUARANTINED`，清除已處理的 `99` 捷徑。

## 不在本階段

- 永久刪除 Quarantine。
- 短影片、相似照片、日期異常與最終日期歸檔。
- UI 最終整理。

## 驗收結果

- [x] 新增 `quarantine_manager.py` 與 SQLite 兩階段交易資料表／API。
- [x] DRY_RUN 不落地、不搬移測試通過。
- [x] 媒體＋JSON 整組驗證後搬移、時間戳保留與狀態更新測試通過。
- [x] 多捷徑 group_id 去重、缺少成員整組停止測試通過。
- [x] 目的衝突與空間不足零覆寫、來源保留測試通過。
- [x] 部分來源已移除後中斷續傳測試通過。
- [x] 未登記捷徑拒絕測試通過。
- [x] Takeout ZIP 唯讀、只移動 ReviewCache 測試通過。
- [x] Phase 5 新增測試 9/9 通過。
- [x] 全專案 99 項測試中 98 通過、1 項因 Windows Symlink 權限明確略過；語法載入與 `git diff --check` 通過。
- [x] Codex 自我複查完成，待建立 Phase 5 簽收 Commit。
