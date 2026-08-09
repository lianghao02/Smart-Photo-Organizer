# Current Task：v3.0 Phase 6 — 短影片與 Live Photo 排除

## 前置基線

- Phase 5 簽收 Commit：`b6cf133`
- Phase 5 簽收測試：全專案 99 項中 98 通過、1 項因 Windows Symlink 權限明確略過

## 目標

以唯讀 ffprobe 取得影片長度，將大於 0 且小於或等於 5 秒的獨立影片登記至 `_Review/05_短影片`；任何 `LIVE_PHOTO_VIDEO` 必須在探測長度前排除。

## 必要功能

1. ffprobe 採參數陣列呼叫、不使用 Shell、不修改或重新編碼影片。
2. 容器 `format.duration` 優先；缺少時採有效串流中最長 duration。
3. `0 < duration <= 5.0` 才建立 ReviewEntry；5.001 秒不得列入。
4. `MediaAnalysisTarget` 必須保留 MediaGroup 是否含 `LIVE_PHOTO_VIDEO` 的權威角色資訊。
5. Live Photo 影片在呼叫 ffprobe 前直接排除，不以檔名或長度猜測。
6. ffprobe 不存在、逾時、回傳錯誤或沒有 duration 時只記錄警告，不把未知長度當成短影片。
7. 命中後只建立 ReviewEntry／捷徑，來源影片保持原狀。

## 驗收結果

- [x] 新增 `VideoDurationProbe`，支援容器與串流 duration。
- [x] 5.0 秒列入、5.001 秒排除測試通過。
- [x] `LIVE_PHOTO_VIDEO` 在 probe 前排除測試通過。
- [x] ffprobe 失敗降級警告測試通過。
- [x] 來源影片不搬移、不刪除測試通過。
- [x] Phase 6 新增測試 5/5 通過。
- [x] 全專案 104 項測試中 103 通過、1 項因 Windows 權限明確略過，語法載入與 `git diff --check` 通過。
- [x] Codex 自我複查完成，待提交 Phase 6 簽收 Commit。
