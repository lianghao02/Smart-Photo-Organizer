# Current Task：v3.0 Phase 8 日期異常

## 基線

- Phase 7 簽收 Commit：`7053dd3`
- 來源唯讀、日期決策可稽核、ReviewEntry 為權威紀錄。

## 目標

把高可信度來源衝突、找不到日期、日期可信度未知或低於 50 分的 MediaGroup
登記到 `_Review/06_日期異常`，並輸出 Excel 可讀的 `date_audit.csv`。

## 必要功能

1. 日期衝突優先列入人工審核，不以最高分來源直接掩蓋衝突。
2. 無日期、未知可信度及低於 50 分者列入；剛好 50 分視為達標。
3. 稽核報表固定排序、UTF-8 BOM、原子更新，並防止 CSV 公式注入。
4. SQLite MediaGroup 保存 `date_conflict`，舊資料庫自動升級至 schema v7。
5. 來源重新索引不得清空既有日期資料或降級 `QUARANTINED`／`ARCHIVED` 狀態。
6. 只建立 ReviewEntry／捷徑與衍生報表，不移動來源媒體。

## 驗收結果

- [x] 衝突、缺少日期、未知／低可信度日期均正確列入 06。
- [x] 50 分門檻、CSV 冪等更新與公式注入防護通過。
- [x] `date_conflict` 保存與重新索引不清空日期測試通過。
- [x] 來源媒體容量、修改時間與內容保持不變。
- [x] Phase 8 新增測試 6/6 通過。
- [x] 全專案 115 項測試中 114 通過、1 項因 Windows 權限明確略過；語法與 `git diff --check` 通過。
- [x] Codex 自我複查完成，待提交 Phase 8 簽收 Commit。
