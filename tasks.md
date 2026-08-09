# Current Task：v3.0 Phase 10 最終產品整合與 UI 驗收

## 基線

- Phase 9 簽收 Commit：`76bf8cd`
- 原始 Takeout ZIP 永久唯讀；所有正式搬移都先提供 DRY_RUN 摘要。

## 目標

把 v3.0 Phase 1～9 的來源索引、MediaGroup、人工審核、Quarantine 與日期歸檔串成單一可操作產品流程，並將介面整理為非技術使用者可依序完成的六項主要操作。

## 必要功能

1. `V3Pipeline` 串接一般資料夾與 Takeout ZIP 的分析、審核、隔離及日期歸檔。
2. Takeout 分析一次只實體化目前 MediaGroup；非審核候選立即清理快取。
3. UI 提供來源選擇、開始分析、開啟審核、處理待刪除、開啟隔離區與依日期整理。
4. 移除 OneDrive／Google Drive placeholder 防下載控制項與產品流程；保留 `.lnk` 及 Windows 媒體日期 fallback。
5. 分析進行中禁止同時執行 Quarantine 或日期歸檔。
6. 正式歸檔前重新驗證資料庫狀態與 `99_待刪除`，不得為待刪除 Takeout 群組重新解壓。
7. UI 明確說明：分析不動來源、ZIP 永久唯讀、程式不提供永久刪除。

## 驗收結果

- [x] v3 分析協調器支援一般資料夾與本機 Takeout ZIP。
- [x] Quarantine 與日期歸檔均採「預覽 → 使用者確認 → 正式執行」。
- [x] 分析中高風險操作互斥；切換任務會釋放 Windows Shell 背景程序。
- [x] 390px 手機寬度與桌面寬度均無水平溢位；來源模式切換及主要按鈕顯示正確。
- [x] 瀏覽器主控台零錯誤。
- [x] 全專案 137 項測試中 136 通過、1 項因 Windows 權限明確略過；0 失敗。
- [x] 全部 Python 檔案語法編譯、模組載入與 `git diff --check` 通過。
- [x] README、架構、UI 規格、計畫、Memory 與 CHANGELOG 已同步 v3.0 最終狀態。
