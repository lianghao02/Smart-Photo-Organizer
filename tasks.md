# Current Task：v3.0 Phase 9 MediaGroup 日期歸檔

## 基線

- Phase 8 簽收 Commit：`23c3188`
- 原始 ZIP 永久唯讀；正式搬移預設先以 DRY_RUN 顯示計畫。

## 目標

使用者明確執行「依日期整理」後，把通過日期檢查且不在 `99_待刪除` 的完整
MediaGroup 交易式搬到 `YYYY/MM/Photos` 或 `YYYY/MM/Videos`。

## 必要功能

1. 照片／影片、Google JSON、Live Photo 與 RAW 配對成員必須整組規劃。
2. 日期衝突、日期缺失、可信度低於 50 分及待刪除群組不得自動歸檔。
3. 先完整複製、fsync、容量與 SHA-256 驗證整組，再開始移除任何來源。
4. SQLite schema v8 記錄群組與逐檔交易，支援複製或移除階段中斷續傳。
5. 目的檔零覆寫；碰撞時整組採共同穩定後綴，維持 Sidecar 命名關係。
6. Takeout 模式只移動 `_ReviewCache` 實體化副本，原始 ZIP 不修改、不刪除。
7. 完成後 MediaGroup／ReviewEntry 標記 `ARCHIVED`，安全移除已失效審核捷徑。

## 驗收結果

- [x] DRY_RUN、照片＋JSON、Live Photo、零覆寫碰撞測試通過。
- [x] 日期異常與 `99_待刪除` 阻擋測試通過。
- [x] 複製失敗時不移除任何來源；移除中斷可依 SQLite 續傳。
- [x] Takeout 原始 ZIP 位元組完全不變。
- [x] Phase 9 新增測試 9/9 通過。
- [x] 全專案 124 項測試中 123 通過、1 項因 Windows 權限明確略過；語法與 `git diff --check` 通過。
- [x] Codex 自我複查完成，待提交 Phase 9 簽收 Commit。
