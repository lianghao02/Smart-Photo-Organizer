# Current Task：Phase 0 — 凍結既有 Takeout 基線

## 目標

在開始 v3.0 MediaGroup、Review Workspace 或 UI 改版前，先讓現有 Takeout ZIP 端到端匯入具備可信任的 Phase 5 驗收基線。

## 已知 Blocking

1. `WebBridge.__init__()` 尚未初始化 `_stop_event`，但 `_run_takeout_audit()` 會先呼叫 `_stop_event.clear()`。
2. `takeout_zip.py` 的媒體副檔名與 `ConfigConstants.EXT_PHOTOS` 不一致，至少遺漏 `.cr3`、`.dng`、`.rw2`、`.orf`、`.pef`、`.sr2`，會讓 RAW 與跨 ZIP Sidecar 未被當成媒體處理。
3. `test_takeout_phase5.py` 的 Chaos 續傳案例只改成員狀態，Job 仍是 `COMPLETED`，因此不會被 `find_resumable_job()` 選中，測試尚未真正模擬可續傳工作。
4. 所謂中型負載目前只有 100 筆 SQLite 批次資料，不能宣稱為大型 ZIP 或斷電壓力測試。

## 本次需求

- [ ] 在 `WebBridge.__init__()` 建立 `threading.Event()`。
- [ ] 建立單一媒體副檔名來源，供一般掃描、Takeout ZIP 與 Metadata 判斷共用。
- [ ] 確認 CR3／DNG／RW2／ORF／PEF／SR2 可被 ZIP 掃描、配對與歸檔。
- [ ] 修正 Phase 5 中斷續傳測試，同步設定合理的 Job 與 Member 未完成狀態，或改成真實跨程序中斷測試。
- [ ] 保留並完成目前未追蹤的 `test_takeout_phase5.py`，未經使用者指示不得刪除或覆寫其無關內容。
- [ ] 更新測試報告用語，不把 100 筆 SQLite 測試描述成數百 GB 壓力測試。

## 不在本次範圍

- v3.0 Phase 1～10 的功能實作。
- UI 改版。
- 相似照片與短影片分類。
- MediaGroup、Review Workspace 或 Quarantine Schema。
- 移除雲端程式碼。
- 大規模架構重寫。

## 驗收條件

- [ ] `python -c "import main; print('Load OK')"` 成功。
- [ ] 既有 34 項測試全部通過。
- [ ] `test_takeout_phase5.py` 的 5 項測試全部通過，總測試至少 39 項。
- [ ] 實際執行 Takeout 流程不再出現 `_stop_event` 缺失。
- [ ] CR3 跨 ZIP Sidecar 案例能產生主媒體與配對 JSON。
- [ ] 續傳測試確實重用同一個未完成 Job，而非另建新 Job 假通過。
- [ ] Git 差異只包含 Phase 0 必要修改與本次文件整理。

